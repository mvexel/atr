# Core cleanup validation

The cleanup candidate was checked on the existing Linux host with Python 3.13 and Node 24. This records observed checks, rather than claiming a NixOS reinstall or a restored production cut-over.

- The complete retained suite passed: **292 tests, zero skips** (`python3.13 -m unittest discover -s tests`). Node-based page checks ran. Coverage includes durable storage/recovery, gate/refinement behavior, delivery reservation/uncertainty/reconciliation, migration fences, stale revision conflicts, document containment and HTTP authorization.
- Focused browser checks used synthetic room/API data at 390px and 1100px widths. Cards, record modal, revision-bearing answer requests, distinct local-save/T3-acceptance copy and layout passed; no page errors or optional integration API requests were observed. Captured screenshots are private maintenance evidence outside this source.
- A disposable fresh home installed the complete source from `git archive`, without source Git metadata, and selected a new external store. Setup and a local decision save worked with an explicitly unavailable T3 executable.
- The entire disposable store was copied with metadata intact, then source and restored store were relocated. Setup/status/delivery inspection and HTTP page/state/search/bundled-document reads passed. All eight saved room files retained their byte hashes, including unknown frontmatter and a binary attachment.
- The source boundary check found no private integration branding in runtime/templates/UI/instructions/docs. Removed implementations and historical material were preserved with complete Git history and hash/mode manifests outside the repository; preservation does not change live stores or services.

Integrated testing found a template coupling bug: removing notification metadata also removed a maintenance room's PRD waiver. The waiver now uses the record API; a regression test covers a template without that metadata. The installed lead skill now locates its bundled rules through `ATR_SOURCE` or its real symlink target.

Run setup commands from [SETUP.md](SETUP.md), recovery checks from [OPERATIONS.md](OPERATIONS.md), and the reinstall checklist from [NIXOS.md](NIXOS.md). A fresh-home local rehearsal does not verify NixOS activation, provider sign-in, an arbitrary newer T3 CLI, or restored real conversation history. Verify a bounded actual T3 launch/message on the target installation before relying on resumed execution. Software installation alone does not restore data.
