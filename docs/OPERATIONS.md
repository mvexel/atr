# Operations

The selected local store is the project record. T3 (a required prerequisite) executes work and transports messages; atr keeps recording without it. Always select the same store for the CLI, web server and launched work. Examples below assume `PYTHON`, `ATR_SOURCE` and `ATR_DATA_DIR` from `docs/SETUP.md`.

## Local saves and T3 delivery

Atr commits local changes before external actions and releases the store lock before bounded T3 calls. A failed external operation does not undo an acknowledged local save. Reading a decision, saving an answer or searching local records does not depend on a running T3 service.

The durable action ledger is `.atr/deliveries.json`. It retains stable identities, target, room, source record/version, payload, attempts and evidence. Do not edit or delete the ledger to force a resend.

| State | Meaning and operator action |
| --- | --- |
| `pending` | Saved obligation, not yet accepted; it may be held by pause, a busy lead, changed routing/source, or a migration fence. Inspect its evidence before retrying. |
| `attempting` | A bounded external attempt is in progress. Wait; do not start a second launch. |
| `confirmed` | CLI acceptance was observed, or acceptance was explicitly reconciled. This does not prove agent receipt, execution or completion. Confirmed actions are not resent. |
| `uncertain` | An interrupted call, timeout, nonzero exit or missing acceptance response left the outcome unknown. Reconcile before retrying. |
| `failed` | No process started, or evidence-bearing reconciliation established non-acceptance. A retry is still subject to current gates and routing. |
| `superseded` | A local room read marker acknowledged a wake obligation; no T3 delivery was attempted. |

A successful process spawn alone is not acceptance. The bridge does not promise exactly-once delivery or execution. Unknown T3 state is not proof that a thread is idle, deleted, received a message or finished its item.

```sh
"$PYTHON" -I "$ATR_SOURCE/bin/atr" delivery list
"$PYTHON" -I "$ATR_SOURCE/bin/atr" t3 show THREAD_ID
"$PYTHON" -I "$ATR_SOURCE/bin/atr" delivery reconcile ACTION_ID --outcome accepted --evidence "specific T3 acceptance evidence"
# Only when a check establishes that no acceptance occurred:
"$PYTHON" -I "$ATR_SOURCE/bin/atr" delivery reconcile ACTION_ID --outcome not-accepted --evidence "specific history/operator check"
"$PYTHON" -I "$ATR_SOURCE/bin/atr" delivery retry ACTION_ID
```

The outcomes in this example are alternatives, not a sequence to apply to the same action. Inspect the target thread/history through the available public T3 tools and retain the evidence. If evidence is insufficient, leave the action uncertain. Reconciliation records what the operator established; it is not an automatic proof that a negative check was exhaustive.

The server retries eligible pending/failed actions after revalidation. Uncertain, confirmed and imported fenced actions are not automatically resent. Paused rooms, changed targets or stale originating versions can hold an obligation. A pending/attempting/uncertain/confirmed item launch reserves that room/item across different prompts and record edits. Reconcile the existing intent instead of creating a second one. Several unattempted wakes to the same room lead may share one bounded attempt; each original obligation retains its identity and evidence.

The page reports a saved answer separately from T3 acceptance. Agent receipt and resumed execution need separate T3/work evidence. Pausing is a local gate; a saved pause does not prove an already running agent received stop instructions.

## Backup and recovery

Keep a private, coherent backup of the whole selected store, including `rooms/`, attachments, `.atr/deliveries.json`, migration manifests, observations and operator state. Protect backup copies and their permissions as you would the original data.

Take a filesystem snapshot or copy only while atr writers and external editors are quiescent. Do not copy changing records and ledgers independently and assume a coherent workflow transition. Back up source resources/version separately. Preserve T3 runtime data using T3's own procedure; an atr store backup does not contain T3 execution history.

Canonical writes use a common advisory lock, atomic replacement, file/directory syncing and a recovery journal. Atr access recovers an interrupted destination transition before further reads/writes. An unacknowledged transition is undone; a committed transition is retained. Never remove `.atr/transaction.json` or a delivery ledger to silence an error. If recovery rejects a journal/path, keep the entire store and journal, avoid further edits, and have the maintainer inspect a copy.

After restoring an older backup, do not immediately enable outbound automation: later T3 acceptance or destination writes may be missing from it. Reconcile current delivery evidence first. Restoring an old directory or changing `ATR_DATA_DIR` alone cannot preserve writes made elsewhere. Migration rollback deliberately refuses such loss; see `docs/MIGRATION.md`.

External editors do not take atr locks or send revision preconditions. Quiesce all writers and complete any recovery before editing. Keep a backup, preserve unknown frontmatter/Markdown, and reload after the edit. Atr-mediated stale saves compare byte revisions and refuse incompatible changes, but cannot guarantee concurrency safety against an uncooperative editor. Several processes may share one local store; this is not synchronization between independent machines.

Operator setup is under `.atr/operator/`. Legacy global cache/state and old setup files are not silently imported.
