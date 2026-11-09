# Proposal: Telegram bot as a demo plugin

Status: draft, for owner decision. Nothing here is implemented in this tree.

## Summary

Restore the Telegram notifier as an optional demo plugin that lives outside the core. It shows how an external channel can use atr without changing atr. It pings you when a room needs you and, in a later step, lets you answer an ask by tapping a button on the ping.

The code exists. It was removed from the core tree in the core cleanup and is preserved in history. See [Source](#source).

## Why this one

- It is the only integration that was built, run for real and reviewed. It has a PRD (three versions), tests and a deploy unit.
- It exercises the core boundary: it needs only the web API, so it proves whether "plugin" can mean "separate process" with no loading framework.
- It addresses the main complaint in the README: agents waiting on you with nothing reaching your phone.

## Shape: a separate process, not a plugin framework

`docs/DEPENDENCIES.md` says the core has no plugin loading framework. This proposal keeps it that way. The plugin is a standalone program that:

1. Polls `GET /api/state` on the local atr web server and works out what needs the owner (asks, PRD sign-off, ready work with no staff, stalled rooms).
2. Sends one Telegram message per need. A ledger prevents duplicates across restarts.
3. Optionally accepts a button tap and records it with `POST /api/answer`.

It runs under its own service unit and fails on its own: a failed send never touches atr commands. It uses only the Python standard library (urllib), so it adds nothing to core dependencies.

Proposed location: `plugins/telegram/` in this repo (or a separate repo), with its own README, tests and unit file. Core source and its neutral-source test would not change in tier 1.

## Tiers

| Tier | Scope | Core change |
| --- | --- | --- |
| 1. Notify | One-way pings with an Open link, dry-run mode, seed on first start, quiet debounce for stalled rooms, burst collapse | None |
| 2. Answer | Option buttons on ask pings, 15 s undo, free text via force-reply, restart recovery | Small: authenticated writes with provenance (below) |

Recommendation: ship tier 1 as the demo, then decide on tier 2 separately. Tier 1 is enough to demonstrate the pattern, and it carries no risk of a wrong write.

## The core gap for tier 2

The old bot relied on a server change that the cleaned core does not have. Today `/api/answer` has no caller authentication beyond the optional Tailscale identity allow-list, and it records no provenance. Tier 2 needs:

- a shared secret file (mode 0600) that the server checks on `/api/answer` for plugin writes;
- `by`, `quote` and `source` fields so a recorded answer says it came from a chat tap and quotes it;
- an idempotency check so a replayed tap cannot answer twice.

This is a core change and needs its own PRD and owner agreement. It should not be smuggled in with the demo.

## Behaviour the plugin must keep

Carried over from the earlier requirements:

- Answers only from one configured private chat id; everyone else is ignored.
- No webhook. Long polling only, so nothing is exposed to the internet.
- Bot token never appears in logs or errors (redaction).
- PRD sign-off and relay cards are not answerable from chat. Only decisions with options get buttons.
- Without the shared secret there are no answer buttons, only the Open link, so no dead buttons.
- A message edit shows the outcome (recorded, undone, already answered, failed) so you are not left guessing.

## Work items

1. Recover and port `bin/tracker-telegram` and its two test files into `plugins/telegram/`. Rename to atr (`/api/state` shape, state dir, env names) and strip our room and item ids from comments so the neutral-source test passes.
2. Make the notifier interface the documented extension point (it already has `send`, `edit`, `toast`, `updates`), so another channel is a subclass.
3. Rewrite the deploy unit without machine-specific paths and hostnames; document install in `docs/`.
4. Verify tier 1 with `--dry-run` for 24 hours against a scratch data dir before any real token is used.
5. Update `README.md` ("What it doesn't, for now: external notifications") and `docs/DEPENDENCIES.md` to describe optional out-of-tree integrations.
6. Separate decision: tier 2 core change, if wanted.

## Risks and open questions

- **Licence and release.** No project licence is chosen. A plugin in the repo inherits that open question.
- **Reachability.** Tap links need the web view reachable from the phone (the old setup used a tailnet URL). Pings are less useful if the link does not open.
- **Machine sleep.** The old unit held a sleep inhibitor. Decide whether the demo does the same.
- **Provenance of the old code.** It was written under the old tracker layout and has not been run against the current core. Expect API drift; budget for porting and a fresh review.
- **Tier 2 safety.** One wrong-card answer was the old kill criterion. It should stay one.

## Decisions needed from the owner

- A. Approve tier 1 as a demo plugin in `plugins/telegram/`, in this repo.
- B. Same, but in a separate repo.
- C. Not now.

And independently: whether to open a PRD for the tier 2 core change.

## Source

Preserved history (private archive, do not publish): `final-tracker-history.bundle`, branch `feat/telegram-buttons`. It contains the earlier `feat/telegram-notify` and `feat/telegram-inbound` work. Relevant files on that branch:

- `bin/tracker-telegram` (about 1,700 lines)
- `tests/test_tracker_telegram.py`, `tests/test_telegram_inbound_e2e.py`
- `deploy/agent-tracker-notify.service`
- `rooms/telegram-notify/PRD.md` and `notes/ux.md` (private room data; read, but do not copy into the core)
