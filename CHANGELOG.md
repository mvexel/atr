# Changelog

All notable changes to atr are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.2.1] - 2026-11-08

### Fixed

- `atr setup` no longer reports "T3 does not find it" for a maintainer thread that T3 knows. It now asks T3 before taking the store lock; under the lock it could only read an empty cache.
- `atr setup` names the file the maintainer thread id is read from correctly (`.atr/operator/maintainer_thread` in the store, not `~/.config/atr/maintainer_thread`).

## [0.2.0] - 2026-11-08

You now work from T3 and the web page; the `atr` command is mostly for agents.

### Added

- `atr setup` keeps the web page running as a user service (systemd `--user` on Linux, launchd on macOS) that starts at login. The same process refreshes T3 thread status and retries queued deliveries in the background. `atr service install|uninstall|status|restart` manages it; `atr setup --no-service` skips it.
- `atr open` opens the web page, starting it first if nothing answers.
- `atr setup` links the lead skill into `~/.claude/skills` and `~/.codex/skills`, so Claude Code and Codex in T3 can start and lead rooms when asked ("start an atr room for …"). `atr setup --no-skills` skips it.
- `atr setup` records the data directory and the exact command in `~/.config/atr/config.json`, so agents use your store without your shell's `atr` function or `ATR_DATA_DIR`.
- `atr start "what you want"` starts a room's lead thread in T3 from the terminal.

### Changed

- The lead skill (`atr-lead`) is rewritten: how to run atr, start a room and take over a room.
- `atr self-update` restarts the web page service; `atr uninstall` removes the service and the skill links; `atr doctor` reports both.
- Text that atr gives agents runs atr with the Python that ran it, not whatever `python3` is on `PATH`.
- `atr room new` without a lead thread points to `atr lead` instead of a T3 tool.
- The README is organised around T3 and the web page.

## [0.1.0] - 2026-11-08

First release.

### Added

- Rooms of plain-Markdown work items (`T`), decisions (`D`), premises, asks and todo cards, with owners, dependencies, locks and time caps (`atr new`, `set`, `need`, `log`, `reply`, `answer`).
- PRD and refinement gates: building stays locked until the owner agrees the PRD (`atr prd ROOM review`, `atr refinement`, `atr brief`).
- `atr status` and `atr check [--strict] [--yield]` to regenerate room pages and catch stalled rooms, missing options and similar problems.
- `atr serve`: a tap-to-decide web page for answering cards, asking questions and pausing or resuming a team.
- T3 Code integration: thread facts, messages and gated item dispatch (`atr t3`), with delivery tracking that keeps saved, pending, uncertain and accepted apart (`atr delivery`).
- A local data directory separate from the source (`--data-dir`, `ATR_DATA_DIR`, config file, XDG default), with locking and crash recovery, plus `atr migrate` for rehearsed moves from the legacy in-checkout layout.
- `atr room list` and `atr room new` (`atr rooms` still works), `atr team`, `atr name`, `atr lead`, `atr inbox` and `atr feedback`.
- `install.sh` (`curl … | sh`), `atr setup`, `atr doctor`, `atr self-update` and `atr uninstall`.
- Tab completion for bash, zsh and fish: commands, options, room names and item/decision ids (`atr completion SHELL`; the installer loads it).

[0.2.1]: https://github.com/mvexel/atr/releases/tag/v0.2.1
[0.2.0]: https://github.com/mvexel/atr/releases/tag/v0.2.0
[0.1.0]: https://github.com/mvexel/atr/releases/tag/v0.1.0
