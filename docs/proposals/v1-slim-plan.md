# atr v1 slim-down: plan

Status: draft, agreed in conversation 2026-11-11. Nothing implemented.

## Goal (the 3 fields, dogfooding the new cycle)
- **Architecture:** all local on the owner's laptop. State is plain files, reached only through one interface (the `atr` CLI / local API). The state/runner split stays possible, but no code is written for it.
- **Minimal viable result:** overview (running / waiting / blocked-on), dependencies with auto-start, owner-only decision cards on the local web page, a goal-setting cycle that gates the start of work.
- **Definition of done:** (1) no worker starts in a room until the owner approves its goal; (2) ready items auto-start, max 3 at once, and new starts pause on the first failure; (3) cards answerable from the phone over the tailnet while the laptop is awake; (4) none of the cut features remain in code, docs, CLI help or tests; (5) the remaining test suite passes.

## Cut
Public installer; PRDs and refinements; maintainer/triage thread and `process` room; delivery-state tracking; team/relay/migrate; check/bottleneck heuristics (pending review); neutral-source tests; hosting (boxd). Parked with triggers: boxd card inbox (revisit after two missed cards), teammate cards (revisit when an Ari teammate must answer one).

## Rules for every step
- One commit per step, each independently revertable. Suite green before and after.
- Delete code, tests and docs together. No flags or "legacy" shims.
- Anything outside this list that looks cuttable goes to the owner as a decision, not a silent delete.

## Steps

### S0. Discovery (read-only, before any deletion)
Answer, in writing, in this file:
1. How does a decision card reach the lead today? Trace `cmd_answer`, `after_answer`, `_web_answer`, `tell_lead_or_defer`, `cmd_inbox`, `cmd_reply`. What is the minimum that must survive once delivery states go?
2. What in `cmd_serve` and `web/index.html` is cards/overview versus teammate, maintainer, PRD or delivery UI? Produce a keep/cut list by function and HTML section.
3. What are `problems`, `bottlenecks`, `continuity` actually used for (page, lead nudges)? Recommend keep, trim or cut.
4. Does the login service (`cmd_service`, `cmd_setup`) stay? What is the smallest setup that works?
Gate: owner reads S0 answers and approves S1 to S5 as written or amended.

### S1. Public-release code
Remove `install.sh`, `cmd_self_update`, `cmd_uninstall`, `cmd_doctor` (unless S0 says keep), completions, NixOS/setup docs, neutral-source tests, installer tests. Update README to a short "run from a checkout" section.

### S2. PRD to goal
Replace `template/prd.md`, `refinement.md`, `cmd_prd`, `cmd_refinement` and `test_refinements.py` with a 3-field goal file (architecture, minimal viable result, definition of done) and `atr goal <room> approve`. `build_locked` becomes "goal not approved"; same refusal in `cmd_set` and `t3 dispatch`. Small rooms: one-line goal, still approved. Rewrite the interview script in `skills/lead/SKILL.md` (3 to 5 typed questions, then a half-page summary to approve). Show the goal at the top of the room page and in every worker brief.

### S3. Maintainer, team, relay, migrate
Remove `cmd_feedback`, maintainer setup, `process` room, `cmd_team`, `cmd_name`, teammate paths in inbox/reply, `atr_migrate.py`, `cmd_migrate` and their tests. Document `ari relay` as the way to reach teammates' agents.

### S4. Delivery states
Replace the queue/attempt/reconcile machinery (`attempt_delivery`, `t3_execute`, `_delivery_block`, `cmd_delivery`, deferred taps) with send-and-record: call T3, write the result to the log, surface failure on the page. Cards must still wake the lead. Depends on S0 answer 1.

### S5. Auto-start
New loop: take `plan()` ready items, subtract running workers from the cap (3), dispatch each, stop and flag on the first failed or blocked start. Only runs when the goal is approved and the room is not paused. About 60 to 100 lines plus tests: cap respected, dependency order, pause on failure, no start before goal approval.

### S6. Web page trim and phone check
Apply the S0 keep/cut list to `cmd_serve` and `web/index.html`. Verify over the tailnet from a phone: overview, answer a card, goal approval.

### S7. Interface rule check
Grep that agents and the page touch state only through the single interface. Fix violations. Add a test that fails on direct file access from the page layer.

### S8. Final review
Independent read of the full diff against the definition of done. Update CHANGELOG and README. Owner approves merge.

## Team and lanes
`bin/atr` is one 4,254-line file, so parallel edits conflict. Keep code steps sequential and parallelise only where files differ.
- **Scout** (read-only): S0.
- **Core builder** (one worktree, sequential): S1, S2, S3, S4, S5, S7. One agent so the cuts and refactors stay consistent.
- **Web builder** (second worktree, from S6 start, after S4 lands): `cmd_serve` and `web/index.html` only.
- **Skill and docs writer** (third worktree): `skills/lead/SKILL.md`, README, CHANGELOG, from S2 onward. No `bin/atr` edits.
- **Reviewer** (read-only, fresh context): runs after S4 and at S8 against this file, not against the builders' summaries.
- **Lead**: owner decisions at the S0 gate, S4 gate and S8 merge only.

## Decisions
- Login service and `atr setup`: dropped. Run `atr serve` by hand. `cmd_service`, `cmd_setup`, `cmd_open` go in S1 (S0 answer 4 is now only "what minimal startup is needed").
- `process` room history: not archived, deleted in S3.

- Delivery (S4): save the answer first, one send attempt, one automatic retry after 60 seconds, then flag "lead not notified" on the room page. No queue, no "uncertain" state.
- Owner said GO on 2026-11-11: S0 runs now; S1 to S5 proceed unless S0 finds something that contradicts this plan.

## S0 findings (2026-11-11, changes to the plan)
- Baseline on branch slim/v1 (from fix/lead-continuation-contract): 398 tests, 2 failures already present (test_neutral_source core references; test_page_copy save/execution claims), 9 skips.
- **Order change:** S4 (delivery) before the deletions in S3. Delivery code (`queue_t3_action`, `_delivery_block`, `t3_execute`, `delivery_actions`) carries maintainer, process-room, migration and launch code, so `atr_migrate` and maintainer code cannot go first.
- **Keep `cmd_inbox`** (pull path for a busy lead), minus its delivery loop. `cmd_reply` sends nothing and stays.
- **S4 shape:** `_web_answer` and `cmd_answer` save first, then one `notify_lead(room, text)` that calls `t3 thread send` once. On failure write a "lead not notified" marker; the `serve` refresher loop re-sends once after 60 seconds, then leaves the flag. ~13 call sites of `queue_t3_action`/`tell_*` to convert.
- **S5 open design question:** atr cannot call T3 MCP tools; the lead dispatches workers today. Auto-start inside `atr serve` must use `t3 thread start` (today's `launch` path, which S4 removes) or message the lead to dispatch. Owner decides before S5.
- **Web:** cut processBlocks/processView, PRD pills and buttons, delivery text, install note, team activity chart; add a goal block and the flag. `/api/nudge`, `/api/search` and `/api/pause` need an owner call (default: keep pause, keep search, cut nudge with its delivery dependence).
- **check/bottlenecks/continuity:** trim `problems` to data integrity; cut overrun/review-stale/bottleneck rules; keep a trimmed `continuity` for the overview. SKILL.md references to `check --yield` and `delivery list` change with it.
- **S1 scope grows:** also remove `cmd_service`, `cmd_setup`, `cmd_open`, `cmd_doctor`, `check_setup`, `setup_warnings`, `service_summary`, `restart_service`, `on_path`. `select_data_dir` shrinks to `--data-dir` / `ATR_DATA_DIR`. `read_setup`/`write_setup` stay until S3 (maintainer uses them).
- **Revised order:** S1, S2, S4, S3, S5, S6, S7, S8.

## Owner decisions after S2 (2026-11-11)
- **S5 mechanism: message the lead.** atr never starts workers itself. It computes ready items from plan(), applies the cap (3 running) and the pause-on-first-failure rule, and sends the lead one message naming the items to dispatch (through notify_lead, so it gets the retry and the flag). The lead dispatches. No `t3 thread start` loop in atr serve. Trigger points: an item reaches done/dropped, a goal is approved, the owner unpauses.
- **Effort:** Sonnet at low effort is accepted for S3, S6, S7. S4 runs at default effort already. S5 and the S8 reviewer stay at default effort unless the owner says otherwise.
