"""Explicit migration rehearsals preserve records and fence imported execution evidence."""
import concurrent.futures
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
import atr_migrate as migration
import atr_runtime as runtime


def tree(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mode & 0o777, path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


class Migration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source, self.destination = self.base / "legacy-copy", self.base / "local-copy"
        self.room = self.source / "rooms/demo"
        (self.room / "items").mkdir(parents=True)
        (self.room / "decisions").mkdir()
        (self.room / "notes/empty").mkdir(parents=True)
        (self.room / "BRIEF.md").write_bytes(b"---\r\ntitle: Demo\r\nlead_thread: synthetic-lead\r\nunknown: [keep, this]\r\n---\r\n# Brief\r\n")
        (self.room / "items/T01-work.md").write_text("---\nid: T01\nstate: todo\ndepends_on: []\nagent: synthetic-worker\nunknown: keep me\n---\n## Acceptance\n- [ ] Result\n")
        (self.room / "decisions/D01-choice.md").write_text("---\nid: D01\ntitle: Choose\nstatus: open\ndecider: owner\n---\n## Options\na) First\nb) Second\n\n## Answer\n")
        self.binary = self.room / "notes/unknown-attachment.bin"
        self.binary.write_bytes(bytes(range(256)))
        self.binary.chmod(0o640)
        os.utime(self.binary, ns=(1700000000123456789, 1700000000123456789))
        state = self.source / ".atr/state"
        state.mkdir(parents=True)
        (state / "relay-receipts.json").write_text('{"unknown_receipt": {"id": "synthetic-receipt", "confirmed": true}}\n')
        (self.source / ".atr/config.json").write_text('{"integrations": {"relay": true, "git": true}}')
        (self.source / ".atr/providers.json").write_text('{"private_provider_configuration": true}')
        (self.source / "PROTOCOL.md").write_text("bundled source rules")
        self.tool = migration.Migration()

    def actions(self):
        rows = {}
        for state in ("pending", "attempting", "confirmed"):
            rows[state] = {"id": state, "kind": "message", "state": state, "target": "synthetic-lead", "room": "demo",
                           "source": "", "revision": "", "payload": "historical " + state, "options": {},
                           "allow_paused": False, "created_at": 1, "attempts": [], "evidence": "original evidence",
                           "unknown_receipt": {"keep": [1, 2]}, "owner_pid": os.getpid(), "lease_until": 0}
        path = self.source / ".atr/deliveries.json"
        path.write_text(json.dumps(rows, indent=2) + "\n")
        return path.read_bytes()

    def copy(self):
        return self.tool.copy(self.source, self.destination)

    def test_preview_is_read_only_and_lists_config_exclusions(self):
        before = tree(self.source)
        with patch.object(subprocess, "Popen", side_effect=AssertionError("migration external call")):
            plan = self.tool.preview(self.source, self.destination)
        self.assertEqual(tree(self.source), before)
        self.assertFalse(self.destination.exists())
        self.assertEqual(plan["counts"]["copied"], 4)
        self.assertEqual(plan["counts"]["retained"], 1)
        self.assertTrue(any(row["path"] == ".atr/config.json" for row in plan["excluded"]))
        self.assertTrue(any(row["path"] == ".atr/providers.json" for row in plan["excluded"]))
        self.assertEqual(len(plan["id"]), 64)

    def test_copy_preserves_unknown_fields_binary_modes_timestamps_and_empty_directories(self):
        original_ledger = self.actions()
        before = tree(self.source)
        with patch.object(subprocess, "Popen", side_effect=AssertionError("migration external call")):
            result = self.copy()
            verified = self.tool.verify(self.source, self.destination)
        self.assertEqual(result["state"], "copied")
        self.assertTrue(verified["verified"])
        self.assertEqual(tree(self.source), before)
        for relative, fingerprint in before.items():
            if relative.startswith("rooms/"):
                self.assertEqual(tree(self.destination)[relative], fingerprint)
        self.assertTrue((self.destination / "rooms/demo/notes/empty").is_dir())
        self.assertEqual((self.destination / ".atr/deliveries.json").read_bytes(), original_ledger)
        self.assertFalse((self.destination / ".atr/config.json").exists())
        self.assertFalse((self.destination / ".atr/providers.json").exists())
        retained = self.destination / result["files"][".atr/state/relay-receipts.json"]["destination"]
        self.assertEqual(retained.read_bytes(), before[".atr/state/relay-receipts.json"][0])
        api = runtime.api_for(root=self.destination)
        self.assertFalse(hasattr(api, "integration_enabled"))

    def test_configuration_named_room_attachments_are_canonical_data(self):
        (self.room / "notes/config.json").write_bytes(b'{"attachment": "not operator configuration"}\n')
        (self.room / "notes/private").mkdir()
        (self.room / "notes/private/credentials.bin").write_bytes(b"synthetic attachment\x00\xff")
        self.copy()
        for relative in ("notes/config.json", "notes/private/credentials.bin"):
            self.assertEqual((self.destination / "rooms/demo" / relative).read_bytes(), (self.room / relative).read_bytes())

    def test_explicit_staged_legacy_history_keeps_provenance_unknown_fields_and_never_replays(self):
        state = self.source / ".atr/state/legacy"
        state.mkdir()
        receipts = {
            "deferred.json": b'{"demo": {"pending": ["original wake"], "unknown": 17}}\n',
            "relay.json": b'{"receipts": {"synthetic-receipt": {"confirmed": true, "unknown": [2]}}}\n',
            "automation.json": b'{"last_sent": "synthetic-confirmation", "unrecognized": true}\n',
        }
        origins = {}
        for name, data in receipts.items():
            (state / name).write_bytes(data)
            origins["legacy/" + name] = {"original_path": "~/.cache/atr/" + name,
                                       "note": "operator-provided synthetic copy; not discovered", "unknown_provenance": ["retain"]}
        (self.source / ".atr/state/migration-provenance.json").write_text(json.dumps(origins))
        with patch.object(subprocess, "Popen", side_effect=AssertionError("history replayed")):
            manifest = self.copy()
            verified = self.tool.verify(self.source, self.destination)
        self.assertTrue(verified["verified"])
        self.assertIn("NOT discovered", manifest["history_policy"])
        for name, data in receipts.items():
            key = ".atr/state/legacy/" + name
            self.assertEqual((self.destination / manifest["files"][key]["destination"]).read_bytes(), data)
            self.assertEqual(manifest["history_provenance"][key], origins["legacy/" + name])
        self.assertFalse((self.destination / ".atr/state").exists())
        self.assertFalse((self.destination / ".atr/deliveries.json").exists())

    def test_rerun_is_idempotent_and_never_overwrites_destination_edits(self):
        first = self.copy()
        before = tree(self.destination)
        second = self.copy()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["outcome"], "already-copied")
        self.assertEqual(tree(self.destination), before)
        path = self.destination / "rooms/demo/notes/new.md"
        path.write_text("acknowledged new note")
        edited = tree(self.destination)
        with self.assertRaisesRegex(migration.MigrationConflict, "destination.*changed|new writes"):
            self.copy()
        self.assertEqual(tree(self.destination), edited)
        with self.assertRaises(migration.MigrationConflict):
            self.tool.rollback(self.source, self.destination)
        self.assertEqual(path.read_text(), "acknowledged new note")

    def test_source_change_after_copy_is_not_silently_accepted_as_a_new_plan(self):
        self.copy()
        before = tree(self.destination)
        (self.room / "notes/later.md").write_text("source advanced")
        with self.assertRaisesRegex(migration.MigrationConflict, "source.*changed|different.*plan"):
            self.copy()
        self.assertEqual(tree(self.destination), before)

    def test_unchanged_copy_rolls_back_transactionally_and_repeat_is_safe(self):
        before = tree(self.source)
        result = self.copy()
        rolled = self.tool.rollback(self.source, self.destination)
        self.assertEqual(rolled["state"], "rolled-back")
        self.assertFalse((self.destination / "rooms/demo/BRIEF.md").exists())
        self.assertEqual(tree(self.source), before)
        self.assertTrue((self.destination / ".atr/migration.json").exists())
        self.assertEqual(self.tool.rollback(self.source, self.destination)["outcome"], "already-rolled-back")
        self.assertEqual(result["source"], str(self.source))

    def test_unsafe_overlapping_symlink_and_conflicting_destinations_are_rejected(self):
        alias = self.base / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        for destination in (self.source, self.base, self.source / "nested", alias):
            with self.subTest(destination=destination), self.assertRaises(migration.MigrationConflict):
                self.tool.preview(self.source, destination)
        self.destination.mkdir()
        sentinel = self.destination / "existing.md"
        sentinel.write_text("unowned data")
        with self.assertRaises(migration.MigrationConflict):
            self.copy()
        self.assertEqual(sentinel.read_text(), "unowned data")
        link = self.room / "notes/link"
        link.symlink_to(self.base / "elsewhere")
        with self.assertRaisesRegex(migration.MigrationConflict, "symlink"):
            self.tool.preview(self.source, self.base / "other-copy")

    def test_preview_refuses_unrecovered_source_journal_without_modifying_it(self):
        journal = self.source / ".atr/transaction.json"
        journal.write_text('{"preserve": "even an unrecognized journal"}')
        before = tree(self.source)
        with self.assertRaisesRegex(migration.MigrationConflict, "recover"):
            self.tool.preview(self.source, self.destination)
        self.assertEqual(tree(self.source), before)

    def test_source_change_during_copy_prevents_acknowledgement_and_rolls_back_destination(self):
        api = runtime.api_for(root=self.destination)
        write = api.durable_write
        changed = []
        def writer(path, text, **kwargs):
            result = write(path, text, **kwargs)
            if not changed:
                changed.append(True)
                (self.room / "notes/concurrent.md").write_text("synthetic uncooperative source writer")
            return result
        with patch.object(api, "durable_write", side_effect=writer), self.assertRaisesRegex(migration.MigrationConflict, "source changed"):
            self.copy()
        self.assertFalse((self.destination / ".atr/migration.json").exists())
        self.assertFalse((self.destination / "rooms/demo/BRIEF.md").exists())

    def test_interrupted_copy_can_be_recovered_by_an_explicit_repeat_without_source_changes(self):
        before = tree(self.source)
        script = """import os,sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import atr_runtime as runtime, atr_migrate
api=runtime.api_for(root=Path(sys.argv[3]))
write=api.durable_write
calls=[]
def interrupt(path,text,**kwargs):
    result=write(path,text,**kwargs)
    calls.append(path)
    if len(calls)==3: os._exit(91)
    return result
api.durable_write=interrupt
atr_migrate.Migration().copy(sys.argv[2], sys.argv[3])
"""
        result = subprocess.run([sys.executable, "-I", "-c", script, str(REPO / "bin"), str(self.source), str(self.destination)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 91, result.stderr)
        self.assertTrue((self.destination / ".atr/transaction.json").exists())
        with self.assertRaises(migration.MigrationConflict):
            self.tool.verify(self.source, self.destination)
        self.assertEqual(self.copy()["state"], "copied")
        self.assertTrue(self.tool.verify(self.source, self.destination)["verified"])
        self.assertEqual(tree(self.source), before)

    def test_touching_identical_bytes_counts_as_a_destination_write(self):
        self.copy()
        path = self.destination / "rooms/demo/BRIEF.md"
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1))
        with self.assertRaisesRegex(migration.MigrationConflict, "destination changed"):
            self.tool.rollback(self.source, self.destination)

    def test_failed_copy_and_failed_rollback_restore_coherent_bytes_and_timestamps(self):
        api = runtime.api_for(root=self.destination)
        write = api.durable_write
        calls = []
        def fail_later(path, text, **kwargs):
            calls.append(path)
            if len(calls) == 3:
                raise OSError("synthetic copy interruption")
            return write(path, text, **kwargs)
        with patch.object(api, "durable_write", side_effect=fail_later), self.assertRaises(OSError):
            self.copy()
        self.assertFalse((self.destination / "rooms/demo/BRIEF.md").exists())
        self.assertFalse((self.destination / ".atr/migration.json").exists())
        self.copy()
        before = tree(self.destination)
        unlink = api.durable_unlink
        removed = []
        def fail_delete(path):
            removed.append(path)
            if len(removed) == 2:
                raise OSError("synthetic rollback interruption")
            return unlink(path)
        with patch.object(api, "durable_unlink", side_effect=fail_delete), self.assertRaises(OSError):
            self.tool.rollback(self.source, self.destination)
        self.assertEqual(tree(self.destination), before)
        self.assertTrue(self.tool.verify(self.source, self.destination)["verified"])

    def test_concurrent_copy_attempts_have_one_owner_and_no_lost_files(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.copy(), range(2)))
        self.assertEqual({result["outcome"] for result in results}, {"copied", "already-copied"})
        self.assertTrue(self.tool.verify(self.source, self.destination)["verified"])

    def test_reciprocal_rollback_processes_finish_without_source_destination_lock_inversion(self):
        # Both roots have ordinary store locks before reciprocal operations begin.
        with runtime.api_for(root=self.source).store_transaction():
            pass
        self.copy()
        source_before = tree(self.source)
        script = """import contextlib,json,sys,time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import atr_migrate as migration
source,destination,markers=map(Path,sys.argv[2:5])
mine,other=sys.argv[5:7]
read_lock=migration._read_lock
@contextlib.contextmanager
def delayed_source(root):
    with read_lock(root):
        if root == source:
            (markers/mine).write_text('source SH acquired')
            deadline=time.monotonic()+0.5
            while not (markers/other).exists() and time.monotonic()<deadline:
                time.sleep(0.005)
        yield
migration._read_lock=delayed_source
(markers/(mine+'-ready')).write_text('ready')
deadline=time.monotonic()+3
while not (markers/'go').exists():
    if time.monotonic()>deadline: raise RuntimeError('test start barrier timed out')
    time.sleep(0.005)
try:
    result=migration.Migration().rollback(source,destination)
    print(json.dumps({'outcome':result['state']}))
except migration.MigrationConflict as error:
    print(json.dumps({'outcome':'conflict','detail':str(error)}))
"""
        markers = self.base / "barrier"
        markers.mkdir()
        processes = []
        try:
            for source, destination, mine, other in ((self.source, self.destination, "valid", "reverse"),
                                                      (self.destination, self.source, "reverse", "valid")):
                processes.append(subprocess.Popen([sys.executable, "-I", "-c", script, str(REPO / "bin"),
                                                   str(source), str(destination), str(markers), mine, other],
                                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            import time
            deadline = time.monotonic() + 3
            while not all((markers / (name + "-ready")).exists() for name in ("valid", "reverse")):
                self.assertLess(time.monotonic(), deadline, "workers did not reach the start barrier")
                time.sleep(0.005)
            (markers / "go").write_text("begin reciprocal operations")
            outputs = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
                outputs.append(json.loads(stdout))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=3)
        self.assertEqual(outputs[0]["outcome"], "rolled-back")
        self.assertEqual(outputs[1]["outcome"], "conflict")
        self.assertEqual(tree(self.source), source_before)
        self.assertTrue(all((markers / name).exists() for name in ("valid", "reverse")))
        self.assertFalse((self.destination / ".atr/transaction.json").exists())
        self.assertFalse((self.source / ".atr/transaction.json").exists())

    def test_manifest_path_tampering_cannot_remove_unowned_data(self):
        self.copy()
        sentinel = self.base / "sentinel.md"
        sentinel.write_text("must survive")
        path = self.destination / ".atr/migration.json"
        manifest = json.loads(path.read_text())
        manifest["files"]["rooms/demo/BRIEF.md"]["destination"] = "../sentinel.md"
        path.write_text(json.dumps(manifest))
        with self.assertRaises(migration.MigrationConflict):
            self.tool.rollback(self.source, self.destination)
        self.assertEqual(sentinel.read_text(), "must survive")

    def test_cli_requires_explicit_paths_and_does_not_change_store_selection(self):
        selected = self.base / "unrelated-selected-store"
        env = dict(os.environ, ATR_DATA_DIR=str(selected), T3CODE_CLI_PATH="/nonexistent", ATR_INTEGRATIONS="")
        for verb in ("preview", "copy", "verify", "rollback"):
            result = subprocess.run([sys.executable, "-I", str(REPO / "bin/atr"), "migrate", verb,
                                     "--source", str(self.source), "--destination", str(self.destination)],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["source"], str(self.source))
        self.assertFalse(selected.exists())


if __name__ == "__main__":
    unittest.main()
