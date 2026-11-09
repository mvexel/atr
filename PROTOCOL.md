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

Use the concrete T3 commands for launches, thread facts and communication. Link store files in messages and records by absolute path, since T3 resolves relative links against the workspace, not the store. A saved record is not delivery. Inspect `delivery list` and reconcile uncertain acceptance using actual T3 evidence before retrying. Never invent a thread, receipt or completed execution. During outages keep the durable obligation and continue independent local work.

## Checkpoints and handoffs

Keep `BRIEF.md` repository/branch/checkouts and `now-head.md` phase, waiting owner and resume event current. Run `status ROOM` and `check ROOM`; before yielding run `check ROOM --yield`. A moving room needs active work, a real owner question, or an external event/time that can resume it. Native helper completion alone does not promise a new T3 turn. A worker's `set state=review|done` queues a notice to the lead thread (delivery rules apply), and `check` flags a room stalled when its free-text `resume:` awaits only finished items and the lead is idle; still keep the turn open on `inbox` as the fallback.

Before handoff, name the current commit, unfinished items, open decisions, checks, preserved artifacts and exact resume steps. Before close, finish/drop items and record disposition of source branches. Do not auto-merge, deploy or delete unmerged work. Back up whole stores including hidden runtime/recovery data; source control alone is not a store backup.
