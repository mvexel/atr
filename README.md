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

It works alongside [T3 Code](https://t3.codes/). T3 runs the agents and threads. `atr` remembers what they were supposed to do, and gives you a CLI and a simple web view to check.

> **Back up your data directory.** Your plans and decisions live there (including the hidden `.atr/` folder). Installing or updating `atr` never restores them, and T3 and project state need their own backup, using T3’s process.

## What it’s like

You create a *room* for a project, write a brief, and break the work into items with dependencies. Agents pick up items through T3. When you open the web view, you see what’s blocked, what needs a decision from you, and what’s done, without scrolling through agent threads to piece it together.

## Why it’s useful

- **Your files, your folder.** Plans and decisions are plain Markdown in a folder you pick, separate from the installed code. Read them, grep them, put them in git.
- **Works when T3 doesn’t.** If T3 is down, you can still read, search, and record decisions. They go out when it’s back.
- **No wishful thinking about delivery.** `atr` won’t claim an agent got your message just because T3 accepted it. It shows saved, pending, uncertain, and accepted as separate states.
- **Review before building.** Rooms can use PRDs, decisions, and review gates, so agents don’t start building until you’ve signed off on the plan.

## Quick start

You’ll need:

- Python 3.13 on a POSIX system
- A complete checkout of this repo
- T3 installed and configured separately (local setup works without it, but you’ll need it, with your model providers authenticated, before dispatching agent work)

Set a few variables and an alias:

```sh
PYTHON=/absolute/path/to/python3.13
ATR_SOURCE=/absolute/path/to/atr
export ATR_DATA_DIR="$HOME/.local/share/atr"
export T3CODE_CLI_PATH=/absolute/path/to/t3
export ATR_T3_PROJECT=/absolute/path/to/registered-project

alias atr='"$PYTHON" -I "$ATR_SOURCE/bin/atr"'
```

Then set up, check, create a room, and start the web view:

```sh
atr setup --no-maintainer   # create the local store; no maintainer thread yet
atr setup --add-to-shell    # put atr on your PATH via ~/.zshrc, ~/.bashrc or fish config
atr setup --check           # verify local setup (T3 is reported separately)
atr room new demo "Demo project"
atr serve --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787/` and you should see your new Demo project room. For the full walkthrough, see **[Setup](docs/SETUP.md)**.

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
