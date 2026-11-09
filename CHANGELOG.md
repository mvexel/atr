# Changelog

All notable changes to atr are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

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

[0.1.0]: https://github.com/mvexel/atr/releases/tag/v0.1.0
