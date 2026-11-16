#!/usr/bin/env python3
"""atr for Claude Code: the turn start, turn end and doorbell jobs from docs/EXTENSIONS.md.

Usage (from hooks.json): atr_hook.py session-start | prompt | stop | listen, with the hook's JSON on stdin.
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


def listen(cwd, session):
    """The push (asyncRewake): wait for the owner, then exit 2 with their actions so Claude Code wakes the lead.

    Runs in the background after every turn and at session start. One listener per session: a new one
    stops the one before it, so a single owner action wakes the lead once.
    """
    import signal
    import tempfile
    from pathlib import Path

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
    state = json.loads(out)
    lines = ["The owner acted on the atr page while you were idle:"]
    for p in state.get("projects") or [state]:
        read = "atr read" if p.get("own", True) else f"atr -p {p['project']} read"
        for c in p["unread"]:
            data = json.dumps({"op": c["op"], "args": c["args"]}) if "op" in c else ""
            lines.append(f"- [{p['project']}] {c['what']} {data}".rstrip())
        if p["unread"]:
            lines.append(f"Act on this, and run `{read}` to mark it read.")
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
    if event == "listen":
        if os.environ.get("ATR_DOORBELL") != "0":
            listen(cwd, hook.get("session_id"))
        return
    code, out = atr(cwd, "unread", "--json")
    if code == 2:
        return  # not an atr project (and following none), or atr is not installed
    state = json.loads(out)
    # Every project this folder's lead follows: its own, plus any added with `atr watch NAME`.
    projects = state.get("projects") or [state]

    def plan(p):
        return atr(cwd, "read")[1] if p.get("own", True) else atr(cwd, "-p", p["project"], "read")[1]

    if event == "session-start":
        for p in projects:
            role = "This folder is atr project" if p.get("own", True) else "You follow atr project"
            print(f"{role} {p['project']}; you are its lead. The plan:\n\n{plan(p)}")
            if p.get("running"):
                print(
                    "\nThese tasks show as in progress. A worker from an earlier session may be gone. Check that "
                    "each is still running; for any that is not, set it back with "
                    f"`atr{'' if p.get('own', True) else ' -p ' + p['project']} task set ID status=todo` and say so:\n"
                    + "\n".join(
                        f"  - {t['id']} {t['title']} (last news {t['last_news_at'] or 'unknown'})"
                        for t in p["running"]
                    )
                )
    elif event == "prompt":
        for p in projects:
            if p["unread"]:
                print(f"The owner changed the atr plan of {p['project']} since you last read it:\n\n{plan(p)}")
    elif event == "stop":
        if hook.get("stop_hook_active"):
            return  # already continuing because of this hook: let the turn end
        changed = [p["project"] for p in projects if p["unread"]]
        if changed:
            how = " and ".join(
                "`atr read`" if p.get("own", True) else f"`atr -p {p['project']} read`"
                for p in projects
                if p["unread"]
            )
            block(f"The owner changed the atr plan while you worked. Run {how} and act on it before ending your turn.")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
