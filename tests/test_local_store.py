"""Local stores select deterministically, serialize updates and recover interrupted transitions."""
import concurrent.futures
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_loader("store_test", importlib.machinery.SourceFileLoader("store_test", str(REPO / "bin/atr")))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LocalStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        (self.source / "bin").mkdir(parents=True)
        shutil.copy(REPO / "bin/atr", self.source / "bin/atr")
        shutil.copytree(REPO / "template", self.source / "template")
        self.data = self.base / "data"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("ATR_")}
        self.env.update(HOME=str(self.base / "home"), XDG_CONFIG_HOME=str(self.base / "config"),
                        XDG_DATA_HOME=str(self.base / "xdg"), T3CODE_CLI_PATH="/nonexistent")

    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, "-I", str(self.source / "bin/atr"), *args],
                              env=env or self.env, cwd=self.base, text=True, capture_output=True, timeout=60)

    def init_room(self):
        room = self.data / "rooms/demo"
        for sub in ("items", "decisions", "notes"):
            (room / sub).mkdir(parents=True, exist_ok=True)
        (room / "BRIEF.md").write_text("---\ntitle: Demo\ntz: UTC\n---\n")
        return room

    def test_selection_order_and_legacy_protection(self):
        tr = load()
        env = dict(self.env)
        self.assertEqual(tr.select_data_dir(self.source, env=env)[0], self.base / "xdg/atr")
        legacy = self.source / "rooms/legacy"
        legacy.mkdir(parents=True)
        self.assertEqual(tr.select_data_dir(self.source, env=env)[0], self.source)
        config = self.base / "config/atr/config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"data_dir": str(self.base / "configured")}))
        self.assertEqual(tr.select_data_dir(self.source, env=env)[0], self.base / "configured")
        env["ATR_DATA_DIR"] = str(self.base / "environment")
        self.assertEqual(tr.select_data_dir(self.source, env=env)[0], self.base / "environment")
        self.assertEqual(tr.select_data_dir(self.source, explicit=str(self.data), env=env)[0], self.data)

    def test_invalid_config_does_not_silently_select_an_empty_store(self):
        config = self.base / "config/atr/config.json"
        config.parent.mkdir(parents=True)
        config.write_text("{broken")
        result = self.run_cli("team")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("config", result.stderr)

    def test_relative_xdg_paths_are_ignored_and_relative_environment_store_is_rejected(self):
        tr = load()
        env = dict(self.env, XDG_DATA_HOME="relative", XDG_CONFIG_HOME="relative")
        self.assertEqual(tr.select_data_dir(self.source, env=env)[0], self.base / "home/.local/share/atr")
        env["ATR_DATA_DIR"] = "relative"
        with self.assertRaises(ValueError):
            tr.select_data_dir(self.source, env=env)

    def test_explicit_store_uses_bundled_templates_from_another_directory(self):
        self.init_room()
        result = self.run_cli("--data-dir", str(self.data), "new", "item", "demo", "Independent")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.data / "rooms/demo/items/T01-independent.md").exists())
        self.assertFalse((self.source / "rooms").exists())
        self.assertTrue((self.data / ".atr/locks/store.lock").exists())

    def test_room_creation_initializes_a_new_external_store_without_setup(self):
        result = self.run_cli("--data-dir", str(self.data), "room", "new", "demo", "Demo",
                              "--lead-thread", "synthetic-lead-thread", "--waive-prd", "maintenance")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("synthetic-lead-thread", (self.data / "rooms/demo/BRIEF.md").read_text())
        self.assertFalse((self.source / "rooms").exists())

    def test_concurrent_allocation_and_appends_retain_every_acknowledged_write(self):
        self.init_room()
        def create(n):
            return self.run_cli("--data-dir", str(self.data), "new", "item", "demo", f"Work {n}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(create, range(12)))
        self.assertTrue(all(r.returncode == 0 for r in results), [r.stderr for r in results])
        paths = list((self.data / "rooms/demo/items").glob("*.md"))
        self.assertEqual(len(paths), 12)
        self.assertEqual(len({p.name.split("-")[0] for p in paths}), 12)
        def append(n):
            return self.run_cli("--data-dir", str(self.data), "log", "demo", "T01", f"entry-{n}!")
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(append, range(12)))
        self.assertTrue(all(r.returncode == 0 for r in results), [r.stderr for r in results])
        text = next(p for p in paths if p.name.startswith("T01-")).read_text()
        for n in range(12):
            self.assertEqual(text.count(f"entry-{n}!"), 1)

    def test_stale_record_conflicts_and_preserves_unknown_content(self):
        room = self.init_room()
        path = room / "items/T01-example.md"
        original = "---\nid: T01\nstate: todo\nfuture-key: {opaque: true}\nunknown: xyz # keep\n---\nCustom **Markdown**\n"
        path.write_text(original)
        tr = load()
        tr.ROOT, tr.ROOMS = self.data, self.data / "rooms"
        first, stale = tr.Record(path), tr.Record(path)
        first.set("state", "doing")
        first.save()
        stale.set("state", "done")
        with self.assertRaises(tr.StoreConflict):
            stale.save()
        self.assertEqual(path.read_text(), original.replace("state: todo", "state: doing"))

    def test_interruption_rolls_back_all_files_before_read(self):
        room = self.init_room()
        first, second = room / "PRD.md", room / "decisions/D01-review.md"
        first.write_text("before-prd")
        second.write_text("before-decision")
        code = """
import importlib.machinery as m, importlib.util as u, os, sys
from pathlib import Path
s=u.spec_from_loader('tr', m.SourceFileLoader('tr', sys.argv[1])); t=u.module_from_spec(s); s.loader.exec_module(t)
t.ROOT=Path(sys.argv[2]); t.ROOMS=t.ROOT/'rooms'
with t.store_transaction():
    t.durable_mkdir(t.ROOT/'rooms/new/items', parents=True)
    t.durable_write(t.ROOT/'rooms/demo/PRD.md', 'after-prd')
    t.durable_write(t.ROOT/'rooms/demo/decisions/D01-review.md', 'after-decision')
    os._exit(9)
"""
        result = subprocess.run([sys.executable, "-I", "-c", code, str(self.source / "bin/atr"), str(self.data)], env=self.env)
        self.assertEqual(result.returncode, 9)
        tr = load()
        tr.ROOT, tr.ROOMS = self.data, self.data / "rooms"
        self.assertEqual([room.name for room in tr.rooms_from([])], ["demo"])
        self.assertEqual(first.read_text(), "before-prd")
        self.assertEqual(second.read_text(), "before-decision")
        self.assertFalse((self.data / ".atr/transaction.json").exists())

    def test_failed_transition_rolls_back_and_emits_no_success_output(self):
        tr = load()
        self.init_room()
        tr.ROOT, tr.ROOMS = self.data, self.data / "rooms"
        path = self.data / "rooms/demo/notes/new.md"
        @tr.store_command
        def operation():
            tr.durable_write(path, "new")
            print("saved")
            raise OSError("failure")
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(OSError):
            operation()
        self.assertEqual(output.getvalue(), "")
        self.assertFalse(path.exists())

    def test_interrupted_approval_is_always_a_coherent_workflow_transition(self):
        room = self.init_room()
        decision = room / "decisions/D01-review.md"
        prd = room / "PRD.md"
        before = {
            decision: "---\nid: D01\ntype: prd\nstatus: open\n---\n## Answer\n",
            prd: "---\nid: PRD\nstatus: review\n---\n## Sign-off\nMartijn:\n",
            room / "BRIEF.md": "---\ntitle: Demo\ntz: UTC\n---\n",
        }
        code = """
import importlib.machinery as m, importlib.util as u, os, sys
from pathlib import Path
from types import SimpleNamespace
s=u.spec_from_loader('tr', m.SourceFileLoader('tr', sys.argv[1])); t=u.module_from_spec(s); s.loader.exec_module(t)
t.ROOT=Path(sys.argv[2]); t.ROOMS=t.ROOT/'rooms'
real=t._atomic_bytes; count=0
def write(*args, **kw):
    global count
    real(*args, **kw)
    count += 1
    if count == int(sys.argv[3]): os._exit(9)
t._atomic_bytes=write
t.cmd_answer(SimpleNamespace(room='demo',id='D01',choice='a',by='martijn',quote=None))
"""
        tr = load()
        tr.ROOT, tr.ROOMS = self.data, self.data / "rooms"
        for crash_after in range(1, 9):
            with self.subTest(crash_after=crash_after):
                for path, text in before.items():
                    path.write_text(text)
                result = subprocess.run([sys.executable, "-I", "-c", code, str(self.source / "bin/atr"),
                                         str(self.data), str(crash_after)], env=self.env, capture_output=True, text=True)
                self.assertIn(result.returncode, (0, 9), result.stderr)
                recovered = tr.Room("demo")
                states = (recovered.find("D01")["status"], recovered.prd["status"], recovered.brief["binding"])
                self.assertIn(states, (("open", "review", ""), ("final", "agreed", "PRD.md")))
                if result.returncode == 0:
                    self.assertEqual(states, ("final", "agreed", "PRD.md"))

    def test_directory_creation_and_orphan_temporary_files_recover(self):
        self.init_room()
        tr = load()
        tr.ROOT, tr.ROOMS = self.data, self.data / "rooms"
        with self.assertRaises(OSError):
            with tr.store_transaction():
                new = self.data / "rooms/new/items"
                tr.durable_mkdir(new, parents=True)
                tr.durable_write(new / "new.md", "new")
                (new / ".atr-write-interrupted").write_text("partial")
                raise OSError("interruption")
        self.assertFalse((self.data / "rooms/new").exists())

    def test_acknowledged_transition_survives_process_exit(self):
        room = self.init_room()
        result = self.run_cli("--data-dir", str(self.data), "new", "item", "demo", "Durable")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("--data-dir", str(self.data), "log", "demo", "T01", "acknowledged")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("acknowledged", (room / "items/T01-durable.md").read_text())
        self.assertFalse((self.data / ".atr/transaction.json").exists())

    def test_concurrent_answers_do_not_overwrite_or_append_to_a_final_answer(self):
        room = self.init_room()
        decision = room / "decisions/D01-choice.md"
        decision.write_text("---\nid: D01\nstatus: open\n---\n## Answer\n")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda choice: self.run_cli("--data-dir", str(self.data), "answer", "demo", "D01", choice), ("a", "b")))
        self.assertEqual(sorted(r.returncode for r in results), [0, 1])
        self.assertEqual(decision.read_text().count(" · martijn · "), 1)
        self.assertIn("conflict", next(r.stderr for r in results if r.returncode))

    def test_symlinked_record_cannot_escape_the_store(self):
        room = self.init_room()
        outside = self.base / "outside.md"
        outside.write_text("outside")
        target = room / "notes/escape.md"
        target.symlink_to(outside)
        tr = load()
        tr.ROOT, tr.ROOMS = self.data, self.data / "rooms"
        with self.assertRaises(ValueError):
            tr.durable_write(target, "changed")
        self.assertEqual(outside.read_text(), "outside")

    def test_symlinked_metadata_directory_is_refused(self):
        self.init_room()
        outside = self.base / "outside"
        outside.mkdir()
        (self.data / ".atr").symlink_to(outside, target_is_directory=True)
        tr = load()
        tr.ROOT, tr.ROOMS = self.data, self.data / "rooms"
        with self.assertRaises(ValueError):
            tr.Room("demo")
        self.assertEqual(list(outside.iterdir()), [])

    def test_bundled_rules_are_searchable_without_copying_them_into_the_store(self):
        self.init_room()
        (self.source / "PROTOCOL.md").write_text("# Rules\n\nBundled zebra rules.\n")
        tr = load()
        tr.ROOT, tr.ROOMS, tr.SOURCE_ROOT = self.data, self.data / "rooms", self.source
        rules = tr.search_data("zebra")["groups"]["Rules"]
        self.assertEqual(rules[0]["file"], "PROTOCOL.md")
        self.assertFalse((self.data / "PROTOCOL.md").exists())

    def test_cli_version_precondition_rejects_a_stale_edit(self):
        room = self.init_room()
        result = self.run_cli("--data-dir", str(self.data), "new", "item", "demo", "Revision")
        self.assertEqual(result.returncode, 0, result.stderr)
        path = room / "items/T01-revision.md"
        import hashlib
        revision = hashlib.sha256(path.read_bytes()).hexdigest()
        result = self.run_cli("--data-dir", str(self.data), "set", "demo", "T01", "owner=first", "--expect-version", revision)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli("--data-dir", str(self.data), "set", "demo", "T01", "owner=second", "--expect-version", revision)
        self.assertEqual(result.returncode, 1)
        self.assertIn("conflict", result.stderr)
        self.assertIn("owner: first", path.read_text())

    def test_fsync_failure_never_acknowledges_and_recovers_on_the_next_read(self):
        room = self.init_room()
        tr = load()
        tr.ROOT, tr.ROOMS = self.data, self.data / "rooms"
        path = room / "notes/value.md"
        path.write_text("before")
        real_sync = tr._fsync_dir
        def fail(directory):
            if directory == path.parent:
                raise OSError("disk failure")
            real_sync(directory)
        @tr.store_command
        def operation():
            tr.durable_write(path, "after")
            print("saved")
        output = io.StringIO()
        with patch.object(tr, "_fsync_dir", side_effect=fail), contextlib.redirect_stdout(output), self.assertRaises(OSError):
            operation()
        self.assertEqual(output.getvalue(), "")
        tr.Room("demo")
        self.assertEqual(path.read_text(), "before")

    def test_crlf_records_keep_metadata_gates_revisions_and_unknown_content(self):
        import hashlib
        from types import SimpleNamespace
        room = self.init_room()
        (room / "BRIEF.md").write_bytes(b"---\r\ntitle: Demo\r\ntz: UTC\r\n---\r\n")
        (room / "PRD.md").write_bytes(b"---\r\nid: PRD\r\nstatus: review\r\n---\r\nPurpose.\r\n")
        path = room / "items/T01-crlf.md"
        original = ("---\r\nid: T01\r\nstate: todo\r\nowner: first\r\nfuture-key: {opaque: true}\r\n"
                    "unknown: xyz # keep\r\n---\r\nCustom **Markdown**\r\n\r\n## Log\r\nexisting\r\n").encode()
        path.write_bytes(original)
        tr = load()
        tr.ROOT, tr.ROOMS = self.data, self.data / "rooms"
        record = tr.Record(path)
        self.assertEqual(record._version, hashlib.sha256(original).hexdigest())
        self.assertEqual(record["id"], "T01")
        self.assertTrue(tr.Room("demo").build_locked)
        with self.assertRaisesRegex(SystemExit, "PRD is review"):
            tr.cmd_set(SimpleNamespace(room="demo", id="T01", pairs=["state=doing"], force=False, by="tester"))
        self.assertEqual(path.read_bytes(), original)
        record.set("owner", "second")
        record.save()
        self.assertEqual(path.read_bytes(), original.replace(b"owner: first", b"owner: second"))
        reread = tr.Record(path)
        self.assertEqual(reread["state"], "todo")
        self.assertEqual(reread["unknown"], "xyz")
        self.assertEqual(reread.section("Log"), "existing")
        self.assertTrue(tr.Room("demo").build_locked)



if __name__ == "__main__":
    unittest.main()
