# Extensions: connecting atr to an agent tool

atr does not run, start or message agents. The owner's changes reach the lead only when the lead runs
`atr read`. An extension closes that gap for one agent tool (a "harness"): Claude Code, Codex, a chat bot, a
cron job. atr itself stays harness-free; an extension is a small adapter that calls the commands below.

`extensions/claude-code/` is the reference extension.

## What an extension does

An extension can do any of these three jobs. Each one is useful on its own.

1. **Turn start.** When the lead's turn starts, show it what the owner changed. Run `atr unread`. If it
   exits 0, run `atr read` and put the output into the lead's context.
2. **Turn end.** Before the lead ends a turn, check again. If the owner changed something while the lead
   worked, keep the turn going and point the lead at `atr read`. Check the harness's loop guard first, so the
   lead is never held forever.
3. **Doorbell.** While the lead is idle, wake it when the owner acts. Run `atr wait`. When it exits 0, wake
   the lead in whatever way the harness offers, for example a message to `lead_thread` or a background job
   that re-invokes the session. Then run `atr wait` again.

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
  "running": [{"id": "T3", "title": "…", "last_news_at": "2026-11-15T19:40Z"}],
  "own": true,
  "projects": [{"project": "adhush", "own": true, "…": "the same fields, once per followed project"}]
}
```

- `unread` lists only the owner's changes. The lead's own changes never wake it. Each one has `what`,
  a sentence for the lead, and `op` and `args`: the page action and what the owner sent with it (the
  card's answer, the decision's verdict, a task's new goal). Pass them on as they are. Changes recorded
  before atr kept `op` have only `what`.
- `lead_waiting` is true while an `atr wait` for this project is running. The page shows "Lead listening"
  and tells the owner the lead is being woken. Turn-end checks can use it: if it is false, the doorbell is
  not armed.
- `projects` lists every project the folder's lead follows: the folder's own (`own: true`) first, then
  any added with `atr watch NAME` from that folder. The top-level fields repeat the first entry. Cover
  every entry: read a followed project with `atr -p NAME read`. `atr wait` returns when any of them changes,
  and exit 2 means the folder has no project and follows none.
- `running` lists the tasks in progress and when there was last news of each. A session start should
  show them to the lead and ask it to confirm each still has a worker: workers often die with the
  session that started them, and atr cannot tell.

## Rules for extensions

- **Read through atr, never through `plan.json`.** The file format is not part of the contract. These
  commands are.
- **Only `atr read` marks changes read.** Run it when its output actually reaches the lead. If you only
  want to look, use `--peek` or `unread`.
- **Do not act as the owner.** Never set `ATR_AS=you`. An extension speaks for the lead.
- **Stay quiet outside atr projects.** On exit 2, do nothing.
- **Keep the lead from looping.** A turn-end check that blocks has to give way when the harness says the
  lead is already continuing because of it.
