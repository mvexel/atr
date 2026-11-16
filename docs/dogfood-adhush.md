# Dogfooding atr on adhush

adhush (`~/dev/adhush`, atr project `adhush`): a macOS menu bar app that mutes commercials in audio the Mac
plays. Used as a real project to find where atr gets in the lead's or the owner's way.

Each entry: what happened, what it says about atr, and what changed (or why nothing did).

## Fixed

- **No way to add a dependency to an existing task.** `task add --after` took one or several, but `task set`
  had no dependency option, so the lead could not say T3 also waits for T2 after the fact. Now:
  `atr task set T3 after=T2` (or `--after`). The help text says `--after` takes `T1,T2`.
- **`decide --owner` came back to the lead as "THE OWNER CHANGED".** The lead recorded what the owner said
  in conversation and then read its own entry as news. The decision still belongs to the owner (accepted,
  `by: you`), but the change is logged as the lead's. `--owner --hard` is refused (it would be a contradiction).

## Observed, not acted on yet

- Goal proposals start as a vague brief and the owner accepts them one at a time; the lead can plan only
  under accepted goals. That worked here: it forced the "where does the audio come from" question before
  any detector tasks existed.
- The first owner answer (the audio source) arrived in chat, not on the page. `--owner` covers it, but the
  owner never sees it as a card to confirm. Watch whether that matters.
- Each fix lands as its own commit on the branch, with a test, and is logged here.
- Accepting a goal on the page does nothing until the lead's next turn: the owner has to message the lead
  as well, so every page action costs a chat message too. The turn hook and the doorbell (README, Plugins)
  are what would close this; neither exists yet. A Claude Code version is the first candidate.
