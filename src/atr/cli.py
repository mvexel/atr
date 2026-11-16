"""atr: a goal tree, tasks and decisions for a team of agents.

One plan file per project in a central folder. The page (owner) and the CLI (lead agent) change it
through the same operations below; nothing is pushed to agents, the lead runs `atr read` each turn.
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

HERE = Path(__file__).resolve().parent
MAX_RUNNING = 3
# review: the lead did it, but it only counts once the owner checks it (a test set the lead marked, say).
AGENT_STATUSES = ("todo", "doing", "blocked", "review", "done", "dropped")
OPEN = ("todo", "doing", "blocked", "review")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

RULES = """\
## Plan (atr)

This project's plan lives in atr. You are the lead; workers report to you, and only you run atr,
except that a worker may report progress on its own task, `atr now T3 "what is happening"`,
record its own judgment calls with its name: `atr decide T3 "..." --why "..." --by worker-name`,
and put a pull request it opened on its goal (rule 7).

1. Run `atr read` when a turn starts and again before it ends. Act on what the owner changed.
2. Every task belongs to a goal: `atr task add G1 "title" --after T2`. Work that fits no goal is
   proposed with `atr goal propose "title" --done "what makes it done"`, not started.
   When you pick up a goal that has no tasks yet, first add a task for planning it and set it to
   doing, before you research anything, so the page shows the goal was picked up.
3. Never change goals. Keep status current: `atr task set T3 status=doing thread=URL`. While a task
   runs, say what is happening every few steps, in a few words: `atr now T3 "scoring run 2 of 3"`.
4. Record every judgment call: `atr decide T3 "what you chose" --why "..." --rejected "..."`.
   If it is hard to undo, add `--hard` and do not act: the task blocks until the owner answers.
   A question only the owner can answer, with no answer to recommend: `atr ask T3 "..." --option ..`.
   Check earlier decisions before proposing something that was already rejected.
5. Record each attempt at a goal (a run, an approach, a tuning round): `atr try G1 "prompt B: 15 of 31"`.
   Keep each goal's outlook current, especially after a try: `atr outlook G1 unsure "half the ads"`.
   When `atr read` says a goal is OUT OF BUDGET, stop its work and ask the owner how it goes on.
   A goal whose method is unproven starts with one small task that checks it can work at all.
6. Start work from `atr next` (at most 3 tasks running). Work only the owner can do (record, test by
   hand, grant a permission) gets `atr task set T3 owner=you`: it shows as their turn, not yours.
   Work you did that only counts once the owner checks it: `atr task set T3 status=review note="check .."`.
   A task you set to done while it has decisions the owner has not reviewed goes to review instead,
   and is done once they accept them (an overturn sends it back to you).
   Attach what you write for the owner: `atr attach T3 path/to/findings.md`.
7. Right after opening a pull request, put it on its goal with the tasks it carries:
   `atr pr G1 https://github.com/o/r/pull/12 --for T3`, and set those tasks to review. The owner merges
   it on GitHub; then atr moves them to done (never the goal: that stays the owner's call). `atr read`
   tells you when it merges, its CI fails or it conflicts: fix those on the same branch.
"""


class Refused(Exception):
    """An operation the plan does not allow. The message says what to do instead."""


class Stale(Exception):
    """The plan changed since the caller last saw it."""


def ago_s(epoch):
    m = int((time.time() - float(epoch)) / 60)
    return "just now" if m < 1 else f"{m} min ago" if m < 60 else f"{m // 60} h ago"


def now():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")


def ago(ts):
    """'12 min ago' for one of now()'s timestamps."""
    try:
        then = datetime.strptime(ts, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return "at an unknown time"
    m = round((datetime.now(UTC) - then).total_seconds() / 60)
    if m < 1:
        return "just now"
    if m < 60:
        return f"{m} min ago"
    return f"{round(m / 60)} h ago" if m < 48 * 60 else f"{round(m / 1440)} days ago"


def running(plan):
    """Tasks in progress, with when there was last news of them (a progress line, or the start)."""
    return [
        {
            "id": t["id"],
            "title": t["title"],
            "last_news_at": t.get("now_at") or t.get("doing_since") or "",
        }
        for t in plan["tasks"]
        if t["status"] == "doing"
    ]


def data_dir():
    return Path(
        os.environ.get("ATR_DATA_DIR") or Path.home() / ".local/share/atr"
    ).expanduser()


def project_dir(name):
    if not NAME_RE.match(name or ""):
        raise Refused(
            f"'{name}' is not a project name (lowercase letters, digits and dashes)"
        )
    return data_dir() / name


def load(name):
    path = project_dir(name) / "plan.json"
    if not path.exists():
        raise Refused(
            f"no project '{name}' in {data_dir()} (atr init {name} \"Title\")"
        )
    return json.loads(path.read_text())


def save(plan):
    d = project_dir(plan["name"])
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".plan-")
    with os.fdopen(fd, "w") as f:
        json.dump(plan, f, indent=1, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, d / "plan.json")


def projects():
    root = data_dir()
    return (
        sorted(p.parent.name for p in root.glob("*/plan.json")) if root.exists() else []
    )


def change(name, by, fn, args=None, base_rev=None):
    """Run one operation under the project's lock. A returned note records a change and raises the revision."""
    d = project_dir(name)
    if not (d / "plan.json").exists():
        load(name)
    with open(d / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        plan = load(name)
        if base_rev is not None and base_rev != plan["rev"]:
            raise Stale()
        args = dict(args or {})
        note = fn(plan, by, args)
        if note:
            plan["rev"] += 1
            c = {"rev": plan["rev"], "by": by, "at": now(), "what": note}
            if by == "you":  # the owner's action as data, so a push can hand it to the lead as is
                c.update(op=next((k for k, f in OPS.items() if f is fn), fn.__name__), args=args)
            plan["changes"] = (plan["changes"] + [c])[-300:]
        save(plan)
        return plan, note


# ---- lookups -------------------------------------------------------------------------------------


def get(plan, kind, ident):
    for x in plan[kind]:
        if x["id"] == ident:
            return x
    raise Refused(f"no {kind[:-1]} {ident}")


def new_id(plan, letter):
    plan["seq"][letter] += 1
    return f"{letter}{plan['seq'][letter]}"


def owner_only(by, what):
    if by != "you":
        raise Refused(f"only the owner can {what}")


def check_on(plan, on):
    if on == "project":
        return
    get(plan, "goals" if on.startswith("G") else "tasks", on)


def label(t):
    return f'{t["id"]} "{t["title"]}"'


def deps_done(plan, t):
    # a dropped task will never be done, so nothing waits on it; a parked one may come back, so it still holds
    return all(get(plan, "tasks", a)["status"] in ("done", "dropped") for a in t["after"])


def needs_owner(plan, on):
    return [d for d in plan["decisions"] if d["on"] == on and d["state"] == "needs_you"]


def held_by(plan, t):
    """Cards that hold task t: its own, or one on its goal. A question about a goal holds the whole goal."""
    return needs_owner(plan, t["id"]) + needs_owner(plan, t["goal"])


def budget_out(g):
    """Why goal g has used up its budget (tries or days), or "" while it has some left."""
    b = g.get("budget") or {}
    if b.get("tries") and b.get("used", 0) >= b["tries"]:
        return f"used all {b['tries']} tries"
    if b.get("days"):
        start = datetime.strptime(b["from"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
        if (datetime.now(UTC) - start).total_seconds() >= b["days"] * 86400:
            return f"ran past its {b['days']} day{'s' if b['days'] != 1 else ''}"
    return ""


def set_budget(g, a):
    """Apply tries= / days= from args (blank or 0 clears one); a changed budget starts fresh."""
    b = dict(g.get("budget") or {})
    changed = False
    for k in ("tries", "days"):
        if a.get(k) in (None, ""):
            continue
        try:
            n = float(a[k]) if k == "days" else int(a[k])
        except (TypeError, ValueError):
            raise Refused(f"{k} is a number") from None
        if n < 0:
            raise Refused(f"{k} is a number")
        n = (int(n) if n == int(n) else n) if n else None
        if n != b.get(k):
            b[k], changed = n, True
    if changed:
        b.update(used=0, **{"from": now()})
        if b.get("tries") or b.get("days"):
            g["budget"] = b
        else:
            g.pop("budget", None)
    return changed


def reaches(plan, start, target):
    """True when `target` is among the tasks `start` comes after, directly or not."""
    seen, todo = set(), [start]
    while todo:
        cur = todo.pop()
        if cur == target:
            return True
        if cur not in seen:
            seen.add(cur)
            todo += get(plan, "tasks", cur)["after"]
    return False


def owners_turn(t):
    """Work only the owner can do (owner=you): never offered to the lead, shown to the owner as their turn."""
    return t["owner"] == "you"


def ready(plan):
    """Unblocked tasks the lead can start now: at most MAX_RUNNING running, most-depended-on first."""
    proposed = {g["id"] for g in plan["goals"] if g.get("proposed") or budget_out(g)}
    running = sum(t["status"] == "doing" for t in plan["tasks"])
    cand = [
        t
        for t in plan["tasks"]
        if t["status"] == "todo"
        and t["goal"] not in proposed
        and deps_done(plan, t)
        and not owners_turn(t)
        and not held_by(plan, t)
    ]
    weight = {
        t["id"]: sum(
            o["status"] in OPEN and reaches(plan, o["id"], t["id"])
            for o in plan["tasks"]
        )
        for t in cand
    }
    cand.sort(key=lambda t: -weight[t["id"]])
    return cand[: max(0, MAX_RUNNING - running)]


def unread(plan):
    """What the lead has not read: the owner's changes, and news from GitHub about the project's PRs."""
    return [
        c
        for c in plan["changes"]
        if c["by"] in ("you", "github") and c["rev"] > plan["lead"]["read_rev"]
    ]


def from_workers(plan):
    """Decisions workers recorded since the lead last read: the lead reviews them (it answers for its workers)."""
    return [
        c
        for c in plan["changes"]
        if c["by"].startswith("worker:") and c["rev"] > plan["lead"]["read_rev"]
    ]


def waiting(name):
    """True while an `atr wait` for this project is running: the lead will be woken by owner changes."""
    try:
        os.kill(int((project_dir(name) / ".waiting").read_text()), 0)
        return True
    except (OSError, ValueError):
        return False


def wait(name, timeout):
    """Block until the owner changes something the lead has not read. Returns the unread changes, or [] on timeout."""
    return wait_all([name], timeout)[name]


def wait_all(names, timeout):
    """wait() over several projects: returns {name: unread changes} as soon as any project has some.

    Registers itself in each project's .waiting file so the page and extensions can tell the lead is listening.
    """
    marks = [project_dir(n) / ".waiting" for n in names]
    for m in marks:
        m.write_text(str(os.getpid()))
    deadline, seen = time.monotonic() + timeout, {}
    try:
        while True:
            changed = False
            for n in names:
                mtime = (project_dir(n) / "plan.json").stat().st_mtime_ns
                if mtime != seen.get(n):
                    seen[n], changed = mtime, True
            if changed:
                found = {n: unread(load(n)) for n in names}
                if any(found.values()):
                    return found
            if time.monotonic() >= deadline:
                return {n: [] for n in names}
            time.sleep(1)
    finally:
        for m in marks:
            with contextlib.suppress(OSError, ValueError):
                if int(m.read_text()) == os.getpid():
                    m.unlink()


# ---- the lead's claim: which thread leads a project (one lead per project, one project per lead) ----------
# Kept beside plan.json, not in it: the hooks refresh it every turn, and a plan revision per turn would
# make the owner's page edits stale while they type.

CLAIM_LIFE = 24 * 3600  # a lead silent this long has let go: another thread may lead


def claim_file(name):
    return project_dir(name) / "lead.json"


def read_claim(name):
    """{"id", "seen"} for the thread that leads `name`, or {} when none does (or its claim has run out)."""
    try:
        c = json.loads(claim_file(name).read_text())
        return c if c.get("id") and time.time() - float(c["seen"]) < CLAIM_LIFE else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def same_thread(a, b):
    """True when two ids name one thread: a provider may print a short id that starts the full one
    (claude --bg prints 85aade68; the session's hooks get 85aade68-...)."""
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def write_claim(name, thread):
    tmp = claim_file(name).with_suffix(".tmp")
    tmp.write_text(json.dumps({"id": thread, "seen": time.time()}))
    os.replace(tmp, claim_file(name))


def claim(name, thread):
    """Make `thread` the lead of `name` if it may be. Returns (is_lead, who leads): the thread may lead when
    the project has no live lead or it already is the lead, and it leads no other project."""
    data_dir().mkdir(parents=True, exist_ok=True)
    with open(data_dir() / ".claim.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cur = read_claim(name)
        if cur and not same_thread(cur["id"], thread):
            return False, {**cur, "project": name}
        for other in projects():
            c = read_claim(other) if other != name else {}
            if c and same_thread(c["id"], thread):
                return False, {**c, "project": other}
        write_claim(name, max(thread, cur.get("id", ""), key=len))  # keep the full id once a hook has sent it
        return True, {**read_claim(name), "project": name}


def release(name, thread=None):
    """Let go of the lead: the thread's own claim (thread given), or whoever holds it (the owner)."""
    cur = read_claim(name)
    if cur and (thread is None or same_thread(cur["id"], thread)):
        claim_file(name).unlink(missing_ok=True)
        return True
    return False


# ---- operations: fn(plan, by, args) -> note ------------------------------------------------------


def op_goal_add(plan, by, a):
    title = (a.get("title") or "").strip()
    if not title:
        raise Refused("a goal needs a title")
    g = {
        "id": new_id(plan, "G"),
        "title": title,
        "done_when": (a.get("done_when") or "").strip(),
        "proposed": by != "you",
    }
    set_budget(g, a)
    # A done test the lead wrote is its guess at what the owner wants, not the owner's word: it stays marked
    # until the owner confirms or rewrites it (on adhush a lead-written test went unquestioned for days).
    if by != "you" and g["done_when"]:
        g["test_guess"] = True
    plan["goals"].append(g)
    return f"{'added' if by == 'you' else 'proposed'} goal {label(g)}"


def op_goal_edit(plan, by, a):
    owner_only(by, "edit a goal")
    g = get(plan, "goals", a["id"])
    for k in ("title", "done_when"):
        if a.get(k) is not None:
            g[k] = a[k].strip()
    if a.get("done_when") is not None:
        g.pop("test_guess", None)
    set_budget(g, a)
    return f"edited goal {label(g)}"


def op_goal_try(plan, by, a):
    """The lead records one attempt at a goal: a run, an approach, a tuning round. Counts against tries=."""
    g = get(plan, "goals", a["id"])
    text = " ".join((a.get("text") or "").split())
    if not text:
        raise Refused('say what was tried and how it went: atr try G1 "prompt B: 15 of 31 caught"')
    b = g.get("budget")
    if b:
        b["used"] = b.get("used", 0) + 1
    g.setdefault("tries", []).append({"at": now(), "what": text})
    count = f" ({b['used']} of {b['tries']})" if b and b.get("tries") else ""
    return f"{g['id']} try{count}: {text}"


def op_goal_accept(plan, by, a):
    owner_only(by, "accept a goal")
    g = get(plan, "goals", a["id"])
    g["proposed"] = False
    if a.get("test") and g.pop("test_guess", None):
        return f"accepted goal {label(g)} and its done test"
    return f"accepted goal {label(g)}"


def op_goal_met(plan, by, a):
    """The owner says the goal's done test passes. Meeting a goal is their call, never the lead's."""
    owner_only(by, "say a goal is met")
    g = get(plan, "goals", a["id"])
    if g.get("proposed"):
        raise Refused(f"{g['id']} is only proposed")
    if g.get("met_at"):
        return None
    left = [t["id"] for t in plan["tasks"] if t["goal"] == g["id"] and t["status"] in OPEN]
    if left:
        raise Refused(f"{g['id']} still has open tasks ({', '.join(left)}): finish, park or drop them first")
    g["met_at"] = now()
    g.pop("test_guess", None)  # judging the test met is accepting it
    return f"MET goal {label(g)}"


def op_goal_reopen(plan, by, a):
    owner_only(by, "reopen a goal")
    g = get(plan, "goals", a["id"])
    if not g.pop("met_at", None):
        return None
    return f"reopened goal {label(g)}" + (f": {a['why'].strip()}" if (a.get("why") or "").strip() else "")


def op_goal_confirm_test(plan, by, a):
    owner_only(by, "confirm a done test")
    g = get(plan, "goals", a["id"])
    if not g.pop("test_guess", None):
        return None
    return f"confirmed the done test of {label(g)}: {g['done_when']}"


def op_goal_remove(plan, by, a):
    owner_only(by, "remove a goal")
    g = get(plan, "goals", a["id"])
    if any(t["goal"] == g["id"] for t in plan["tasks"]):
        raise Refused(f"{g['id']} still has tasks; move or drop them first")
    plan["goals"].remove(g)
    plan["decisions"] = [d for d in plan["decisions"] if d["on"] != g["id"]]
    return f"{'rejected proposed' if g.get('proposed') else 'removed'} goal {label(g)}"


def op_task_add(plan, by, a):
    g = get(plan, "goals", a.get("goal") or "")
    if g.get("proposed"):
        raise Refused(
            f"{g['id']} is only proposed; the owner has to accept it before it gets tasks"
        )
    if g.get("met_at") and by != "you":
        raise Refused(
            f"{g['id']} is met; new work goes under another goal, or the owner reopens it"
        )
    title = (a.get("title") or "").strip()
    if not title:
        raise Refused("a task needs a title")
    after = list(dict.fromkeys(a.get("after") or []))
    for dep in after:
        get(plan, "tasks", dep)
    t = {
        "id": new_id(plan, "T"),
        "goal": g["id"],
        "title": title,
        "status": "todo",
        "after": after,
        "owner": "",
        "thread": "",
        "note": "",
        "added_by": by,
        "added_at": now(),
        "agreed": by == "you",
    }
    plan["tasks"].append(t)
    return f"added task {label(t)} under {g['id']}"


def op_task_set(plan, by, a):
    t = get(plan, "tasks", a["id"])
    if by != "you" and t.get("pruned_by") == "you":
        raise Refused(
            f'the owner {t["status"]} {t["id"]}; stop any work on it, then: atr task stopped {t["id"]} "what was left"'
        )
    said = []
    for k in ("title", "owner", "thread", "note"):
        if a.get(k) is not None and a[k] != t[k]:
            t[k] = a[k].strip()
            said.append(k)
    status = a.get("status")
    if status and status != t["status"]:
        if status not in AGENT_STATUSES:
            raise Refused(f"status is one of: {', '.join(AGENT_STATUSES)}")
        if t["status"] == "review" and status == "done" and by != "you":
            raise Refused(f"{t['id']} waits for the owner's check; only they can pass it")
        unreviewed = [d["id"] for d in plan["decisions"] if d["on"] == t["id"] and d["state"] == "to_review"]
        if status == "done" and by != "you" and unreviewed:
            # done only counts once the owner has seen the calls made on the way
            status = "review"
            t["awaits"] = unreviewed
            a["note"] = a.get("note") or f"review {', '.join(unreviewed)}"
            if t["note"] != a["note"]:
                t["note"] = a["note"]
                said.append("note")
        if status == "review" and not (a.get("note") or t["note"]):
            raise Refused(f'say what the owner should check: atr task set {t["id"]} status=review note="..."')
        if status == "doing":
            if not deps_done(plan, t):
                raise Refused(
                    f"{t['id']} comes after {', '.join(t['after'])}, which is not all done"
                )
            out = budget_out(get(plan, "goals", t["goal"]))
            if out:
                raise Refused(
                    f"{t['goal']} {out}: ask the owner how it goes on first (a --hard card on {t['goal']})"
                )
            if held_by(plan, t):
                d = held_by(plan, t)[0]
                raise Refused(
                    f"{t['id']} waits on the owner's answer to {d['id']} (on {d['on']})"
                )
        if status == "doing":
            t["doing_since"] = now()
        else:  # the progress line belongs to the run that just ended
            for k in ("now", "now_at"):
                t.pop(k, None)
        t["status"] = status
        t.pop("blocked_by", None)
        said.append(status)
    for dep in a.get("after") or []:
        if op_dep(plan, by, {"id": t["id"], "other": dep}):
            said.append(f"after {dep}")
    return f"{label(t)}: {', '.join(said)}" if said else None


def op_task_check(plan, by, a):
    """The owner checks a task in review: it passes (done), or goes back to the lead with what is wrong."""
    owner_only(by, "check a task")
    t = get(plan, "tasks", a["id"])
    if t["status"] != "review":
        raise Refused(f"{t['id']} is not waiting for a check")
    t.pop("awaits", None)
    if a.get("ok"):
        t["status"] = "done"
        return f"checked {label(t)}: it is right"
    why = (a.get("note") or "").strip()
    if not why:
        raise Refused("say what is wrong, so the lead can fix it")
    t["status"] = "todo"
    return f"checked {label(t)}: NOT RIGHT, {why}"


def op_task_now(plan, by, a):
    """What is happening on a running task right now: one short line the owner sees without opening it."""
    t = get(plan, "tasks", a["id"])
    if t["status"] != "doing":
        raise Refused(
            f"{t['id']} is not in progress; first: atr task set {t['id']} status=doing"
        )
    text = " ".join((a.get("text") or "").split())
    if not text:
        raise Refused('say what is happening: atr now T3 "scoring run 2 of 3"')
    t.update(now=text, now_at=now())
    return f"{t['id']} now: {text}"


OUTLOOKS = ("likely", "unsure", "unlikely")


def op_goal_outlook(plan, by, a):
    """The lead's current read on whether a goal can be met as written. One line, kept current."""
    g = get(plan, "goals", a["id"])
    if g.get("proposed"):
        raise Refused(f"{g['id']} is only proposed")
    level = a.get("level")
    if level not in OUTLOOKS:
        raise Refused(f"the outlook is one of: {', '.join(OUTLOOKS)}")
    text = " ".join((a.get("text") or "").split())
    if not text:
        raise Refused('say why, in a line: atr outlook G1 unsure "catches half the ads; edges late"')
    g["outlook"] = {"level": level, "text": text, "at": now()}
    return f"{g['id']} outlook: {level}, {text}"


def op_task_move(plan, by, a):
    owner_only(by, "rearrange the plan")
    t = get(plan, "tasks", a["id"])
    g = get(plan, "goals", a.get("goal") or t["goal"])
    if g.get("proposed"):
        raise Refused(f"{g['id']} is only proposed")
    moved = g["id"] != t["goal"]
    plan["tasks"].remove(t)
    t["goal"] = g["id"]
    before = a.get("before")
    idx = next((i for i, o in enumerate(plan["tasks"]) if o["id"] == before), None)
    if idx is None:  # no anchor: after the goal's last task
        idx = (
            max(
                (i for i, o in enumerate(plan["tasks"]) if o["goal"] == g["id"]),
                default=len(plan["tasks"]) - 1,
            )
            + 1
        )
    plan["tasks"].insert(idx, t)
    return f"moved {label(t)} to {g['id']}" if moved else f"reordered {label(t)}"


def op_task_prune(plan, by, a):
    owner_only(by, "drop or park a task")
    t = get(plan, "tasks", a["id"])
    mode = "parked" if a.get("mode") == "park" else "dropped"
    was = t["status"]
    if was in ("parked", "dropped"):
        raise Refused(f"{t['id']} is already {was}")
    why = " ".join((a.get("why") or "").split())
    t.update(status=mode, pruned_by="you", was=was, stopped=was != "doing")
    t.pop("blocked_by", None)
    if why:
        t["pruned_why"] = why
    return (
        f"{mode} {label(t)}"
        + (" while it was in progress" if was == "doing" else "")
        + (f": {why}" if why else "")
    )


def op_task_restore(plan, by, a):
    owner_only(by, "restore a task")
    t = get(plan, "tasks", a["id"])
    if t["status"] not in ("parked", "dropped"):
        raise Refused(f"{t['id']} is not parked or dropped")
    t["status"] = "todo"
    for k in ("pruned_by", "was", "stopped", "pruned_why"):
        t.pop(k, None)
    return f"restored {label(t)}"


def op_task_stopped(plan, by, a):
    t = get(plan, "tasks", a["id"])
    if t["status"] not in ("parked", "dropped"):
        raise Refused(f"{t['id']} is not parked or dropped")
    t["stopped"] = True
    if a.get("note"):
        t["note"] = a["note"].strip()
    return f"stopped work on {label(t)}"


def op_agree(plan, by, a):
    """The owner accepts the plan as it stands: tasks agents add after this show as new."""
    owner_only(by, "agree the plan")
    # Only open tasks are news: one the lead already finished, or the owner parked, is past.
    new = [t for t in plan["tasks"] if not t.get("agreed") and t["status"] in OPEN]
    for t in plan["tasks"]:
        t["agreed"] = True
    return (
        f"agreed the plan as it stands ({len(new)} new open task{'s' if len(new) != 1 else ''})"
        if new
        else None
    )


def op_dep(plan, by, a):
    t, other = get(plan, "tasks", a["id"]), get(plan, "tasks", a["other"])
    if a.get("remove"):
        if other["id"] not in t["after"]:
            return None
        t["after"].remove(other["id"])
        return f"{t['id']} no longer waits for {other['id']}"
    if other["id"] == t["id"] or reaches(plan, other["id"], t["id"]):
        raise Refused(f"{t['id']} after {other['id']} would make a loop")
    if other["id"] in t["after"]:
        return None
    t["after"].append(other["id"])
    return f"{t['id']} now comes after {other['id']}"


def op_decide(plan, by, a):
    on = a.get("on") or "project"
    check_on(plan, on)
    chosen = (a.get("chosen") or "").strip()
    if a.get("ask"):
        return ask(plan, on, a)
    if not chosen:
        raise Refused(
            "a decision needs what was chosen (or, with --hard, what you recommend)"
        )
    rejected = [r.strip() for r in a.get("rejected") or [] if r.strip()]
    hard = bool(a.get("hard"))
    # --owner: the lead records what the owner said in conversation. The decision is the owner's, but the
    # change is the lead's, so it does not come back to the lead as unread.
    said = bool(a.get("owner"))
    if said and hard:
        raise Refused(
            "--owner records an answer the owner already gave; it cannot also be --hard"
        )
    worker = (a.get("worker") or "").strip()
    if worker:
        if not NAME_RE.match(worker):
            raise Refused("a worker name is lowercase letters, digits and dashes")
        if said:
            raise Refused("--by records a worker's call; --owner records the owner's")
    who = "you" if said else f"worker:{worker}" if worker else by
    d = {
        "id": new_id(plan, "D"),
        "on": on,
        "by": who,
        "at": now(),
        "question": (a.get("question") or "").strip(),
        "chosen": chosen,
        "why": (a.get("why") or "").strip(),
        "rejected": rejected,
        "undo": "hard" if hard else "easy",
        # What the owner said in chat is theirs, but in the lead's words: it waits for them to confirm it.
        "state": "needs_you" if hard else "to_review",
        "note": "",
    }
    if said:
        d["said"] = True
    if who == "you" and not said:
        d["state"] = "accepted"
    plan["decisions"].append(d)
    if d["state"] != "needs_you":
        return f"{d['id']} on {on}{' (the owner said)' if said and by != 'you' else ''}: {chosen}"
    d["options"] = [chosen] + rejected
    d["chosen"] = ""
    d["recommended"] = chosen
    d["rejected"] = []
    if on.startswith("T"):
        t = get(plan, "tasks", on)
        if t["status"] in ("todo", "doing"):
            t.update(was=t["status"], status="blocked", blocked_by=d["id"])
    return f"{d['id']} on {on} needs the owner: {d['question'] or chosen}"


def ask(plan, on, a):
    """A plain question for the owner, with no recommendation: some answers are theirs alone
    ("what do you watch with ads?"), and a suggested answer would only be made up."""
    question = (a.get("question") or "").strip()
    if not question:
        raise Refused('a question needs its text: atr ask T3 "what do you watch?"')
    d = {
        "id": new_id(plan, "D"),
        "on": on,
        "by": "agent",
        "at": now(),
        "question": question,
        "chosen": "",
        "why": (a.get("why") or "").strip(),
        "rejected": [],
        "undo": "hard",
        "state": "needs_you",
        "note": "",
        "options": [o.strip() for o in a.get("options") or [] if o.strip()],
        "recommended": "",
        "ask": True,
    }
    plan["decisions"].append(d)
    if on.startswith("T"):
        t = get(plan, "tasks", on)
        if t["status"] in ("todo", "doing"):
            t.update(was=t["status"], status="blocked", blocked_by=d["id"])
    return f"{d['id']} on {on} asks the owner: {question}"


def op_answer(plan, by, a):
    owner_only(by, "answer a card")
    d = get(plan, "decisions", a["id"])
    if d["state"] != "needs_you":
        raise Refused(f"{d['id']} is already answered")
    choice = (a.get("choice") or "").strip()
    if not choice:
        raise Refused("pick an option or write an answer")
    d.update(
        chosen=choice,
        rejected=[o for o in d.get("options", []) if o != choice],
        state="accepted",
        note=(a.get("note") or "").strip(),
        answered_at=now(),
    )
    for t in plan["tasks"]:
        if t.get("blocked_by") == d["id"]:
            t["status"] = t.pop("was", "todo")
            del t["blocked_by"]
    if d["on"].startswith("G"):  # the owner has said how the goal goes on: it gets a fresh budget
        g = get(plan, "goals", d["on"])
        if g.get("budget"):
            g["budget"].update(used=0, **{"from": now()})
    return (
        f"answered {d['id']} ({d['question'] or d.get('recommended', '')}): {choice}"
        + (f" — {d['note']}" if d["note"] else "")
    )


def op_review(plan, by, a):
    owner_only(by, "review a decision")
    d = get(plan, "decisions", a["id"])
    if d["state"] == "needs_you":
        raise Refused(f"{d['id']} is a card: answer it instead")
    verdict = a.get("verdict")
    if verdict not in ("accept", "overturn"):
        raise Refused("verdict is accept or overturn")
    d["state"] = "accepted" if verdict == "accept" else "overturned"
    d["note"] = (a.get("note") or "").strip()
    t = next((t for t in plan["tasks"] if t["id"] == d["on"] and t["status"] == "review" and t.get("awaits")), None)
    if t:  # the task went to review only for its decisions: they settle it
        if verdict == "overturn":
            t["status"] = "todo"
            t.pop("awaits")
        elif not any(x["on"] == t["id"] and x["state"] == "to_review" for x in plan["decisions"]):
            t["status"] = "done"
            t.pop("awaits")
    if verdict == "accept":
        return f"{'confirmed' if d.get('said') else 'accepted'} {d['id']}: {d['chosen']}"
    return f'OVERTURNED {d["id"]} on {d["on"]} ("{d["chosen"]}")' + (
        f": {d['note']}" if d["note"] else ""
    )


def op_attach(plan, by, a):
    on = a.get("on") or "project"
    check_on(plan, on)
    src = (a.get("src") or "").strip()
    doc = {"id": new_id(plan, "A"), "on": on, "by": by, "at": now()}
    if re.match(r"^https?://", src):
        doc.update(url=src, title=(a.get("title") or src).strip())
    else:
        path = Path(src).expanduser()
        if not path.is_file():
            raise Refused(f"{src} is not a file or an http(s) link")
        docs = project_dir(plan["name"]) / "docs"
        docs.mkdir(exist_ok=True)
        stored = f"{doc['id']}-{re.sub(r'[^A-Za-z0-9._-]', '_', path.name)}"
        shutil.copyfile(path, docs / stored)
        doc.update(file=stored, title=(a.get("title") or path.name).strip())
    plan["docs"].append(doc)
    return f'attached "{doc["title"]}" to {on}'


# ---- pull requests: they sit on a goal, the owner merges them on GitHub ------------------------------------
# A PR is the owner's turn on its goal. atr serve asks gh about every open PR of every project in one GraphQL
# query per round and stores what GitHub says; merged, CI turning failing and a conflict are news for the lead.

PR_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/(\d+)(?:[/?#].*)?$")


def pr_parse(url):
    """(owner, repo, number) of a GitHub pull request link."""
    m = PR_RE.match((url or "").strip())
    if not m:
        raise Refused(f"{url} is not a GitHub pull request link (https://github.com/OWNER/REPO/pull/N)")
    return m[1], m[2], int(m[3])


def find_pr(plan, url):
    for g in plan["goals"]:
        for p in g.get("prs", []):
            if p["url"] == url:
                return g, p
    return None, None


def pr_turn(p):
    """An open PR is the owner's turn (merge it), unless GitHub says it is a draft, failing or conflicting."""
    return p["state"] == "open" and not (
        p.get("known") and (p.get("draft") or p.get("ci") == "failing" or p.get("mergeable") == "conflicting")
    )


def pr_words(p):
    """What is known of a PR, for the lead: 'open, CI passing, mergeable'."""
    if p["state"] != "open" or not p.get("known"):
        return p["state"] if p["state"] != "open" else "open, state unknown (gh did not answer)"
    return ", ".join(
        ["draft" if p.get("draft") else "open", f"CI {p.get('ci') or 'none'}"]
        + [{"conflicting": "CONFLICTS with its base", "mergeable": "mergeable"}.get(p.get("mergeable"), "mergeability unknown")]
    )


def op_pr(plan, by, a):
    """The lead or a worker puts a PR it opened on its goal, for the tasks it carries (--for)."""
    g = get(plan, "goals", a.get("goal") or "")
    if g.get("proposed"):
        raise Refused(f"{g['id']} is only proposed")
    if g.get("met_at") and by != "you":
        raise Refused(f"{g['id']} is met; the owner reopens it first")
    owner, repo, number = pr_parse(a.get("url"))
    url = f"https://github.com/{owner}/{repo}/pull/{number}"
    tasks = list(dict.fromkeys(a.get("for") or []))
    for tid in tasks:
        t = get(plan, "tasks", tid)
        if t["goal"] != g["id"]:
            raise Refused(f"{tid} is under {t['goal']}, not {g['id']}: a PR sits on the goal of the tasks it carries")
    on, p = find_pr(plan, url)
    if p:
        if on is not g:
            raise Refused(f"PR #{number} is already on {on['id']}")
        if p["state"] != "open":
            raise Refused(f"PR #{number} is already {p['state']}")
        new = [t for t in tasks if t not in p["for"]]
        if not new:
            return None
        p["for"] += new
        return f"PR #{number} on {g['id']} is also for {', '.join(new)}"
    p = {"url": url, "repo": f"{owner}/{repo}", "number": number, "for": tasks, "by": by, "at": now(), "state": "open", "known": False}
    g.setdefault("prs", []).append(p)
    return f"PR #{number} on {g['id']}" + (f" for {', '.join(tasks)}" if tasks else "") + f": {url}"


def op_pr_seen(plan, by, a):
    """What GitHub says of a PR now (from the poller). Merged, CI turning failing and a new conflict are news,
    so they reach the lead; any other change is stored silently. A merge moves the PR into the goal's history
    and its tasks in review to done; it never says the goal is met: that stays the owner's call."""
    g, p = find_pr(plan, a.get("url"))
    if not p or p["state"] != "open":
        return None
    if not a.get("known"):
        p["known"] = False  # gh is missing or failed: the page shows a link, state unknown
        return None
    was = dict(p)
    p.update(known=True, draft=bool(a.get("draft")), mergeable=a.get("mergeable") or "unknown", ci=a.get("ci") or "none")
    tag = f"PR #{p['number']} on {g['id']}"
    if a.get("state") == "merged":
        p.update(state="merged", merged_at=now())
        done = []
        for tid in p["for"]:
            t = next((t for t in plan["tasks"] if t["id"] == tid), None)
            if t and t["status"] == "review":
                t["status"] = "done"
                t.pop("awaits", None)
                done.append(tid)
        return f"{tag} was merged on GitHub" + (f"; {', '.join(done)} done" if done else "") + f" ({p['url']})"
    if a.get("state") == "closed":
        p.update(state="closed", closed_at=now())
        return None
    news = []
    if p["ci"] == "failing" and was.get("ci") != "failing":
        news.append("its CI is failing")
    if p["mergeable"] == "conflicting" and was.get("mergeable") != "conflicting":
        news.append("it conflicts with its base branch")
    return f"{tag}: {' and '.join(news)} ({p['url']})" if news else None


def op_lead(plan, by, a):
    plan["lead"]["thread"] = (a.get("thread") or "").strip()
    return "set the lead thread"


def op_lead_release(plan, by, a):
    if by != "you":
        raise Refused("only the owner lets go of the lead for it; a lead ends its own claim with atr lead --release ID")
    if not release(plan["name"]):
        raise Refused("no thread leads this project now")
    return "let go of the lead thread: the next session to start a turn in the repo becomes the lead"


def op_mark_read(plan, by, a):
    plan["lead"].update(read_rev=plan["rev"], read_at=now())


OPS = {
    "goal_add": op_goal_add,
    "goal_edit": op_goal_edit,
    "goal_accept": op_goal_accept,
    "goal_remove": op_goal_remove,
    "goal_confirm_test": op_goal_confirm_test,
    "goal_met": op_goal_met,
    "goal_reopen": op_goal_reopen,
    "task_add": op_task_add,
    "task_set": op_task_set,
    "task_move": op_task_move,
    "task_prune": op_task_prune,
    "task_check": op_task_check,
    "task_restore": op_task_restore,
    "agree": op_agree,
    "lead_release": op_lead_release,
    "dep": op_dep,
    "decide": op_decide,
    "answer": op_answer,
    "review": op_review,
}


# ---- the lead's view -----------------------------------------------------------------------------


def render(plan, since):
    out = [f"{plan['title']} ({plan['name']}) · revision {plan['rev']}", ""]
    owner, github = [c for c in since if c["by"] != "github"], [c for c in since if c["by"] == "github"]
    if owner:
        out.append("THE OWNER CHANGED, since you last read:")
        out += [f"  - {c['what']}" for c in owner]
        out.append("")
    if github:
        out.append("FROM GITHUB, since you last read (your PRs):")
        out += [f"  - {c['what']}" for c in github]
        out.append("")
    workers = from_workers(plan)
    if workers:
        out.append(
            "FROM YOUR WORKERS, since you last read (check each; overturn by recording your own call):"
        )
        out += [f"  - {c['by'][7:]}: {c['what']}" for c in workers]
        out.append("")
    stop = [t for t in plan["tasks"] if t.get("pruned_by") and not t.get("stopped")]
    if stop:
        out.append("STOP THESE (the owner pruned them while they were running):")
        out += [
            f"  - {label(t)} [{t['status']}]{' ' + t['thread'] if t['thread'] else ''}: stop the worker, "
            f'then: atr task stopped {t["id"]} "what was left"'
            for t in stop
        ]
        out.append("")
    spent = [
        g
        for g in plan["goals"]
        if not g.get("proposed") and budget_out(g) and not needs_owner(plan, g["id"])
    ]
    if spent:
        out.append(
            "OUT OF BUDGET (stop work on these goals and ask the owner how they go on):"
        )
        out += [
            f"  - {label(g)} {budget_out(g)}. Post: atr decide {g['id']} \"<your recommendation>\" --hard "
            f'--question "..." --why "<what the tries showed>" with the other options as --rejected: '
            "keep going, change the done test, change the method, drop the goal"
            for g in spent
        ]
        out.append("")
    waiting = [d for d in plan["decisions"] if d["state"] == "needs_you"]
    proposed = [g for g in plan["goals"] if g.get("proposed")]
    if waiting or proposed:
        out.append(
            "WAITING ON THE OWNER (keep your thread pinned if your tool can, and do not act on these):"
        )
        out += [
            f"  - {d['id']} on {d['on']}: {d['question'] or d['recommended']}"
            for d in waiting
        ]
        out += [f"  - proposed goal {label(g)}" for g in proposed]
        out.append("")
    overturned = [d for d in plan["decisions"] if d["state"] == "overturned"]
    met = [g for g in plan["goals"] if g.get("met_at")]
    for g in plan["goals"]:
        if g.get("met_at"):
            continue
        out.append(
            f"{g['id']} {g['title']}{' [PROPOSED, not accepted]' if g.get('proposed') else ''}"
        )
        if g["done_when"]:
            guess = " (YOUR GUESS, the owner has not confirmed it: treat it as a hypothesis)" if g.get("test_guess") else ""
            out.append(f"   done when{guess}: {g['done_when']}")
        o = g.get("outlook")
        if o:
            out.append(f"   your outlook ({ago(o['at'])}): {o['level']}, {o['text']}")
        elif not g.get("proposed") and any(
            t["goal"] == g["id"] and t["status"] in OPEN for t in plan["tasks"]
        ):
            out.append(f'   no outlook yet: atr outlook {g["id"]} likely|unsure|unlikely "why"')
        b = g.get("budget")
        if b:
            left = [f"{b.get('used', 0)} of {b['tries']} tries used"] if b.get("tries") else []
            left += [f"{b['days']} days from {b['from'][:10]}"] if b.get("days") else []
            out.append(f"   budget: {', '.join(left)}")
        for p in g.get("prs", []):
            if p["state"] == "open":
                carries = f" for {', '.join(p['for'])}" if p["for"] else ""
                out.append(f"   PR #{p['number']}{carries}: {pr_words(p)} {p['url']}")
        for t in (t for t in plan["tasks"] if t["goal"] == g["id"]):
            bits = [f"after {', '.join(t['after'])}"] if t["after"] else []
            bits += [f"{d['id']} needs owner" for d in held_by(plan, t)]
            bits += [t["owner"]] if t["owner"] else []
            bits += [f"owner's reason: {t['pruned_why']}"] if t.get("pruned_why") else []
            out.append(
                f"   {t['id']:<4} {t['status']:<8} {t['title']}"
                + (f"  ({'; '.join(bits)})" if bits else "")
            )
            if t.get("now"):
                out.append(f"        now: {t['now']} ({ago(t['now_at'])})")
            elif t["status"] == "doing":
                out.append(f"        no news since it started {ago(t.get('doing_since'))}")
    if met:
        out.append(
            "MET (the owner closed these): "
            + ", ".join(f"{label(g)} {g['met_at'][:10]}" for g in met)
        )
    made = [d for d in plan["decisions"] if d["state"] in ("accepted", "to_review")]
    if made or overturned:
        out += ["", "DECISIONS (do not re-propose what was rejected):"]
        for d in made + overturned:
            tag = {
                "overturned": "OVERTURNED BY OWNER: ",
                "to_review": "(the owner said this in chat; not confirmed yet) "
                if d.get("said")
                else "(not reviewed yet) ",
            }.get(d["state"], "")
            rej = f" | rejected: {'; '.join(d['rejected'])}" if d["rejected"] else ""
            out.append(
                f"  - {d['id']} {d['on']}: {tag}{d['chosen']}{rej}"
                + (f" | owner: {d['note']}" if d["note"] else "")
            )
    yours = [
        t
        for t in plan["tasks"]
        if (t["status"] in ("todo", "doing") and owners_turn(t) and deps_done(plan, t))
        or t["status"] == "review"
    ]
    finished = [
        g
        for g in plan["goals"]
        if not g.get("proposed")
        and not g.get("met_at")
        and any(t["goal"] == g["id"] and t["status"] == "done" for t in plan["tasks"])
        and not any(t["goal"] == g["id"] and t["status"] in OPEN for t in plan["tasks"])
    ]
    if yours or finished or any(pr_turn(p) for g in plan["goals"] for p in g.get("prs", [])):
        out += [
            "",
            "THE OWNER'S TURN (only they can do these; do not start them): "
            + ", ".join(
                [label(t) for t in yours]
                + [f"say whether {g['id']} is met (all its tasks are done)" for g in finished]
                + [f"merge PR #{p['number']} on {g['id']}" for g in plan["goals"] for p in g.get("prs", []) if pr_turn(p)]
            ),
        ]
    nxt = ready(plan)
    running = sum(t["status"] == "doing" for t in plan["tasks"])
    out += [
        "",
        f"READY TO START ({running} of {MAX_RUNNING} running): "
        + (", ".join(label(t) for t in nxt) or "nothing"),
    ]
    return "\n".join(out)


def summary(plan):
    tasks = [t for t in plan["tasks"] if t["status"] not in ("parked", "dropped")]
    return {
        "name": plan["name"],
        "title": plan["title"],
        "rev": plan["rev"],
        "goals": sum(not g.get("proposed") for g in plan["goals"]),
        "met": sum(bool(g.get("met_at")) for g in plan["goals"]),
        "tasks": len(tasks),
        "done": sum(t["status"] == "done" for t in tasks),
        "running": sum(t["status"] == "doing" for t in tasks),
        "needs_you": sum(d["state"] == "needs_you" for d in plan["decisions"])
        + sum(bool(g.get("proposed")) for g in plan["goals"])
        + sum(t["status"] == "review" for t in plan["tasks"])
        + sum(pr_turn(p) for g in plan["goals"] for p in g.get("prs", [])),
        "to_review": sum(d["state"] == "to_review" for d in plan["decisions"]),
        "unread": sum(c["by"] == "you" for c in unread(plan)),
        "lead_waiting": waiting(plan["name"]),
    }


def sig(plan):
    # What GitHub says of a PR is stored without a new revision, so the PRs are in the signature too.
    prs = zlib.crc32(json.dumps([g.get("prs") for g in plan["goals"]], sort_keys=True).encode())
    return f"{plan['rev']}.{plan['lead']['read_rev']}.{sum(bool(t.get('stopped')) for t in plan['tasks'])}.{int(waiting(plan['name']))}.{prs:x}"


# ---- web -----------------------------------------------------------------------------------------


# ---- versions: is there a newer atr, and how this one upgrades itself ---------------------------------------

RELEASES = "https://api.github.com/repos/mvexel/atr/releases/latest"
CHECK_EVERY = 6 * 3600


def version():
    """The version this atr runs: the checkout's pyproject.toml, else the installed package's."""
    pyproject = HERE.parent.parent / "pyproject.toml"
    if pyproject.is_file():
        import tomllib

        with contextlib.suppress(OSError, ValueError, KeyError):
            return tomllib.loads(pyproject.read_text())["project"]["version"]
    from importlib import metadata

    try:
        return metadata.version("atr")
    except metadata.PackageNotFoundError:
        return "0"


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v.split("-")[0])[:3]) or (0,)


def newer(latest, current):
    """True when release tag `latest` (v0.4.0) is a later version than `current`."""
    return bool(latest) and vtuple(latest) > vtuple(current)


def latest_release():
    """{"version", "url"} of the latest GitHub release, or None when GitHub does not answer."""
    import urllib.request

    try:
        req = urllib.request.Request(RELEASES, headers={"Accept": "application/vnd.github+json", "User-Agent": "atr"})
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read())
        return {"version": body["tag_name"].lstrip("v"), "url": body.get("html_url", "")}
    except (OSError, ValueError, KeyError):
        return None


def check_release(now=None):
    """One round of the release check: ask GitHub unless it was asked less than 6 h ago (by this server or the
    one before a restart), and keep what it said in Handler.latest. Returns the seconds until the next round.
    When GitHub does not answer, the page hears nothing and atr asks again in 6 h."""
    now = time.time() if now is None else now
    cache = data_dir() / ".release.json"
    try:
        seen = json.loads(cache.read_text())
    except (OSError, ValueError):
        seen = {}
    if seen.get("latest"):
        Handler.latest = seen["latest"]
    wait = seen.get("checked", -CHECK_EVERY) + CHECK_EVERY - now
    if 0 < wait <= CHECK_EVERY:  # more than 6 h ahead: the clock went back, so ask
        return wait
    found = latest_release()
    if found:
        Handler.latest = found
    with contextlib.suppress(OSError):
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"checked": now, "latest": found or seen.get("latest")}))
    return CHECK_EVERY


def watch_releases():
    """For atr serve: check for a newer release now and every 6 h, in the background, so the page never waits."""
    import threading

    def loop():
        while True:
            time.sleep(check_release())

    threading.Thread(target=loop, daemon=True).start()


# ---- pull requests: what GitHub says of them, through the owner's gh ----------------------------------------

PR_EVERY, PR_SLOW = 15, 60  # seconds between rounds; slow when under a fifth of the hourly limit is left
CI_STATES = {"SUCCESS": "passing", "FAILURE": "failing", "ERROR": "failing", "PENDING": "pending", "EXPECTED": "pending"}


def pr_query(prs):
    """One GraphQL query for all of `prs` [(owner, repo, number)], aliased p0, p1, ..., and the rate limit.
    pr_parse only lets letters, digits, '.', '_' and '-' into owner and repo, so they cannot break the query."""
    fields = "state isDraft mergeable commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }"
    return "query { rateLimit { limit remaining } " + " ".join(
        f'p{i}: repository(owner: "{o}", name: "{r}") {{ pullRequest(number: {n}) {{ {fields} }} }}'
        for i, (o, r, n) in enumerate(prs)
    ) + " }"


def gh_graphql(query):
    """The data gh returns for `query`, or None without gh or when it fails. A PR GitHub cannot find comes back
    as null beside the others (gh exits 1 then, but still prints the data)."""
    gh = shutil.which("gh")
    if not gh:
        return None
    try:
        r = subprocess.run([gh, "api", "graphql", "-f", f"query={query}"], capture_output=True, text=True, timeout=30, check=False)
        data = json.loads(r.stdout).get("data")
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None
    return data if isinstance(data, dict) else None


def pr_fields(pr):
    """What the poller stores of one pullRequest from the query; {"known": False} when there is none."""
    if not isinstance(pr, dict):
        return {"known": False}
    nodes = (pr.get("commits") or {}).get("nodes") or [{}]
    rollup = ((nodes[0] or {}).get("commit") or {}).get("statusCheckRollup") or {}
    return {
        "known": True,
        "state": (pr.get("state") or "open").lower(),
        "draft": bool(pr.get("isDraft")),
        "mergeable": (pr.get("mergeable") or "unknown").lower(),
        "ci": CI_STATES.get(rollup.get("state"), "none"),
    }


def check_prs():
    """One round of the PR poll: one gh query for the open PRs of all projects. A plan is written only when
    what GitHub says differs from what it holds. Returns the seconds until the next round."""
    found = []
    for name in projects():
        with contextlib.suppress(OSError, ValueError, Refused):
            for g in load(name)["goals"]:
                found += [(name, p, pr_parse(p["url"])) for p in g.get("prs", []) if p["state"] == "open"]
    if not found:
        return PR_EVERY
    data = gh_graphql(pr_query([where for *_, where in found])) or {}
    for i, (name, p, _) in enumerate(found):
        seen = pr_fields((data.get(f"p{i}") or {}).get("pullRequest"))
        if any(p.get(k) != v for k, v in seen.items()):
            with contextlib.suppress(OSError, ValueError, Refused):
                change(name, "github", op_pr_seen, {"url": p["url"], **seen})
    limit = data.get("rateLimit") or {}
    try:
        slow = limit["remaining"] < 0.2 * limit["limit"]
    except (KeyError, TypeError):
        slow = False
    return PR_SLOW if slow else PR_EVERY


def watch_prs():
    """For atr serve: poll the open PRs in the background, so the page never waits on gh."""
    import threading

    def loop():
        while True:
            try:
                wait = check_prs()
            except Exception as e:  # noqa: BLE001 - a bad round must not end the poll
                print(f"atr: PR check failed: {e}", file=sys.stderr, flush=True)
                wait = PR_SLOW
            time.sleep(wait)

    threading.Thread(target=loop, daemon=True).start()


def install_kind():
    """How this atr is installed: 'checkout' (a git clone, linked by atr install), 'uv' (uv tool install),
    or '' when atr cannot tell."""
    if (HERE.parent.parent / ".git").exists():
        return "checkout"
    if "tools" in Path(sys.prefix).parts and Path(sys.prefix).name == "atr":
        return "uv"
    return ""


def upgrade_steps():
    """The commands that upgrade this atr, as (what, argv, needed). The page never sends a command: only these
    run. A step that is not needed (the Claude Code plugin) may fail without failing the upgrade."""
    kind, root = install_kind(), HERE.parent.parent
    if kind == "checkout":
        git = ["git", "-C", str(root)]
        branch = subprocess.run([*git, "branch", "--show-current"], capture_output=True, text=True, check=False)
        if branch.stdout.strip() != "main":
            raise Refused(f"the atr checkout at {root} is not on main: upgrade it by hand")
        dirty = subprocess.run([*git, "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, check=False)
        if dirty.returncode or dirty.stdout.strip():
            raise Refused(f"the atr checkout at {root} has local changes: upgrade it by hand")
        steps = [("atr", [*git, "pull", "--ff-only"], True)]
    elif kind == "uv":
        uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
        steps = [("atr", [uv, "tool", "upgrade", "atr"], True)]
    else:
        raise Refused("atr cannot tell how it was installed: upgrade it the way you installed it")
    claude = shutil.which("claude")
    if claude:
        listed = subprocess.run([claude, "plugin", "list"], capture_output=True, text=True, timeout=60, check=False)
        if "atr@atr" in listed.stdout:
            steps.append(("the Claude Code plugin", [claude, "plugin", "update", "atr@atr"], False))
    return steps


def upgrade():
    """Run upgrade_steps(); returns (ok, report lines)."""
    lines, ok = [], True
    for what, argv, needed in upgrade_steps():
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=300, check=False)
            said = (r.stdout + r.stderr).strip().splitlines()
            done = r.returncode == 0
        except (OSError, subprocess.SubprocessError) as e:
            said, done = [str(e)], False
        lines.append(f"{what}: {'upgraded' if done else 'failed'}" + (f" ({said[-1]})" if said else ""))
        ok = ok and (done or not needed)
    return ok, lines


def restart():
    """Replace this process with a fresh one running the same command: the new code, the same port.
    Under launchd or systemd it stays the same service; in a terminal it keeps the terminal."""
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])


def code_stamp():
    """What the code on disk looks like now; the server compares it with the stamp it started with."""
    st = Path(__file__).resolve().stat()
    return (st.st_mtime_ns, st.st_size)


class Handler(BaseHTTPRequestHandler):
    allowed_hosts: ClassVar[set[str]] = set()
    started_with: ClassVar[tuple] = ()
    latest: ClassVar[dict] = {}
    restart = staticmethod(restart)  # tests replace it
    server_version = "atr"

    def log_message(self, format, *a):
        pass

    def send_json(self, body, code=200):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def host_ok(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in self.allowed_hosts

    def do_GET(self):
        if not self.host_ok():
            return self.send_json(
                {"error": "host not allowed; start atr serve with --allow-host NAME"},
                403,
            )
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        try:
            if not parts:
                raw = (HERE / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(raw)
            if parts == ["api", "projects"]:
                return self.send_json([summary(load(n)) for n in projects()])
            if parts == ["api", "sig"]:
                # "" is not a project name, so it can carry the server's own state.
                return self.send_json(
                    {n: sig(load(n)) for n in projects()}
                    | {
                        "": {
                            "outdated": code_stamp() != self.started_with,
                            "version": version(),
                            "latest": self.latest if newer(self.latest.get("version"), version()) else None,
                        }
                    }
                )
            if len(parts) == 3 and parts[:2] == ["api", "p"]:
                plan = load(parts[2])
                return self.send_json(
                    {
                        "plan": plan,
                        "unread": unread(plan),
                        "lead_waiting": waiting(parts[2]),
                        "lead_claim": read_claim(parts[2]),
                        "ready": [t["id"] for t in ready(plan)],
                        "sig": sig(plan),
                    }
                )
            if len(parts) == 4 and parts[:2] == ["api", "doc"]:
                doc = get(load(parts[2]), "docs", parts[3])
                path = project_dir(parts[2]) / "docs" / doc.get("file", "")
                if "file" not in doc or not path.is_file():
                    raise Refused("that document is a link, or its file is gone")
                data = path.read_bytes()[:1_000_000]
                try:
                    return self.send_json(
                        {"title": doc["title"], "text": data.decode()}
                    )
                except UnicodeDecodeError:
                    return self.send_json(
                        {"title": doc["title"], "text": "", "binary": True}
                    )
        except Refused as e:
            return self.send_json({"error": str(e)}, 404)
        self.send_json({"error": "not found"}, 404)

    def upgrade_or_restart(self, what):
        """POST /api/upgrade runs the upgrade for how atr is installed, then restarts; /api/restart only restarts
        (the code on disk changed under a running server). The answer goes out before the restart."""
        import threading

        try:
            if what == "upgrade":
                if not newer(self.latest.get("version"), version()):
                    raise Refused("there is no newer atr to upgrade to")
                ok, lines = upgrade()
                if not ok:
                    return self.send_json({"error": "The upgrade did not finish: " + "; ".join(lines), "log": lines}, 500)
            else:
                lines = []
        except Refused as e:
            return self.send_json({"error": str(e)}, 400)
        self.send_json({"ok": True, "log": lines, "restarting": True})
        self.wfile.flush()
        threading.Timer(0.5, type(self).restart).start()

    def do_POST(self):
        # The custom header forces a browser preflight, which this server never grants: other sites cannot post here.
        if not self.host_ok() or self.headers.get("X-Atr") != "1":
            return self.send_json({"error": "not allowed"}, 403)
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        if parts in (["api", "upgrade"], ["api", "restart"]):
            return self.upgrade_or_restart(parts[1])
        try:
            body = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"
            )
            if (
                len(parts) != 3
                or parts[:2] != ["api", "p"]
                or body.get("op") not in OPS
            ):
                return self.send_json({"error": "not found"}, 404)
            plan, _ = change(
                parts[2],
                "you",
                OPS[body["op"]],
                body.get("args") or {},
                base_rev=body.get("rev"),
            )
            self.send_json({"ok": True, "rev": plan["rev"]})
        except Stale:
            self.send_json(
                {
                    "error": "The plan changed while you were looking at it. It has been reloaded: check it, then do that again (what you typed is kept).",
                    "stale": True,
                },
                409,
            )
        except Refused as e:
            self.send_json({"error": str(e)}, 400)
        except (ValueError, KeyError) as e:
            self.send_json({"error": f"bad request: {e}"}, 400)


# ---- command line --------------------------------------------------------------------------------


def install(where):
    """Link `where`/atr to the checkout's bin/atr, so a git pull updates the installed atr too."""
    me, link = HERE.parent.parent / "bin" / "atr", where / "atr"
    if not me.exists():
        raise Refused(
            "this atr is an installed package, not a checkout: uv tool install <repo> puts `atr` on your PATH"
        )
    if link.is_symlink() and link.resolve() == me.resolve():
        print(f"{link} already points at {me}")
    elif link.exists() or link.is_symlink():
        raise Refused(f"{link} exists and is not this atr; move it away first")
    else:
        where.mkdir(parents=True, exist_ok=True)
        link.symlink_to(me)
        print(f"linked {link} -> {me}")
    for provider in sorted((HERE.parent.parent / "extensions").glob("*/bin/atr-lead-*")):
        plink = where / provider.name
        if plink.is_symlink() and plink.resolve() == provider.resolve():
            continue
        if plink.exists() or plink.is_symlink():
            print(f"{plink} exists and is not this atr's; left it alone")
            continue
        plink.symlink_to(provider)
        print(f"linked {plink} -> {provider}")
    dirs = [Path(p).expanduser().resolve() for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if where.resolve() not in dirs:
        print(f"{where} is not on your PATH: add it in your shell profile, e.g. export PATH=\"{where}:$PATH\"")


def serve_command():
    """The command a background service runs: this Python, this atr. Not a throwaway `uvx` environment."""
    py = Path(sys.executable)
    if any(p.startswith("archive-v") for p in py.parts):
        raise Refused("this atr runs from a temporary uvx environment: uv tool install it first")
    launcher = HERE.parent.parent / "bin" / "atr"
    return [str(py), str(launcher)] if launcher.exists() else [str(py), "-m", "atr"]


def service_files(cmd, env, home, system):
    """(path, text, start, stop) for a login service running `cmd`; pure, so it can be tested."""
    if system == "Darwin":
        path = home / "Library/LaunchAgents/atr.serve.plist"
        esc = lambda x: x.replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
        args = "".join(f"\n    <string>{esc(a)}</string>" for a in cmd)
        envs = "".join(f"\n    <key>{k}</key><string>{esc(v)}</string>" for k, v in env.items())
        text = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            f"<plist version=\"1.0\"><dict>\n  <key>Label</key><string>atr.serve</string>\n"
            f"  <key>ProgramArguments</key><array>{args}\n  </array>\n"
            + (f"  <key>EnvironmentVariables</key><dict>{envs}\n  </dict>\n" if env else "")
            + "  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><true/>\n"
            "  <key>StandardErrorPath</key><string>/tmp/atr.log</string>\n</dict></plist>\n"
        )
        dom = f"gui/{os.getuid()}"
        return (
            path,
            text,
            [["launchctl", "bootout", dom, str(path)], ["launchctl", "bootstrap", dom, str(path)]],
            [["launchctl", "bootout", dom, str(path)]],
        )
    path = home / ".config/systemd/user/atr.service"
    q = lambda x: '"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"'  # noqa: E731
    text = (
        "[Unit]\nDescription=atr page\n\n[Service]\n"
        + "".join(f"Environment={q(f'{k}={v}')}\n" for k, v in env.items())
        + f"ExecStart={' '.join(q(a) for a in cmd)}\nRestart=on-failure\n\n"
        "[Install]\nWantedBy=default.target\n"
    )
    return (
        path,
        text,
        [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", "atr.service"]],
        [["systemctl", "--user", "disable", "--now", "atr.service"]],
    )


def service(a):
    """Install or remove a login service that keeps `atr serve` running."""
    import platform

    system = platform.system()
    if system not in ("Darwin", "Linux"):
        raise Refused(f"no service support on {system}")
    cmd = [*serve_command(), "serve", "--host", a.host, "--port", str(a.port)]
    for h in a.allow_host:
        cmd += ["--allow-host", h]
    env = {"ATR_DATA_DIR": os.environ["ATR_DATA_DIR"]} if os.environ.get("ATR_DATA_DIR") else {}
    path, text, start, stop = service_files(cmd, env, Path.home(), system)
    if a.action == "uninstall":
        for c in stop:
            subprocess.run(c, check=False, capture_output=True)
        path.unlink(missing_ok=True)
        return print(f"removed {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():  # stop the old one first, so a changed host or port takes effect
        for c in stop:
            subprocess.run(c, check=False, capture_output=True)
    path.write_text(text)
    for c in start:
        r = subprocess.run(c, check=False, capture_output=True, text=True)
        if r.returncode and c[1] not in ("bootout",):
            raise Refused(f"{' '.join(c)} failed: {r.stderr.strip()}")
    print(f"wrote {path}\natr serve now runs at login and restarts if it stops: http://{a.host}:{a.port}/")
    print("after upgrading atr, run `atr service install` again to restart it on the new code")


def lead_providers():
    """Programs named atr-lead-<tool> on PATH, by tool: each starts a lead thread in one agent tool."""
    found = {}
    for d in os.environ.get("PATH", "").split(os.pathsep):
        try:
            entries = sorted(Path(d).glob("atr-lead-*")) if d else []
        except OSError:
            continue
        for exe in entries:
            tool = exe.name.removeprefix("atr-lead-")
            if tool and tool not in found and exe.is_file() and os.access(exe, os.X_OK):
                found[tool] = exe
    return found


def start_lead(name, tool="auto"):
    """Start the project's lead thread through a provider and store the link it prints.

    Returns a line for the owner. Never raises for a provider's failure: a project without a lead is still a project.
    """
    found = lead_providers()
    if tool == "auto":
        if not found:
            return "No lead provider (atr-lead-<tool>) on your PATH: start your lead agent here and have it run `atr lead LINK`."
        if len(found) > 1:
            return f"Several lead providers: {', '.join(found)}. Start one with `atr lead --start TOOL`."
        tool = next(iter(found))
    if tool not in found:
        return f"No atr-lead-{tool} on your PATH" + (f" (found: {', '.join(found)})" if found else "") + "."
    plan = load(name)
    try:
        r = subprocess.run(
            [str(found[tool]), name, plan["title"]],
            cwd=plan.get("repo") or None,
            env={**{k: v for k, v in os.environ.items() if k != "ATR_AS"}, "ATR_PROJECT": name},
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return f"atr-lead-{tool} could not start the lead: {e}"
    lines = [x.strip() for x in r.stdout.strip().splitlines()]
    link = (lines or [""])[-1]
    thread = next((x.split(":", 1)[1].strip() for x in lines if x.startswith("thread-id:")), "")
    if r.returncode or not link:
        why = (r.stderr.strip() or r.stdout.strip() or f"exit {r.returncode}").splitlines()[-1]
        return f"atr-lead-{tool} did not start the lead: {why}\nTo try again: atr lead --start {tool}"
    change(name, "agent", op_lead, {"thread": link})
    if thread:  # the owner started this thread to lead: it takes over from any lead there was
        release(name)
        claim(name, thread)
    return f"started the lead in {tool}: {link}"


def repo_root(here):
    """The git checkout `here` is in (its main checkout, for a worktree), or `here` outside git."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=here,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if r.returncode == 0:
            return Path(r.stdout.strip()).parent.resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return here.resolve()


def op_set_repo(plan, by, a):
    plan["repo"] = a["repo"]  # bookkeeping, not news: no note


def wrong_folder(plan):
    """A warning when the lead works on this project from outside its repo: the turn hooks key on the
    folder a session runs in, so they stay silent for this project."""
    repo = plan.get("repo")
    if not repo:
        return ""
    here = repo_root(Path.cwd())
    if here == Path(repo) or Path(repo) in here.parents:
        return ""
    return (
        f"NOTE: you are in {here}, but {plan['name']}'s repo is {repo}. The atr hooks only see the project "
        f"of the folder a session runs in, so the owner's changes will not reach you by themselves: "
        f"lead it from {repo}.\n"
    )


def find_project(explicit):
    if explicit or os.environ.get("ATR_PROJECT"):
        return explicit or os.environ["ATR_PROJECT"]
    here = Path.cwd()
    roots = [here, *here.parents]
    try:  # a worktree may not have the pointer file; the main checkout does
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if common.returncode == 0:
            roots.append(Path(common.stdout.strip()).parent)
    except (OSError, subprocess.SubprocessError):
        pass
    for d in roots:
        if (d / ".atr").is_file():
            return (d / ".atr").read_text().strip()
    raise Refused(
        "which project? Run from a folder with a .atr file, or pass -p NAME (atr projects lists them)"
    )


def report(a):
    """atr unread / atr wait."""
    name = find_project(a.project)
    found = unread(load(name)) if a.cmd == "unread" else wait(name, a.timeout)
    if a.json:
        plan = load(name)
        print(
            json.dumps(
                {
                    "project": name,
                    "lead_thread": plan["lead"]["thread"],
                    "lead_id": read_claim(name).get("id", ""),
                    "lead_waiting": waiting(name),
                    "unread": found,
                    "running": running(plan),
                }
            )
        )
    else:
        print("\n".join(c["what"] for c in found))
    return 0 if found else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="atr", description="A goal tree, tasks and decisions for a team of agents."
    )
    ap.add_argument("--version", action="version", version=f"atr {version()}")
    ap.add_argument(
        "-p",
        "--project",
        help="project name (default: the .atr file in this repo, or ATR_PROJECT)",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("init", help="create a project and point this folder at it")
    x.add_argument("name")
    x.add_argument("title", nargs="?")
    x.add_argument(
        "--lead",
        default="auto",
        metavar="TOOL",
        help="start the lead thread with atr-lead-TOOL (default auto: the one provider on PATH; none: skip)",
    )
    x = sub.add_parser("install", help="put atr on your PATH (a link to this file)")
    x.add_argument("--dir", default="~/.local/bin", help="where the link goes (default ~/.local/bin)")
    x = sub.add_parser("service", help="keep `atr serve` running in the background (launchd or systemd)")
    x.add_argument("action", choices=["install", "uninstall"])
    x.add_argument("--host", default="127.0.0.1")
    x.add_argument("--port", type=int, default=8787)
    x.add_argument("--allow-host", action="append", default=[], help="as for atr serve")
    sub.add_parser("rules", help="print the rule block for AGENTS.md / CLAUDE.md")
    sub.add_parser("projects", help="list projects")
    x = sub.add_parser("serve", help="run the page")
    x.add_argument("--host", default="127.0.0.1")
    x.add_argument("--port", type=int, default=8787)
    x.add_argument(
        "--allow-host",
        action="append",
        default=[],
        help="extra hostname the page may be opened under (e.g. a tailnet name)",
    )
    x = sub.add_parser(
        "read", help="the plan, and what the owner changed since you last read"
    )
    x.add_argument("--peek", action="store_true", help="do not mark as read")
    x = sub.add_parser(
        "unread",
        help="for plugins: owner changes the lead has not read (exit 1 when none)",
    )
    x.add_argument("--json", action="store_true")
    x = sub.add_parser(
        "wait",
        help="for plugins: block until the owner changes something the lead has not read (exit 1 on timeout)",
    )
    x.add_argument("--timeout", type=float, default=3600, help="seconds (default 3600)")
    x.add_argument("--json", action="store_true")
    sub.add_parser("next", help="unblocked tasks to start now")
    x = sub.add_parser("goal", help="propose a goal to the owner")
    x.add_argument("action", choices=["propose", "add"])
    x.add_argument("title")
    x.add_argument("--done", default="")
    x.add_argument("--tries", help="attempts the goal gets before the owner is asked how to go on")
    x.add_argument("--days", help="days the goal gets before the owner is asked how to go on")
    x = sub.add_parser(
        "outlook", help="say how likely a goal is to be met as written, and why"
    )
    x.add_argument("id")
    x.add_argument("level", help="likely, unsure or unlikely")
    x.add_argument("text", nargs="+")
    x = sub.add_parser("try", help="record one attempt at a goal (counts against its tries)")
    x.add_argument("id")
    x.add_argument("text", nargs="+")
    x = sub.add_parser("task", help="add or update a task")
    x.add_argument("action", choices=["add", "set", "stopped"])
    x.add_argument("args", nargs="+")
    x.add_argument(
        "--after",
        action="append",
        default=[],
        help="task(s) this one waits for; repeat or comma-separate (T1,T2)",
    )
    x = sub.add_parser("decide", help="record a judgment call")
    x.add_argument("on", help="task or goal id, or 'project'")
    x.add_argument("chosen")
    x.add_argument("--why", default="")
    x.add_argument("--rejected", action="append", default=[])
    x.add_argument("--question", default="")
    x.add_argument(
        "--hard",
        action="store_true",
        help="hard to undo: ask the owner instead of acting",
    )
    x.add_argument(
        "--owner", action="store_true", help="the owner decided this in conversation"
    )
    x.add_argument(
        "--by", default="", metavar="WORKER", help="a worker records its own call (its name)"
    )
    x = sub.add_parser(
        "ask", help="ask the owner a plain question with no recommendation (holds the task or goal)"
    )
    x.add_argument("on", help="task or goal id, or 'project'")
    x.add_argument("question")
    x.add_argument("--option", action="append", default=[], help="a possible answer (repeat); they can also write their own")
    x.add_argument("--why", default="", help="why you need to know")
    x = sub.add_parser("attach", help="link a document to a task or goal")
    x.add_argument("on")
    x.add_argument("src", help="file path or http(s) link")
    x.add_argument("--title")
    x = sub.add_parser(
        "now", help="say what is happening on a running task (workers may use this)"
    )
    x.add_argument("id")
    x.add_argument("text", nargs="+")
    x = sub.add_parser("pr", help="put a pull request you opened on its goal (workers may use this)")
    x.add_argument("goal")
    x.add_argument("url")
    x.add_argument(
        "--for", dest="for_", action="append", default=[], metavar="TASK",
        help="task(s) the PR carries; they go to done when it merges (repeat or comma-separate)",
    )
    x = sub.add_parser("lead", help="store the lead's thread link, or start a lead thread (--start)")
    x.add_argument("thread", nargs="?")
    x.add_argument("--start", metavar="TOOL", help="start the lead thread with atr-lead-TOOL ('auto': the one on PATH)")
    x.add_argument("--claim", metavar="ID", help="for extensions: make thread ID the lead unless another thread is (exit 1)")
    x.add_argument("--release", metavar="ID", help="for extensions: thread ID stops leading (its session ended)")
    x.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    by = "you" if os.environ.get("ATR_AS") == "you" else "agent"
    try:
        if a.cmd == "install":
            return install(Path(a.dir).expanduser())
        if a.cmd == "service":
            return service(a)
        if a.cmd == "rules":
            return print(RULES, end="")
        if a.cmd == "projects":
            for n in projects():
                s = summary(load(n))
                print(
                    f"{n:<24} {s['done']}/{s['tasks']} done · {s['needs_you']} waiting on owner · {s['to_review']} to review · {s['title']}"
                )
            return
        if a.cmd == "serve":
            Handler.allowed_hosts = {
                "localhost",
                "127.0.0.1",
                "::1",
                a.host.lower(),
                *(h.lower() for h in a.allow_host),
            }
            Handler.started_with = code_stamp()
            if os.environ.get("ATR_UPDATE_CHECK") != "0":
                watch_releases()
            if os.environ.get("ATR_PR_CHECK") != "0":
                watch_prs()
            print(f"atr: {data_dir()} at http://{a.host}:{a.port}/", flush=True)
            return ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()
        if a.cmd == "init":
            d = project_dir(a.name)
            if (d / "plan.json").exists():
                raise Refused(f"project '{a.name}' already exists")
            d.mkdir(parents=True)
            save(
                {
                    "name": a.name,
                    "title": a.title or a.name,
                    "rev": 0,
                    "lead": {"thread": "", "read_rev": 0, "read_at": ""},
                    "goals": [],
                    "tasks": [],
                    "decisions": [],
                    "docs": [],
                    "changes": [],
                    "seq": {"G": 0, "T": 0, "D": 0, "A": 0},
                    "repo": str(repo_root(Path.cwd())),
                }
            )
            if not Path(".atr").exists():
                Path(".atr").write_text(a.name + "\n")
            print(f"created {d}\nwrote .atr here (commit it).")
            if a.lead != "none":
                print(start_lead(a.name, a.lead))
            return print("Next: add goals on the page (atr serve), and add `atr rules` to AGENTS.md or CLAUDE.md.")
        if a.cmd in ("unread", "wait"):
            return report(a)
        name = find_project(a.project)
        if a.cmd == "read":
            plan = load(name)
            if not plan.get("repo") and not (a.project or os.environ.get("ATR_PROJECT")):
                # found through this folder's .atr: this is the project's repo (projects made before atr kept it)
                plan = change(name, by, op_set_repo, {"repo": str(repo_root(Path.cwd()))})[0]
            print(wrong_folder(plan) + render(plan, unread(plan)))
            if not a.peek:
                change(name, by, op_mark_read)
            return
        if a.cmd == "next":
            return print(
                "\n".join(label(t) for t in ready(load(name))) or "nothing is ready"
            )
        if a.cmd == "goal":
            if a.action == "add" and by != "you":
                raise Refused("only the owner adds goals; use: atr goal propose")
            fn, args = op_goal_add, {
                "title": a.title,
                "done_when": a.done,
                "tries": a.tries,
                "days": a.days,
            }
        elif a.cmd == "outlook":
            fn, args = op_goal_outlook, {"id": a.id, "level": a.level, "text": " ".join(a.text)}
        elif a.cmd == "try":
            fn, args = op_goal_try, {"id": a.id, "text": " ".join(a.text)}
        elif a.cmd == "task" and a.action == "add":
            if len(a.args) != 2:
                raise Refused('usage: atr task add G1 "title" [--after T1,T2]')
            fn, args = (
                op_task_add,
                {
                    "goal": a.args[0],
                    "title": a.args[1],
                    "after": [d for s in a.after for d in s.split(",") if d],
                },
            )
        elif a.cmd == "task" and a.action == "stopped":
            fn, args = op_task_stopped, {"id": a.args[0], "note": " ".join(a.args[1:])}
        elif a.cmd == "task":
            pairs = dict(p.split("=", 1) for p in a.args[1:] if "=" in p)
            after = [
                d for s in [*a.after, pairs.pop("after", "")] for d in s.split(",") if d
            ]
            if (not pairs and not after) or set(pairs) - {
                "status",
                "title",
                "owner",
                "thread",
                "note",
            }:
                raise Refused(
                    "usage: atr task set T1 status=doing [owner=.. thread=.. title=.. note=.. after=T2,T3]"
                )
            fn, args = op_task_set, {"id": a.args[0], **pairs, "after": after}
        elif a.cmd == "decide":
            fn, args = (
                op_decide,
                {
                    "on": a.on,
                    "chosen": a.chosen,
                    "why": a.why,
                    "rejected": a.rejected,
                    "question": a.question,
                    "hard": a.hard,
                    "owner": a.owner,
                    "worker": a.by,
                },
            )
        elif a.cmd == "ask":
            fn, args = op_decide, {"on": a.on, "question": a.question, "options": a.option, "why": a.why, "ask": True}
        elif a.cmd == "attach":
            fn, args = op_attach, {"on": a.on, "src": a.src, "title": a.title}
        elif a.cmd == "now":
            fn, args = op_task_now, {"id": a.id, "text": " ".join(a.text)}
        elif a.cmd == "pr":
            fn, args = op_pr, {"goal": a.goal, "url": a.url, "for": [t for s in a.for_ for t in s.split(",") if t]}
        elif a.start:
            return print(start_lead(name, a.start))
        elif a.claim:
            ok, who = claim(name, a.claim)
            if a.json:
                print(json.dumps({"lead": ok, **who}))
            elif ok:
                print(f"you lead {name}")
            else:
                print(f"thread {who['id']} leads {who['project']} (seen {ago_s(who['seen'])})")
            return 0 if ok else 1
        elif a.release:
            return print("released" if release(name, a.release) else "this thread does not lead the project")
        elif not a.thread:
            raise Refused("usage: atr lead LINK, or atr lead --start TOOL")
        else:
            fn, args = op_lead, {"thread": a.thread}
        if a.cmd == "decide" and a.by:
            by = f"worker:{a.by}"
        _, note = change(name, by, fn, args)
        print(note or "no change")
    except Refused as e:
        print(f"atr: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
