```
█████╗ ████████╗██████╗ 
██╔══██╗╚══██╔══╝██╔══██╗
███████║   ██║   ██████╔╝
██╔══██║   ██║   ██╔══██╗
██║  ██║   ██║   ██║  ██║
╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝
```

**Own your agent teams. Keep your sanity.**

> “Why are my agents not doing anything? Are they waiting for me?”  
> “What is that agent up to? I didn’t tell them to do that.”

If you run several agents at once, you’ve probably asked yourself both of those questions. `atr` is a small local tool that answers them. It keeps a plain-text record of what’s planned, what’s in progress, what’s waiting on you, and what has actually shipped.

**Requires [T3](https://t3.codes/).** T3 runs the agents; atr records and tracks them. atr keeps recording without it, but nothing reaches an agent until T3 is there.

`atr` is a layer on top of [T3 Code](https://t3.codes/). T3 runs the agents (Claude, Codex or whichever providers you’ve signed in) and their threads. `atr` adds the plan, the record of what happened, and a CLI and simple web view to check on it.

> **Back up your data directory.** Your plans and decisions live there (including the hidden `.atr/` folder). Updating `atr` never restores them, and T3 and project state need their own backup, using T3’s process.

## How it works

You work in T3 and check in on atr’s web page. You don’t need the `atr` command much:

- **You** describe what you want in a T3 thread, answer questions, and approve plans.
- **The lead**, the agent in that thread, writes the plan, splits it into items, starts a worker thread in T3 for each item, and records what happened. It uses the `atr` command to do this.
- **atr** keeps all of it as plain files and shows it on a web page, so you can see the state without reading agent threads.

One room is one project or feature, led by one T3 thread.

## Why it’s useful

- **Your files, your folder.** Plans and decisions are plain Markdown in a folder you pick, separate from the code. Read them, grep them, put them in git.
- **Keeps recording when T3 is down.** T3 is required, but if it is down or missing you can still read, search, and record decisions. Nothing is queued: the lead is flagged as not notified and reads what it missed with `atr inbox`.
- **No wishful thinking about messages.** atr won’t claim an agent got your message just because T3 accepted it. It saves your answer first, sends the lead one message, retries once after a minute, and flags the room “Lead not notified” if T3 never accepted it.
- **Review before building.** No worker starts until you’ve approved the room’s goal.

## Run from a checkout

You’ll need Python 3.13+ on a POSIX system (Linux or macOS), git, and [T3](https://t3.codes/) with at least one model provider signed in (for example `claude auth login`).

```sh
git clone https://github.com/mvexel/atr && cd atr
python3 bin/atr serve --data-dir DIR
```

`DIR` is where your plans and decisions live. `--data-dir` (or `ATR_DATA_DIR`) selects it for every command; with neither, atr uses `~/.local/share/atr`. The web page is at `http://127.0.0.1:8787/`.

## Your first project

1. **Open the web page** at `http://127.0.0.1:8787/`, after `atr serve` is running.

2. **Start a room from T3.** Open a new thread in T3, in the project you want worked on, and ask for it, like you’d brief a person:

   > Start an atr room for a settings page: dark mode, language, and notification preferences.

   The agent creates the room and becomes its lead. The room shows up on the web page.

   From a terminal, `atr start "a settings page …"` does the same: it starts the thread in T3 for you, in the project of the folder you run it from.

3. **Approve the goal.** The lead asks you a few questions in the thread (architecture, minimal viable result, definition of done) and writes them up as the room's goal. A card on the web page asks you to approve it. No worker starts before you do.

From there, the lead splits the work into items and starts workers in T3.

## Day to day

Check the web page:

- **Cards waiting on you**: questions and decisions. Tap an answer and the lead picks it up.
- **Items**: what’s to do, in progress, in review, blocked or done. Open one for its details and result.
- **Rooms**: which of your rooms need you, if you run several.

Once a goal is approved, atr messages the lead when items are ready: at most 3 running at once, critical path first, one message per change. It never starts workers itself. A blocked item (`atr need`) or a paused room stops new offers, and the room page says why.

To change course, talk to the lead in its T3 thread. To start something new, ask in a new T3 thread: one thread leads one room.

## The command line

The `atr` command is mainly for the lead and its workers. The ones you might use:

| Command | What it does |
| --- | --- |
| `atr start "what you want"` | start a room’s lead thread in T3 from the terminal |
| `atr lead ROOM` | text that hands an existing room to a different T3 thread |
| `atr room list` | every room, from the terminal |
| `atr next ROOM` | dry run: which ready items atr would offer the lead now (sends nothing) |

`atr --help` lists the rest.

## Documentation

- [Operations](docs/OPERATIONS.md): telling the lead, backup, restore
- [Dependencies](docs/DEPENDENCIES.md): runtime requirements and licensing notes
- [Workflow](PROTOCOL.md) and [lead skill](skills/lead/SKILL.md): how agent work gets coordinated

## Good to know

- **What it does:** local records, rooms, items and decisions, dependency tracking, review gates, the CLI and web view, the T3 bridge.
- **What it doesn’t, for now:** Git/PR tracking, usage and budget collection, scheduled runs, external notifications. To reach a teammate's agent, use `ari relay`.
- **Licensing:** project licensing and any public release are separate decisions; see [Dependencies](docs/DEPENDENCIES.md).

## License

atr is licensed under the [Functional Source License 1.1](LICENSE.md) (FSL-1.1-ALv2). You may use, modify and redistribute it for anything except offering a competing commercial product or service. Each release becomes available under the Apache License 2.0 two years after it is published. For other terms, contact the author.
