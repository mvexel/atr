# Operations

The selected local store is the project record. T3 (a required prerequisite) executes work and transports messages; atr keeps recording without it. Always select the same store for the CLI, web server and launched work. Examples below assume `PYTHON` (Python 3.13+), `ATR_SOURCE` (the checkout) and `ATR_DATA_DIR` (the store) are set.

## Local saves and telling the lead

Atr commits local changes before external actions and releases the store lock before bounded T3 calls. A failed external operation does not undo an acknowledged local save. Reading a decision, saving an answer or searching local records does not depend on a running T3 service.

When the owner answers a card or the page records an event, atr saves it first, then sends one message to the room's lead with `t3 thread send`. The send is a single attempt. Each room has at most one marker, `.atr/lead-flag/ROOM.json`, which exists only when the lead was not told:

| Marker reason | What it means and what to do |
| --- | --- |
| T3 did not accept the message | The CLI failed, timed out or gave no acceptance response. `atr serve` re-sends once, 60 seconds later. If that also fails the marker stays and the page shows "Lead not notified". |
| room paused | The room is paused, so the lead was not messaged. Resuming sends the resume notice. |
| lead snoozed or settled | The lead thread was not woken. Wake it in T3, or hand the room to another thread with `atr lead`. |
| no lead thread | The room has none. Run `atr lead ROOM`. |

A lead that pulls with `atr inbox ROOM` sees the unsent message and clears the marker. Every send, failure and retry is logged in `rooms/ROOM/pings.log`. A clean exit from T3 means accepted only: it does not prove the agent received the message, resumed or finished. A timeout leaves acceptance unknown, so a retry can duplicate a message; leads treat repeats as harmless. Unknown T3 state is not proof that a thread is idle, deleted or finished its item.

```sh
"$PYTHON" -I "$ATR_SOURCE/bin/atr" t3 show THREAD_ID
"$PYTHON" -I "$ATR_SOURCE/bin/atr" inbox ROOM
```

The page reports a saved answer separately from T3 acceptance. Agent receipt and resumed execution need separate T3/work evidence. Pausing is a local gate; a saved pause does not prove an already running agent received stop instructions.

## Backup and recovery

Keep a private, coherent backup of the whole selected store, including `rooms/`, attachments, observations and operator state. Protect backup copies and their permissions as you would the original data.

Take a filesystem snapshot or copy only while atr writers and external editors are quiescent. Do not copy changing records independently and assume a coherent workflow transition. Back up source resources/version separately. Preserve T3 runtime data using T3's own procedure; an atr store backup does not contain T3 execution history.

Canonical writes use a common advisory lock, atomic replacement, file/directory syncing and a recovery journal. Atr access recovers an interrupted destination transition before further reads/writes. An unacknowledged transition is undone; a committed transition is retained. Never remove `.atr/transaction.json` to silence an error. If recovery rejects a journal/path, keep the entire store and journal, avoid further edits, and have the maintainer inspect a copy.

After restoring an older backup, do not immediately enable outbound automation: later T3 acceptance or destination writes may be missing from it. Check the room pages for "Lead not notified" flags first. Restoring an old directory or changing `ATR_DATA_DIR` alone cannot preserve writes made elsewhere.

External editors do not take atr locks or send revision preconditions. Quiesce all writers and complete any recovery before editing. Keep a backup, preserve unknown frontmatter/Markdown, and reload after the edit. Atr-mediated stale saves compare byte revisions and refuse incompatible changes, but cannot guarantee concurrency safety against an uncooperative editor. Several processes may share one local store; this is not synchronization between independent machines.

Runtime state (lead-notice flags, offers, locks) is under `.atr/` in the store. Older global cache or state files from earlier versions are not imported.
