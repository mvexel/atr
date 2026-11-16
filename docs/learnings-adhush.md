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

## The brief against what we built

The brief was "deliberately vague": mute the commercials. That was the point, and atr did turn it into
questions. But the lead then wrote a precise done test for G2: each break edge within 5 s, at most 1 false
mute per hour. The owner accepted it, and from then on nobody asked whether it was the right test.

- **The test came from the lead, not from the owner.** Nothing showed the owner needed 5-second edges.
  "Mute most ads within a minute, Mute now for the rest" might have been a good product. Nobody asked.
- **A precise test made tuning feel like progress.** Every run moved a number, so the next step was always
  another prompt, another description, another sampling fix. That was six or more runs over two test sets.
  The numbers swung from missing most ads to muting most of the programme. That pointed to the wrong method,
  not to the wrong settings.
- **The evidence came early.** The first NFL run caught 12 of 33 ad windows. That was the moment to re-open
  the goal and D6 (on-device only), the decision that boxed the method in. Instead D6 was re-opened only at
  the very end, in D22.
- **The owner raised the reality check, not the lead.** The lead had the numbers all along.
- **atr had nothing to catch it.** An accepted goal is never revisited. Its done test is static, no matter
  who wrote it. There is no time box or limit on attempts. Nothing turns repeated misses into a question
  for the owner.

The lesson for leads: when the brief is vague, a sharp done test is a guess about what the owner wants,
not a fact. Test that guess the way you test the code, and test it early. That means a quick feasibility
check before planning detail, and a card back to the owner as soon as the numbers say the goal as written
won't be met.

## The plan

Five goals, proposed in the atr project `atr`. Tasks come once a goal is accepted.

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
- **G5. Goals get questioned, not only pursued.**
  - A done test the lead wrote is marked as the lead's guess until the owner confirms it as their own.
  - A goal can carry a time box or a number of attempts. When it runs out, the lead must post a card: keep
    going, change the test, change the method, or drop the goal.
  - A new goal with an unproven method starts with a feasibility check before any other tasks.

The order is G5, G2 and G1 first. G5 and G2 together would have stopped the detector tuning hours earlier,
and G1 would have saved the hand-copied decisions. G3 is mostly packaging, and G4 is polish on a part that already mostly works.
