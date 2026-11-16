# Extensions: connecting atr to an agent tool

atr does not run, start or message agents. The owner's changes reach the lead only when the lead runs
`atr read`. An extension closes that gap for one agent tool (a "harness"): Claude Code, Codex, a chat bot, a
cron job. atr itself stays harness-free; an extension is a small adapter that calls the commands below.

`extensions/claude-code/` is the reference extension.

## What an extension does

An extension can do any of these four jobs. Each one is useful on its own.

1. **Turn start.** When the lead's turn starts, show it what the owner changed. Run `atr unread`. If it
   exits 0, run `atr read` and put the output into the lead's context.
2. **Turn end.** Before the lead ends a turn, check again. If the owner changed something while the lead
   worked, keep the turn going and point the lead at `atr read`. Check the harness's loop guard first, so the
   lead is never held forever.
3. **Doorbell.** While the lead is idle, wake it when the owner acts. Run `atr wait`. When it exits 0, wake
   the lead in whatever way the harness offers, for example a message to `lead_thread` or a background job
   that re-invokes the session. Hand the lead the owner's changes from `atr wait --json` (`what`, `op`,
   `args`) so it can act without asking. Then run `atr wait` again. The Claude Code extension does this
   with an `asyncRewake` hook, so the lead never has to arm it.

4. **Lead provider.** Start the lead thread when the owner creates a project, and say whether a thread is
   still running and bring it back. Ship an executable named `atr-lead-<tool>` (see below); `atr init`,
   `atr lead --start`, `atr alive`, `atr resume` and `atr serve` run it.
5. **Session end.** When a session ends, run `atr ended ID` with its thread id: it lets go of the lead (if
   that thread led) and tells the lead at once about any running task whose worker it was.

## Lead providers

A lead provider is any executable on `PATH` named `atr-lead-<tool>`. atr runs it as
`atr-lead-<tool> PROJECT TITLE`, in the project's repo, with `ATR_PROJECT` set, and waits up to two minutes.

- **Success:** exit 0 and print the lead's link as the last line of stdout. atr stores it as the lead
  thread (`atr lead`). If an earlier line reads `thread-id: ID`, atr makes thread `ID` the lead (see
  [One lead per project](#one-lead-per-project)), replacing any lead there was. An `http(s)` link shows on the page as a link; anything else, such as the command
  that opens a local session, shows as text to copy.
- **Failure:** exit non-zero and say why on stderr. atr shows the last line to the owner and stores
  nothing. `atr init` still succeeds.
- Start the lead so it reads its rules (`atr rules`) and the plan (`atr read`). The new project has no
  goals yet, so the lead should say so and wait for the owner.

A provider also answers three verbs (atr passes them as the first argument, so a provider must check for them
before it reads a project name):

| Call | Answer |
| --- | --- |
| `atr-lead-<tool> resume ID [MESSAGE]` | bring thread `ID` back with its context and give it `MESSAGE`; exit 0 and print `thread-id: ID` and its link as for a start, or exit non-zero and say why on stderr |
| `atr-lead-<tool> alive ID` | exit 0 when thread `ID` is running, 1 when it is not, anything else when it cannot tell |
| `atr-lead-<tool> ask PROJECT QUESTION [ID]` | answer the owner's side question in a new thread, or as a follow-up in thread `ID`, reading only; exit 0 and print `thread-id: ID`, then the answer (markdown), or exit non-zero and say why on stderr |

The Claude Code provider runs `claude --bg --resume ID MESSAGE` and `claude agents --json`. atr uses them
to bring back a lead that is gone (it starts a fresh lead with the start call when the resume fails) and a
worker the lead asks for (`atr resume T3`), and to check, before calling a lead gone, that its tool does not
still run it. atr picks the provider that started the lead, or the one on `PATH`.

**Side questions.** The page has a box on each project where the owner asks about it. `atr serve` runs
`ask` in the background (up to 15 minutes) with `ATR_SIDE=1` set, and shows the answer under the box with a
follow-up box. Under `ATR_SIDE` atr runs only `read` (which then marks nothing read), `next`, `rules`,
`projects` and `unread`, and refuses every change; an extension's hooks should stay quiet in such a session
(no lead claim, no listener, no worker rules). Side questions are kept in the project's `side.json`, outside
the plan: they raise no revision and never wake the lead. The Claude Code provider runs `claude -p` in plan
mode with the edit tools off, and `--resume ID` for a follow-up.

`atr init` uses the provider when exactly one is on `PATH` (`--lead TOOL` picks one, `--lead none` skips).
`atr install` (from a checkout) links every `extensions/*/bin/atr-lead-*` next to `atr`.

## The contract

Every command finds the project the way the lead does: from the `.atr` file in the working directory (or a
parent, or the main checkout of a git worktree), or from `-p NAME` / `ATR_PROJECT`. The plan data is in
`ATR_DATA_DIR`, or `~/.local/share/atr` by default.

| Command | Exit codes | Use |
| --- | --- | --- |
| `atr unread [--json]` | 0 unread owner changes · 1 none · 2 no project here, or another error | cheap check; never marks anything read |
| `atr wait [--timeout S] [--json]` | 0 owner changes arrived (or were already unread) · 1 timed out · 2 error | blocks; polls the plan file about once a second; default timeout 3600 s |
| `atr read [--peek]` | 0 · 2 error | the full plan for the lead; marks it read unless `--peek` |

Treat exit 2 as "this folder is not an atr project". Do nothing, silently. That way an extension can be
installed globally and only act where a `.atr` file exists.

`--json` output, the same for `unread` and `wait`:

```json
{
  "project": "adhush",
  "lead_thread": "https://…",
  "lead_waiting": true,
  "unread": [{"rev": 4, "by": "you", "at": "2026-11-15T20:01Z", "what": "answered D1 (…): sqlite",
              "op": "answer", "args": {"id": "D1", "choice": "sqlite", "note": ""}}],
  "lead_id": "85aade68-…",
  "running": [{"id": "T3", "title": "…", "last_news_at": "2026-11-15T19:40Z"}]
}
```

- `unread` lists the owner's changes (`by: "you"`), news from GitHub about the project's pull requests
  (`by: "github"`: one merged, its CI turned failing, or it conflicts) and news from atr about the project's
  threads (`by: "atr"`: a worker went silent or ended, the lead was brought back). The lead's own changes never wake it.
  Each one has `what`, a sentence for the lead. The owner's also have `op` and `args`: the page action and
  what the owner sent with it (the card's answer, the decision's verdict, a task's new goal). Pass them on as
  they are. GitHub's news, and changes recorded before atr kept `op`, have only `what`.
- `lead_waiting` is true while an `atr wait` for this project is running. The page shows "Lead listening"
  and tells the owner the lead is being woken. Turn-end checks can use it: if it is false, the doorbell is
  not armed.
- `lead_id` is the thread that leads the project now, or `""` when none does (or it is gone).
- `lead_state` is `listening`, `working`, `running`, `gone`, or `""` when no thread has claimed the lead.
- `running` lists the tasks in progress, when there was last news of each, its `thread`, and whether atr
  has marked it `silent` or `ended`. A session start should show them to the lead and ask it to confirm each
  still has a worker: workers often die with the session that started them.

## One lead per project

A project has one lead thread, and a thread leads one project. An extension whose harness names its
sessions enforces this with two commands:

| Command | Exit codes | Use |
| --- | --- | --- |
| `atr lead --claim ID [--json]` | 0 thread `ID` leads the project (it took the lead, or already had it) · 1 another thread leads it, or `ID` leads another project · 2 error | run at every turn start and end, and before arming the doorbell; it also refreshes the claim |
| `atr lead --release ID` | 0 | the session ended (older atr; `atr ended ID` does this and more) |
| `atr ended ID` | 0 | run when the session ends: the lead lets go, and a running task with `thread=ID` is news for the lead |

`--json` prints `{"lead": true|false, "id": "…", "seen": 1763318400.0, "project": "…"}`: who leads, when it
was last seen (Unix time), and which project (when `ID` already leads another one, that one).

- Give the lead's jobs (turn start, turn end, doorbell) to the lead only. Tell any other session who leads,
  that it is not the lead, and that it may work as a worker.
- A short id that starts the full one names the same thread (a provider may print the short one).
- **A gone lead holds nothing.** A lead is gone when its session ended (`atr ended`), or when for 10 minutes
  it has neither listened (`atr wait`) nor taken a turn (`--claim`), and its provider does not say it is
  still running. Its claim then blocks no one: the next session to claim becomes the lead. The page says the
  lead is gone and offers to bring it back; when the owner acts on the page and the lead has been gone 10
  minutes, `atr serve` brings it back on its own (at most once an hour). The owner can also let go of the
  lead on the page.

## Workers

Whoever starts a worker puts its thread on the task: the lead with `atr task set T3 thread=ID`, or the
worker with its first report, `atr now T3 "..." --thread ID`. A running task with no news for 30 minutes is
marked silent and written to the plan as news from atr (`by: "atr"`), so the doorbell wakes the lead; so is a
worker's session ending (`atr ended`). The lead then checks it (`atr alive T3`), brings it back
(`atr resume T3`), or sets the task back to todo. `atr serve` and a running `atr wait` look for silent tasks
every minute.

## Rules for extensions

- **Read through atr, never through `plan.json`.** The file format is not part of the contract. These
  commands are.
- **Only `atr read` marks changes read.** Run it when its output actually reaches the lead. If you only
  want to look, use `--peek` or `unread`.
- **Do not act as the owner.** Never set `ATR_AS=you`. An extension speaks for the lead.
- **Stay quiet outside atr projects.** On exit 2, do nothing.
- **Keep the lead from looping.** A turn-end check that blocks has to give way when the harness says the
  lead is already continuing because of it.
