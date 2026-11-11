---
name: atr-lead
description: Start, lead or check on an atr room, the owner's record of a project run by a team of T3 agents. Use when the owner asks to start an atr room (or "a room") for something, to take the lead of a room, to resume or hand off a room, to plan or dispatch its items, or asks about their rooms, items, decisions or goal.
---

# Lead an atr room

atr keeps the owner's record of a project: brief, goal, items, decisions and evidence, as Markdown in a local store. T3 runs the agents. You, the lead, are a T3 thread; one thread leads one room. The owner checks in on atr's web page and talks to you here.

## Run atr

Don't rely on an `atr` command or `ATR_DATA_DIR` in your shell: they belong to the owner's shell. Resolve this skill directory to its real path, go up two directories to the atr source, and run `python3 -I <source>/bin/atr --data-dir DIR ...`, where DIR is the store the owner named (ask if you were not told). Never assume rooms live beside the source.

Before leading, read the source's `PROTOCOL.md`, then the room's `BRIEF.md`, `now-head.md`, `atr brief ROOM` (the room's goal) and the item you're on.

## Start a room

When the owner asks for a new room or project:

1. Find your own T3 thread id in your thread configuration.
2. Pick a short room name (lowercase letters, digits and dashes) and a title from what the owner asked for.
3. Run `room new NAME "Title" --lead-thread YOUR_THREAD_ID`. Building is locked from this moment: no item can start, and no worker can be dispatched, until the owner approves the room's goal.
4. Tell the owner the room is on the web page (`atr serve`, default `http://127.0.0.1:8787/`) and quote their request in a premise or decision.
5. Set the goal (next section).

## Set the goal

The goal has three fields: **Architecture** (how it will be built and where it runs), **Minimal viable result** (the smallest thing that is worth having) and **Definition of done** (what must be true, and who checks it, before it counts as shipped).

1. Interview the owner with 3 to 5 typed questions (ask cards or `atr new decision ... --option`, one question each, with options when there are obvious ones). Cover architecture, minimal viable result and definition of done; add one or two only if an answer leaves a field vague.
2. Write the half-page summary from their answers: `goal ROOM new --architecture "..." --result "..." --done "..."`. This saves a draft. Keep each field short and concrete.
3. Run `goal ROOM approve`. That opens a card for the owner; the answer is theirs alone, and you never mark a goal approved yourself. Until the card is answered, say the room is waiting for goal approval and name the card.
4. A small room (a fix, a publishing step) gets a one-line goal: one line per field. It still needs the approval card.
5. If the owner answers "changes needed", rewrite the goal with `goal ROOM new ...` and run `goal ROOM approve` again. An approved goal is not rewritten silently: a changed goal goes back to the owner as a new card.

`atr brief ROOM` prints the goal; put it at the top of every worker brief.

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

`atr t3 organize ROOM` prints the `t3_thread_organize` calls your own thread needs (JSON; atr cannot call T3 tools): `pin` while an owner decision, ask or goal approval card is open, `unpin` then `settle` once the room is closed. Only the lead is pinned; nothing is snoozed. The standing process maintainer stays pinned even without an open owner card. Run it before `check ROOM --yield` and again when you close the room, then make the calls it lists (omit `threadId` for your own thread; settle last, it applies at turn end). Steps T3 already satisfies are skipped, and a repeat is harmless. If T3 facts are unavailable the steps are marked `unknown`: make them anyway. `atr status` and `check` hint when the pin state is out of line.

## Dispatching what atr offers

atr never starts workers. Once the goal is approved, it messages you ("N items ready to start") when the ready set or the running count changes, naming up to `3 - running` items, critical path first. Dispatch exactly those, one worker per item, each in its own worktree (see Delegating workers), then `atr set ROOM ID state=doing owner=ROLE agent=THREAD`. Never exceed 3 items in `doing`; review does not count. `atr next ROOM` shows the same offer without sending. atr offers nothing while the goal is unapproved, the room is paused, or any item is `blocked`: resolve the block (see `need`), then set the item back to `todo` or `doing` and atr offers again. The room page shows the state as auto-start.

## Delegating workers

`atr t3 launch ROOM "instructions" --item ID` is a CLI and cannot call T3 tools, so it creates no thread. After the dependency and brief checks it prints a ready `delegate_task` brief (title `<room> · <item> · <role>`, task text with room, item, store and atr command, `isolation: worktree`, role `implementation`). Then:

1. Call `delegate_task` yourself with that brief (isolation worktree: each editing agent gets its own checkout).
2. Record the child: `atr set ROOM ID agent=<childThreadId>`.
3. You must be mid-turn to delegate: only a running lead can call `delegate_task`. Dispatch before you yield.
4. Child threads take no messages. Don't `t3_thread_send` to a worker; it messages you (final answer, `atr need`). Review and re-delegate instead.
5. If `delegate_task` is unavailable, block: set the item `state=blocked`, tell the owner plainly why. Never fall back to a top-level thread.

## Reaching a teammate's agent

To ask or tell a teammate's agent something, use `ari relay` (see the agent-relay skill). atr has no teammate cards or relay of its own; every card is the owner's.

## Lead

On each owner message or worker result, update the records and continue authorized work in the same turn. Reporting receipt is an intermediate obligation, not a reason to stop. Review completed workers, reconcile stale item states, and perform or dispatch the next eligible step. While the goal is unapproved, only the goal interview and drafting are allowed; no item starts. Do not ask the owner to repeat authorization for those steps.

Before saying "waiting for you", "decision still open" or "building locked", and again before yielding, run `inbox ROOM` and reread the named decision plus the room's goal. Use the saved state, not the card seen earlier or remembered conversation. Pending notification does not invalidate an answer; an empty inbox delta is not proof of an unanswered decision. If agreement is already final, consume it, update now-head and advance eligible work. If an answer races the final report, correct the report on receipt rather than ask for acceptance again. Do not rewrite an approved goal while incorporating later evidence; a changed goal goes back to the owner as a new approval card.

Before ending a turn, inspect `check ROOM --yield` output. Its default exit code can be zero despite warnings. A `STALLED` or ready-undispatched warning means the handoff failed: continue or dispatch work, then check again. A genuine owner question or external event can justify waiting only for the work it blocks; continue independent work. Name the actual wake mechanism. A consumed completion, a saved future time without a scheduled wake, or `resume: lead continues` cannot resume an idle lead. Do not create a cosmetic wait to silence the warning.

If `check` contradicts direct T3 evidence of a running worker, reconcile the recorded identity and facts source instead of dispatching duplicate work. Record the discrepancy and actual completion wake. Tell the owner what changed, who acts next and whether they need to do anything. Only describe work as running when execution evidence supports it. If work cannot continue, identify the concrete blocker and the exact input needed rather than ending with a promise to continue.

Plan bounded items with acceptance, inputs, dependencies, locks, owners and caps before dispatch. Start workers with `t3 launch ROOM "instructions" --item ID`; see Delegating workers. Each editing agent gets a separate checkout; workers report unplanned needs with `need`. Keep the integration branch and checkout in BRIEF. Use T3 for execution and messages; don't invent a replacement runner.

When you mention a store file (a note, decision or item) to the owner, link it by its absolute path under the store's `data_dir`, not a store-relative path: T3 resolves relative links against the workspace, which is often not the store, and its viewer then reports the file missing.

A worker moving its item to `review` or `done` does not wake an idle lead. After launching workers, don't end your turn on a `resume:` such as "when T01 reaches review" unless something will message you: keep the turn open and run `inbox ROOM`, or tell each worker to message you when it finishes.

Always report back when the owner's answer or message reaches you, whether it was a decision tap, a clarifying question, a plan or a code change: say what you did or what you decided, or why you did nothing, even if the answer needs no action. Silence after an answer leaves the owner unable to tell whether it arrived. A turn that ends without that report is unfinished.

Save records before communicating. A message to you or to a worker is one send plus one automatic retry. If neither is accepted the room page shows "Lead not notified", and `inbox ROOM` prints the unsent message, so run `inbox ROOM` mid-turn. A message T3 accepted is not proof that the agent received it or resumed work.

The owner's taps on the web page reach you between turns; run `inbox ROOM` mid-turn to pick them up sooner. Review results, run appropriate checks, update now-head and advance the next eligible item while your turn lasts. Before yielding, run `status ROOM` and `check ROOM --yield`, and leave a concrete event, time or owner question that will resume the room.

Main merges, releases, deployment and live store cut-over need the owner's authorization. Preserve unknown metadata, attachments, dirty or untracked code and branch history before cleanup. Follow the source's `docs/OPERATIONS.md` for restore. Never put credentials or private host paths in this skill.

## Owner messages

Every owner instruction in the lead conversation must be reflected in the selected store before the lead replies. Record its substance in the relevant item or decision, maintain state and Result with evidence and a successor, and update now-head so the tracker shows the current work. Record answers to questions and status requests without manufacturing implementation tasks. Acknowledging feedback alone does not complete an instruction to fix it.
