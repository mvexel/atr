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

- **Page actions did not reach the lead.** Added `atr wait` and a generic extension contract
  (docs/EXTENSIONS.md), plus a Claude Code extension (extensions/claude-code) with turn-start, turn-end and
  doorbell hooks. The page shows "Lead listening" while a wait runs.
- **The lead could not tell reviewed decisions from unreviewed ones.** `atr read` now marks the owner's
  unreviewed calls with "(not reviewed yet)".
- **The owner could not select text on the page.** The whole task card was draggable, so trying to select
  text reordered T3 twice instead. Now only the grip drags.
- **The lead's task note read as part of a decision.** The owner read "tested on a fake device" (T3's note)
  as part of D4, shown right below it. The note is now labelled "Lead's note".

## Observed, not acted on yet

- Goal proposals start as a vague brief and the owner accepts them one at a time; the lead can plan only
  under accepted goals. That worked here: it forced the "where does the audio come from" question before
  any detector tasks existed.
- The first owner answer (the audio source) arrived in chat, not on the page. `--owner` covers it, but the
  owner never sees it as a card to confirm. Watch whether that matters.
- Each fix lands as its own commit on the branch, with a test, and is logged here.
- `atr init` does not put atr on the PATH, but the rules tell the lead to type plain `atr`. On adhush the
  lead used the full path to `bin/atr` throughout. An install step (or `uv tool install`, since there is a
  pyproject) is missing.
- The lead session for adhush runs in `~/dev/atr`, not in `~/dev/adhush`. Hooks key on the session's
  working directory, so the extension stays silent for this session. A lead should be started in its
  project's repo; the docs say so, but nothing warns when it is not.
- Goals have no dependencies, only tasks do. The owner had to ask whether accepting G2 and G3 was linked.
  G3 builds on G2, but before either has tasks, only the titles hint at it. Not acted on: cross-goal task
  dependencies may be enough once tasks exist.
- A card is shaped as a judgment call: atr wants a recommendation first. D5 ("what do you watch with
  ads?") is a plain question, so the lead had to invent a suggested answer. Cards may need a question-only
  form.
- T6 (record and mark an hour of shows) is the owner's work. atr has no way to say a task is waiting on the
  owner's hands rather than on an answer, so the task's owner field (`owner=`) is the only hint.
