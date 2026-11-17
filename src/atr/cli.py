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
import threading
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
except that a worker may report progress on its own task, `atr now T3 "what is happening"` (its first
report adds `--thread ID`, the session it runs in, unless the task already has one),
record its own judgment calls with its name: `atr decide T3 "..." --why "..." --by worker-name`,
and put a pull request it opened on its goal (rule 7).

1. Run `atr read` when a turn starts and again before it ends. Act on what the owner changed.
2. Every task belongs to a goal: `atr task add G1 "title" --after T2`. Work that fits no goal is
   proposed with `atr goal propose "title" --done "what makes it done"`, not started.
   When you pick up a goal that has no tasks yet, first add a task for planning it and set it to
   doing, before you research anything, so the page shows the goal was picked up.
3. Never change goals. Keep status current: `atr task set T3 status=doing thread=ID`, where ID is the
   thread (session id, or link) of the worker you started for it, so atr can check on it and bring it back.
   While a task runs, say what is happening every few steps, in a few words: `atr now T3 "scoring run 2 of 3"`.
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
   The note is the evidence the decisions do not hold (branch or PR, tests run, what you saw), not the
   choices again: the owner sees the task's decisions beside it, and checking the task accepts them too.
   A task you set to done while it has decisions the owner has not reviewed goes to review instead,
   and is done once they accept them (an overturn sends it back to you).
   Attach what you write for the owner: `atr attach T3 path/to/findings.md`.
7. Right after opening a pull request, put it on its goal with the tasks it carries:
   `atr pr G1 https://github.com/o/r/pull/12 --for T3`, and set those tasks to review. The owner merges
   it on GitHub: that is their check, so such a task needs no review note and gets no check of its own;
   the merge moves it to done and accepts its decisions (never the goal: that stays the owner's call).
   `atr read` tells you when it merges, its CI fails or it conflicts: fix those on the same branch.
   Tie each checklist box of the PR to the task that covers it (`--item T3='text of the box'`), or `--drop`
   one no task covers; atr ticks a box when its task is finished, and lists the boxes not yet tied.
   atr codes (G1, T3, D5) mean nothing on GitHub: PR titles, bodies and commits say what changed in words.
8. When `atr read` says a worker went silent (no news for 30 min) or ended, check it: `atr alive T3`.
   If it is not running, bring it back with `atr resume T3`, or set the task back to todo and say why.
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
            "thread": t["thread"],
            "silent": bool(t.get("silent_at")),
            "ended": bool(t.get("ended_at")),
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
    if os.environ.get("ATR_SIDE"):
        raise Refused(SIDE_ONLY_READS)
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
    """What the lead has not read: the owner's changes, news from GitHub about the project's PRs, and atr's own
    news about threads (a worker gone silent or ended, the lead brought back)."""
    return [
        c
        for c in plan["changes"]
        if c["by"] in ("you", "github", "atr") and c["rev"] > plan["lead"]["read_rev"]
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
    deadline, seen, check = time.monotonic() + timeout, {}, 0.0
    try:
        while True:
            if time.monotonic() >= check:  # a worker gone silent is news too: it wakes the lead
                check = time.monotonic() + 60
                for n in names:
                    with contextlib.suppress(OSError, ValueError, Refused):
                        check_silence(n)
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
                    (m.parent / ".listened").write_text(str(time.time()))  # the lead was there until now


# ---- the lead's claim: which thread leads a project (one lead per project, one project per lead) ----------
# Kept beside plan.json, not in it: the hooks refresh it every turn, and a plan revision per turn would
# make the owner's page edits stale while they type.

GONE_AFTER = 10 * 60  # a lead whose listener has been absent this long, with no turn either, is gone
SILENT_AFTER = 30 * 60  # a running task with no news this long is silent: the lead is told
RESUME_EVERY = 3600  # atr brings a gone lead back on its own at most this often


def claim_file(name):
    return project_dir(name) / "lead.json"


def raw_claim(name):
    """What lead.json holds: {"id", "seen", "tool"?, "ended"?}, or {}."""
    try:
        c = json.loads(claim_file(name).read_text())
        float(c["seen"])
        return c if c.get("id") else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def listened_at(name):
    """When the project's last `atr wait` ended (Unix time), or 0."""
    try:
        return float((project_dir(name) / ".listened").read_text())
    except (OSError, ValueError):
        return 0.0


def lead_status(name, ask=False):
    """How the lead thread is doing: {} when no thread has claimed the project, else the claim plus `state`:
    listening (its `atr wait` runs), working (it took a turn or listened under 10 min ago), running (its tool
    says the thread is alive, though it has not listened for 10 min) or gone (its session ended, or none of
    these for 10 min). `since` is when it was last seen, or when its session ended. With ask, the provider is
    asked whether a lead that looks gone is still running; without, only a recent answer is used."""
    c = raw_claim(name)
    if not c:
        return {}
    last = max(float(c["seen"]), listened_at(name))
    s = {**c, "since": float(c.get("ended") or last), "listening": waiting(name)}
    if s["listening"]:
        return {**s, "state": "listening"}
    if c.get("ended"):
        return {**s, "state": "gone", "why": "ended"}
    if time.time() - last < GONE_AFTER:
        return {**s, "state": "working"}
    if thread_alive(name, c["id"], ask) is True:
        return {**s, "state": "running"}
    return {**s, "state": "gone", "why": "silent"}


def read_claim(name, ask=False):
    """{"id", "seen", ...} for the thread that leads `name`, or {} when none does: a gone lead leads nothing."""
    s = lead_status(name, ask)
    return s if s and s["state"] != "gone" else {}


def same_thread(a, b):
    """True when two ids name one thread: a provider may print a short id that starts the full one
    (claude --bg prints 85aade68; the session's hooks get 85aade68-...)."""
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def write_claim(name, thread, tool="", c=None):
    c = c or {"id": thread, "seen": time.time(), **({"tool": tool} if tool else {})}
    tmp = claim_file(name).with_suffix(".tmp")
    tmp.write_text(json.dumps(c))
    os.replace(tmp, claim_file(name))


def claim(name, thread, tool=""):
    """Make `thread` the lead of `name` if it may be. Returns (is_lead, who leads): the thread may lead when
    the project has no live lead (none, or a gone one) or it already is the lead, and it leads no other project."""
    data_dir().mkdir(parents=True, exist_ok=True)
    with open(data_dir() / ".claim.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cur = read_claim(name, ask=True)
        if cur and not same_thread(cur["id"], thread):
            return False, {"id": cur["id"], "seen": cur["seen"], "project": name}
        for other in projects():
            c = read_claim(other) if other != name else {}
            if c and same_thread(c["id"], thread):
                return False, {"id": c["id"], "seen": c["seen"], "project": other}
        was = raw_claim(name)
        mine = was if same_thread(was.get("id"), thread) else {}
        # keep the full id once a hook has sent it, and the tool a provider started it in
        write_claim(name, max(thread, mine.get("id", ""), key=len), tool or mine.get("tool", ""))
        return True, {"id": raw_claim(name)["id"], "seen": raw_claim(name)["seen"], "project": name}


def release(name, thread=None):
    """Let go of the lead. A thread's own release (its session ended) keeps the claim, marked ended, so the
    page can say the lead is gone and atr can bring that thread back; the owner's release forgets it."""
    cur = raw_claim(name)
    if thread is None and cur:
        claim_file(name).unlink(missing_ok=True)
        return True
    if same_thread(cur.get("id"), thread) and not cur.get("ended"):
        write_claim(name, cur["id"], c={**cur, "ended": time.time()})
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
    if "thread" in said:  # a new thread on the task: what was said of the old one is past
        for k in ("silent_at", "ended_at"):
            t.pop(k, None)
    status = a.get("status")
    if status and status != t["status"]:
        if status not in AGENT_STATUSES:
            raise Refused(f"status is one of: {', '.join(AGENT_STATUSES)}")
        if t["status"] == "review" and status == "done" and by != "you":
            raise Refused(f"{t['id']} waits for the owner's check; only they can pass it")
        unreviewed = [d["id"] for d in plan["decisions"] if d["on"] == t["id"] and d["state"] == "to_review"]
        if status == "done" and by != "you" and unreviewed:
            # done only counts once the owner has seen the calls made on the way
            status = "review"  # the page lists the decisions beside the check: no note needed to name them
            t["awaits"] = unreviewed
        if status == "review" and by != "you" and not unreviewed and task_pr(plan, t, "merged"):
            status = "done"  # its PR is merged already: the owner checked it then
        if status == "review" and not (a.get("note") or t["note"] or t.get("awaits") or task_pr(plan, t, "open")):
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
        for k in ("silent_at", "ended_at"):  # a new run, or none: the old worker's silence is past
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
    if a.get("ok"):  # one judgment: the task is right, and so are the calls made on the way (G13)
        t["status"] = "done"
        settled = [d for d in plan["decisions"] if d["on"] == t["id"] and d["state"] == "to_review"]
        for d in settled:
            d.update(state="accepted", note="")
        return f"checked {label(t)}: it is right" + (f", accepting {', '.join(d['id'] for d in settled)}" if settled else "")
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
    for k in ("silent_at", "ended_at"):  # news: the worker is there
        t.pop(k, None)
    thread = (a.get("thread") or "").strip()
    if thread and not t["thread"]:  # a worker's first `atr now` says which thread it is
        t["thread"] = thread
        return f"{t['id']} now: {text} (thread {thread})"
    return f"{t['id']} now: {text}"


def minutes_since(ts):
    try:
        then = datetime.strptime(ts, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return 0
    return (datetime.now(UTC) - then).total_seconds() / 60


def op_task_silent(plan, by, a):
    """atr says a running task has had no news for 30 min: news for the lead, once per silence."""
    t = get(plan, "tasks", a["id"])
    last = t.get("now_at") or t.get("doing_since")
    if t["status"] != "doing" or t.get("silent_at") or minutes_since(last) * 60 < SILENT_AFTER:
        return None
    t["silent_at"] = now()
    return (
        f"{label(t)} has had no news for {round(minutes_since(last))} min: its worker may be gone. "
        + worker_steps(t)
    )


def worker_steps(t):
    if t["thread"]:
        return f"Check it (atr alive {t['id']}), bring it back (atr resume {t['id']}) or set it back: atr task set {t['id']} status=todo"
    return f"It has no thread, so atr cannot check it: if its worker is gone, set it back: atr task set {t['id']} status=todo"


def op_thread_ended(plan, by, a):
    """A thread's session ended (the extension says so): the running tasks it worked are news for the lead."""
    hit = [t for t in plan["tasks"] if t["status"] == "doing" and same_thread(t["thread"], a["thread"]) and not t.get("ended_at")]
    for t in hit:
        t["ended_at"] = now()
    return "; ".join(f"the worker of {label(t)} ended (its session closed). {worker_steps(t)}" for t in hit) or None


def op_note(plan, by, a):
    """News atr itself writes into the plan (the lead brought back, say)."""
    return a["what"]


def check_silence(name):
    """Write news for each running task that has gone silent. Returns how many."""
    plan, n = load(name), 0
    for t in plan["tasks"]:
        last = t.get("now_at") or t.get("doing_since")
        if t["status"] == "doing" and not t.get("silent_at") and last and minutes_since(last) * 60 >= SILENT_AFTER:
            n += bool(change(name, "atr", op_task_silent, {"id": t["id"]})[1])
    return n


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


IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
MAX_UPLOAD = 10 * 1024 * 1024


def attach_upload(name, on, filename, data):
    """The owner attaches an image from the page (pasted, dropped or picked): `data` is base64. It is stored like
    any attached file, and the lead sees it in atr read with its path, so it can look at it."""
    import base64

    suffix = Path(filename or "").suffix.lower()
    if suffix not in IMAGE_TYPES:
        raise Refused("only images (png, jpg, gif, webp) can be attached from the page")
    raw = base64.b64decode(data or "", validate=True)
    if not raw or len(raw) > MAX_UPLOAD:
        raise Refused("the image is empty or over 10 MB")
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).stem)[:60] or "image"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{stem}{suffix}"
        path.write_bytes(raw)
        return change(name, "you", op_attach, {"on": on or "project", "src": str(path), "title": path.name})


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


def task_pr(plan, t, state=None):
    """The PR that carries task t (atr pr --for), or None; with state, only a PR in that state."""
    for p in next((g.get("prs", []) for g in plan["goals"] if g["id"] == t["goal"]), []):
        if t["id"] in p["for"] and (state is None or p["state"] == state):
            return p
    return None


def check_of(plan, t):
    """Whether task t waits for the owner's own check: in review, and no open PR carries it (a PR is
    checked by merging it, so its tasks are not a second thing to check)."""
    return t["status"] == "review" and not task_pr(plan, t, "open")


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
    items = dict(a.get("items") or {})  # task -> the text of its checklist box (G14)
    drops = [x.strip() for x in a.get("drop") or [] if x.strip()]
    tasks = list(dict.fromkeys([*(a.get("for") or []), *items]))
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
        ties = {t: x for t, x in items.items() if (p.get("items") or {}).get(t) != x}
        dropped = [x for x in drops if x not in p.get("dropped", [])]
        if not (new or ties or dropped):
            return None
        p["for"] += new
        p["items"] = {**(p.get("items") or {}), **ties}
        p["ticked"] = [t for t in p.get("ticked", []) if t not in ties]  # a new tie is ticked afresh
        p["dropped"] = p.get("dropped", []) + dropped
        said = ([f"is also for {', '.join(new)}"] if new else []) + [f"ties {t} to '{x}'" for t, x in ties.items()]
        said += [f"drops '{x}'" for x in dropped]
        return f"PR #{number} on {g['id']} " + ", ".join(said)
    p = {"url": url, "repo": f"{owner}/{repo}", "number": number, "for": tasks, "by": by, "at": now(), "state": "open", "known": False}
    if items:
        p["items"] = items
    if drops:
        p["dropped"] = drops
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
    if a.get("boxes") is not None:
        p["boxes"] = a["boxes"]
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
        # merging is the owner's one judgment of the work (G13): the calls made on it are accepted with it
        accepted = [d for d in plan["decisions"] if d["on"] in done and d["state"] == "to_review"]
        for d in accepted:
            d.update(state="accepted", note="")
        return (f"{tag} was merged on GitHub" + (f"; {', '.join(done)} done" if done else "")
                + (f", accepting {', '.join(d['id'] for d in accepted)}" if accepted else "") + f" ({p['url']})")
    if a.get("state") == "closed":
        p.update(state="closed", closed_at=now())
        return None
    news = []
    if p["ci"] == "failing" and was.get("ci") != "failing":
        news.append("its CI is failing")
    if p["mergeable"] == "conflicting" and was.get("mergeable") != "conflicting":
        news.append("it conflicts with its base branch")
    return f"{tag}: {' and '.join(news)} ({p['url']})" if news else None


# ---- PR checklists: a box ticks when the task tied to it is finished (G14) ------------------------------
# The tie lives in atr (atr pr --item T3='text of the box'): nothing atr writes to GitHub names a goal, task
# or decision (D42, D43). A box is matched by its text, ignoring case, spacing, the tick and atr's own mark.

BOX_RE = re.compile(r"^(\s*[-*+]\s+\[)([ xX])(\]\s+)(.*?)\s*$")
DONE_MARK = re.compile(r"\s+—\s+done(?::\s*\S+)?$")


def box_key(text):
    return " ".join(DONE_MARK.sub("", text or "").lower().split())


def boxes(body):
    """The checklist of a PR body, as [[text, ticked]], with atr's ' — done: link' left off the text."""
    out = []
    for line in (body or "").splitlines():
        m = BOX_RE.match(line)
        if m:
            out.append([DONE_MARK.sub("", m.group(4)).strip(), m.group(2) != " "])
    return out


def evidence(plan, t):
    """The link that shows a task's work: the first http(s) link in its note, else its first attached link."""
    m = re.search(r"https?://[^\s)>\]]+", t.get("note") or "")
    if m:
        return m.group(0).rstrip(".,;")
    return next((d["url"] for d in plan["docs"] if d["on"] == t["id"] and d.get("url")), "")


def finished_on(plan, p, tid):
    """A tied task counts as finished for its box when it is done, or in review waiting for this PR's merge."""
    t = next((t for t in plan["tasks"] if t["id"] == tid), None)
    return bool(t) and (t["status"] == "done" or (t["status"] == "review" and p["state"] == "open"))


def ticked_body(plan, p, body):
    """`body` with the boxes of p's finished tied tasks ticked and marked ' — done: <link>'. Returns (new body,
    or None when nothing changes; the tasks whose box is now ticked). A box ticked by hand is left as it is,
    and atr never unticks one."""
    want = {box_key(text): tid for tid, text in (p.get("items") or {}).items()
            if tid not in p.get("ticked", []) and finished_on(plan, p, tid)}
    if not want:
        return None, []
    lines, done = [], []
    for line in body.split("\n"):
        cr = "\r" if line.endswith("\r") else ""
        m = BOX_RE.match(line.rstrip("\r"))
        tid = m and want.get(box_key(m.group(4)))
        if tid and tid not in done:
            if m.group(2) == " ":
                link = evidence(plan, next(t for t in plan["tasks"] if t["id"] == tid))
                line = f"{m.group(1)}x{m.group(3)}{m.group(4)}" + (f" — done: {link}" if link else "") + cr
            done.append(tid)
        lines.append(line)
    new = "\n".join(lines)
    return (new if new != body else None), done


def gh_pr_body(repo, number, body=None):
    """Read a PR's body through gh, or write `body` to it. Returns the body (or True when written), None on failure."""
    gh = shutil.which("gh")
    if not gh:
        return None
    path = f"repos/{repo}/pulls/{number}"
    try:
        if body is None:
            r = subprocess.run([gh, "api", path], capture_output=True, text=True, timeout=30, check=False)
            return json.loads(r.stdout).get("body") or "" if r.returncode == 0 else None
        r = subprocess.run([gh, "api", "-X", "PATCH", path, "--input", "-"], input=json.dumps({"body": body}),
                           capture_output=True, text=True, timeout=30, check=False)
        return True if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None


def sync_checklist(name, url, body):
    """Tick the boxes of a PR's finished tied tasks. The body from the poll says whether there is anything to do;
    the edit starts from the body as it is now, so a change made since the poll is kept."""
    plan = load(name)
    _, p = find_pr(plan, url)
    if not p or not ticked_body(plan, p, body or "")[1]:
        return
    fresh = gh_pr_body(p["repo"], p["number"])
    if fresh is None:
        return
    new, done = ticked_body(load(name), p, fresh)
    if done and (new is None or gh_pr_body(p["repo"], p["number"], new)):
        change(name, "github", op_pr_ticked, {"url": url, "ids": done})


def op_pr_ticked(plan, by, a):
    """atr ticked (or found ticked) the boxes of these tasks: it leaves them alone from now on. Not news."""
    _, p = find_pr(plan, a.get("url"))
    if p:
        p["ticked"] = list(dict.fromkeys(p.get("ticked", []) + list(a.get("ids") or [])))


def checklist_lines(g, p):
    """For atr read: how far the PR's checklist is, and the boxes the lead still has to tie or drop."""
    if p.get("boxes") is None:
        return []
    known = {box_key(x) for x in [*(p.get("items") or {}).values(), *p.get("dropped", [])]}
    have = {box_key(text) for text, _ in p["boxes"]}
    out = []
    if p["boxes"]:
        out.append(f"      checklist: {sum(t for _, t in p['boxes'])} of {len(p['boxes'])} ticked")
    loose = [text for text, _ in p["boxes"] if box_key(text) not in known]
    if loose:
        out.append(f"      NOT TIED (tie: atr pr {g['id']} {p['url']} --item T3='text'; or --drop 'text'): "
                   + "; ".join(f"'{x}'" for x in loose))
    lost = [f"{tid} '{text}'" for tid, text in (p.get("items") or {}).items() if box_key(text) not in have]
    if lost:
        out.append("      TIE LOST (no box with that text any more; tie it again): " + "; ".join(lost))
    return out


def op_lead(plan, by, a):
    plan["lead"]["thread"] = (a.get("thread") or "").strip()
    return "set the lead thread"


def op_lead_release(plan, by, a):
    if by != "you":
        raise Refused("only the owner lets go of the lead for it; a lead ends its own claim with atr lead --release ID")
    if not release(plan["name"]):
        raise Refused("no thread leads this project now")
    return "let go of the lead thread: the next session to start a turn in the repo becomes the lead"


def rules_stamp():
    return f"{zlib.crc32(RULES.encode()):x}"


def op_mark_read(plan, by, a):
    plan["lead"].update(read_rev=plan["rev"], read_at=now(), rules=rules_stamp())


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
    "pr_ticked": op_pr_ticked,
}


# ---- the lead's view -----------------------------------------------------------------------------


def doc_lines(plan, on, indent="   "):
    """For atr read: what is attached to a goal or task; a stored file with its path, so the lead can open it."""
    return [f"{indent}attached {d['id']}: {d['title']} " + (d["url"] if d.get("url") else str(project_dir(plan["name"]) / "docs" / d["file"]))
            for d in plan["docs"] if d["on"] == on]


def render(plan, since):
    out = [f"{plan['title']} ({plan['name']}) · revision {plan['rev']}", ""]
    if plan["lead"].get("rules") != rules_stamp():  # a lead keeps the rules it read when it started
        out += ["ATR'S RULES CHANGED since you last read: run `atr rules` now and follow the new version.", ""]
    owner = [c for c in since if c["by"] == "you"]
    github = [c for c in since if c["by"] == "github"]
    news = [c for c in since if c["by"] == "atr"]
    if owner:
        out.append("THE OWNER CHANGED, since you last read:")
        out += [f"  - {c['what']}" for c in owner]
        out.append("")
    if github:
        out.append("FROM GITHUB, since you last read (your PRs):")
        out += [f"  - {c['what']}" for c in github]
        out.append("")
    if news:
        out.append("FROM ATR, since you last read (your workers and your thread):")
        out += [f"  - {c['what']}" for c in news]
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
        out += doc_lines(plan, g["id"])
        for p in g.get("prs", []):
            if p["state"] == "open":
                carries = f" for {', '.join(p['for'])}" if p["for"] else ""
                out.append(f"   PR #{p['number']}{carries}: {pr_words(p)} {p['url']}")
                out += checklist_lines(g, p)
        for t in (t for t in plan["tasks"] if t["goal"] == g["id"]):
            bits = [f"after {', '.join(t['after'])}"] if t["after"] else []
            bits += [f"{d['id']} needs owner" for d in held_by(plan, t)]
            bits += [t["owner"]] if t["owner"] else []
            bits += [f"owner's reason: {t['pruned_why']}"] if t.get("pruned_why") else []
            if t["status"] == "doing":
                bits += [f"thread {t['thread']}"] if t["thread"] else ["no thread: set thread= when you start its worker"]
                bits += ["WORKER ENDED"] if t.get("ended_at") else ["SILENT"] if t.get("silent_at") else []
            out.append(
                f"   {t['id']:<4} {t['status']:<8} {t['title']}"
                + (f"  ({'; '.join(bits)})" if bits else "")
            )
            if t.get("now"):
                out.append(f"        now: {t['now']} ({ago(t['now_at'])})")
            elif t["status"] == "doing":
                out.append(f"        no news since it started {ago(t.get('doing_since'))}")
            if t["status"] in OPEN:
                out += doc_lines(plan, t["id"], "        ")
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
        or check_of(plan, t)
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
        + sum(check_of(plan, t) for t in plan["tasks"])
        + sum(pr_turn(p) for g in plan["goals"] for p in g.get("prs", [])),
        "to_review": sum(d["state"] == "to_review" for d in plan["decisions"]),
        "unread": sum(c["by"] == "you" for c in unread(plan)),
        "lead_waiting": waiting(plan["name"]),
        "lead_gone": lead_status(plan["name"]).get("state") == "gone",
    }


def sig(plan):
    # What GitHub says of a PR is stored without a new revision, so the PRs are in the signature too.
    prs = zlib.crc32(json.dumps([g.get("prs") for g in plan["goals"]], sort_keys=True).encode())
    lead = lead_status(plan["name"])
    return f"{plan['rev']}.{plan['lead']['read_rev']}.{sum(bool(t.get('stopped')) for t in plan['tasks'])}.{int(waiting(plan['name']))}.{prs:x}.{lead.get('state', '')}{int(lead.get('since', 0))}"


# ---- web -----------------------------------------------------------------------------------------


# ---- versions: is there a newer atr, and how this one upgrades itself ---------------------------------------

RELEASES = "https://api.github.com/repos/mvexel/atr/releases/latest"
CHECK_EVERY = 6 * 3600  # the background check; the page's 'Check for updates' asks at once (T30)


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


def check_release(now=None, force=False):
    """One round of the release check: ask GitHub unless it was asked less than 6 h ago (by this server or the
    one before a restart), and keep what it said in Handler.latest. Returns the seconds until the next round.
    When GitHub does not answer, the page hears nothing and atr asks again in 6 h. force (the page's 'Check for
    updates') asks now, whenever it last asked."""
    now = time.time() if now is None else now
    cache = data_dir() / ".release.json"
    try:
        seen = json.loads(cache.read_text())
    except (OSError, ValueError):
        seen = {}
    if seen.get("latest"):
        Handler.latest = seen["latest"]
    wait = seen.get("checked", -CHECK_EVERY) + CHECK_EVERY - now
    if 0 < wait <= CHECK_EVERY and not force:  # further ahead than one round: the clock went back, so ask
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
    fields = "state isDraft mergeable body commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }"
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
        "boxes": boxes(pr.get("body")),
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
        body = ((data.get(f"p{i}") or {}).get("pullRequest") or {}).get("body")
        if body is not None and p.get("items"):
            with contextlib.suppress(OSError, ValueError, Refused):
                sync_checklist(name, p["url"], body)
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


def check_threads():
    """One round of the thread watch: news for silent workers, and ask the providers about leads that look gone."""
    for name in projects():
        with contextlib.suppress(OSError, ValueError, Refused):
            check_silence(name)
            lead_status(name, ask=True)
    for line in restart_leads():
        print(f"atr: {line}", file=sys.stderr, flush=True)


def watch_threads():
    """For atr serve: watch the projects' threads every minute, in the background."""

    def loop():
        while True:
            try:
                check_threads()
            except Exception as e:  # noqa: BLE001 - a bad round must not end the watch
                print(f"atr: thread check failed: {e}", file=sys.stderr, flush=True)
            time.sleep(60)

    threading.Thread(target=loop, daemon=True).start()


def auto_resume(name):
    with contextlib.suppress(Refused, OSError, ValueError):
        said = bring_back_lead(name, auto=True)
        if said:
            print(f"atr: {name}: {said}", file=sys.stderr, flush=True)


def last_resume(name):
    """The last time atr tried to bring the lead back, and what came of it: {"at", "ok", "said"} or {}."""
    try:
        return json.loads(resume_file(name).read_text())
    except (OSError, ValueError):
        return {}


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
                    {n: sig(load(n)) + side_sig(n) for n in projects()}
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
                        "lead": lead_status(parts[2]),
                        "resumed": last_resume(parts[2]),
                        "side": side_load(parts[2]),
                        "restart": restarts().get(parts[2]),
                        "ready": [t["id"] for t in ready(plan)],
                        "sig": sig(plan) + side_sig(parts[2]),
                    }
                )
            if len(parts) == 4 and parts[:2] == ["api", "file"]:  # an attached file as it is (images on the page)
                doc = get(load(parts[2]), "docs", parts[3])
                path = project_dir(parts[2]) / "docs" / doc.get("file", "")
                if "file" not in doc or not path.is_file():
                    raise Refused("that document is a link, or its file is gone")
                raw = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", IMAGE_TYPES.get(path.suffix.lower(), "application/octet-stream"))
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                return self.wfile.write(raw)
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
                mark_restarts()  # the leads come back on the new code, each when it is idle (G16)
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
        if parts == ["api", "check"]:  # the page's "Check for updates": ask GitHub now
            check_release(force=True)
            latest = self.latest if newer(self.latest.get("version"), version()) else None
            return self.send_json({"ok": True, "version": version(), "latest": latest})
        if parts in (["api", "upgrade"], ["api", "restart"]):
            return self.upgrade_or_restart(parts[1])
        if len(parts) == 3 and parts[:2] == ["api", "side"]:  # the page's side-question box
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if "hide" in body:  # the page's Dismiss / Bring back
                    side_hide(parts[2], body.get("id"), bool(body["hide"]))
                    return self.send_json({"ok": True})
                return self.send_json({"ok": True, "id": side_ask(parts[2], body.get("question"), body.get("id"))})
            except Refused as e:
                return self.send_json({"error": str(e)}, 400)
            except (ValueError, AttributeError) as e:
                return self.send_json({"error": f"bad request: {e}"}, 400)
        if len(parts) == 3 and parts[:2] == ["api", "attach"]:  # the page: an image pasted, dropped or picked (G17)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                plan, note = attach_upload(parts[2], body.get("on"), body.get("name"), body.get("data"))
                return self.send_json({"ok": True, "rev": plan["rev"], "said": note})
            except Refused as e:
                return self.send_json({"error": str(e)}, 400)
            except (ValueError, TypeError) as e:
                return self.send_json({"error": f"bad request: {e}"}, 400)
        if len(parts) == 3 and parts[:2] == ["api", "resume"]:  # the page's "Bring the lead back"
            try:
                return self.send_json({"ok": True, "said": bring_back_lead(parts[2])})
            except Refused as e:
                return self.send_json({"error": str(e)}, 400)
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
            # The owner acted while the lead is gone: bring it back so it hears them (at most once an hour).
            threading.Thread(target=auto_resume, args=(parts[2],), daemon=True).start()
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


def service_env(environ):
    """What the service keeps of the installing shell's environment. PATH goes with it: launchd starts a
    service with /usr/bin:/bin only, where atr serve finds no gh (PR states), claude or atr-lead-* (leads)."""
    return {k: environ[k] for k in ("PATH", "ATR_DATA_DIR") if environ.get(k)}


def service(a):
    """Install or remove a login service that keeps `atr serve` running."""
    import platform

    system = platform.system()
    if system not in ("Darwin", "Linux"):
        raise Refused(f"no service support on {system}")
    cmd = [*serve_command(), "serve", "--host", a.host, "--port", str(a.port)]
    for h in a.allow_host:
        cmd += ["--allow-host", h]
    path, text, start, stop = service_files(cmd, service_env(os.environ), Path.home(), system)
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


def thread_tool(name):
    """The provider (tool name) the project's threads run in: the one that started the lead, else the one on PATH."""
    found = lead_providers()
    tool = raw_claim(name).get("tool", "")
    if tool in found:
        return tool
    return next(iter(found)) if len(found) == 1 else ""


def run_provider(name, tool, args, timeout=120, env=None, raw=False):
    """Run atr-lead-TOOL with `args` in the project's repo. Returns (exit code, stdout lines, why it failed);
    with raw, stdout as it was printed instead of its lines. `env` is added to atr's own environment."""
    exe = lead_providers().get(tool)
    if not exe:
        return 127, [], f"no atr-lead-{tool} on your PATH"
    plan = load(name)
    try:
        r = subprocess.run(
            [str(exe), *args],
            cwd=plan.get("repo") or None,
            env={**{k: v for k, v in os.environ.items() if k != "ATR_AS"}, "ATR_PROJECT": name, **(env or {})},
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return 126, [], str(e)
    lines = r.stdout if raw else [x.strip() for x in r.stdout.strip().splitlines() if x.strip()]
    why = (r.stderr.strip() or r.stdout.strip() or f"exit {r.returncode}").splitlines()[-1]
    return r.returncode, lines, why


ALIVE: dict = {}  # thread -> (when asked, answer): the provider is asked at most once a minute per thread


def thread_alive(name, thread, ask=True):
    """Whether the provider says `thread` is still running: True, False, or None when it cannot tell (no
    provider, or it failed). Without ask, only an answer from the last two minutes counts."""
    at, said = ALIVE.get(thread, (0.0, None))
    if time.time() - at < (60 if ask else 120):
        return said
    if not ask:
        return None
    tool = thread_tool(name)
    if not tool:
        return None
    code, _, _ = run_provider(name, tool, ["alive", thread], timeout=30)
    said = True if code == 0 else False if code == 1 else None
    ALIVE[thread] = (time.time(), said)
    return said


def resume_thread(name, thread, message):
    """Bring `thread` back through its provider (`atr-lead-TOOL resume ID MESSAGE`). Returns (ok, thread id, why)."""
    tool = thread_tool(name)
    if not tool:
        return False, "", "no single lead provider on your PATH to bring it back with"
    code, lines, why = run_provider(name, tool, ["resume", thread, message])
    if code:
        return False, "", f"atr-lead-{tool} could not resume it: {why}"
    back = next((x.split(":", 1)[1].strip() for x in lines if x.startswith("thread-id:")), thread)
    ALIVE.pop(thread, None)
    return True, back, ""


def resume_file(name):
    return project_dir(name) / ".resume.json"


RESUMING = threading.Lock()


def bring_back_lead(name, auto=False):
    """Bring a gone lead back: resume its thread through the provider, or start a fresh lead when that fails
    or the provider cannot. auto (the owner acted on the page): only once the lead has been gone 10 min, and
    at most once an hour. Returns a line for the owner, or "" when auto had nothing to do."""
    st = lead_status(name, ask=True)
    if not st or st["state"] != "gone":
        if auto:
            return ""
        raise Refused("the lead is not gone" if st else "no thread has led this project: start one with atr lead --start")
    try:
        last = json.loads(resume_file(name).read_text()).get("at", 0)
    except (OSError, ValueError):
        last = 0
    if auto and (time.time() - st["since"] < GONE_AFTER or time.time() - last < RESUME_EVERY):
        return ""
    if not RESUMING.acquire(blocking=False):
        raise Refused("atr is already bringing the lead back")
    try:
        resume_file(name).write_text(json.dumps({"at": time.time()}))
        msg = (
            f"atr resumed you: you lead the atr project {name}, and your thread had "
            + ("ended. " if st.get("why") == "ended" else "gone quiet. ")
            + "Run `atr read` and carry on with the plan."
        )
        ok, back, why = resume_thread(name, st["id"], msg)
        if ok:
            with open(data_dir() / ".claim.lock", "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                same = same_thread(back, st["id"])
                write_claim(name, max(back, st["id"], key=len) if same else back, st.get("tool", ""))
            said = f"atr brought the lead back: resumed thread {back}" + (" on its own, as the owner acted" if auto else "")
            change(name, "atr", op_note, {"what": said})
        else:
            tool = thread_tool(name)
            started = start_lead(name, tool) if tool else "No lead provider on your PATH to start a new lead with."
            said = f"atr could not resume the lead thread {st['id']} ({why}). {started}"
            change(name, "atr", op_note, {"what": said})
        resume_file(name).write_text(json.dumps({"at": time.time(), "ok": ok, "said": said}))
        return said
    finally:
        RESUMING.release()


def resume_task(name, ident):
    """Bring the worker of a running task back through the provider (the lead runs this)."""
    t = get(load(name), "tasks", ident)
    if not t["thread"]:
        raise Refused(f"{ident} has no thread to resume: set it back with atr task set {ident} status=todo")
    ok, back, why = resume_thread(
        name, t["thread"],
        f"atr resumed you to carry on with task {ident} ({t['title']}) of the atr project {name}. "
        f'Report progress with `atr now {ident} "..."`.',
    )
    if not ok:
        raise Refused(f"{why}. If its work cannot go on, set it back: atr task set {ident} status=todo")
    return change(name, "agent", op_task_resumed, {"id": ident, "thread": back})[1]


def op_task_resumed(plan, by, a):
    t = get(plan, "tasks", a["id"])
    for k in ("silent_at", "ended_at"):
        t.pop(k, None)
    t["thread"] = a["thread"]
    return f"resumed the worker of {label(t)} (thread {a['thread']})"


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
    code, lines, why = run_provider(name, tool, [name, load(name)["title"]])
    link = (lines or [""])[-1]
    thread = next((x.split(":", 1)[1].strip() for x in lines if x.startswith("thread-id:")), "")
    if code or not link:
        return f"atr-lead-{tool} did not start the lead: {why}\nTo try again: atr lead --start {tool}"
    change(name, "agent", op_lead, {"thread": link})
    if thread:  # the owner started this thread to lead: it takes over from any lead there was
        release(name)
        claim(name, thread, tool)
    return f"started the lead in {tool}: {link}"


# ---- side questions: the owner asks about the project in a thread that only reads (G10) ----------------

SIDE_ONLY_READS = "this thread answers a side question: it may read the plan, not change it"
SIDE_READS = ("read", "next", "rules", "projects", "unread")  # the commands a side-question thread may run
SIDE_TIMEOUT = 900  # seconds a provider gets to answer
SIDE_KEEP = 50  # side questions kept per project
SIDE_LOCK = threading.Lock()  # only atr serve writes side.json


def side_file(name):
    return project_dir(name) / "side.json"


def side_load(name):
    """The project's side questions, oldest first: [{"id", "thread", "tool", "turns": [{"q", "at", "state", "a"}]}].
    Kept outside the plan (D34): asking bumps no revision and does not wake the lead."""
    try:
        items = json.loads(side_file(name).read_text())
    except (OSError, ValueError):
        return []
    for e in items:  # atr serve stopped while a provider was answering: that answer is not coming
        for t in e["turns"]:
            if t["state"] == "thinking" and minutes_since(t["at"]) * 60 > SIDE_TIMEOUT + 60:
                t.update(state="failed", a="No answer: atr serve stopped while it was being answered. Ask again.")
    return items


def side_update(name, fn):
    with SIDE_LOCK:
        items = side_load(name)
        out = fn(items)
        fd, tmp = tempfile.mkstemp(dir=project_dir(name), prefix=".side-")
        with os.fdopen(fd, "w") as f:
            json.dump(items[-SIDE_KEEP:], f, indent=1, ensure_ascii=False)
        os.replace(tmp, side_file(name))
        return out


def side_sig(name):
    """Changes when a side question is asked or answered, so the page redraws; not part of the plan's revision."""
    try:
        return f".{side_file(name).stat().st_mtime_ns:x}"
    except OSError:
        return ""


def side_hide(name, qid, hide=True):
    """Dismiss a side question from the page (or bring it back). Kept in side.json, so it stays dismissed."""

    def mark(items):
        e = next((x for x in items if x["id"] == qid), None)
        if not e:
            raise Refused(f"no side question {qid}")
        if hide:
            e["hidden"] = True
        else:
            e.pop("hidden", None)

    side_update(name, mark)


def side_ask(name, question, qid=None):
    """Ask a side question, or follow up on side question `qid` in its thread. The provider answers in the
    background (side_run); returns the side question's id."""
    question = (question or "").strip()
    if not question:
        raise Refused("write a question first")
    load(name)
    tool = thread_tool(name)
    if not tool:
        raise Refused("no single lead provider (atr-lead-<tool>) on your PATH to ask with")

    def add(items):
        if qid:
            e = next((x for x in items if x["id"] == qid), None)
            if not e:
                raise Refused(f"no side question {qid}")
            if e["turns"][-1]["state"] == "thinking":
                raise Refused(f"{qid} is still being answered")
            if not e.get("thread"):
                raise Refused(f"{qid} has no thread to follow up in: ask it as a new question")
        else:
            n = max((int(x["id"][1:]) for x in items), default=0) + 1
            e = {"id": f"Q{n}", "thread": "", "tool": tool, "turns": []}
            items.append(e)
        e["turns"].append({"q": question, "at": now(), "state": "thinking", "a": ""})
        return e["id"], e.get("thread", "")

    qid, thread = side_update(name, add)
    threading.Thread(target=side_run, args=(name, qid, tool, question, thread), daemon=True).start()
    return qid


def side_run(name, qid, tool, question, thread):
    """Have the provider answer (`atr-lead-TOOL ask PROJECT QUESTION [THREAD]`, under ATR_SIDE=1, so atr refuses
    every change from it) and store what it said: a first line `thread-id: ID`, then the answer."""
    code, out, why = run_provider(
        name, tool, ["ask", name, question, *([thread] if thread else [])],
        timeout=SIDE_TIMEOUT, env={"ATR_SIDE": "1"}, raw=True,
    )
    out = out if isinstance(out, str) else ""
    head, _, rest = out.lstrip().partition("\n")
    said = head.split(":", 1)[1].strip() if head.startswith("thread-id:") else ""
    answer = rest.strip() if said else out.strip()

    def store(items):
        e = next((x for x in items if x["id"] == qid), None)
        if not e:
            return
        if said:
            e["thread"] = said
        ok = code == 0 and answer
        e["turns"][-1].update(state="answered" if ok else "failed",
                              a=answer if ok else f"atr-lead-{tool} did not answer: {why}")

    with contextlib.suppress(OSError, ValueError, Refused):
        side_update(name, store)


# ---- after an upgrade: the leads come back on the new code (G16) -----------------------------------------
# A running session keeps the plugin it started with. After an upgrade atr restarts each project's lead
# through its provider (`restart ID MESSAGE`: stop it and resume the same thread), but only while the lead is
# idle, listening for the owner: a lead in the middle of a turn is restarted at its next idle moment (D48).
# A lead in a terminal the owner has open cannot be restarted by atr: the page asks the owner to (D49).


def restarts_file():
    return data_dir() / ".restart.json"


def restarts():
    """{project: {"version", "interactive"?}}: leads still to bring back on the new code."""
    try:
        return json.loads(restarts_file().read_text())
    except (OSError, ValueError):
        return {}


def save_restarts(pending):
    with contextlib.suppress(OSError):
        if pending:
            restarts_file().write_text(json.dumps(pending))
        else:
            restarts_file().unlink(missing_ok=True)


def mark_restarts():
    """After an upgrade: every project with a lead thread has its lead restarted (the version is filled in by
    the new code, which knows it)."""
    save_restarts({n: {} for n in projects() if raw_claim(n).get("id") and not raw_claim(n).get("ended")})


def restart_leads():
    """One round, from the thread watch: restart each pending lead that is idle now. Returns what was said."""
    pending, said = restarts(), []
    for name, r in list(pending.items()):
        st = lead_status(name)
        if not st or st["state"] == "gone":  # nothing to restart (a gone lead is brought back as it is)
            pending.pop(name)
            continue
        if st["state"] != "listening" or r.get("interactive"):
            continue
        tool = thread_tool(name)
        msg = (f"atr was upgraded to {version()} and restarted you, in the same thread, so this session runs the "
               "new plugin. Run `atr rules` (they may have changed), then `atr read`, and carry on.")
        code, lines, why = run_provider(name, tool, ["restart", st["id"], msg]) if tool else (127, [], "no provider")
        if code == 3:  # an interactive session: only the owner can restart it
            pending[name] = {**r, "interactive": True}
            continue
        pending.pop(name)
        note = (f"atr restarted the lead on atr {version()} (same thread)" if code == 0
                else f"atr could not restart the lead on atr {version()}: {why}. Restart its session to load the new plugin")
        with contextlib.suppress(OSError, ValueError, Refused):
            change(name, "atr", op_note, {"what": note})
        said.append(f"{name}: {note}")
    save_restarts(pending)
    return said


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
                    "lead_state": lead_status(name).get("state", ""),
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
    x.add_argument("--thread", default="", help="a worker's first report: the thread (session id) it runs in")
    x = sub.add_parser("alive", help="ask the provider whether a task's worker (or the lead) is still running")
    x.add_argument("id", help="task id, or 'lead'")
    x = sub.add_parser("resume", help="bring a task's worker (or the lead) back in its thread, through the provider")
    x.add_argument("id", help="task id, or 'lead'")
    x = sub.add_parser("ended", help="for extensions: thread ID's session ended (lets go of the lead, tells the lead of its tasks)")
    x.add_argument("thread")
    x = sub.add_parser("pr", help="put a pull request you opened on its goal (workers may use this)")
    x.add_argument("goal")
    x.add_argument("url")
    x.add_argument(
        "--for", dest="for_", action="append", default=[], metavar="TASK",
        help="task(s) the PR carries; they go to done when it merges (repeat or comma-separate)",
    )
    x.add_argument("--item", action="append", default=[], metavar="T3=TEXT",
                   help="tie a checklist box of the PR (by its text) to a task: atr ticks it when the task is finished")
    x.add_argument("--drop", action="append", default=[], metavar="TEXT", help="a checklist box no task covers: stop listing it")
    x = sub.add_parser("lead", help="store the lead's thread link, or start a lead thread (--start)")
    x.add_argument("thread", nargs="?")
    x.add_argument("--start", metavar="TOOL", help="start the lead thread with atr-lead-TOOL ('auto': the one on PATH)")
    x.add_argument("--claim", metavar="ID", help="for extensions: make thread ID the lead unless another thread is (exit 1)")
    x.add_argument("--release", metavar="ID", help="for extensions: thread ID stops leading (its session ended)")
    x.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    by = "you" if os.environ.get("ATR_AS") == "you" else "agent"
    side = bool(os.environ.get("ATR_SIDE"))  # a side-question thread (G10): it reads, it never changes anything
    try:
        if side and a.cmd not in SIDE_READS:
            raise Refused(SIDE_ONLY_READS)
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
            if os.environ.get("ATR_THREAD_CHECK") != "0":
                watch_threads()
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
                    "lead": {"thread": "", "read_rev": 0, "read_at": "", "rules": rules_stamp()},
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
            if side:  # reading is all it does: the lead's unread changes stay unread
                return print(render(plan, unread(plan)))
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
            fn, args = op_task_now, {"id": a.id, "text": " ".join(a.text), "thread": a.thread}
        elif a.cmd == "alive":
            thread = raw_claim(name).get("id", "") if a.id == "lead" else get(load(name), "tasks", a.id)["thread"]
            if not thread:
                raise Refused(f"{a.id} has no thread to ask about")
            said = thread_alive(name, thread)
            print(f"thread {thread} " + {True: "is running", False: "is not running", None: "is unknown: atr cannot tell (no provider, or it failed)"}[said])
            return {True: 0, False: 1, None: 2}[said]
        elif a.cmd == "resume":
            return print(bring_back_lead(name) if a.id == "lead" else resume_task(name, a.id))
        elif a.cmd == "ended":
            released = release(name, a.thread)
            note = change(name, "atr", op_thread_ended, {"thread": a.thread})[1]
            return print("\n".join(x for x in ["released the lead" if released else "", note or ""] if x) or "nothing ran in that thread")
        elif a.cmd == "pr":
            if any("=" not in x for x in a.item):
                raise Refused("usage: atr pr G1 URL --item T3='text of the checklist box'")
            items = dict(x.split("=", 1) for x in a.item)
            fn, args = op_pr, {"goal": a.goal, "url": a.url, "for": [t for s in a.for_ for t in s.split(",") if t],
                               "items": {k.strip(): v.strip() for k, v in items.items()}, "drop": a.drop}
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
