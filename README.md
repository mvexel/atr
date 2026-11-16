# atr

A goal tree, tasks and decisions for a team of coding agents, on one page you can touch.

atr answers three questions that get lost when several agents work at once: why does this task exist,
what was decided, and how did the plan grow. It does not run, start or message agents; your agent tool does that.

## How it works

- **You** own the goals. On the page you answer cards, review the lead's judgment calls, drag tasks between
  goals, set what comes after what, and drop or park tasks.
- **The lead agent** adds tasks under your goals, keeps status current, records every judgment call with
  what it rejected, and attaches documents. It uses the `atr` command.
- **Nothing is pushed to agents.** The lead runs `atr read` when a turn starts and before it ends, and sees
  what you changed. The page shows when the lead has not read your changes yet; nudge it in its thread.

Each project is one `plan.json` (plus a `docs/` folder) under `~/.local/share/atr/<project>/`, or under
`ATR_DATA_DIR`. Only atr writes it. Back that folder up.

## Run it

Python 3 on macOS or Linux (tested on 3.14), no dependencies.

```sh
bin/atr serve                      # the page, at http://127.0.0.1:8787/
cd ~/dev/my-repo
atr init my-project "My project"   # creates the project and a .atr pointer file here; commit it
atr rules >> AGENTS.md             # the five rules the lead follows (or CLAUDE.md)
```

Then add your goals on the page and ask your lead agent to plan under them.

To open the page from a phone on your tailnet: `atr serve --host 0.0.0.0 --allow-host my-laptop.tailnet.ts.net`.
The page has no login, so only bind it to networks you trust.

## The lead's commands

| Command | What it does |
| --- | --- |
| `atr read` | the plan, plus what the owner changed since the last read (`--peek` does not mark it read) |
| `atr next` | unblocked tasks to start now; at most 3 run at once |
| `atr task add G1 "title" --after T1,T2` | add a task under a goal; refused without an accepted goal |
| `atr task set T3 status=doing thread=URL owner=NAME` | update a task; `doing` is refused while dependencies or a card are open; `after=T2` adds a dependency |
| `atr task stopped T3 "what was left"` | confirm work stopped on a task the owner dropped or parked |
| `atr decide T3 "chosen" --why ".." --rejected ".."` | record a judgment call; `--hard` asks the owner instead and blocks the task; `--owner` records something the owner said |
| `atr goal propose "title" --done ".."` | suggest a goal; it gets no tasks until the owner accepts it |
| `atr attach T3 file-or-link` | link a document; files are copied into the project so they outlive a worktree |
| `atr lead URL` | store the lead's thread link |

`-p NAME` or `ATR_PROJECT` selects a project when there is no `.atr` file. From your own terminal,
`ATR_AS=you atr goal add "title" --done ".."` adds a goal without the page. Agents are told not to set `ATR_AS`;
atr cannot tell who is typing, so this is a convention, not a lock.

## Plugins

atr has no harness-specific code. Two optional pieces can live outside it, per agent tool:

- **A turn hook** that runs `atr read` for the lead automatically, where the tool supports hooks.
- **A doorbell** that wakes an idle lead: poll `atr unread --json` (exit 0 when there are unread owner changes;
  the output includes the lead's thread link) and call the tool's own way of messaging a thread.

Neither ships here yet.

## Tests

```sh
python3 -m unittest discover tests
```

## License

[Functional Source License 1.1](LICENSE.md) (FSL-1.1-ALv2).
