# What adhush taught atr

adhush was a toy project (a menu bar app to mute TV ads) led through atr from 2026-11-14 to 2026-11-16, to
find where atr gets in the way. The full record is in [dogfood-adhush.md](dogfood-adhush.md). The project
itself has been discarded. The follow-up work is the atr project `atr`, run from this repo.

## What worked, keep it

- **Goals proposed as briefs, accepted one at a time.** This forced the first real question ("where does the
  audio come from?") before any tasks existed.
- **Cards with a recommendation.** The owner answered most cards in one click.
- **`owner=you` for work only the owner can do.** Granting permissions and recording TV was owner's work.
  "Your turn" on the page and a separate list in `atr read` made that clear.
- **Progress lines (`atr now`).** Workers posted them at natural milestones with no extra prompting.
- **The extension contract (`unread`, `wait`, exit codes).** The Claude Code plugin was built on it without
  changes to the core.
- **One commit and one test per fix, logged as it happened.**

## What got in the way

1. **Setup and reach.**
   - atr is not on the PATH, so the lead and workers typed the full path.
   - The lead ran from the atr repo, not adhush's, so the turn hook stayed silent. As a result the lead
     missed an answered card for several turns.
   - The page's server kept running old code until it was restarted, and nothing said so.
2. **Owner's turns that atr can't express.**
   - A plain question with no sensible recommendation ("what do you watch with ads?").
   - A task the lead did that only counts once the owner checks it (the lead-marked test set).
   - An answer given in chat, which the owner never sees as a card.
   - Parking a task with no way to say why.
3. **Workers.**
   - Workers can't record decisions, so the lead copied about 20 of them from worker reports by hand.
   - A worker that died with the lead's session still showed as "doing".
4. **Goals.**
   - The lead's confidence in a goal is nowhere. The owner had to ask "how likely is this to work?" late,
     after many hours spent tuning a detector that never got close.
   - A card on a goal holds back none of its tasks.
   - Goals can't depend on each other.

## The plan

Four goals, proposed in the atr project `atr`. Tasks come once a goal is accepted.

- **G1. Workers report through atr.**
  - Workers record their own decisions (marked as the worker's, for the lead to review).
  - At session start, the lead is shown its `doing` tasks with the age of their last progress line, and
    confirms each one is still running.
- **G2. Goals carry the lead's outlook.**
  - A per-goal outlook line the lead keeps current, with its age, shown on the page.
  - A hard card on a goal stops `next` from offering that goal's tasks.
  - Goal dependencies stay open: see whether task dependencies across goals are enough first.
- **G3. atr reaches the lead wherever it runs.**
  - One install command puts `atr` on the PATH.
  - The extension watches a list of projects, not only the folder's own.
  - The lead is warned when its folder is not the project's repo.
  - The page says when the server is older than the code on disk.
- **G4. Every kind of owner's turn has its own shape.**
  - Question-only cards.
  - Review tasks ("done by the lead, waiting for your check").
  - Chat answers shown as cards to confirm.
  - Park with a reason.

The order is G1 and G2 first. They would have changed the outcome on adhush (hand-copied decisions, the
late reality check). G3 is mostly packaging, and G4 is polish on a part that already mostly works.
