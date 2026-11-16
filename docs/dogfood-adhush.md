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
- T5 got stuck on something only the owner can do (grant macOS audio permission from their own terminal).
  The lead could only mark the task `blocked` and explain it in the note. That's the second case of owner
  work after T6: a task waiting on the owner's hands is a recurring shape, not an exception.
- A card on a goal (D15, live latency on G3) blocks no task. Cards block only the task they are on, so the
  lead could start G3 work whose design hangs on the answer. Here it did not matter (the window length is a
  setting), but a goal-level card arguably should hold that goal's tasks, or say plainly that it does not.
- The owner made T4 wait for T8, removed both of T4's dependencies, then parked it. The lead sees every
  step as a separate change, with no idea what the owner meant. A park with a reason (`note`) would say
  more than the trail of steps does.
- A worker agent did T8. Only the lead runs atr, so the worker's ~10 judgment calls came back in its
  report and the lead had to record them by hand, condensing them into 4 decisions. Workers need a way to
  record decisions (`--by worker-name`?), or atr should accept a batch of them.
- **The page could go quietly stale.** It skips refreshes while a text box has typing in it, and the owner
  saw T8 as "in progress" after it was done. It now says when it is holding back changes, and catches up
  when focus leaves the box. (Probable cause, not confirmed: the owner may simply have had an old tab open.)
- **The owner could not tell if or when a task would start.** The page showed "after T1" whether T1 was done
  or not, and nothing for a task that could start now. Each to-do now says when it starts. Parked tasks say
  they won't start until restored.
- **Long tasks gave no feedback.** During T8 (over an hour, run by a worker) the page said only "In progress".
  Added `atr now T8 "..."` (workers may use it), a "Working on" strip at the top of the page, and a progress
  line on each running task. Accepted decisions fold to one line so a task's body stays short.
- **Answered cards were labelled "decided by the lead, without asking".** Fixed.
- **Agreeing the plan counted finished tasks as new** ("9 new tasks", 7 of them done or parked). Only open
  tasks count now. The open question behind it: the lead started and finished tasks the owner had not agreed
  yet. atr allows that by design ("new" marks a task, it does not hold it back). The owner decided (2026-11-15):
  no stricter mode. Agent-added tasks stay startable; "new" only marks them.
- **The lead missed an answered card for several turns.** The owner answered D15. The lead was working on atr
  itself and did not run `atr read` for adhush for the next several turns, until the owner asked. Rule 1 alone
  did not hold when the lead's attention was elsewhere. The turn hook in the Claude Code extension exists
  for this, but is not installed, and this session's folder is the atr repo, so it would stay silent anyway.
  Leading one project from another project's folder is a real pattern: the extension could take a list of
  projects to watch, not only the one in the folder.
- **Progress lines work.** The T10 worker posted 4 `atr now` lines over ~20 minutes, at natural milestones,
  with no extra prompting beyond the brief. The worker's decisions still came back only in its report, so
  the lead recorded them by hand (D16-D18).
- Workers run `atr` by its full path (`~/dev/atr/bin/atr -p adhush`), because atr is not on the PATH yet.
