# atr for Claude Code

A Claude Code plugin that keeps the lead in step with its atr plan. It implements the three jobs in
[docs/EXTENSIONS.md](../../docs/EXTENSIONS.md) with hooks:

| Hook | What it does |
| --- | --- |
| SessionStart | puts `atr read` into the new session's context, so the lead starts with the plan |
| UserPromptSubmit | when the owner changed something since the lead last read, adds `atr read` to the prompt |
| Stop | holds the turn if the owner changed something while the lead worked; otherwise, if the doorbell is not armed, asks the lead to arm it |

**The doorbell.** Claude Code re-invokes a session when a background command finishes. The lead runs
`atr wait` in the background. When you accept a goal, answer a card or drop a task on the page, `atr wait`
exits and the lead wakes up and runs `atr read`. While it waits, the page shows "Lead listening". The wait
times out after about two hours, which is Claude Code's limit for background commands. Then the lead
re-arms it.

The plugin does nothing in folders without a `.atr` file.

## Install

atr has to be on your `PATH`, or set `ATR_BIN` to its full path:

```sh
uv tool install git+https://github.com/mvexel/atr   # or, from a checkout: bin/atr install
```

Then in Claude Code:

```
/plugin marketplace add ~/dev/atr
/plugin install atr@atr
```

Set `ATR_DOORBELL=0` to keep the turn-start and turn-end checks but turn off the doorbell reminder.

## Limits

- The doorbell only works while the Claude Code session is open. If the session is closed, your changes
  wait for the lead's next session, and SessionStart shows them then.
- Hooks see only the session's working directory. Start the lead in the project's repo, or in a worktree
  of it.
