"""`atr set ... state=review|done` warns when the Log has no `set state=doing` line.
Run: python3 -I -m unittest tests.test_set_warn_doing
"""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import goal_fixture
import contextlib, importlib.machinery, importlib.util, io, tempfile, types, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

ITEM = "---\nid: T01\ntitle: x\nstate: {state}\nowner: dev\nupdated: 2026-10-26T23:55Z\n---\n## Acceptance\n- [ ] works\n\n## Inputs\n- spec\n\n## Log\n{log}\n## Result\nDone:\n"


class SetWarn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = tr.ROOMS
        tr.ROOMS = Path(self.tmp.name) / "rooms"
        self._canonical_root_before = tr.ROOT
        tr.ROOT = tr.ROOMS.parent
        self.addCleanup(setattr, tr, "ROOT", self._canonical_root_before)
        (tr.ROOMS / "r1" / "items").mkdir(parents=True)
        (tr.ROOMS / "r1" / "BRIEF.md").write_text("---\ntitle: t\n---\n")
        goal_fixture.approve(tr.ROOMS / "r1")

    def tearDown(self):
        tr.ROOMS = self.saved
        self.tmp.cleanup()

    def run_set(self, pairs, log="- 01:00Z dev: created"):
        (tr.ROOMS / "r1" / "items" / "T01-x.md").write_text(ITEM.format(state="todo", log=log))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            tr.cmd_set(types.SimpleNamespace(room="r1", id="T01", pairs=pairs, by="dev", force=False))
        return err.getvalue()

    def test_warns_review_and_done_without_doing_line(self):
        for state in ("review", "done"):
            self.assertIn("no 'set state=doing'", self.run_set([f"state={state}"]))

    def test_state_still_set_despite_warning(self):
        self.run_set(["state=review"])
        self.assertEqual(tr.Room("r1").find("T01")["state"], "review")

    def test_quiet_when_doing_line_present(self):
        log = "- 01:00Z dev: set state=doing owner=dev"
        self.assertEqual(self.run_set(["state=done"], log), "")

    def test_quiet_for_other_states(self):
        self.assertEqual(self.run_set(["state=blocked"]), "")

    def test_doing_without_cap_warns_but_applies(self):
        err = self.run_set(["state=doing"])
        self.assertIn("cap_h=<hours>", err)
        self.assertEqual(tr.Room("r1").find("T01")["state"], "doing")

    def test_doing_quiet_with_cap_or_cap_in_same_call(self):
        self.assertEqual(self.run_set(["state=doing", "cap_h=1"]), "")
        (tr.ROOMS / "r1" / "items" / "T01-x.md").write_text(
            ITEM.format(state="todo", log="").replace("owner: dev\n", "owner: dev\ncap_h: 1\n"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            tr.cmd_set(types.SimpleNamespace(room="r1", id="T01", pairs=["state=doing"], by="dev", force=False))
        self.assertEqual(err.getvalue(), "")

if __name__ == "__main__":
    unittest.main()
