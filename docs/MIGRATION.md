# Migration rehearsals and rollback

These commands rehearse migration on explicit quiescent copies. They do not choose the application's global store, change a service, operate existing user threads, import hosted state or perform a live cut-over. Keep the originals and use synthetic or separately prepared copies for acceptance work.

## Prepare and inspect copies

Set `PYTHON` (Python 3.13+) and `ATR_SOURCE` (the checkout). Choose distinct absolute paths:

```sh
LEGACY_COPY=/absolute/path/to/quiescent-legacy-copy
LOCAL_COPY=/absolute/path/to/new-empty-copy
"$PYTHON" -I "$ATR_SOURCE/bin/atr" migrate preview --source "$LEGACY_COPY" --destination "$LOCAL_COPY"
```

The source contains `rooms/`. The destination must be empty or belong to the exact same unchanged migration. Equal/ancestor/descendant paths, symlink aliases/entries, conflicting destinations and special files are refused. Existing source recovery journals require explicit recovery first; preview/verification never recover or write the source.

Preview prints a plan identity, source/destination, SHA-256 hashes, file/byte counts, file modes/mtimes, paths and classifications. Room files and directories are canonical user data regardless of names: a note called `config.json` or an attachment inside `private/` remains data. Unknown frontmatter/Markdown, IDs, timestamps, answers, dependencies, PRDs/refinements, binary attachments and T3 correlations retain their bytes. Empty room directories are preserved.

The native T3 delivery ledger and cached observations are copied. Historical `.atr/state/` and export evidence are retained under a migration-specific inert archive, with recognized private/operator/provider configuration excluded. Bundled source resources, Git metadata, locks, credentials and unrelated source-root material are not imported as active configuration. Preview/manifest list exclusions. Migration is not a secret scanner: review the room content you intentionally supply.

## Explicitly stage legacy external history

Older atr installations kept deferred wake/automation/relay receipts outside the checkout, such as under a user's cache or state directories. The migrator **does not discover, read or cover those external locations**. It makes no whole-state-equivalence claim for unstaged history.

To retain that evidence, prepare file copies under the rehearsal source's `.atr/state/` before preview. Do not stage actual credentials or operator/provider configuration. Add `.atr/state/migration-provenance.json` mapping staged paths relative to `.atr/state/` to their original path and a preparation note, for example:

```json
{
  "legacy/rewakes.json": {
    "original_path": "~/.cache/atr/rewakes.json",
    "note": "Operator-provided quiescent copy; captured at the stated rehearsal snapshot"
  },
  "legacy/relay-ingest.json": {
    "original_path": "~/.local/state/atr/relay-ingest.json",
    "note": "Copied history only; do not activate or replay"
  }
}
```

Those strings document provenance; the tool does not follow them to real/global files. Staged bytes and unknown fields are retained inertly, along with the provenance note. If no external origin is supplied, the manifest records source-relative provenance and discloses that limit. An old deferred receipt is not converted into a confirmed T3 action or replayable live obligation.

## Copy and verify

```sh
"$PYTHON" -I "$ATR_SOURCE/bin/atr" migrate copy --source "$LEGACY_COPY" --destination "$LOCAL_COPY"
"$PYTHON" -I "$ATR_SOURCE/bin/atr" migrate verify --source "$LEGACY_COPY" --destination "$LOCAL_COPY"
```

Copy installs records and `.atr/migration.json` in a recoverable destination transaction. It leaves the source intact. Repeating the same unchanged copy returns `already-copied`; source changes or destination edits cause a conflict instead of an overwrite. An interrupted copy can be recovered by an explicit repeat when its destination journal belongs to the matching migration. Unowned journals require explicit inspection/recovery.

Verification compares the preserved inventory, counts and hashes, including modes/mtimes. It is a baseline comparison, not proof of whole-state coverage or working T3 execution. New destination files, changed content/metadata, source changes or a tampered manifest are reported. Preview and verification make no source writes or implicit recovery changes.

The destination begins **fenced**. Outbound actions and automatic thread-refresh work remain held; local records and decision saves stay available. Imported delivery rows retain their original identities, states, attempts, receipts and unknown fields. An imported `attempting` row is historical evidence, not authority for a live destination attempt.

## Roll back an unchanged rehearsal

```sh
"$PYTHON" -I "$ATR_SOURCE/bin/atr" migrate rollback --source "$LEGACY_COPY" --destination "$LOCAL_COPY"
```

Rollback checks ownership and the unchanged baseline before removing imported canonical files transactionally. The source remains intact; the destination keeps its manifest, inert historical archive and empty directories. A repeated rollback is a safe no-op. It does not modify store selection; select the original explicitly only when that is appropriate.

After destination writes, store review or individual delivery reconciliation, rollback refuses with preservation instructions. Even a new timestamp on otherwise identical bytes counts as a change. Keep both copies, identify the newer records and delivery evidence, and reconcile/preserve them before selecting an older source. Do not delete the manifest or change directories to bypass this check. An old source path alone is not a safe rollback after acknowledged destination work.

## Review a copy for further operation

For a rehearsal, leave the fence in place unless you intentionally need to test its release with fakes. A future live cut-over needs its own approval and plan.

```sh
"$PYTHON" -I "$ATR_SOURCE/bin/atr" migrate review --source "$LEGACY_COPY" --destination "$LOCAL_COPY" --evidence "specific copy, routing and isolation checks"
"$PYTHON" -I "$ATR_SOURCE/bin/atr" --data-dir "$LOCAL_COPY" delivery list
```

Store review permits new destination obligations to be attempted, including eligible new pending work if a server is running. Review itself does not send or replay imported actions. Every imported action remains individually fenced until evidence-bearing `delivery reconcile ACTION_ID --outcome accepted|not-accepted --evidence ...`; see `docs/OPERATIONS.md`. Historical confirmed acceptance cannot be reset for resend. Check actual T3 evidence, and leave uncertain outcomes unresolved when evidence is insufficient.

No migration command copies old operator or external-service configuration into active use. Prepare any new explicit configuration separately, after deciding which store and T3 routing are authoritative. This procedure does not supersede an existing migration agreement or authorize a second live writer.
