---
name: atr-lead
description: Start, lead or check on an atr room, the owner's record of a project run by a team of T3 agents. Use when the owner asks to start an atr room (or "a room") for something, to take the lead of a room, to resume or hand off a room, to plan or dispatch its items, or asks about their rooms, items, decisions or PRD.
---

# Lead an atr room

atr keeps the owner's record of a project: brief, PRD, items, decisions and evidence, as Markdown in a local store. T3 runs the agents. You, the lead, are a T3 thread; one thread leads one room. The owner checks in on atr's web page and talks to you here.

## Run atr

Don't rely on an `atr` command or `ATR_DATA_DIR` in your shell: they belong to the owner's shell. Read `~/.config/atr/config.json` (under `$XDG_CONFIG_HOME` if set). Its `command` runs atr, and its `data_dir` is the store, so `<command> <subcommand>` works from any directory. If the file is missing, resolve this skill directory to its real path, go up two directories to the atr source, run `python3 -I <source>/bin/atr`, and ask the owner which store to use with `--data-dir`. Never assume rooms live beside the source.

Before leading, read the source's `PROTOCOL.md`, then the room's `BRIEF.md`, `now-head.md`, `atr brief ROOM` (the binding PRD and refinements) and the item you're on.

## Start a room

When the owner asks for a new room or project:

1. Find your own T3 thread id in your thread configuration.
2. Pick a short room name (lowercase letters, digits and dashes) and a title from what the owner asked for.
3. Run `room new NAME "Title" --lead-thread YOUR_THREAD_ID`. For work that isn't a feature (a fix, publishing), add `--waive-prd "not a feature: reason"` and record the owner's go-ahead in their words.
4. Tell the owner the room is on the web page at `http://127.0.0.1:PORT/` (`web_port` in config.json, default 8787), quote their request in a premise or decision, and draft the PRD with them. Building stays locked until they agree it.

Don't create a second room for a thread that already leads one, and don't add new work to a closed room: ask the owner to start a new thread.

## Take over a room

To lead an existing room, run `lead ROOM YOUR_THREAD_ID`, then `inbox ROOM` and `check ROOM --yield`, and carry on.

## Lead

Plan bounded items with acceptance, inputs, dependencies, locks, owners and caps before dispatch. Start workers with `t3 launch ROOM "instructions" --item ID`. Each editing agent gets a separate checkout; workers report unplanned needs with `need`. Keep the integration branch and checkout in BRIEF. Use T3 for execution and messages; don't invent a replacement runner.

When you mention a store file (a note, decision or item) to the owner, link it by its absolute path under the store's `data_dir`, not a store-relative path: T3 resolves relative links against the workspace, which is often not the store, and its viewer then reports the file missing.

Save records before communicating. Use `delivery list` to tell local saves from pending, uncertain or confirmed T3 acceptance. Reconcile uncertainty with actual evidence before retrying. A confirmed message is not proof that the agent received it or resumed work.

The owner's taps on the web page reach you between turns; run `inbox ROOM` mid-turn to pick them up sooner. Review results, run appropriate checks, update now-head and advance the next eligible item while your turn lasts. Before yielding, run `status ROOM` and `check ROOM --yield`, and leave a concrete event, time or owner question that will resume the room.

Main merges, releases, deployment and live store cut-over need the owner's authorization. Preserve unknown metadata, attachments, dirty or untracked code and branch history before cleanup. Follow the source's `docs/OPERATIONS.md` and `docs/NIXOS.md` for restore and reinstall. Never put credentials or private host paths in this skill.
