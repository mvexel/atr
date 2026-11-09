"""Copy-only migration rehearsals. Never select a store, change a source, or contact an integration."""
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

import atr_runtime as runtime


class MigrationConflict(RuntimeError):
    """Preserve both directories and resolve the reported conflict before continuing."""


CONTROL = ".atr/migration.json"
ACTIVE_HISTORY = {"deliveries.json", "t3-observations.json"}


def _stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _root(value):
    path = Path(value).expanduser().absolute()
    _path(Path(path.anchor), path.relative_to(path.anchor))
    return path


def _path(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise MigrationConflict(f"unsafe migration path {relative}")
    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise MigrationConflict(f"migration refuses symlink {path}")
        if not path.resolve().is_relative_to(root.resolve()):
            raise MigrationConflict(f"migration path escapes its directory: {path}")
    return path


def _roots(source, destination):
    source, destination = _root(source), _root(destination)
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise MigrationConflict("source and destination overlap; use distinct, non-overlapping copies")
    if not (source / "rooms").is_dir():
        raise MigrationConflict("source must be an explicit quiescent legacy copy containing rooms/")
    if destination.exists() and not destination.is_dir():
        raise MigrationConflict("destination must be a directory, not a pre-existing file")
    return source, destination


@contextlib.contextmanager
def _read_lock(root):
    """An existing lock may be read, but preview/verification never initialize or recover a store."""
    journal = _path(root, ".atr/transaction.json")
    lock = _path(root, ".atr/locks/store.lock")
    if lock.exists():
        with lock.open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_SH)
            if journal.exists():
                raise MigrationConflict(f"recover {root} explicitly before preview/verification; read-only commands never recover data")
            yield
    else:
        if journal.exists():
            raise MigrationConflict(f"recover {root} explicitly before preview/verification; read-only commands never recover data")
        yield


@contextlib.contextmanager
def _paired_locks(source, destination, destination_api=None):
    """Every two-store operation acquires locks in canonical path order, regardless of mode."""
    contexts = [(source, _read_lock(source)),
                (destination, destination_api.store_transaction() if destination_api else _read_lock(destination))]
    with contextlib.ExitStack() as stack:
        for root, context in sorted(contexts, key=lambda pair: str(pair[0].resolve())):
            stack.enter_context(context)
        yield


def _fingerprint(path):
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise MigrationConflict(f"migration refuses a non-regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise MigrationConflict(f"source changed while reading {path}; stop writers and create a stable copy")
    return {"sha256": digest.hexdigest(), "size": after.st_size, "mode": stat.S_IMODE(after.st_mode), "mtime_ns": after.st_mtime_ns}


def _private(relative):
    return any(re.fullmatch(r"(?i)(?:\.env(?:\..*)?|config(?:\..*)?|providers(?:\..*)?|credentials?(?:\..*)?|secrets?(?:\..*)?|tokens?(?:\..*)?|operator|private|\.ssh|id_rsa|id_ed25519|usage-samples\.jsonl)", part)
               for part in Path(relative).parts)


def _walk(root, relative):
    directory = _path(root, relative)
    if not directory.exists():
        return
    for path in sorted(directory.rglob("*")):
        _path(root, path.relative_to(root))
        yield path


def _digest(plan):
    files = {relative: {key: value for key, value in entry.items() if key != "destination"}
             for relative, entry in plan["files"].items()}
    value = [plan["source"], plan["destination"], files, plan["directories"], plan["excluded"], plan.get("imported_actions", []), plan.get("history_provenance", {})]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def validate_fence(manifest, destination):
    """Validate immutable inventory and evidence-bearing review before core outbound work."""
    if manifest["version"] != 1 or manifest["id"] != _digest(manifest) or manifest["destination"] != str(Path(destination).resolve()):
        raise ValueError("migration identity or inventory hash does not match")
    if manifest["state"] not in ("copied", "reviewed", "rolled-back"):
        raise ValueError("unknown migration state")
    if not isinstance(manifest["imported_actions"], list) or not all(isinstance(key, str) for key in manifest["imported_actions"]):
        raise ValueError("invalid imported action identities")
    reviewed = manifest["reviewed_actions"]
    if not isinstance(reviewed, dict) or not set(reviewed).issubset(manifest["imported_actions"]):
        raise ValueError("invalid reviewed action identities")
    for row in reviewed.values():
        if row["outcome"] not in ("accepted", "not-accepted") or not isinstance(row["evidence"], str) or not row["evidence"].strip():
            raise ValueError("reconciliation requires evidence")
    if manifest["state"] == "reviewed" and not manifest.get("review", {}).get("evidence", "").strip():
        raise ValueError("store review requires evidence")
    counts = manifest["counts"]
    if counts["files"] != len(manifest["files"]) or counts["bytes"] != sum(entry["size"] for entry in manifest["files"].values()):
        raise ValueError("migration file/byte counts do not match the inventory")


def _target(plan_id, relative, category):
    return relative if category == "copied" else f".atr/migrations/{plan_id}/retained/{relative}"


def _source_plan(source, destination):
    if _path(source, ".atr/transaction.json").exists():
        raise MigrationConflict(f"recover {source} explicitly before migration")
    files, directories, excluded = {}, ["rooms"], []
    for path in _walk(source, "rooms"):
        relative = str(path.relative_to(source))
        if path.is_dir():
            directories.append(relative)
        else:
            files[relative] = {**_fingerprint(path), "category": "copied"}
    for path in sorted(source.iterdir()):
        if path.name not in ("rooms", ".atr"):
            excluded.append({"path": path.name, "reason": "source resources, configuration or unrelated data; retained at source"})
    metadata = _path(source, ".atr")
    if metadata.exists():
        if not metadata.is_dir():
            raise MigrationConflict("source .atr metadata must be a directory")
        for path in sorted(metadata.iterdir()):
            relative = str(path.relative_to(source))
            if path.name in ACTIVE_HISTORY and not path.is_dir():
                _path(source, relative)
                files[relative] = {**_fingerprint(path), "category": "copied"}
            elif path.name in ("state", "exports") and path.is_dir():
                for entry in _walk(source, relative):
                    rel = str(entry.relative_to(source))
                    if _private(rel):
                        excluded.append({"path": rel, "reason": "private/configuration history; retained at source"})
                    elif entry.is_file():
                        files[rel] = {**_fingerprint(entry), "category": "retained"}
            else:
                excluded.append({"path": relative, "reason": "operational/private configuration; regenerate locks and keep source intact"})
    plan = {"version": 1, "source": str(source), "destination": str(destination), "files": files,
            "directories": sorted(directories), "excluded": sorted(excluded, key=lambda row: row["path"])}
    provenance = {relative: {"original_path": str(source / relative), "note": "Source-relative provenance only; an external origin was not supplied"}
                  for relative, entry in files.items() if entry["category"] == "retained"}
    staging_note = ".atr/state/migration-provenance.json"
    if staging_note in files:
        try:
            supplied = json.loads((source / staging_note).read_bytes())
            if not isinstance(supplied, dict):
                raise ValueError("expected an object mapping staged relative paths to provenance objects")
            for relative, origin in supplied.items():
                _path(source / ".atr/state", relative)
                key = str(Path(".atr/state") / relative)
                if key not in provenance or not isinstance(origin, dict) or not isinstance(origin.get("original_path"), str) or not origin["original_path"].strip():
                    raise ValueError(f"invalid or missing provenance for staged path {relative}")
                provenance[key] = origin
        except (ValueError, TypeError) as error:
            raise MigrationConflict(f"invalid copied-history staging note: {error}") from error
    plan["history_provenance"] = provenance
    plan["history_policy"] = ("External legacy cache/state/configuration is NOT discovered or covered. No global paths are probed. "
                              "Stage desired historical file copies under SOURCE/.atr/state/ before preview; record their original paths "
                              "in .atr/state/migration-provenance.json as {staged_relative_path: {original_path: ..., note: ...}}. "
                              "History stays inert; never stage credentials/operator/provider configuration.")
    plan["counts"] = {category: sum(entry["category"] == category for entry in files.values()) for category in ("copied", "retained")}
    plan["counts"].update(files=len(files), bytes=sum(entry["size"] for entry in files.values()), directories=len(directories))
    plan["imported_actions"] = []
    if ".atr/deliveries.json" in files:
        try:
            actions = json.loads((source / ".atr/deliveries.json").read_bytes())
            if not isinstance(actions, dict) or any(not isinstance(row, dict) or row.get("id") != key for key, row in actions.items()):
                raise ValueError("expected action rows keyed by their original stable identity")
        except (ValueError, TypeError) as error:
            raise MigrationConflict(f"preserve and repair the source delivery ledger before migration: {error}") from error
        plan["imported_actions"] = sorted(actions)
    plan["id"] = _digest(plan)
    for relative, entry in files.items():
        entry["destination"] = _target(plan["id"], relative, entry["category"])
    plan["warning"] = "Quiescent copies only. No selection or service changes. Excluded configuration is not whole-state equivalence."
    return plan


def _load(source, destination):
    path = _path(destination, CONTROL)
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_bytes())
        validate_fence(manifest, destination)
        if manifest["source"] != str(source):
            raise ValueError("manifest belongs to different directories or an unsupported format")
        for relative, entry in manifest["files"].items():
            _path(source, relative)
            if entry["category"] not in ("copied", "retained") or entry["destination"] != _target(manifest["id"], relative, entry["category"]):
                raise ValueError("unsafe destination mapping")
            _path(destination, entry["destination"])
        return manifest
    except (ValueError, TypeError, KeyError) as error:
        raise MigrationConflict(f"invalid migration manifest; preserve both copies and inspect {path}: {error}") from error


def _inventory(destination, fingerprint_paths=None):
    files, directories = {}, set()
    if not destination.exists():
        return files, directories
    for path in _walk(destination, "."):
        relative = str(path.relative_to(destination))
        if relative == ".atr" or relative == ".atr/locks" or relative.startswith(".atr/locks/"):
            continue
        if relative in (CONTROL, ".atr/transaction.json"):
            continue
        if path.is_dir():
            directories.add(relative)
        else:
            files[relative] = _fingerprint(path) if fingerprint_paths is None or relative in fingerprint_paths else None
    return files, directories


def _expected(manifest):
    files, directories = {}, set(manifest["directories"])
    for entry in manifest["files"].values():
        relative = entry["destination"]
        if manifest["state"] != "rolled-back" or entry["category"] == "retained":
            files[relative] = {key: entry[key] for key in ("sha256", "size", "mode", "mtime_ns")}
        for parent in Path(relative).parents:
            if str(parent) not in (".", ".atr"):
                directories.add(str(parent))
    return files, directories


def _unchanged(manifest):
    expected, allowed_dirs = _expected(manifest)
    files, directories = _inventory(Path(manifest["destination"]), expected)
    changes = sorted(set(files) ^ set(expected) | {relative for relative in files.keys() & expected.keys() if files[relative] != expected[relative]})
    changes += sorted(directories - allowed_dirs)
    if manifest["state"] != "rolled-back":
        changes += sorted(allowed_dirs - directories)
    if changes:
        raise MigrationConflict("destination changed or contains new writes: " + ", ".join(changes[:8]) +
                                ". Preserve this destination and reconcile/export its new records and delivery evidence; rollback/copy will not discard them.")


def _matches(plan, manifest):
    if plan["id"] != manifest["id"]:
        raise MigrationConflict("source changed or destination belongs to a different migration plan; preserve both copies and choose a new destination")


def _metadata(path, entry):
    os.chmod(path, entry["mode"])
    os.utime(path, ns=(entry["mtime_ns"], entry["mtime_ns"]))
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


class Migration:
    def preview(self, source, destination):
        source, destination = _roots(source, destination)
        with _paired_locks(source, destination):
            plan = _source_plan(source, destination)
            existing = _load(source, destination)
            if existing:
                _matches(plan, existing)
                _unchanged(existing)
            elif any(_inventory(destination, ())):
                raise MigrationConflict("conflicting destination is not empty or owned by this migration; choose a new empty directory")
            return {**plan, "state": "preview"}

    def copy(self, source, destination):
        source, destination = _roots(source, destination)
        api = runtime.api_for(root=destination)
        journal = _path(destination, ".atr/transaction.json")
        if journal.exists():
            # Only a matching migration-owned destination journal may be recovered by copy.
            # Preview/verify and all source access remain strictly read-only.
            try:
                owner = json.loads(journal.read_bytes())["migration"]
                if owner["source"] != str(source) or owner["destination"] != str(destination):
                    raise ValueError("different migration owner")
            except (ValueError, TypeError, KeyError) as error:
                raise MigrationConflict("destination has an unowned recovery journal; preserve it and recover explicitly before migration") from error
            with api.store_transaction():
                pass
        plan = self.preview(source, destination)
        source, destination = Path(plan["source"]), Path(plan["destination"])
        with _paired_locks(source, destination, api):
            current = _source_plan(source, destination)
            _matches(current, plan)
            existing = _load(source, destination)
            if existing:
                _matches(plan, existing)
                _unchanged(existing)
                if existing["state"] != "copied":
                    raise MigrationConflict("destination was reviewed or rolled back; preserve it and use a new destination for another rehearsal")
                return {**existing, "outcome": "already-copied"}
            if any(_inventory(destination, ())):
                raise MigrationConflict("conflicting destination changed before copying; no existing data was overwritten")
            api._store_state.journal["migration"] = {"id": plan["id"], "source": str(source), "destination": str(destination)}
            for relative in plan["directories"]:
                api.durable_mkdir(_path(destination, relative), parents=True, exist_ok=True)
            for relative, entry in plan["files"].items():
                original = _path(source, relative)
                data = original.read_bytes()
                if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise MigrationConflict(f"source changed while copying {relative}; no copy acknowledged")
                target = _path(destination, entry["destination"])
                api.durable_write(target, data)
                _metadata(target, entry)
            _matches(_source_plan(source, destination), plan)
            manifest = {**plan, "state": "copied", "copied_at": _stamp(), "reviewed_actions": {}}
            api.durable_write(destination / CONTROL, json.dumps(manifest, sort_keys=True, indent=2) + "\n")
            _unchanged(manifest)
        return {**manifest, "outcome": "copied"}

    def verify(self, source, destination):
        source, destination = _roots(source, destination)
        with _paired_locks(source, destination):
            manifest = _load(source, destination)
            if not manifest:
                raise MigrationConflict("no migration manifest; preserve this unowned destination")
            _matches(_source_plan(source, destination), manifest)
            _unchanged(manifest)
            return {**manifest, "verified": True}

    def review(self, source, destination, evidence):
        if not evidence.strip():
            raise MigrationConflict("store review requires evidence describing the routing and copy checks")
        source, destination = _roots(source, destination)
        api = runtime.api_for(root=destination)
        with api.store_transaction():
            manifest = _load(source, destination)
            if not manifest or manifest["state"] == "rolled-back":
                raise MigrationConflict("no copied destination is available for review")
            manifest.update(state="reviewed", review={"evidence": evidence.strip(), "at": _stamp()})
            api.durable_write(destination / CONTROL, json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        return {**manifest, "outcome": "reviewed; imported actions still require individual delivery reconciliation; no actions executed"}

    def rollback(self, source, destination):
        source, destination = _roots(source, destination)
        api = runtime.api_for(root=destination)
        with _paired_locks(source, destination, api):
            manifest = _load(source, destination)
            if not manifest:
                raise MigrationConflict("no owned migration manifest; rollback will not remove unowned data")
            if manifest["state"] == "reviewed" or manifest.get("reviewed_actions"):
                raise MigrationConflict("destination was reviewed or reconciled; preserve/reconcile its new records and delivery evidence before selecting an older source")
            _matches(_source_plan(source, destination), manifest)
            _unchanged(manifest)
            if manifest["state"] == "rolled-back":
                return {**manifest, "outcome": "already-rolled-back"}
            api._store_state.journal["migration"] = {"id": manifest["id"], "source": str(source), "destination": str(destination)}
            for entry in manifest["files"].values():
                if entry["category"] == "copied":
                    api.durable_unlink(_path(destination, entry["destination"]))
            manifest.update(state="rolled-back", rolled_back_at=_stamp())
            api.durable_write(destination / CONTROL, json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        return {**manifest, "outcome": "rolled-back; source intact, inert history/manifest and empty directories retained; select source explicitly if appropriate"}
