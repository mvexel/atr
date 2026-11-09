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

You’ll need Python 3.13+ on a POSIX system (Linux or macOS), and git or curl + tar.

```sh
curl -fsSL https://raw.githubusercontent.com/mvexel/atr/main/install.sh | sh
```

The installer:

1. fetches the source into `~/.atr/src` (rerun it to update),
2. asks where your data should live (default `~/.local/share/atr`),
3. shows the lines that put `atr` on your PATH and, if you say yes, adds them to `~/.zshrc`, `~/.bashrc` or your fish config,
4. offers to install the [T3 CLI](https://t3.codes/) with T3’s own installer if it’s missing,
5. runs `atr setup`.

It asks before each change. Add `-s -- --yes` after `sh` to accept every default. From a checkout, `./install.sh` installs that checkout instead of fetching one.

T3 needs at least one model provider signed in (for example `claude auth login`) before atr can dispatch agent work. Local recording works without it.

Then, in a new terminal:

```sh
atr doctor                  # diagnose local setup (T3 is reported separately)
atr room new demo "Demo project"
atr serve --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787/` and you should see your new Demo project room. For the full walkthrough, see **[Setup](docs/SETUP.md)**.

## Update and diagnose

Run `atr self-update` to update the running installation. Git checkouts must be clean and on a branch with an upstream; updates only fast-forward. Installer tarballs are downloaded again using `ATR_REPO` and `ATR_REF` (defaults: this repository and `main`). Tarball updates replace the bundled source, so keep custom edits in a Git checkout. Updates keep your data, shell configuration and T3; restart a running `atr serve` afterward.

Run `atr doctor` to check Python, bundled files, data-directory access and local setup without changing files. Missing local requirements exit nonzero. Missing T3 is a warning because local records still work; doctor does not verify T3 execution or provider sign-in. `atr setup --check` remains available.

## Uninstall

```sh
atr uninstall
```

This removes the atr block from your shell startup files and deletes the source the installer fetched, asking before each step. It keeps your data directory and leaves T3 alone. Without a working `atr`, run `curl -fsSL https://raw.githubusercontent.com/mvexel/atr/main/install.sh | sh -s -- --uninstall`.

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
