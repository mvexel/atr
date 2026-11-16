#!/usr/bin/env python3
"""atr for Claude Code: the turn start, turn end and doorbell jobs from docs/EXTENSIONS.md.

Usage (from hooks.json): atr_hook.py session-start | prompt | stop, with the hook's JSON on stdin.
Finds atr via ATR_BIN or PATH. Silent outside atr projects. ATR_DOORBELL=0 turns the doorbell reminder off.
"""

import json
import os
import shutil
import subprocess
import sys

DOORBELL = (
    "Before ending your turn, arm the atr doorbell so the owner's changes on the page wake you: run "
    "`atr wait --timeout 7000` with the Bash tool, run_in_background true and timeout 7200000. When it "
    "exits 0, run `atr read` (`atr -p NAME read` for each other project it names) and act on it. Exit 1 "
    "means it timed out with nothing new: arm it again."
)


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


def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))


def main(event):
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        hook = {}
    cwd = hook.get("cwd") or os.getcwd()
    code, out = atr(cwd, "unread", "--json")
    if code == 2:
        return  # not an atr project (and following none), or atr is not installed
    state = json.loads(out)
    # Every project this folder's lead follows: its own, plus any added with `atr watch NAME`.
    projects = state.get("projects") or [state]
    doorbell = os.environ.get("ATR_DOORBELL", "1") != "0"
    listening = all(p["lead_waiting"] for p in projects)

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
        if doorbell and not listening:
            print("\n" + DOORBELL)
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
        elif doorbell and not listening:
            block(DOORBELL)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
