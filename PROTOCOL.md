# Agent coordination workflow

Atr coordinates work on required T3. The selected local Markdown store is canonical; T3 owns agent execution, threads and messages. Use the same explicit `--data-dir` for every command and agent. See [setup](docs/SETUP.md) and [operations](docs/OPERATIONS.md).

## Start or resume a room

Read the room's `BRIEF.md`, `now-head.md`, binding PRD/refinements, and assigned item before work. A thread leads one room. Follow-up maintenance gets a separate room and thread; use `rooms new ... --waive-prd "not a feature: reason"` for authorized work that needs no product design. Quote the owner's request in a premise or decision before implementation.

New features start with a PRD. Record purpose, stakeholders, scope, testable requirements and definition of done. Product and technical sign-off precede `prd ROOM review`; the owner's explicit agreement opens building. Do not bypass the gate. Preserve agreed PRDs; record an authorized refinement for a bounded change and seek owner agreement for a pivot or changed acceptance.

## Plan and execute

Create an item for each bounded deliverable. State owner, acceptance, inputs, dependencies, locks and `cap_h` before starting. Plan dependencies first. Set `state=doing` before work; record progress, evidence and the next record in its Result before review/done. Workers report unforeseen prerequisites with `need ROOM ITEM "reason"` rather than expanding scope.

Each editing agent uses its own branch and checkout. Leave others' edits, stashes and primary branches intact. Use a separate durable scratch directory outside source/stores. Preserve salvageable code and untracked files before cleanup. Review before integrating; record the relevant tests and their limitations.

## Decisions and communication

Decisions carry lettered options, a named decider and whether they are easy or hard to undo. Record chat answers with `answer ... --quote` as well as page answers. Owner approval governs scope/phase changes, main merges, releases, deployment and irreversible actions. A prior scoped authorization is sufficient; do not ask for it twice.

Use the concrete T3 commands for launches, thread facts and communication. Link store files in messages and records by absolute path, since T3 resolves relative links against the workspace, not the store. Leads always report back after an owner answer or message, even when no action follows. A saved record is not delivery. Inspect `delivery list` and reconcile uncertain acceptance using actual T3 evidence before retrying. Never invent a thread, receipt or completed execution. During outages keep the durable obligation and continue independent local work.

## Checkpoints and handoffs

An acknowledgement or progress report does not end authorized work. After an owner message or worker completion, reconcile the result and continue the next eligible step in the same turn. If the lead owns that step, do it; if a worker owns it, dispatch it before yielding. A PRD building gate blocks implementation, not the discovery, drafting and reviews needed to reach owner agreement.

Treat a `STALLED` or ready-undispatched warning from `check ROOM --yield` as a failed handoff: repair it and check again before ending the turn. A zero exit code from non-strict `check` is not a pass; inspect its output. An open owner question permits a wait only for work it actually blocks. Do not invent a question or waiting note to suppress a stall. `resume: lead continues` and already-consumed worker completions are not future triggers. A future time in a note does not itself schedule a wake.

If the check contradicts direct T3 execution evidence, reconcile the worker identity and facts source; do not launch duplicate work to silence it. Record the discrepancy and the verified completion wake before yielding.

The standing maintainer owns recurring workflow failures through diagnosis, a bounded correction, verification and successor tracking. Restarting a stalled lead is recovery, not resolution. Inspect T3 history to distinguish missed delivery from a lead that received the event and stopped. Record what the correction enforces and what still depends on agent compliance; do not promise runtime prevention from instructions or a diagnostic check alone.

Keep `BRIEF.md` repository/branch/checkouts and `now-head.md` phase, waiting owner and resume event current. Run `status ROOM` and `check ROOM`; before yielding run `check ROOM --yield`. A moving room needs active work, a real owner question, or an external event/time that can resume it. Native helper completion alone does not promise a new T3 turn. A worker's `set state=review|done` queues a notice to the lead thread (delivery rules apply), and `check` flags a room stalled when its free-text `resume:` awaits only finished items and the lead is idle; still keep the turn open on `inbox` as the fallback.

Before handoff, name the current commit, unfinished items, open decisions, checks, preserved artifacts and exact resume steps. Before close, finish/drop items and record disposition of source branches. Once the room's branch is pushed, its lead may open the PR and remove the room's own worktrees and local branches listed in `BRIEF.md`, only when the remote head matches the local head, the worktree has no dirty or untracked files, and every local branch is contained in the pushed branch (fold stacked worker branches into the integration branch first). Record commit, branch, PR URL and what was removed before removing it. If a check fails, stop and name what is at risk. Never touch other rooms' branches or worktrees. Main merge, remote branch deletion and removing unpushed or unmerged work need the owner's authorization. Do not auto-merge, deploy or delete unmerged work. Back up whole stores including hidden runtime/recovery data; source control alone is not a store backup.

## Standing maintainer initialization and owner messages

The process maintainer starts in the atr T3 project rooted at the atr source clone. Setup registers that project before launching the lead and opens the accepted thread in T3. On first run the lead reads the room records, registers itself, sets its title to `Room · process · lead`, pins itself, and fills the room goal, scope, repository paths and current status. The standing maintainer stays pinned even when no owner decision is open.

Every owner instruction in the lead conversation must be reflected in the selected store before the lead replies. Record its substance in the relevant item or decision, maintain state and Result with evidence and a successor, and update now-head so the tracker shows the current work. Record answers to questions and status requests without manufacturing implementation tasks. Acknowledging feedback alone does not complete an instruction to fix it.

## Maintenance feedback stays in process

Maintenance feedback, proposal progress, owner review and approval cards stay in the process room and its maintainer conversation. A project room may submit feedback but must not become a forwarding channel for maintenance updates. Do not send proposal/status/approval announcements back to a project lead for the owner. Verify actual tracker/API and rendered card visibility before saying an owner card is available, and provide its direct process-view link. A saved decision file alone is not proof of visible UI. Keep the process view separate from ordinary project rooms while making its pending owner actions discoverable.

Feedback resolution and successor block transfer update the shared store without automatically notifying originating project leads. Do not use generic tell_thread(project_lead, ...) for maintenance announcements: its routing is inferred from the recipient, so it is not a maintenance-origin guard. Use the process lead and process-scoped records. Confirmed historical messages can arrive later; inspect delivery timestamps and queued messages before diagnosing a new send. Never infer owner approval from a project-room message.
