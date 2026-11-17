# atr for T3 Code

Connects atr to [T3 Code](https://t3.codes) (and Ari Code, which is built on it). The project's lead and its
workers are T3 threads. Two parts:

| Part | What it does |
| --- | --- |
| `bin/atr-lead-t3` (lead provider) | starts the lead as a T3 thread (`t3 thread start`), wakes a thread with a message (`t3 thread send`), and says whether a thread is working, idle or gone (`t3 thread show`) |
| the `atr` Claude Code plugin (`hooks/`) | runs inside T3's Claude threads: the plan at turn start, a check at turn end, and the lead claim |

| Hook | What it does |
| --- | --- |
| SessionStart | a new thread: claims the lead (the first thread to take a turn in the repo, or the one atr started), and puts `atr read` into its context. A resumed thread (T3 starts a new process for each run) only hears what changed |
| UserPromptSubmit | when the owner changed something since the lead last read, adds `atr read` to the prompt |
| Stop | holds the turn if the owner changed something while the lead worked |

Threads are named by their T3 thread id (`T3CODE_THREAD_ID`). Any other thread in the repo is told it is a
worker, and given its id to put on its task with its first `atr now T3 "..." --thread <id>`, so the lead can
check on it (`atr alive T3`) and wake it (`atr resume T3`).

**The push.** T3 ends a thread's process when its turn is over, so nothing can listen inside the thread.
Instead `atr serve` rings the lead: about 20 seconds after you stop acting on the page (and on its minute
watch, for news from GitHub and about workers), it sends the lead what changed as a message in its own thread,
as a sentence and as data:

```
The owner acted on the atr page (or GitHub on your PRs, or atr on your workers) while you were idle:
- [demo] answered D1 (which db?): sqlite {"op": "answer", "args": {"id": "D1", "choice": "sqlite"}}
Act on this, and run `atr read` to mark it read.
```

Each change rings the lead once. A lead in the middle of a turn is not rung: its Stop check shows it the news.
`ATR_DOORBELL=0` (in `atr serve`'s environment) turns the push off.

The plugin does nothing outside T3 (no `T3CODE_THREAD_ID`) and in folders without a `.atr` file.

## Install

1. atr on your `PATH` (or `ATR_BIN`), and the provider next to it: from a checkout, `bin/atr install` links
   both; otherwise `ln -s ~/dev/atr/extensions/t3/bin/atr-lead-t3 ~/.local/bin/`.
2. T3's `t3` command: open T3 Code once, which writes `~/.t3/bin/t3`. The provider also finds it through
   `T3_BIN`, `T3CODE_CLI_PATH` or `PATH`.
3. The plugin, in **every Claude config folder T3 uses**. Each Claude provider instance in T3 may have its own
   (Settings → Providers → home path, e.g. `~/.claude_work`); the default is `~/.claude`. For each:
   ```sh
   CLAUDE_CONFIG_DIR=~/.claude_work claude plugin marketplace add mvexel/atr
   CLAUDE_CONFIG_DIR=~/.claude_work claude plugin install atr@atr
   ```
   The atr page's **Upgrade** updates the plugin in each of them. A thread loads plugins when its process
   starts, so a thread that is running when you install picks it up on its next turn.
4. Add the repo as a T3 project, so `atr init` can start the lead there.
5. Run `atr serve` as a service (`atr service install`), so the push works while you are away.

## Side questions

T3 cannot start a read-only thread, so the provider answers the page's side questions with headless Claude
(`claude -p` in plan mode, edit tools off, `ATR_SIDE` set). It needs `claude` on `atr serve`'s `PATH`.

## Limits

- Workers have to run in their own T3 threads (launched or delegated) for atr to check and wake them; a
  subagent inside the lead's turn has no thread.
- A T3 thread that never ends is never "gone": atr calls the lead gone only when T3 no longer has the thread
  (or it is archived), or you let it go on the page.
