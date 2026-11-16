#!/usr/bin/env python3
"""atr for Claude Code: the turn start, turn end and doorbell jobs from docs/EXTENSIONS.md.

Usage (from hooks.json): atr_hook.py session-start | prompt | stop | listen | session-end, with the hook's JSON on stdin.
Finds atr via ATR_BIN or PATH. Silent outside atr projects. ATR_DOORBELL=0 turns the listener (the push) off.
"""

import json
import os
import shutil
import subprocess
import sys

def atr(cwd, *args):
    exe = os.environ.get("ATR_BIN") or shutil.which("atr")
    if not exe:
        return 2, ""
    env = {
        k: v for k, v in os.environ.items() if k != "ATR_AS"
    }  # an extension never speaks as the owner
    try:
        r = subprocess.run(
            [exe, *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 2, ""
    return r.returncode, r.stdout


def lead(cwd, session):
    """Whether this session leads the folder's project: (True, info), (False, info), or (None, {}) outside one.

    The first session to take a turn leads; the others are told who does. A session the hooks cannot name
    (no session_id) is treated as the lead, as before atr knew threads.
    """
    if not session:
        code, out = atr(cwd, "unread", "--json")
        return (None, {}) if code == 2 else (True, {})
    code, out = atr(cwd, "lead", "--claim", session, "--json")
    if code not in (0, 1):
        return None, {}
    try:
        return code == 0, json.loads(out)
    except ValueError:
        return None, {}


def listen(cwd, session):
    """The push (asyncRewake): wait for the owner, then exit 2 with their actions so Claude Code wakes the lead.

    Runs in the background after every turn and at session start, for the lead only. One listener per
    session: a new one stops the one before it, so a single owner action wakes the lead once.
    """
    import signal
    import tempfile
    from pathlib import Path

    if not lead(cwd, session)[0]:
        return
    exe = os.environ.get("ATR_BIN") or shutil.which("atr")
    pidfile = Path(tempfile.gettempdir()) / f"atr-listen-{session or 'default'}.pid"
    try:
        os.kill(int(pidfile.read_text()), signal.SIGTERM)
    except (OSError, ValueError):
        pass
    pidfile.write_text(str(os.getpid()))
    child = None

    def stop(*_):
        if child:
            child.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    env = {k: v for k, v in os.environ.items() if k != "ATR_AS"}
    while True:
        child = subprocess.Popen(
            [exe, "wait", "--timeout", "3500", "--json"], cwd=cwd, env=env, stdout=subprocess.PIPE, text=True
        )
        out, _ = child.communicate()
        if child.returncode == 0:
            break
        if child.returncode != 1:
            return  # not an atr project, or atr failed: stay quiet
    if not lead(cwd, session)[0]:
        return  # the owner let another thread lead while this one was idle
    state = json.loads(out)
    lines = ["The owner acted on the atr page (or GitHub on your PRs, or atr on your workers) while you were idle:"]
    for c in state["unread"]:
        data = json.dumps({"op": c["op"], "args": c["args"]}) if "op" in c else ""
        lines.append(f"- [{state['project']}] {c['what']} {data}".rstrip())
    lines.append("Act on this, and run `atr read` to mark it read.")
    print("\n".join(lines), file=sys.stderr)
    sys.exit(2)


def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))


def main(event):
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        hook = {}
    cwd = hook.get("cwd") or os.getcwd()
    session = hook.get("session_id")
    if event == "listen":
        if os.environ.get("ATR_DOORBELL") != "0":
            listen(cwd, session)
        return
    if event == "session-end":
        # lets go of the lead, and tells the lead at once when a worker's session ends
        if session and atr(cwd, "ended", session)[0] == 2:
            atr(cwd, "lead", "--release", session)  # an atr from before `atr ended`
        return
    is_lead, who = lead(cwd, session)
    if is_lead is None:
        return  # not an atr project, or atr is not installed
    if not is_lead:
        if event == "session-start":
            code, out = atr(cwd, "unread", "--json")
            here = json.loads(out)["project"] if code in (0, 1) else "this folder's project"
            if who["project"] != here:
                print(
                    f"This folder is atr project {here}, but this session already leads {who['project']}, "
                    "and a session leads one project only. You are not the lead here: do not run atr for "
                    f"{here}; if the owner asked you for work in it, do it as a worker."
                )
            else:
                print(
                    f"This folder is atr project {here}. Its lead is another session ({who['id']}); you are "
                    "not the lead. Do not plan, read or change the atr plan as its lead. If the owner asked you "
                    "for work here, do it as a worker: you may report progress on your own task "
                    f"(`atr now T3 \"...\"`; the first time, add `--thread {session}` so the lead can check on "
                    "and resume this session) and record your own judgment calls with `--by`."
                )
        return
    code, out = atr(cwd, "unread", "--json")
    if code == 2:
        return
    state = json.loads(out)
    if event == "session-start":
        print(f"This folder is atr project {state['project']}; you are its lead. The plan:\n\n{atr(cwd, 'read')[1]}")
        if state.get("running"):
            print(
                "\nThese tasks show as in progress. A worker from an earlier session may be gone. Check that "
                "each is still running (`atr alive ID` for a task with a thread); for any that is not, bring it "
                "back with `atr resume ID` or set it back with `atr task set ID status=todo`, and say so:\n"
                + "\n".join(
                    f"  - {t['id']} {t['title']} (last news {t['last_news_at'] or 'unknown'})"
                    for t in state["running"]
                )
            )
    elif event == "prompt":
        if state["unread"]:
            print(f"The owner (or GitHub, or atr) changed the atr plan of {state['project']} since you last read it:\n\n{atr(cwd, 'read')[1]}")
    elif event == "stop":
        if hook.get("stop_hook_active"):
            return  # already continuing because of this hook: let the turn end
        if state["unread"]:
            block("The owner changed the atr plan while you worked. Run `atr read` and act on it before ending your turn.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
