"""Warn on non-thread `agent:` values and explain finished-worker stalls. Fake threads, no messages.
Run: python3 -m unittest tests.test_agent_field
"""
import unittest
from test_bottlenecks import Bottlenecks as Base, item, tr, NOW, ago, LEAD

WORKER = "f9901e28-7885-4901-930f-d1443a9ec735"


class AgentField(Base):
    def stall(self, agent):
        room = self.room([item("T84", "doing", since_min=10, agent=agent)])
        return tr.continuity(room)

    def warns(self, agent):
        room = self.room([item("T84", "doing", since_min=10, agent=agent)])
        return [p for p in tr.problems(room) if p.startswith("T84: agent:")]

    def test_role_name_warns(self):
        w = self.warns("webdev")
        self.assertEqual(len(w), 1)
        self.assertIn("T84: agent: 'webdev' is not a thread id, the page can't see the worker", w[0])

    def test_empty_agent_no_warning(self):
        self.assertEqual(self.warns(""), [])

    def test_running_thread_no_warning_and_moving(self):
        self.threads[WORKER] = {"status": "running", "settled": False, "updated": tr.stamp(ago(1))}
        self.assertEqual(self.warns(WORKER), [])
        self.assertEqual(self.stall(WORKER)[0], "moving")

    def test_finished_thread_explained(self):
        self.threads[WORKER] = {"status": "completed", "settled": True, "title": "Web dev", "updated": "2026-10-27T11:54:00.123Z"}
        state, detail = self.stall(WORKER)
        self.assertEqual(state, "stalled")
        self.assertIn("T84 marked doing, but its worker", detail)
        self.assertIn("finished at", detail)
        self.assertIn("settled", detail)
        self.assertIn("nobody flipped the item", detail)
        self.assertEqual(self.warns(WORKER), [])

    def test_non_thread_agent_explained_in_stall(self):
        state, detail = self.stall("webdev")
        self.assertEqual(state, "stalled")
        self.assertIn("T84 marked doing, but its agent: field is not a thread id", detail)

    def test_empty_agent_keeps_old_wording(self):
        self.threads[LEAD] = {"status": "idle", "settled": False}
        self.assertIn("marked doing, but nothing is running: the lead is idle and no item has a live T3 agent", self.stall("")[1])

    def test_unknown_lead_is_not_reported_as_idle_or_stalled(self):
        state, detail = self.stall("")
        self.assertEqual(state, "unavailable")
        self.assertIn("local records and decision saves remain usable", detail)
        self.assertNotIn("lead is idle", detail)


del Base  # keep unittest from re-running the parent's tests here
if __name__ == "__main__":
    unittest.main()
