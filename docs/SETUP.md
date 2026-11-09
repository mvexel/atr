# Setup

Atr coordinates projects on T3. It keeps briefs, work items, decisions and evidence in local Markdown; T3 supplies agents, threads, execution and communication. The web server is optional. T3 must be available and configured for automated work, while local reading and decision capture continue during an outage.

## Prerequisites

- Python 3.13, using its standard library, on a POSIX system with `fcntl.flock` and an IANA timezone database. This is the rehearsed Python version; a browser is needed only for the web page.
- A complete atr source installation: `bin/`, `template/`, `web/`, assets and supporting rules/docs stay together. There is no pip or frontend build step for the core.
- A separately installed [T3 Code](https://t3.codes/) runtime and public CLI for dispatch and communication, with a working project and provider configuration. The installer below offers to run T3's official CLI installer; provider sign-in and project setup stay with T3.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/mvexel/atr/main/install.sh | sh
```

The installer fetches the source into `$ATR_HOME/src` (default `~/.atr/src`; git clone, or a tarball without git), picks Python 3.13+ (`PYTHON` overrides), asks for the data directory (`ATR_DATA_DIR`, default `~/.local/share/atr`), offers to put `atr` on your PATH, offers to install the T3 CLI if atr cannot find it, and runs `atr setup`. Run from a checkout, `./install.sh` uses that checkout. `--yes` (`sh -s -- --yes` when piped) accepts every default; without a terminal and without `--yes` it changes no startup file and installs nothing.

To put `atr` on your PATH it adds an `atr` shell function, `ATR_DATA_DIR` and a line that loads tab completion to your shell's startup file (`~/.zshrc`, `~/.bashrc` or `~/.config/fish/config.fish`, picked from `$SHELL`), between `# >>> atr >>>` and `# <<< atr <<<` markers. It shows the lines first. Rerunning replaces the block instead of adding another; a symlinked dotfile stays a symlink. `setup --check` notes when `atr` is not on your `PATH`; this never fails the check.

atr finds the T3 CLI at `$T3CODE_CLI_PATH`, else `~/.t3/bin/t3` (desktop app), else `~/.local/bin/t3` (CLI installer), else `t3` on `PATH`.

`atr uninstall` (or `install.sh --uninstall`) removes the startup-file block and a source the installer fetched, asking first. It keeps the data directory, a checkout you cloned yourself, a fetched source with local changes, and T3.

`atr doctor` checks Python, bundled assets, data-directory access and the saved setup choice without writing files or contacting T3. Missing local requirements exit nonzero; missing T3 and shell integration are advisory. Use `atr setup` to address missing setup. T3 execution and provider sign-in still need separate verification.

`atr self-update` updates the running source installation without rerunning setup or changing shell configuration. Git checkouts must have no local changes and a branch with an upstream; only fast-forward updates are accepted. Installer tarballs are replaced from `ATR_REPO` / `ATR_REF` (defaults: this repository / `main`); preserve custom source edits in Git, and retain any custom repository/ref settings when updating. Tarballs containing legacy local data refuse to update. Restart `atr serve` after updating.

The manual route below gives the same result without the installer.

See `docs/DEPENDENCIES.md` for runtime and license boundaries. Source updates and installed software do not restore private records; see `docs/NIXOS.md` for reinstall planning.

## Select one data directory

Choose an absolute data path outside the source installation. The same path must be used by the CLI, web server and agents. Commands can run from any working directory:

```sh
PYTHON=/absolute/path/to/python3.13
ATR_SOURCE=/absolute/path/to/atr
export ATR_DATA_DIR="$HOME/.local/share/atr"
"$PYTHON" -I "$ATR_SOURCE/bin/atr" setup --no-maintainer
"$PYTHON" -I "$ATR_SOURCE/bin/atr" setup --check
```

`setup --no-maintainer` creates the local `process` room and records that no maintainer thread is wanted yet. `setup --check` checks that local setup and reports T3 separately. “Configured; runtime acceptance unverified” establishes only that a CLI file was found. “Setup ok” does not establish working T3 execution.

Store selection follows this order:

1. `--data-dir /absolute/path`, before the subcommand.
2. `ATR_DATA_DIR`, an absolute path or one beginning with `~/`.
3. `data_dir` in `$XDG_CONFIG_HOME/atr/config.json`; `XDG_CONFIG_HOME` defaults to `~/.config`.
4. Legacy `rooms/` beside the installed source, if present.
5. `$XDG_DATA_HOME/atr`; `XDG_DATA_HOME` defaults to `~/.local/share`.

If both legacy source rooms and default local rooms exist without an explicit selection, atr refuses the ambiguity. Selection never copies, migrates or deletes existing data. Explicit path/environment selection also lets you bypass a broken selection config for recovery.

A selection config contains only the path, for example:

```json
{"data_dir": "/absolute/path/to/atr-data"}
```

Use `atr --data-dir /absolute/path/to/atr-data setup --check` to make a command's destination unambiguous. Changing working directories, switching source branches or pulling source updates does not change an explicitly selected store.

## What lives where

| Location | Purpose |
| --- | --- |
| Selected store `rooms/` | Canonical Markdown records, notes, answers and attachments |
| Selected store `.atr/` | Store locks/recovery journal, T3 obligations and observations, local operator state |
| Selected store `.atr/operator/` | Setup choice and recorded maintainer thread |
| Source `template/`, `web/`, `docs/`, `PROTOCOL.md`, `skills/` | Bundled templates, UI and supporting instructions |

Back up the selected store, including its hidden `.atr/` data. The source repository alone is not a backup of a separate store. Do not publish `.atr/`, operator configuration, credentials or private rooms. See `docs/OPERATIONS.md` before backup, restore or external editing.

## Connect T3 for automated work

Without T3 installed and linked, atr only records. Answers, pauses and notes are saved locally, but nothing is sent to agents and no agent starts or reacts. When atr cannot find the T3 program, the web page shows a banner saying so, and `setup --check` reports "T3: unavailable".

Set the public CLI executable and a valid existing T3 project path or ID in the environment of every atr process:

```sh
export T3CODE_CLI_PATH=/absolute/path/to/t3
export ATR_T3_PROJECT=/absolute/path/to/registered-project
# Only when using a separate public T3 runtime base directory:
export ATR_T3_BASE_DIR=/absolute/path/to/t3-runtime
"$T3CODE_CLI_PATH" --help
"$PYTHON" -I "$ATR_SOURCE/bin/atr" setup --check
```

Without `T3CODE_CLI_PATH`, atr uses `~/.t3/bin/t3`, then `~/.local/bin/t3`, then `t3` on `PATH`. The default launch project is the source installation, which must be valid in T3; atr does not register arbitrary projects. The data directory is not assumed to be an executable T3 project. `ATR_T3_BASE_DIR` is optional and is forwarded through the public CLI. Make these settings available to a service explicitly; its environment may differ from your terminal.

Integration verification used installed T3 CLI **v0.1.2** on 2026-11-08; compatibility with every T3 version is not assumed. The bridge uses public [thread start/send/show, stdin messages and JSON options](https://github.com/pingdotgg/t3code/blob/main/apps/server/src/cli/thread.ts), plus the public [base-directory configuration](https://github.com/pingdotgg/t3code/blob/main/apps/server/src/cli/config.ts). The bridge uses the generally available CLI.

To choose a standing maintainer after T3 is ready, `setup --yes` records that choice and creates a durable launch obligation. It can create a real T3 thread. Inspect `delivery list` for the actual outcome. Use `setup --recreate-maintainer` only after checking the old thread and its launch obligation; an outage alone does not prove the old thread was deleted.

To make a thread the lead of a room, run `atr lead ROOM` with no thread id (or use the room page's "Take the lead" box). It prints text to paste into that T3 thread, whose agent runs `atr lead ROOM <its own thread id>`, and a terminal form with a `THREAD_ID` placeholder. The text carries the explicit source and `--data-dir`, so it works from any directory and without `atr` on your `PATH`.

For an existing lead thread, `t3 show THREAD_ID` refreshes facts and `lead ROOM THREAD_ID` validates the target before changing room routing. A room's `lead_thread`, item `agent`, thread IDs and delivery evidence remain local records. Launch instructions include the selected store and an explicit `--data-dir` command, since a running T3 server may not inherit the caller's environment.

## Create local records

The following commands are safe to rehearse in a new disposable store with T3 unavailable:

```sh
"$PYTHON" -I "$ATR_SOURCE/bin/atr" room new demo "Demo project"
"$PYTHON" -I "$ATR_SOURCE/bin/atr" new decision demo "Choose a name" --option "First" --option "Second"
"$PYTHON" -I "$ATR_SOURCE/bin/atr" answer demo D01 a --quote "D01 a; keeping the first name"
"$PYTHON" -I "$ATR_SOURCE/bin/atr" status demo
"$PYTHON" -I "$ATR_SOURCE/bin/atr" check demo
"$PYTHON" -I "$ATR_SOURCE/bin/atr" delivery list
```

Use the actual ID printed by `new decision` if the room already contains cards. A room without a configured lead retains the answer but cannot notify an invented target. A real T3 outage likewise preserves the answer and its pending obligation. `check` may still report genuine PRD, staffing or dependency warnings; availability is not a waiver of those gates.

For work that has passed its applicable gates, `t3 launch ROOM "bounded work instructions" --item ITEM_ID` dispatches through T3. `--project`, `--provider`, `--model` and `--title` select supported public T3 options; pass `--provider` and `--model` together. An item with a pending, attempting, uncertain or confirmed launch remains reserved against a second launch intent. Changing its prompt or editing the record does not resolve uncertain acceptance. See `docs/OPERATIONS.md` for reconciliation.

## Open the optional web page

```sh
"$PYTHON" -I "$ATR_SOURCE/bin/atr" serve --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787/` on the same machine. The page reads the selected store and offers search, records, local supporting documents, answers/questions and room pause. It does not add general creation/editing forms. The CLI and HTTP server can share the store; stale incompatible edits receive a conflict. On a conflict, reload the record and review the current content before resubmitting your draft.

Local setup help is served at `/doc?file=docs/SETUP.md`. Offered room/document links use the selected store or bundled source resources, rather than requiring GitHub. Arbitrary paths and symlink escapes are refused.

Keep the default loopback binding for local use. If publishing through a trusted Tailscale Serve proxy, configure `ATR_USERS` with the permitted Tailscale login identities. The proxy must supply authenticated identity and prevent clients from forging its headers; do not expose the backend directly to untrusted networks. Document GETs and state-changing requests retain their identity checks. Authentication headers are trusted only behind that controlled proxy; loopback is the default local boundary.

## Next steps

Read `docs/OPERATIONS.md` for unavailable/uncertain delivery and recovery. Use `docs/MIGRATION.md` only with quiescent copies when rehearsing existing rooms. Neither setup nor migration changes a service or performs a live cut-over.

See [validation](VALIDATION.md) for the checked setup/restore commands and their limits.
