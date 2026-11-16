# Dogfooding atr on itself

The atr project `atr` (this repo) carries the follow-up from adhush ([learnings-adhush.md](learnings-adhush.md)).
Same format as [dogfood-adhush.md](dogfood-adhush.md): what happened, what it says about atr, what changed.

## Observed, not acted on yet

- **Goals have no "met" state.** G1, G2, G4 and G5 have all their tasks done. The lead can only say so in
  the outlook line ("likely: all built, check it"), and the owner has nothing to click to close a goal.
  With T1, the done test is a guess until the owner confirms it, so "met" is naturally the owner's call:
  a "this goal is met" button on the page, next to the done test, would close the loop.
- **The server had to be restarted twice in one session** for new operations to work on the page. T11 now
  says so on the page. A lead that changes atr itself still has to restart it by hand.
- **The lead's first card in the new project was on a task whose design it was unsure of (T9).** The
  outlook line (T5) said "unsure" before the card existed. This is the pattern G2 and G5 wanted: the doubt
  showed up early, and became a question instead of a guess.
