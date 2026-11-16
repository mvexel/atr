# Dogfooding atr on itself

The atr project `atr` (this repo) carries the follow-up from adhush ([learnings-adhush.md](learnings-adhush.md)).
Same format as [dogfood-adhush.md](dogfood-adhush.md): what happened, what it says about atr, what changed.

## Fixed

- **Goals had no "met" state.** G1, G2, G4 and G5 had all their tasks done, and the lead could only say so
  in the outlook line. Now a goal whose tasks are all done shows the owner a "This goal is met" card. Met
  goals fold away at the bottom, take no new tasks from the lead, and can be reopened. Only the owner can
  close a goal: it is a judgment on the done test, which is theirs (T1).

- **A new goal looked untouched while the lead planned it.** The owner added G1 in `atr-claude-extension`.
  The lead read it and spent several steps researching, but the page showed nothing until the owner asked.
  The rules now say: when a goal has no tasks, add a planning task and set it to doing first.

- **A task showed Done while its decision still waited for the owner.** The lead set the planning task T1
  to done right after recording D1 on it. Now a task the lead sets to done while it has unreviewed
  decisions goes to review ("review D1"), and becomes done once the owner accepts them. An overturn sends
  it back to the lead.

## Observed, not acted on yet

- **The server had to be restarted twice in one session** for new operations to work on the page. T11 now
  says so on the page. A lead that changes atr itself still has to restart it by hand.
- **The lead's first card in the new project was on a task whose design it was unsure of (T9).** The
  outlook line (T5) said "unsure" before the card existed. This is the pattern G2 and G5 wanted: the doubt
  showed up early, and became a question instead of a guess.
