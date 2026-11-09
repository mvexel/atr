---
name: atr-lead
description: Coordinate a project room on T3 using local durable Markdown records and explicit review gates.
---

# Lead an atr room

Use the installed `atr` command (or Python 3.13 with `-I /path/to/source/bin/atr`). Locate source using `ATR_SOURCE`; when installed as a directory symlink, resolve the skill directory to its real target and go up two directories (`skills/lead` → source root). Read that source's `PROTOCOL.md`, `docs/SETUP.md` and `docs/OPERATIONS.md`, then the room's BRIEF, now-head, binding PRD/refinements and relevant item. Use an explicit `--data-dir` or `ATR_DATA_DIR`; never assume rooms live beside source.

One thread leads one room. Start a new feature with `rooms new ROOM "Title" --lead-thread THREAD`; authorized maintenance can use `--waive-prd "not a feature: reason"`. Record the owner's scope/approval quote before building. Do not create a second room for the same lead thread or append new work to a closed room.

Plan bounded items with acceptance, inputs, dependencies, locks, owners and caps before dispatch. Each editing agent gets a separate checkout; agents report unplanned needs to the lead. Keep the integration branch and checkout in BRIEF. Use T3 for execution and messages; do not invent a replacement runner.

Maintain durable records before communication. Use `delivery list` to distinguish local saves from pending, uncertain or confirmed T3 acceptance. Reconcile uncertainty with actual evidence before retry. A confirmed message is not proof of agent receipt or resumed work.

Review results, run appropriate checks, update now-head and advance the next eligible item while your turn remains active. Before yielding run `status ROOM` and `check ROOM --yield`. Leave a concrete event/time/owner for a real wait. Native helper completion is not a guaranteed future wake.

Main merges, release, deployment and live store cut-over need the applicable owner's authorization. Preserve all unknown metadata, attachments, dirty/untracked code and branch history before cleanup. Follow `docs/NIXOS.md` and `docs/OPERATIONS.md` for reinstall/restore; never embed user credentials or private host paths in this skill.
