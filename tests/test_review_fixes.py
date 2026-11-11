"""Regression tests for the independent review of slim/v1 (goal lock, goal approval, offers, retry races)."""
import sys, types, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_goal import GoalGate, tr as trg
from test_dependency_plan import Base, tr

LEAD = "lead-thread-0001"


class GoalLockAndApproval(GoalGate):
    def test_force_does_not_bypass_goal_lock(self):
        self.goal("new")
        with self.assertRaisesRegex(SystemExit, "goal draft"):
            self.run_fn(trg.cmd_set, room="r1", id="T01", pairs=["state=doing"], by="dev", force=True)

    def test_no_doing_in_closed_room(self):
        self.goal("new")
        self.approve_as_owner()
        (trg.ROOMS / "r1/BRIEF.md").write_text("---\ntitle: Room one\nclosed: 2026-11-01\n---\n")
        with self.assertRaisesRegex(SystemExit, "closed"):
            self.run_fn(trg.cmd_set, room="r1", id="T01", pairs=["state=doing"], by="dev", force=True)

    def test_hand_made_goal_card_cannot_approve(self):
        self.goal("new")
        (trg.ROOMS / "r1/decisions/D01-x.md").write_text(
            "---\nid: D01\ntype: goal\ndecider: owner\nstatus: open\n---\n## Options\na) y\nb) n\n\n## Answer\n")
        self.run_fn(trg.cmd_answer, room="r1", id="D01", choice="a", by="owner", quote=None)
        self.assertTrue(trg.Room("r1").build_locked)

    def test_answer_needs_owner_decider_open_and_valid_option(self):
        self.goal("new"); self.goal("approve")
        with self.assertRaisesRegex(SystemExit, "no option"):
            self.run_fn(trg.cmd_answer, room="r1", id="D01", choice="z", by="owner", quote=None)
        d = trg.ROOMS / "r1/decisions/D01-approve-goal.md"
        d.write_text(d.read_text().replace("decider: owner", "decider: lead"))
        with self.assertRaisesRegex(SystemExit, "only an open card for the owner"):
            self.run_fn(trg.cmd_answer, room="r1", id="D01", choice="a", by="owner", quote=None)
        self.assertTrue(trg.Room("r1").build_locked)

    def test_goal_type_not_creatable_with_new_decision(self):
        with self.assertRaises(SystemExit):
            trg.build_parser().parse_args(["new", "decision", "r1", "x", "--type", "goal", "--option", "a", "--option", "b"])

    def test_second_goal_new_withdraws_open_card_and_clears_offer(self):
        self.goal("new"); self.goal("approve")
        trg._record_offer("r1", {"offered": ["T01"], "running": 0})
        self.goal("new", result="something else")
        self.assertEqual(trg.Room("r1").find("D01")["status"], "superseded")
        self.assertIsNone(trg.read_offer("r1"))
        with self.assertRaises(SystemExit):        # the withdrawn card can no longer be answered
            self.run_fn(trg.cmd_answer, room="r1", id="D01", choice="a", by="owner", quote=None)
        self.assertTrue(trg.Room("r1").build_locked)


class Delivery(Base):
    """notify_lead with the real delivery path and a fake T3."""
    def setUp(self):
        super().setUp()
        tr.notify_lead = self.saved[1]
        self.calls, self.result = [], {"ok": True, "evidence": "ok", "thread": None}
        p = patch.object(tr, "t3_call", side_effect=lambda k, t, text, o=None: (self.calls.append(text), self.result)[1])
        p.start(); self.addCleanup(p.stop)
        q = patch.object(tr, "thread_info", side_effect=lambda th: {})
        q.start(); self.addCleanup(q.stop)

    def mk(self, items=(("T01", {}),), brief=f"---\ntitle: t\nlead_thread: {LEAD}\n---\n"):
        return self.room(list(items), brief=brief)

    def test_offer_recorded_only_when_sent(self):
        self.mk(brief="---\ntitle: t\n---\n")                  # no lead thread: not sent
        tr.offer_ready("r1")
        self.assertIsNone(tr.read_offer("r1"))
        self.mk()
        self.result = {"ok": False, "evidence": "T3 exited unsuccessfully", "thread": None}
        tr.offer_ready("r1")
        self.assertIsNone(tr.read_offer("r1"))
        self.assertEqual(tr.read_lead_flag("r1")["offer"]["offered"], ["T01"])

    def test_pending_offer_is_not_resent_and_retry_records_it(self):
        self.mk()
        self.result = {"ok": False, "evidence": "boom", "thread": None}
        tr.offer_ready("r1")
        n = len(self.calls)
        a = tr.offer_ready("r1")
        self.assertTrue(a["pending"])
        self.assertEqual(len(self.calls), n)
        self.result = {"ok": True, "evidence": "ok", "thread": None}
        tr.retry_lead_flags(tr.read_lead_flag("r1")["since_epoch"] + 61)
        self.assertEqual(tr.read_offer("r1")["offered"], ["T01"])
        self.assertIsNone(tr.read_lead_flag("r1"))
        self.assertFalse(tr.offer_ready("r1")["new"])

    def test_inbox_read_records_pending_offer(self):
        self.mk()
        self.result = {"ok": False, "evidence": "boom", "thread": None}
        tr.offer_ready("r1")
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            tr.cmd_inbox(types.SimpleNamespace(room="r1"))
        self.assertEqual(tr.read_offer("r1")["offered"], ["T01"])

    def test_retry_does_not_recreate_a_flag_inbox_cleared_during_the_send(self):
        self.mk()
        tr._flag_lead("r1", LEAD, "text", "boom", True)
        since = tr.read_lead_flag("r1")["since_epoch"]
        def send_while_inbox_clears(name, thread, text):
            tr.clear_lead_flag(name)
            return False, "boom"
        with patch.object(tr, "_send_notice", side_effect=send_while_inbox_clears):
            tr.retry_lead_flags(since + 61)
        self.assertIsNone(tr.read_lead_flag("r1"))

    def test_retry_skips_a_flag_replaced_by_a_newer_failure(self):
        self.mk()
        tr._flag_lead("r1", LEAD, "old", "boom", True)
        old = tr.read_lead_flag("r1")["since_epoch"]
        tr._flag_lead("r1", LEAD, "new", "boom", True)
        f = tr.read_lead_flag("r1"); f["since_epoch"] = old + 1; tr._write_lead_flag("r1", f)
        orig = tr.read_lead_flag
        seen = []
        def first_then_other(name):
            f = orig(name)
            if f and not seen:
                seen.append(1)
            elif f:
                f = dict(f, since_epoch=f["since_epoch"] + 5)
            return f
        with patch.object(tr, "read_lead_flag", side_effect=first_then_other):
            tr.retry_lead_flags(old + 100)
        self.assertEqual(self.calls, [])

    def test_timeout_is_not_retried_and_flag_says_unknown(self):
        self.mk()
        self.result = {"ok": False, "evidence": "T3 timed out; acceptance unknown", "thread": None}
        tr.offer_ready("r1")
        f = tr.read_lead_flag("r1")
        self.assertFalse(f["retryable"])
        self.assertIn("delivery unknown", f["reason"])
        n = len(self.calls)
        tr.retry_lead_flags(f["since_epoch"] + 600)
        self.assertEqual(len(self.calls), n)


class Unready(Base):
    def test_cycle_and_unknown_dependency_are_not_ready(self):
        self.room([("T01", {"deps": "T02"}), ("T02", {"deps": "T01"}), ("T03", {"deps": "T99"}), ("T04", {})])
        p = {x["id"]: x for x in tr.plan(tr.Room("r1"))["items"]}
        self.assertEqual([k for k, x in p.items() if x["ready"]], ["T04"])
        a = tr.autostart(tr.Room("r1"))
        self.assertEqual(a["offer"], ["T04"])
        why = {x["id"]: x["why"] for x in a["unready"]}
        self.assertIn("cycle", why["T01"])
        self.assertIn("T99", why["T03"])

    def test_self_dependency_is_not_ready(self):
        self.room([("T01", {"deps": "T01"})])
        self.assertEqual(tr.autostart(tr.Room("r1"))["offer"], [])


if __name__ == "__main__":
    unittest.main()
