"""Core T3 delivery accepts only after durable local saves, with recoverable obligations."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_loader("local_integration_test", importlib.machinery.SourceFileLoader("local_integration_test", str(REPO / "bin/atr")))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class T3Delivery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tr = load()
        self.tr.ROOT, self.tr.ROOMS = self.root, self.root / "rooms"
        self.room = self.root / "rooms/demo"
        for part in ("items", "decisions", "notes"):
            (self.room / part).mkdir(parents=True)
        (self.room / "BRIEF.md").write_text("---\ntitle: Demo\ntz: UTC\nlead_thread: synthetic-thread\n---\n")
        self.decision = self.room / "decisions/D01-choice.md"
        self.decision.write_text("---\nid: D01\ntitle: Choose\nstatus: open\ndecider: owner\n---\n## Options\na) First\nb) Second\n\n## Answer\n")

    def answer(self, choice="a"):
        return self.tr.web_answer(self.tr.Room("demo"), "D01", choice, "saved note", False)


    def test_failed_process_start_is_never_reported_as_notified(self):
        with patch.dict(os.environ, T3CODE_CLI_PATH="/bin/false"):
            result = self.answer()
        self.assertTrue(result["saved"])
        self.assertFalse(result["told_lead"])
        self.assertIn(result["delivery"]["state"], ("pending", "failed", "uncertain"))
        self.assertIn("status: final", self.decision.read_text())
        self.assertIn("saved note", self.decision.read_text())

    def test_delivery_happens_after_durable_save_and_outside_the_store_lock(self):
        tr = self.tr
        checked = []
        def send(action):
            self.assertEqual(getattr(tr._store_state, "depth", 0), 0)
            self.assertIn("status: final", self.decision.read_text())
            acquired = []
            def reader():
                with tr.store_transaction(): acquired.append(True)
            thread = threading.Thread(target=reader)
            thread.start(); thread.join(1)
            self.assertEqual(acquired, [True])
            checked.append(action["id"])
            return {"state": "confirmed", "evidence": "synthetic T3 acceptance"}
        with patch.object(tr, "t3_execute", side_effect=send):
            result = self.answer()
        self.assertEqual(len(checked), 1)
        self.assertEqual(result["delivery"]["state"], "confirmed")
        self.assertTrue(result["saved"])
        self.assertNotIn("received", result["delivery"]["evidence"])

    def test_confirmed_actions_are_not_resent_and_uncertain_actions_require_reconciliation(self):
        tr = self.tr
        with patch.object(tr, "t3_execute", return_value={"state": "confirmed", "evidence": "accepted"}) as send:
            result = self.answer()
            action_id = result["delivery"]["id"]
            tr.attempt_delivery(action_id)
            self.assertEqual(send.call_count, 1)
        with tr.store_transaction():
            actions = tr.delivery_actions()
            actions[action_id]["state"] = "uncertain"
            tr.save_delivery_actions(actions)
        with patch.object(tr, "t3_execute") as send:
            self.assertEqual(tr.attempt_delivery(action_id)["state"], "uncertain")
            send.assert_not_called()
        tr.reconcile_delivery(action_id, "accepted", "operator checked synthetic T3 history")
        self.assertEqual(tr.delivery_actions()[action_id]["state"], "confirmed")

    def test_interrupted_attempt_becomes_uncertain_after_restart(self):
        tr = self.tr
        with patch.object(tr, "t3_execute", return_value={"state": "failed", "evidence": "not started"}):
            action_id = self.answer()["delivery"]["id"]
        with tr.store_transaction():
            actions = tr.delivery_actions()
            actions[action_id].update(state="attempting", owner_pid=-1, owner_started="missing")
            tr.save_delivery_actions(actions)
        self.assertEqual(tr.delivery_actions()[action_id]["state"], "uncertain")

    def test_saved_decision_and_pending_obligation_roll_back_together(self):
        tr = self.tr
        with self.assertRaises(OSError):
            with tr.store_transaction():
                self.answer()
                raise OSError("before commit")
        self.assertIn("status: open", self.decision.read_text())
        self.assertEqual(tr.delivery_actions(), {})

    def test_pending_action_does_not_replay_to_a_changed_target_or_through_pause(self):
        tr = self.tr
        with patch.object(tr, "t3_execute", return_value={"state": "failed", "evidence": "not started"}):
            action_id = self.answer()["delivery"]["id"]
        brief = tr.Record(self.room / "BRIEF.md")
        brief.set("lead_thread", "different-synthetic-thread"); brief.save()
        with patch.object(tr, "t3_execute") as send:
            state = tr.attempt_delivery(action_id)
            send.assert_not_called()
        self.assertIn("target", state["evidence"])

    def test_local_documents_reject_symlinks_and_escape_paths(self):
        tr = self.tr
        note = self.room / "notes/context.md"
        note.write_text("# Local context\n")
        self.assertEqual(tr.local_document("rooms/demo/notes/context.md")[0], "# Local context\n")
        note.unlink(); note.symlink_to(self.root.parent / "outside.md")
        for path in ("../outside.md", "/etc/passwd", "rooms/demo/notes/context.md", ".atr/deliveries.json"):
            with self.subTest(path=path), self.assertRaises((ValueError, FileNotFoundError)):
                tr.local_document(path)

    def test_sibling_store_imports_share_the_canonical_transaction(self):
        code = """
import importlib.machinery as m, importlib.util as u, sys
from pathlib import Path
def load(name):
    spec=u.spec_from_loader(name,m.SourceFileLoader(name,sys.argv[1])); module=u.module_from_spec(spec); spec.loader.exec_module(module)
    module.ROOT=Path(sys.argv[2]); module.ROOMS=module.ROOT/'rooms'; return module
first, second=load('first'),load('second')
path=first.ROOT/'rooms/demo/notes/shared.md'
try:
    with first.store_transaction():
        second.durable_write(path,'uncommitted')
        raise ValueError('rollback')
except ValueError: pass
assert not path.exists(), 'sibling write escaped the canonical rollback'
"""
        result = subprocess.run([os.sys.executable, "-I", "-c", code, str(REPO / "bin/atr"), str(self.root)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sibling_writes_keep_the_selected_store_for_a_room_named_rooms(self):
        import sys
        sys.path.insert(0, str(REPO / "bin"))
        import atr_runtime as runtime
        previous = runtime._bound
        runtime.bind(self.tr)
        self.addCleanup(runtime.bind, previous)
        target = self.root / "rooms/rooms/notes/rooms/evidence.md"
        target.parent.mkdir(parents=True)
        with self.assertRaises(ValueError):
            with self.tr.store_transaction():
                runtime.write_text(target, "uncommitted nested evidence")
                self.assertIs(runtime.api_for(target), self.tr)
                raise ValueError("rollback")
        self.assertFalse(target.exists())
        self.assertFalse((self.root / "rooms/.atr").exists())
        self.assertFalse((self.root / "rooms/rooms/notes/.atr").exists())

    def test_new_notice_during_an_attempt_keeps_its_own_unacknowledged_generation(self):
        tr = self.tr
        entered, release = threading.Event(), threading.Event()
        calls, errors = [], []
        def execute(action):
            calls.append(action)
            entered.set()
            self.assertTrue(release.wait(3))
            return {"state": "confirmed", "evidence": "synthetic acceptance"}
        def first():
            try:
                tr.tell_lead_or_defer(tr.Room("demo"), "first notice")
            except BaseException as error:
                errors.append(error)
        with patch.object(tr, "t3_execute", side_effect=execute):
            worker = threading.Thread(target=first)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertFalse(tr.tell_lead_or_defer(tr.Room("demo"), "new notice"))
                pending = next(action for action in tr.delivery_actions().values() if action["payload"] == "new notice")
                self.assertEqual(pending["state"], "pending")
                self.assertEqual(pending["attempts"], [])
            finally:
                release.set(); worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(tr.delivery_actions()[pending["id"]]["state"], "pending")
            tr.attempt_delivery(pending["id"])
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0]["id"], calls[1]["id"])

    def test_item_launch_prints_delegate_task_brief_and_creates_no_thread(self):
        tr = self.tr
        item = self.room / "items/T01-work.md"
        item.write_text("---\nid: T01\ntitle: Work\nstate: todo\ndepends_on: []\n---\n## Acceptance\n- [ ] Result exists\n\n## Inputs\n- Synthetic fixture\n")
        capture = self.root / "public-cli-capture.json"
        cli = self.root / "fake-public-t3"
        cli.write_text("#!" + os.sys.executable + "\nfrom pathlib import Path\n" + f"Path({str(capture)!r}).write_text('called')\n")
        cli.chmod(0o755)
        args = SimpleNamespace(verb="launch", target="demo", text="Do the bounded fixture work", item="T01", project=None,
                               provider=None, model=None, title="my own title")
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, T3CODE_CLI_PATH=str(cli)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            tr.cmd_t3(args)
        self.assertFalse(capture.exists(), "no T3 CLI call: no top-level thread")
        self.assertEqual(tr.delivery_actions(), {})
        brief = json.loads(out.getvalue())
        self.assertEqual((brief["tool"], brief["title"], brief["isolation"], brief["role"]),
                         ("delegate_task", "demo · T01 · worker", "worktree", "implementation"))
        for needle in ("Do the bounded fixture work", "Atr room: demo. Item: T01", str(self.root), "--data-dir"):
            self.assertIn(needle, brief["task"])
        self.assertIn("agent=<childThreadId>", err.getvalue())
        self.assertIn("do NOT launch a top-level thread", err.getvalue())
        self.assertIn("mid-turn", err.getvalue())
        self.assertEqual(tr.Record(item)["agent"], "")

    def test_item_launch_keeps_dependency_and_brief_gap_checks(self):
        tr = self.tr
        item = self.room / "items/T01-work.md"
        item.write_text("---\nid: T01\nstate: todo\ndepends_on: []\n---\n")
        args = SimpleNamespace(verb="launch", target="demo", text="x", item="T01", project=None, provider=None, model=None, title=None)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(tr.StoreConflict):
            tr.cmd_t3(args)

    def test_item_launch_reservation_survives_uncertain_acceptance_and_record_edits(self):
        tr = self.tr
        path = self.room / "items/T01-work.md"
        path.write_text("---\nid: T01\nstate: todo\n---\n")
        entered, release = threading.Event(), threading.Event()
        errors, original = [], []
        def execute(action):
            entered.set()
            self.assertTrue(release.wait(3))
            return {"state": "uncertain", "evidence": "synthetic lost response"}
        def launch():
            try:
                original.append(tr.queue_t3_action("launch", "project", "first", room="demo",
                                                  source=tr.Record(path), options={"item": "T01"}))
            except BaseException as error:
                errors.append(error)
        with patch.object(tr, "t3_execute", side_effect=execute):
            worker = threading.Thread(target=launch)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaises(tr.StoreConflict):
                    tr.queue_t3_action("launch", "project", "different prompt", room="demo",
                                       source=tr.Record(path), options={"item": "T01", "model": "changed"})
            finally:
                release.set(); worker.join(3)
        self.assertEqual(errors, [])
        action_id = original[0]["id"]
        self.assertEqual(tr.delivery_actions()[action_id]["state"], "uncertain")
        record = tr.Record(path)
        record.set("future", "edited while acceptance unknown")
        record.save()
        with self.assertRaises(tr.StoreConflict):
            tr.queue_t3_action("launch", "project", "fresh revision", room="demo", source=tr.Record(path), options={"item": "T01"})
        tr.reconcile_delivery(action_id, "not-accepted", "synthetic operator checked T3 history")
        with patch.object(tr, "t3_execute", return_value={"state": "confirmed", "evidence": "accepted"}) as execute_again:
            replacement = tr.queue_t3_action("launch", "project", "fresh revision", room="demo", source=tr.Record(path), options={"item": "T01"})
        self.assertEqual(tr.delivery_actions()[replacement["id"]]["state"], "confirmed")
        execute_again.assert_called_once()

    def test_preexisting_duplicate_pending_launches_elect_one_claimant_before_execution(self):
        tr = self.tr
        path = self.room / "items/T01-work.md"
        path.write_text("---\nid: T01\nstate: todo\n---\n")
        with patch.object(tr, "after_commit"):
            original = tr.queue_t3_action("launch", "project", "first", room="demo", source=tr.Record(path), options={"item": "T01"})
            with self.assertRaises(tr.StoreConflict):
                tr.queue_t3_action("launch", "project", "changed before any attempt", room="demo", source=tr.Record(path), options={"item": "T01"})
        actions = tr.delivery_actions()
        duplicate = {**actions[original["id"]], "id": "synthetic-duplicate", "payload": "changed", "created_at": original["created_at"] + 1}
        actions[duplicate["id"]] = duplicate
        tr.save_delivery_actions(actions)
        with patch.object(tr, "t3_execute", return_value={"state": "confirmed", "evidence": "accepted"}) as execute:
            self.assertEqual(tr.attempt_delivery(duplicate["id"])["state"], "pending")
            self.assertEqual(tr.attempt_delivery(original["id"])["state"], "confirmed")
            self.assertEqual(tr.attempt_delivery(duplicate["id"])["state"], "pending")
        execute.assert_called_once()



    def test_live_attempt_is_not_abandoned_without_proc_and_late_result_cannot_undo_reconciliation(self):
        tr = self.tr
        entered, release = threading.Event(), threading.Event()
        failures = []
        def execute(action):
            entered.set()
            self.assertTrue(release.wait(3))
            return {"state": "uncertain", "evidence": "late timeout result"}
        def send():
            try:
                tr.tell_lead_or_defer(tr.Room("demo"), "synthetic notice")
            except BaseException as error:
                failures.append(error)
        with patch.object(tr, "_process_started", return_value=""), patch.object(tr, "t3_execute", side_effect=execute):
            worker = threading.Thread(target=send)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                action = next(iter(tr.delivery_actions().values()))
                self.assertEqual(action["state"], "attempting")
                with tr.store_transaction():
                    actions = tr.delivery_actions()
                    actions[action["id"]]["lease_until"] = time.time() - 1
                    tr.save_delivery_actions(actions)
                self.assertEqual(tr.delivery_actions()[action["id"]]["state"], "uncertain")
                tr.reconcile_delivery(action["id"], "accepted", "operator checked synthetic T3 history")
            finally:
                release.set(); worker.join(3)
        self.assertEqual(failures, [])
        result = tr.delivery_actions()[action["id"]]
        self.assertEqual(result["state"], "confirmed")
        self.assertEqual(result["evidence"], "operator checked synthetic T3 history")
        self.assertEqual(result["late_evidence"][-1]["evidence"], "late timeout result")




if __name__ == "__main__":
    unittest.main()
