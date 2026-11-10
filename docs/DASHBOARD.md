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
