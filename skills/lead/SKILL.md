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

The owner gets no card until `prd ROOM review` runs, and it refuses until the Product lead and Tech lead sign-off lines are in the PRD's Sign-off section. Don't tell the owner you are waiting for their agreement before that: get the sign-offs and run `prd ROOM review`, or name the missing sign-off as the thing blocking (a NEEDS YOU item in now-head) so the owner isn't left waiting on a card that doesn't exist.

Don't create a second room for a thread that already leads one, and don't add new work to a closed room: ask the owner to start a new thread.

## Take over a room

To lead an existing room, run `lead ROOM YOUR_THREAD_ID`, then `inbox ROOM` and `check ROOM --yield`, and carry on.

## Titles, links and paths

- Title your own thread `Room · <room> · lead` (set it with `t3_thread_update`). `atr t3 launch` titles each worker `<room> · <item> · <role>` (role: `--role`, else the item owner) and corrects any other title it is given. Tell workers to keep that title.
- T3 can regenerate a thread's title. If it did, set the convention title again with `t3_thread_update`; `atr check` warns when the lead's title is off.
- When you mention a thread to the owner, use a link, `t3-thread://v2/<env>/<thread>`: it shows the thread's current title and opens it. `<env>` is the environment id in the thread's T3 link (`https://app.t3.codes/threads/<env>/<thread>`). Don't write bare thread ids.
- Name store files by absolute path (under the store's `rooms/` directory), never relative to a checkout.
- atr's web page links the lead and each worker that way once their ids are known (set `ATR_T3_ENVIRONMENT` if T3 doesn't report the environment).

## Pin while the owner is needed, settle on close

`atr t3 organize ROOM` prints the `t3_thread_organize` calls your own thread needs (JSON; atr cannot call T3 tools): `pin` while an owner decision, ask or PRD/refinement agree card is open, `unpin` then `settle` once the room is closed. Only the lead is pinned; nothing is snoozed. Run it before `check ROOM --yield` and again when you close the room, then make the calls it lists (omit `threadId` for your own thread; settle last, it applies at turn end). Steps T3 already satisfies are skipped, and a repeat is harmless. If T3 facts are unavailable the steps are marked `unknown`: make them anyway. `atr status` and `check` hint when the pin state is out of line.

## Delegating workers

`atr t3 launch ROOM "instructions" --item ID` is a CLI and cannot call T3 tools, so it creates no thread. After the dependency and brief checks it prints a ready `delegate_task` brief (title `<room> · <item> · <role>`, task text with room, item, store and atr command, `isolation: worktree`, role `implementation`). Then:

1. Call `delegate_task` yourself with that brief (isolation worktree: each editing agent gets its own checkout).
2. Record the child: `atr set ROOM ID agent=<childThreadId>`.
3. You must be mid-turn to delegate: only a running lead can call `delegate_task`. Dispatch before you yield.
4. Child threads take no messages. Don't `t3_thread_send` to a worker; it messages you (final answer, `atr need`). Review and re-delegate instead.
5. If `delegate_task` is unavailable, block: set the item `state=blocked`, tell the owner plainly why. Never fall back to a top-level thread.

## Lead

Plan bounded items with acceptance, inputs, dependencies, locks, owners and caps before dispatch. Start workers with `t3 launch ROOM "instructions" --item ID`; see Delegating workers. Each editing agent gets a separate checkout; workers report unplanned needs with `need`. Keep the integration branch and checkout in BRIEF. Use T3 for execution and messages; don't invent a replacement runner.

When you mention a store file (a note, decision or item) to the owner, link it by its absolute path under the store's `data_dir`, not a store-relative path: T3 resolves relative links against the workspace, which is often not the store, and its viewer then reports the file missing.

A worker moving its item to `review` or `done` does not wake an idle lead. After launching workers, don't end your turn on a `resume:` such as "when T01 reaches review" unless something will message you: keep the turn open and run `inbox ROOM`, or tell each worker to message you when it finishes.

Always report back when the owner's answer or message reaches you, whether it was a decision tap, a clarifying question, a plan or a code change: say what you did or what you decided, or why you did nothing, even if the answer needs no action. Silence after an answer leaves the owner unable to tell whether it arrived. A turn that ends without that report is unfinished.

Save records before communicating. Use `delivery list` to tell local saves from pending, uncertain or confirmed T3 acceptance. Reconcile uncertainty with actual evidence before retrying. A confirmed message is not proof that the agent received it or resumed work.

The owner's taps on the web page reach you between turns; run `inbox ROOM` mid-turn to pick them up sooner. Review results, run appropriate checks, update now-head and advance the next eligible item while your turn lasts. Before yielding, run `status ROOM` and `check ROOM --yield`, and leave a concrete event, time or owner question that will resume the room.

Main merges, releases, deployment and live store cut-over need the owner's authorization. Preserve unknown metadata, attachments, dirty or untracked code and branch history before cleanup. Follow the source's `docs/OPERATIONS.md` and `docs/NIXOS.md` for restore and reinstall. Never put credentials or private host paths in this skill.
