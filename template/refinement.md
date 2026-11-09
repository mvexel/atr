---
id: {id}
title: {title}
status: draft          # draft | review | agreed | superseded
touches: [{touches}]   # PRD ids this changes, e.g. FR4, NFR2
supersedes: [{supersedes}]  # RF ids this replaces
kind: tune             # tighten | extend | tune | waive | correct
agreed:                # set when the owner agrees; an agreed refinement is never edited
updated: {now}
---
<!-- One page. Longer means two refinements, or a pivot (new PRD, new room). -->
## Trigger
What happened: the field result, the owner's quoted words, a bug report, a finding. Link the evidence.

## Change
For each touched id: was: <exact text>; now: <exact text>. This is the effective requirement.

## Why this stays inside the PRD
Purpose, stakeholders, goals and non-goals, definition of done: unchanged, one line each. If you cannot write this honestly, stop: it is a pivot.

## Effect on work
Items to create, change or drop (ids). Code that predates this: reviewed against it.

## Sign-off
Product lead:
Tech lead: (write n/a if feasibility does not change)
Owner:
