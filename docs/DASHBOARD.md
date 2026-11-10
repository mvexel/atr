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
Item frontmatter may contain `evidence_assertions`, a list of mappings. Every
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
Result revision (`describes_result_revision`) is contradicted only by a strictly
later, valid, differently stated assertion of the same scope AND stage. Prose is
never parsed for this comparison. Other stale-looking prose requires human
reconciliation. No canonical Result or state is changed.

Action assertions additionally require action and actor strings. A unique valid
action populates room action/actor; multiple actions remain inspectable in claims
and the summary stays unknown. Latest evidenced change is the latest valid
assertion, carrying the same conservative trust label. Record update time is not
an evidence observation. Existing top-level stage fields remain unknown because
scope-specific assertions cannot establish whole-item fulfillment.
