# Owner dashboard read model

`GET /api/dashboard` is an additive local-only projection; `/api/state` is unchanged.
It includes maintenance and closed rooms, all items (including completed predecessors),
open actions, owner decision context and Result successor references. Links use
canonical room/item identities. Multiple, dangling and cyclic successors remain visible.
Evidence includes the original file, content revision and recorded update timestamp;
that timestamp is not an execution observation and freshness remains unknown.

This first bounded model preserves prose rather than claiming to understand it.
`recorded_state` and disposition are canonical assertions, not verified execution or
fulfillment. Current action/actor and latest evidenced change remain null where no
supported structured evidence exists. Results and Feedback remain available for
review; feedback explicitly requests evidence reconciliation. Review, integration
and fulfillment are independent unknown fields, even when prose mentions a merge.
No log entry, role, settlement or acceptance resolves an obligation. Closed items
remain inspectable, including their outgoing successor edges.

Capacity is unavailable with configuration, eligibility, scoped running work and
account consumption independently unknown. No provider is contacted. This version
neither ranks accounts nor imports external integration evidence. The next bounded
implementation needs a reviewed structured evidence contract to resolve these
unknowns and detect specific stale-result contradictions. It must retain original
prose and provenance. UI implementation and owner walkthroughs remain separate.

### Curated evidence contract
Item body may contain an `Evidence assertions` section with a JSON array of mappings (not frontmatter). Every
mapping requires nonempty string scope, stage, state, source, ref, observed_at.
Stages: implementation, review, integration, fulfillment, action. States: pending,
complete, deferred, open. Time must be timezone-aware ISO8601 and not future;
ref is a non-whitespace reference token supplied by the curator. This is syntax
validation, never verification of the referenced artifact. All claims carry
`curated assertion; reference not independently verified`. No integrations exist;
manual curation is the supported input. No git/network inspection occurs.

Claims are exposed by scope and stage without reducing them to global completion.
Missing stages remain unknown. Each claim retains its source/reference/time;
conflicting claims remain visible. An explicit assertion describing the current
Result section UTF-8 SHA256 (`describes_result_sha256`) is contradicted only by a strictly
later, valid, differently stated assertion of the same scope AND stage. Prose is
never parsed for this comparison. Other stale-looking prose requires human
reconciliation. No canonical Result or state is changed.

Action assertions additionally require action and actor strings. Actions remain inspectable in claims; current execution summaries stay unknown. Latest evidenced change is the latest valid
assertion, carrying the same conservative trust label. Record update time is not
an evidence observation. Existing top-level stage fields remain unknown because
scope-specific assertions cannot establish whole-item fulfillment.

The Result hash is independent of the surrounding record and evidence section, so appending evidence does not invalidate its reference. Real Markdown parsing is covered by a round-trip fixture.

Curated action assertions describe obligations, including pending, deferred and
completed actions. They never establish current execution: current_action and
current_actor remain unknown until a separately correlated execution contract
exists. Source and observed_at belong to the curator; references are not
independently verified. Validation remains active under optimized Python.

Current-work evidence: `current_work` lists every open doing item with recorded
title and assigned actor; a single item also populates current_action/actor.
These fields establish recorded activity only. Each runtime observation is keyed
by the item's assigned T3 thread in the existing read-only observation cache.
Only running/idle/interrupted observations aged 0–60 seconds are displayed as
known. Missing, future, stale or explicitly mismatched thread facts remain unknown;
source and original observation timestamp remain visible. Thread content updatedAt
is not an execution observation timestamp. Dashboard reads never renew cache age.
Owner pause comes from canonical BRIEF paused; structured now-head wait_actor and
wait_event together establish an external wait (free-text resume does not).
Todo obligations without an agent whose dependencies are all done are explicitly
unclaimed ready; missing actors remain unknown. Stage assertions never prove execution.
