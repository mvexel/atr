"""Auto-start: atr offers ready items to the lead (never starts workers), capped at 3 running, paused on failure.
Run: python3 -I -m unittest tests.test_autostart
"""
import contextlib, io, sys, types, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dependency_plan import Base, tr, item, goal_fixture


class Autostart(Base):
    def offer(self):
        return tr.offer_ready("r1")

    def test_no_offer_before_goal_approved(self):
        room = self.room([("T01", {})])
        (room.dir / "GOAL.md").unlink()
        a = self.offer()
        self.assertEqual(a["state"], "locked")
        self.assertEqual(self.told, [])
        self.assertEqual(tr.room_json(tr.Room("r1"))["autostart"]["state"], "locked")

    def test_offer_respects_cap(self):
        self.room([("T01", {"state": "doing"}), ("T02", {"state": "doing"}), ("T03", {}), ("T04", {})])
        a = self.offer()
        self.assertEqual(a["offer"], ["T03"])
        self.assertEqual(len(self.told), 1)
        self.assertIn("T03", self.told[0][1])
        self.assertNotIn("T04", self.told[0][1])

    def test_review_does_not_occupy_a_slot(self):
        self.room([("T01", {"state": "review"}), ("T02", {})])
        self.assertEqual(self.offer()["running"], 0)

    def test_capped_sends_nothing(self):
        self.room([(f"T0{n}", {"state": "doing"}) for n in (1, 2, 3)] + [("T04", {})])
        self.assertEqual(self.offer()["state"], "capped")
        self.assertEqual(self.told, [])

    def test_order_follows_critical_path(self):
        self.room([("T01", {"cap": "1"}), ("T02", {"cap": "5"}), ("T03", {"deps": "T02"})])
        a = self.offer()
        self.assertEqual(a["offer"], ["T02", "T01"])
        self.assertLess(self.told[0][1].index("T02"), self.told[0][1].index("T01"))

    def test_unmet_dependency_not_offered_and_done_dependency_named(self):
        self.room([("T01", {"state": "done"}), ("T02", {"deps": "T01"}), ("T03", {"deps": "T04"}), ("T04", {"state": "doing"})])
        a = self.offer()
        self.assertEqual(a["offer"], ["T02"])
        self.assertIn("depends on T01, done", self.told[0][1])
        self.assertNotIn("T03", self.told[0][1])

    def test_blocked_item_pauses_offers_and_says_why(self):
        self.room([("T01", {"state": "blocked"}), ("T02", {})])
        a = self.offer()
        self.assertEqual(a["state"], "paused-failure")
        self.assertEqual(self.told, [])
        j = tr.room_json(tr.Room("r1"))["autostart"]
        self.assertEqual(j["state"], "paused-failure")
        self.assertIn("T01", j["reason"])
        self.assertEqual(j["ready"], ["T02"])

    def test_paused_room_sends_nothing(self):
        self.room([("T01", {})], brief="---\ntitle: t\npaused: 2026-01-01T00:00Z\n---\n")
        self.assertEqual(self.offer()["state"], "paused")
        self.assertEqual(self.told, [])

    def test_no_duplicate_offer_and_reoffer_after_item_finishes(self):
        room = self.room([("T01", {"state": "doing"}), ("T02", {}), ("T03", {}), ("T04", {}), ("T05", {})])
        self.offer(); self.offer()
        self.assertEqual(len(self.told), 1)                      # T02, T03; unchanged set is not re-sent
        self.assertEqual(self.offer()["offer"], ["T02", "T03"])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            tr.cmd_set(types.SimpleNamespace(room="r1", id="T01", pairs=["state=done"], by="dev", force=False))
        offers = [t for _, t in self.told if "ready to start" in t]
        self.assertEqual(len(offers), 2)                         # running 1 -> 0: three items now
        self.assertIn("T04", offers[1])

    def test_dry_run_sends_nothing_and_records_nothing(self):
        self.room([("T01", {})])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tr.cmd_next(types.SimpleNamespace(room="r1"))
        self.assertIn("would be offered", out.getvalue())
        self.assertEqual(self.told, [])
        self.assertIsNone(tr.read_offer("r1"))

    def test_goal_approval_triggers_offer(self):
        room = self.room([("T01", {})])
        (room.dir / "GOAL.md").write_text(goal_fixture.APPROVED.replace("approved", "draft", 1).replace("status:", "card: D01\nstatus:", 1))
        room = tr.Room("r1")
        tr.after_answer(room, {"type": "goal", "id": "D01"}, "a")
        self.assertEqual(len(self.told), 1)
        self.assertIn("T01", self.told[0][1])


if __name__ == "__main__":
    unittest.main()
