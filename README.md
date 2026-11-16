# atr

A goal tree, tasks and decisions for a team of coding agents, and a locally hosted tracking page.

`atr` answers three questions I very often have when working with a team of agents on a project or larger task: 

1. why does this task exist,
2. what was decided, 
3. how did the plan grow.

YMMV: working with agents in a team setting is something that has not been figured out yet, and I believe we should all figure it out for ourselves and share our approaches. It's the only way to learn and grow.

My design principles for this project were:
- KISS
- YAGNI
- harness-agnostic
- extensible

## How it works

- Every project starts with one or more goals. **You** own these and only these fully. 
- On the page you answer cards, review the lead's judgment calls, drag tasks between
  goals, set what comes after what, and drop or park tasks.
- The lead agent adds tasks under your goals, keeps status current, records every judgment call with
  what it rejected, and attaches documents. It uses the `atr` command.
- **Nothing is pushed to agents.** The lead runs `atr read` when a turn starts and before it ends, and sees
  what you changed. The page shows when the lead has not read your changes yet; nudge it in its thread.

Each project is one `plan.json` (plus a `docs/` folder) under `~/.local/share/atr/<project>/`, or under
`ATR_DATA_DIR`. Only atr writes it. Back that folder up.

## Getting started

Python 3.13+ on macOS or Linux (tested on 3.14), no dependencies.

1. **Install the command.** Either way gives you `atr` on your `PATH`:
   ```sh
   uv tool install git+https://github.com/mvexel/atr   # installed copy; update with uv tool upgrade atr
   # or, from a checkout (a git pull updates it):
   bin/atr install                    # links ~/.local/bin/atr to this checkout (--dir for elsewhere)
   ```
   To try it without installing, prefix any command with `uvx --from git+https://github.com/mvexel/atr`,
   e.g. `uvx --from git+https://github.com/mvexel/atr atr serve`. Agents and the extension hooks need
   `atr` on `PATH`, so install it for real use. `~/.local/bin` must be on your `PATH`.
2. **Start the page.** Leave it running:
   ```sh
   atr serve                          # http://127.0.0.1:8787/
   ```
3. **Create a project** in the repo your lead agent works in:
   ```sh
   cd ~/dev/my-repo
   atr init my-project "My project"   # creates the project and a .atr pointer file here; commit it
   ```
4. **Give the lead its rules.** Append them to the file your agent reads:
   ```sh
   atr rules >> AGENTS.md             # or CLAUDE.md
   ```
5. **Add a goal on the page**, with a done test: how will you know it is met?
6. **Ask your lead agent to plan under it.** It runs `atr read`, proposes tasks and records its decisions.
   Answer its cards on the page; it sees your answers on its next `atr read`.
7. **Optional:** install an [extension](#extensions) so the lead is shown your changes without being asked.

**Keep the page running.** `atr service install` registers a login service (launchd on macOS, a systemd
user unit on Linux) that runs `atr serve` at login and restarts it if it stops. It takes `serve`'s
`--host`, `--port` and `--allow-host`, and passes on `ATR_DATA_DIR` if set. Run it again after
`uv tool upgrade atr` to restart on the new code; `atr service uninstall` removes it. It needs a real
install (`uv tool install` or a checkout), not `uvx`. Logs: `/tmp/atr.log` on macOS, `journalctl --user -u atr` on Linux.

To open the page from a phone on your tailnet: `atr serve --host 0.0.0.0 --allow-host my-laptop.tailnet.ts.net`.
The page has no login, so only bind it to networks you trust.

## The lead's commands

| Command | What it does |
| --- | --- |
| `atr read` | the plan, plus what the owner changed since the last read (`--peek` does not mark it read) |
| `atr next` | unblocked tasks to start now; it offers at most 3 running at a time |
| `atr task add G1 "title" --after T1,T2` | add a task under a goal; refused without an accepted goal |
| `atr task set T3 status=doing thread=URL owner=NAME` | update a task (`status`: `todo`, `doing`, `blocked`, `review`, `done`, `dropped`; also `title=`, `note=`); `doing` is refused while dependencies or a card are open, or the goal is out of budget; `after=T2` adds a dependency; `owner=you` marks work only the owner can do |
| `atr task set T3 status=review note="check .."` | hand finished work to the owner to check; only the owner can mark it done |
| `atr task stopped T3 "what was left"` | confirm work stopped on a task the owner dropped or parked |
| `atr decide T3 "chosen" --why ".." --rejected ".."` | record a judgment call; `--hard` asks the owner instead and blocks the task (on a goal: holds all its tasks); `--owner` records something the owner said in chat; it shows on the page for them to confirm |
| `atr ask T3 "What do you watch?" --option cable --option streaming` | a plain question with no recommendation; holds the task (or goal) until the owner answers |
| `atr decide T3 ".." --by worker-name` | a worker records its own call; the lead sees it on its next read |
| `atr now T3 "scoring run 2 of 3"` | one line on what a running task is doing (workers may use it) |
| `atr goal propose "title" --done ".." --tries 5 --days 3` | suggest a goal; it gets no tasks until the owner accepts it. The done test shows as the lead's guess until the owner confirms it. `--tries`/`--days` give it a budget |
| `atr try G1 "prompt B: 15 of 31 caught"` | record one attempt at a goal; when its tries or days run out, its tasks stop until the owner answers a card on the goal |
| (page) This goal is met | once all of a goal's tasks are done, the owner closes it; met goals take no new tasks until reopened |
| `atr outlook G1 unsure "half the ads"` | the lead's current read on whether a goal can be met as written (`likely`, `unsure`, `unlikely`) |
| `atr attach T3 file-or-link` | link a document; files are copied into the project so they outlive a worktree |
| `atr watch NAME` | follow another project from this folder (`--stop` to stop): the hooks and `atr wait` cover it too |
| `atr lead URL` | store the lead's thread link |
| `atr projects` | list projects with done, waiting and to-review counts |
| `atr service install` | keep `atr serve` running in the background (`uninstall` removes it) |
| `atr rules` | print the rule block for `AGENTS.md` / `CLAUDE.md` |
| `atr unread`, `atr wait` | for extensions: whether the owner changed something unread; block until they do (`--timeout`, default 3600 s). See Extensions |

`-p NAME` or `ATR_PROJECT` selects a project when there is no `.atr` file. From your own terminal,
`ATR_AS=you atr goal add "title" --done ".."` adds a goal without the page. Agents are told not to set `ATR_AS`;
atr cannot tell who is typing, so this is a convention, not a lock.

## Extensions

atr's core has no code for any particular agent tool. An extension connects atr to one tool: it shows the
lead the owner's changes when a turn starts, holds a turn that is about to end while changes are unread,
and wakes an idle lead when the owner acts (`atr wait`). [docs/EXTENSIONS.md](docs/EXTENSIONS.md) describes
the commands and rules an extension builds on.

Shipped here: [Claude Code](extensions/claude-code/).

## Tests

```sh
python3 -m unittest discover tests
```

## License

[Functional Source License 1.1](LICENSE.md) (FSL-1.1-ALv2).
