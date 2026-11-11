"""Lead pin/settle plan (FR8-10): pure derivation, idempotent steps, T3 unreachable. No real T3 call.
Run: python3 -I -m unittest tests.test_t3_organize
"""
import contextlib, io, json, types, unittest
from test_dependency_plan import Base, tr

LEAD = "lead-thread-1"
OPEN = ("---\nid: D01\ntitle: q\ntype: decision\nstatus: open\ndecider: owner\ndoor: two\nopened: 2026-10-27T10:00Z\nupdated: 2026-10-27T10:00Z\n---\n"
        "## Options\n- a: x\n- b: y\n\n## Answer\n")

class Organize(Base):
    def setUp(self):
        super().setUp()
        self.facts = None
        self.saved_ti = tr.thread_info
        tr.thread_info = lambda t: self.facts

    def tearDown(self):
        tr.thread_info = self.saved_ti
        super().tearDown()

    def mk(self, ask=False, closed=False):
        extra = "closed: done\n" if closed else ""
        room = self.room([("T01", {})], brief=f"---\ntitle: t\nlead_thread: {LEAD}\n{extra}---\n")
        if ask:
            (room.dir / "decisions" / "D01-q.md").write_text(OPEN)
        return tr.Room("r1")

    def steps(self, room):
        return [(s["action"], s["state"]) for s in tr.organize_plan(room)["steps"]]

    def test_pin_while_owner_needed(self):
        self.assertEqual(self.steps(self.mk(ask=True)), [("pin", "unknown")])
        self.facts = {"pinned": False, "settled": False}
        self.assertEqual(self.steps(self.mk(ask=True)), [("pin", "pending")])

    def test_unchanged_when_not_needed(self):
        self.assertEqual(self.steps(self.mk()), [])
        self.assertIsNone(tr.organize_wanted(self.mk())["pinned"])

    def test_close_unpins_and_settles(self):
        self.facts = {"pinned": True, "settled": False}
        self.assertEqual(self.steps(self.mk(closed=True)), [("unpin", "pending"), ("settle", "pending")])

    def test_already_satisfied_is_skipped(self):
        self.facts = {"pinned": False, "settled": True}
        self.assertEqual(self.steps(self.mk(closed=True)), [])
        self.facts = {"pinned": True, "settled": False}
        self.assertEqual(self.steps(self.mk(ask=True)), [])

    def test_t3_unreachable_marks_unknown(self):
        plan = tr.organize_plan(self.mk(closed=True))
        self.assertFalse(plan["t3_known"])
        self.assertEqual([(s["action"], s["state"]) for s in plan["steps"]], [("unpin", "unknown"), ("settle", "unknown")])

    def test_command_prints_json(self):
        self.mk(ask=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            tr.cmd_t3(types.SimpleNamespace(verb="organize", target="r1"))
        self.assertEqual(json.loads(out.getvalue())["steps"][0]["action"], "pin")

    def test_warn_only_when_known_out_of_line(self):
        self.assertIsNone(tr.organize_warn(self.mk(ask=True)))
        self.facts = {"pinned": False}
        self.assertIn("t3 organize r1", tr.organize_warn(self.mk(ask=True)))
        self.facts = {"pinned": True}
        self.assertIsNone(tr.organize_warn(self.mk(ask=True)))

if __name__ == "__main__":
    unittest.main()
