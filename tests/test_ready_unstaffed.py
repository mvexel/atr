"""`check --yield` catches wave-0 todo items nobody is running; status PLAN marks them. No real message is sent.
Run: python3 -I -m unittest discover tests -p 'test_ready_unstaffed.py'
"""
import unittest
from test_dependency_plan import Base, tr


def head(waiting="", resume=""):
    return f"---\nwaiting: {waiting}\nresume: {resume}\n---\n"


class Ready(Base):
    def setUp(self):
        super().setUp()
        self.saved_ts = tr.thread_status
        tr.thread_status = lambda t: "running" if t == "live" else None

    def tearDown(self):
        tr.thread_status = self.saved_ts
        super().tearDown()

    def wave0(self, waiting=None, **brief_extra):
        room = self.room([("T06", {}), ("T07", {}), ("T12", {})])
        if waiting is not None:
            (room.dir / "now-head.md").write_text(head(waiting, "2099-01-01T00:00Z"))
        return tr.Room("r1")

    def msgs(self, room):
        return [p for p in tr.problems(room, True) if "ready (wave 0, no agent)" in p]

    def test_waiting_names_one_of_three(self):
        room = self.wave0("Maintainer T07")
        m = self.msgs(room)
        self.assertEqual(len(m), 1)
        self.assertIn("T06, T12 are ready (wave 0, no agent): dispatch them before yielding", m[0])
        self.assertNotIn("T07", m[0])

    def test_room_level_waiting_no_longer_silences(self):
        room = self.wave0("Maintainer T21-T24")
        self.assertIn("T06, T07, T12 are ready", self.msgs(room)[0])

    def test_waiting_names_all(self):
        self.assertEqual(self.msgs(self.wave0("Maintainer T06 T07, T12")), [])

    def test_not_flagged_without_yield(self):
        room = self.wave0()
        self.assertFalse([p for p in tr.problems(room) if "ready (wave 0" in p and "STALLED" not in p])

    def test_paused_room(self):
        room = self.room([("T06", {}), ("T07", {})], brief="---\ntitle: t\nprd: waived (test)\npaused: 2026-10-27T10:00Z\n---\n")
        self.assertEqual(self.msgs(room), [])

    def test_locked_item_not_ready(self):
        room = self.room([("T01", dict(state="doing", locks="bin/x")), ("T02", dict(locks="bin/x")), ("T03", {})])
        self.assertEqual(tr.ready_unstaffed(room), ["T03"])

    def test_dependency_not_done(self):
        room = self.room([("T01", {}), ("T02", dict(deps="T01"))])
        self.assertEqual(tr.ready_unstaffed(room), ["T01"])
        room = self.room([("T01", dict(state="done")), ("T02", dict(deps="T01"))])
        self.assertEqual(tr.ready_unstaffed(room), ["T02"])

    def test_live_agent_not_flagged(self):
        room = self.room([("T01", dict(extra="agent: live\n")), ("T02", dict(extra="agent: dead\n"))])
        self.assertEqual(tr.ready_unstaffed(room), ["T02"])

    def test_item_blocked_by_open_owner_decision_not_ready(self):
        room = self.room([("T01", {}), ("T02", {})])
        (room.dir / "decisions" / "D01-q.md").write_text(
            "---\nid: D01\ntitle: q\ntype: ask\nstatus: open\ndecider: owner\nblocks: [T01]\n---\n## Options\n")
        self.assertEqual(tr.ready_unstaffed(tr.Room("r1")), ["T02"])

    def test_plan_marks_and_stall_detail_names_them(self):
        room = self.wave0()
        self.assertTrue(all(x["unstaffed"] for x in tr.plan(room)["items"]))
        self.assertIn("ready, no agent: T06 T07 T12", "\n".join(tr.plan_lines(room)))
        state, detail = tr.continuity(room, True)
        self.assertEqual(state, "stalled")
        self.assertIn("T06, T07, T12 are ready", detail)


if __name__ == "__main__":
    unittest.main()
