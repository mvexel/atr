# atr for Claude Code

A Claude Code plugin that keeps the lead in step with its atr plan. It implements the three jobs in
[docs/EXTENSIONS.md](../../docs/EXTENSIONS.md) with hooks:

| Hook | What it does |
| --- | --- |
| SessionStart | puts `atr read` into the new session's context, so the lead starts with the plan, and starts the listener |
| UserPromptSubmit | when the owner changed something since the lead last read, adds `atr read` to the prompt |
| Stop | holds the turn if the owner changed something while the lead worked, and starts the listener again |
| SessionEnd | `atr ended <session>`: the lead lets go (the page says it is gone), and a task this session worked is news for the lead |

Any other session in the repo is told it is a worker, and given its session id to put on its task with its
first `atr now T3 "..." --thread <id>`, so the lead can check on it and resume it.

**The push.** The listener is an `asyncRewake` hook: it runs `atr wait` in the background while the lead
is idle. When you accept a goal, answer a card, pass a task or drop one on the page, it exits and Claude
Code wakes the lead with what you did, as a sentence and as data:

```
The owner acted on the atr page while you were idle:
- [atr] answered D1 (which db?): sqlite {"op": "answer", "args": {"id": "D1", "choice": "sqlite"}}
Act on this, and run `atr read` to mark it read.
```

The lead does not have to arm anything. Each session has one listener, so one action wakes the lead once.
While it listens, the page shows "Lead listening".

The plugin does nothing in folders without a `.atr` file.

**Starting the lead.** `bin/atr-lead-claude-code` is a lead provider: with it on your `PATH`, `atr init`
starts the lead as a background Claude Code session (`claude --bg`), named `<project> · lead`, told to
read `atr rules` and the plan and wait for your first goal. atr stores `claude attach <id>`, which the page
shows next to the project title: run it to open the lead. `atr install` from a checkout links the provider
next to `atr`; otherwise link it yourself, e.g. `ln -s ~/dev/atr/extensions/claude-code/bin/atr-lead-claude-code ~/.local/bin/`.
Claude Code has to trust the repo first (run `claude` there once); until then the provider says so and
`init` goes on without a lead. Set `CLAUDE_BIN` if `claude` is not on your `PATH`.
The provider also brings a session back, `atr-lead-claude-code resume ID` (`claude --bg --resume ID`, the
same session with its context), and says whether one runs, `atr-lead-claude-code alive ID`
(`claude agents --json`); atr uses them for a gone lead and for `atr alive` / `atr resume`.

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

Set `ATR_DOORBELL=0` to keep the turn-start and turn-end checks but turn off the push.

## Limits

- The push only works while the Claude Code session is open. If the session is closed, your changes
  wait for the lead's next session, and SessionStart shows them then.
- The listener's hook timeout is 24 hours. A lead idle longer than that stops listening until its next turn.
- Hooks see only the session's working directory. Start the lead in the project's repo, or in a worktree
  of it.
