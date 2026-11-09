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

**Requires [T3](https://t3.codes/).** T3 runs the agents; atr records and tracks them. The installer checks for T3 first and offers to install and start it. If you decline, setup still finishes and tells you T3 is missing; atr keeps recording, but nothing reaches an agent until T3 is there. `atr setup --check` exits non-zero without T3 (`--skip-t3` for CI or a restore).

`atr` is a layer on top of [T3 Code](https://t3.codes/). T3 runs the agents (Claude, Codex or whichever providers you’ve signed in) and their threads. `atr` adds the plan, the record of what happened, and a CLI and simple web view to check on it.

> **Back up your data directory.** Your plans and decisions live there (including the hidden `.atr/` folder). Installing or updating `atr` never restores them, and T3 and project state need their own backup, using T3’s process.

## How it works

You work in T3 and check in on atr’s web page. You don’t need the `atr` command much:

- **You** describe what you want in a T3 thread, answer questions, and approve plans.
- **The lead**, the agent in that thread, writes the plan, splits it into items, starts a worker thread in T3 for each item, and records what happened. It uses the `atr` command to do this.
- **atr** keeps all of it as plain files and shows it on a web page, so you can see the state without reading agent threads.

One room is one project or feature, led by one T3 thread.

## Why it’s useful

- **Your files, your folder.** Plans and decisions are plain Markdown in a folder you pick, separate from the installed code. Read them, grep them, put them in git.
- **Keeps recording when T3 is down.** T3 is required, but if it is down or missing you can still read, search, and record decisions. They go out when it’s back.
- **No wishful thinking about delivery.** atr won’t claim an agent got your message just because T3 accepted it. It shows saved, pending, uncertain, and accepted as separate states.
- **Review before building.** Agents don’t start building until you’ve agreed to the plan.

## Install

You’ll need Python 3.13+ on a POSIX system (Linux or macOS), git or curl + tar, and [T3](https://t3.codes/) with at least one model provider signed in (for example `claude auth login`).

```sh
curl -fsSL https://raw.githubusercontent.com/mvexel/atr/main/install.sh | sh
```

The installer fetches atr into `~/.atr/src`, asks where your data should live (default `~/.local/share/atr`), offers to put `atr` on your PATH and to install the T3 CLI if it’s missing, and runs `atr setup`. Setup does three things so you never have to manage atr by hand:

- **Keeps the web page running.** It installs a user service (systemd on Linux, launchd on macOS) that starts when you log in. The same process keeps track of your T3 threads and sends queued messages to them.
- **Lets agents in T3 find atr.** It links atr’s lead skill into `~/.claude/skills` and `~/.codex/skills`, where Claude Code and Codex look.
- **Records your data folder** in `~/.config/atr/config.json`, so agents use the same one you do.

`atr uninstall` undoes all three and keeps your data. The installer asks before each change; add `-s -- --yes` after `sh` to accept every default. To add the shell lines yourself, `atr setup --print-env` prints them for your shell and changes nothing. See [Setup](docs/SETUP.md) for the details.

## Your first project

1. **Open the web page** at `http://127.0.0.1:8787/`, or run `atr open`. Bookmark it; it’s always there.

2. **Start a room from T3.** Open a new thread in T3, in the project you want worked on, and ask for it, like you’d brief a person:

   > Start an atr room for a settings page: dark mode, language, and notification preferences.

   The agent creates the room and becomes its lead. The room shows up on the web page.

   From a terminal, `atr start "a settings page …"` does the same: it starts the thread in T3 for you, in the project of the folder you run it from.

3. **Agree the plan.** The lead drafts a plan with you in the thread. When it’s ready, a card on the web page asks you to agree. Nothing gets built before you do.

From there, the lead splits the work into items and starts workers in T3.

## Day to day

Check the web page:

- **Cards waiting on you**: questions and decisions. Tap an answer and the lead picks it up.
- **Items**: what’s to do, in progress, in review, blocked or done. Open one for its details and result.
- **Rooms**: which of your rooms need you, if you run several.

To change course, talk to the lead in its T3 thread. To start something new, ask in a new T3 thread: one thread leads one room.

## The command line

The `atr` command is mainly for the lead and its workers. The ones you might use:

| Command | What it does |
| --- | --- |
| `atr open` | open the web page (and start it, if it isn’t running) |
| `atr start "what you want"` | start a room’s lead thread in T3 from the terminal |
| `atr lead ROOM` | text that hands an existing room to a different T3 thread |
| `atr room list` | every room, from the terminal |
| `atr doctor` | check your setup without changing anything |
| `atr service status` | is the web page service running; `install`, `uninstall` and `restart` manage it |
| `atr self-update` | update atr and restart the web page; keeps your data |
| `atr uninstall` | remove atr from your shell and delete the fetched source; keeps your data and T3 |

`atr --help` lists the rest. Tab completion comes with the install in bash, zsh and fish.

## Documentation

- [Setup](docs/SETUP.md): install, choose a data store, connect T3, open the web view
- [Operations](docs/OPERATIONS.md): delivery states, reconciliation, backup, restore
- [Migration](docs/MIGRATION.md): copy, verify, roll back, apply delivery fences
- [NixOS and reinstall](docs/NIXOS.md): reproducible installs and what you need to resume
- [Dependencies](docs/DEPENDENCIES.md): runtime requirements and licensing notes
- [Workflow](PROTOCOL.md) and [lead skill](skills/lead/SKILL.md): how agent work gets coordinated

## Good to know

- **Existing stores aren’t migrated automatically.** Choosing a path or updating the source never copies or moves existing data.
- **What it does:** local records, rooms, items and decisions, dependency tracking, review gates, the CLI and web view, the T3 bridge, delivery tracking, and explicit migration tools.
- **What it doesn’t, for now:** Git/PR tracking, third-party relay, usage and budget collection, scheduled runs, external notifications.
- **Licensing:** project licensing and any public release are separate decisions; see [Dependencies](docs/DEPENDENCIES.md).

## License

atr is licensed under the [Functional Source License 1.1](LICENSE.md) (FSL-1.1-ALv2). You may use, modify and redistribute it for anything except offering a competing commercial product or service. Each release becomes available under the Apache License 2.0 two years after it is published. For other terms, contact the author.
