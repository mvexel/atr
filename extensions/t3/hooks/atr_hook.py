#!/usr/bin/env python3
"""atr in T3 Code threads: the turn start and turn end jobs from docs/EXTENSIONS.md.

Usage (from hooks.json): atr_hook.py session-start | prompt | stop, with the hook's JSON on stdin.
A thread is named by its T3 thread id (T3CODE_THREAD_ID, which T3 sets for the Claude sessions it runs), so
atr-lead-t3 can check on it and wake it. The doorbell is not here: T3 ends a thread's process when its turn
is over, so `atr serve` wakes an idle lead through atr-lead-t3 instead.

Finds atr via ATR_BIN or PATH. Silent outside atr projects, outside T3 (no T3CODE_THREAD_ID), and in a
side-question session (ATR_SIDE).
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
    env = {k: v for k, v in os.environ.items() if k != "ATR_AS"}  # an extension never speaks as the owner
    try:
        r = subprocess.run([exe, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return 2, ""
    return r.returncode, r.stdout


def lead(cwd, thread):
    """Whether this thread leads the folder's project: (True, info), (False, info), or (None, {}) outside one.
    The first thread to take a turn leads (or the one atr-lead-t3 started); the others are told who does."""
    code, out = atr(cwd, "lead", "--claim", thread, "--json")
    if code not in (0, 1):
        return None, {}
    try:
        return code == 0, json.loads(out)
    except ValueError:
        return None, {}


def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))


def main(event):
    thread = os.environ.get("T3CODE_THREAD_ID", "")
    if not thread or os.environ.get("ATR_SIDE"):
        return  # not a T3 thread, or a side-question session (atr serve started it to answer the owner)
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        hook = {}
    cwd = hook.get("cwd") or os.getcwd()
    # T3 starts a new process for each run of a thread: only a new thread, or one whose context was
    # compacted, needs the whole picture again; a resumed one has it and only needs what changed.
    fresh = event == "session-start" and hook.get("source", "startup") in ("startup", "clear", "compact")
    is_lead, who = lead(cwd, thread)
    if is_lead is None:
        return  # not an atr project, or atr is not installed
    if not is_lead:
        if fresh:
            code, out = atr(cwd, "unread", "--json")
            here = json.loads(out)["project"] if code in (0, 1) else "this folder's project"
            if who["project"] != here:
                print(
                    f"This folder is atr project {here}, but this thread already leads {who['project']}, "
                    "and a thread leads one project only. You are not the lead here: do not run atr for "
                    f"{here}; if the owner asked you for work in it, do it as a worker."
                )
            else:
                print(
                    f"This folder is atr project {here}. Its lead is another T3 thread ({who['id']}); you are "
                    "not the lead. Do not plan, read or change the atr plan as its lead. If the owner asked you "
                    "for work here, do it as a worker: report progress on your own task "
                    f"(`atr now T3 \"...\"`; the first time, add `--thread {thread}` so the lead can check on "
                    "and wake this thread) and record your own judgment calls with `--by`."
                )
        return
    code, out = atr(cwd, "unread", "--json")
    if code == 2:
        return
    state = json.loads(out)
    if fresh:
        print(f"This folder is atr project {state['project']}; you are its lead (T3 thread {thread}). The plan:\n\n{atr(cwd, 'read')[1]}")
        if state.get("running"):
            print(
                "\nThese tasks show as in progress. Check that each worker is still on it (`atr alive ID` for a "
                "task with a thread); wake an idle one with `atr resume ID`, or set the task back with "
                "`atr task set ID status=todo`, and say so:\n"
                + "\n".join(
                    f"  - {t['id']} {t['title']} (last news {t['last_news_at'] or 'unknown'})"
                    for t in state["running"]
                )
            )
    elif event in ("session-start", "prompt"):
        if state["unread"]:
            print(f"The owner (or GitHub, or atr) changed the atr plan of {state['project']} since you last read it:\n\n{atr(cwd, 'read')[1]}")
    elif event == "stop":
        if hook.get("stop_hook_active"):
            return  # already continuing because of this hook: let the turn end
        if state["unread"]:
            block("The owner changed the atr plan while you worked. Run `atr read` and act on it before ending your turn.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
