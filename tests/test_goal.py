"""The goal gate: three fields, owner approval, no work before it."""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import isolated_data  # noqa: E402,F401
import contextlib, importlib.machinery, importlib.util, io, tempfile, types, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

ITEM = ("---\nid: T01\ntitle: x\nstate: todo\nowner: dev\ncap_h: 1\nupdated: 2026-10-26T23:55Z\n---\n"
        "## Acceptance\n- [ ] works\n\n## Inputs\n- spec\n\n## Log\n- 01:00Z dev: created\n\n## Result\n")


class GoalGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved = (tr.ROOMS, tr.ROOT, tr.TEMPLATES, tr.notify_lead)
        self.addCleanup(lambda: (setattr(tr, "ROOMS", self.saved[0]), setattr(tr, "ROOT", self.saved[1]),
                                 setattr(tr, "TEMPLATES", self.saved[2]), setattr(tr, "notify_lead", self.saved[3])))
        tr.ROOT = Path(self.tmp.name)
        tr.ROOMS, tr.TEMPLATES = tr.ROOT / "rooms", REPO / "template"
        tr.notify_lead = lambda *a, **k: None
        d = tr.ROOMS / "r1"
        (d / "items").mkdir(parents=True)
        (d / "decisions").mkdir()
        (d / "BRIEF.md").write_text("---\ntitle: Room one\n---\n")
        (d / "items" / "T01-x.md").write_text(ITEM)

    def run_fn(self, fn, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            fn(types.SimpleNamespace(**kw))
        return out.getvalue()

    def goal(self, verb, architecture="local files", result="it runs", done="tests pass"):
        return self.run_fn(tr.cmd_goal, room="r1", verb=verb, architecture=architecture, result=result, done=done)

    def start(self, **kw):
        return self.run_fn(tr.cmd_set, room="r1", id="T01", pairs=["state=doing"], by="dev", force=False, **kw)

    def approve_as_owner(self, choice="a"):
        self.goal("approve")
        self.run_fn(tr.cmd_answer, room="r1", id="D01", choice=choice, by="owner", quote=None)

    def test_no_state_doing_before_approval(self):
        with self.assertRaisesRegex(SystemExit, "no goal yet"):
            self.start()
        self.goal("new")
        with self.assertRaisesRegex(SystemExit, "goal draft"):
            self.start()
        self.goal("approve")                       # the card is open; still not approved
        with self.assertRaisesRegex(SystemExit, "goal draft"):
            self.start()
        self.assertEqual(tr.Room("r1").find("T01")["state"], "todo")

    def test_no_dispatch_before_approval(self):
        self.goal("new")
        self.assertTrue(tr.Room("r1").build_locked)
        a = types.SimpleNamespace(verb="launch", target="r1", item="T01", text="", project=None, provider=None,
                                  model=None, title=None, role=None)
        with self.assertRaises(tr.StoreConflict) as e:
            tr.cmd_t3(a)
        self.assertIn("goal approval", str(e.exception))

    def test_only_the_owner_answer_approves(self):
        self.goal("new")
        self.approve_as_owner("b")
        self.assertEqual(tr.Room("r1").goal["status"], "draft")
        with self.assertRaisesRegex(SystemExit, "goal draft"):
            self.start()
        self.run_fn(tr.cmd_goal, room="r1", verb="approve", architecture="", result="", done="")
        self.run_fn(tr.cmd_answer, room="r1", id="D02", choice="a", by="owner", quote=None)
        room = tr.Room("r1")
        self.assertEqual(room.goal["status"], "approved")
        self.assertFalse(room.build_locked)
        self.start()
        self.assertEqual(tr.Room("r1").find("T01")["state"], "doing")

    def test_approved_goal_appears_in_brief(self):
        self.goal("new", "files on disk", "overview page", "owner approves a card")
        self.assertIn("goal: goal draft", self.run_fn(tr.cmd_brief, room="r1"))
        self.approve_as_owner()
        out = self.run_fn(tr.cmd_brief, room="r1")
        self.assertIn("goal: goal approved", out)
        self.assertIn("Architecture: files on disk", out)
        self.assertIn("Minimal viable result: overview page", out)
        self.assertIn("Definition of done: owner approves a card", out)

    def test_one_line_goal_is_accepted_and_still_needs_approval(self):
        self.goal("new", "one script", "it prints hello", "hello is printed")
        self.assertEqual(tr.Room("r1").goal["status"], "draft")
        self.assertTrue(tr.Room("r1").build_locked)

    def test_empty_field_is_rejected(self):
        for field in ("architecture", "result", "done"):
            with self.assertRaisesRegex(SystemExit, "all three fields"):
                self.goal("new", **{field: "  "})
        self.assertFalse((tr.ROOMS / "r1" / "GOAL.md").exists())

    def test_approve_needs_a_goal(self):
        with self.assertRaisesRegex(SystemExit, "no goal"):
            self.goal("approve")


if __name__ == "__main__":
    unittest.main()
