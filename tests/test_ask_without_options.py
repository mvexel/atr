"""check: an open ask card for the owner needs no lettered options (free-text answer); other cards still do.
Run: python3 -m unittest tests.test_ask_without_options
"""
import importlib.machinery, importlib.util, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)


class AskWithoutOptions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = tr.ROOMS
        tr.ROOMS = Path(self.tmp.name) / "rooms"
        self._canonical_root_before = tr.ROOT
        tr.ROOT = tr.ROOMS.parent
        self.addCleanup(setattr, tr, "ROOT", self._canonical_root_before)

    def tearDown(self):
        tr.ROOMS = self.saved
        self.tmp.cleanup()

    def warnings(self, typ, options=""):
        d = tr.ROOMS / "r"
        (d / "items").mkdir(parents=True, exist_ok=True)
        (d / "decisions").mkdir(exist_ok=True)
        (d / "BRIEF.md").write_text("---\ntitle: t\n---\n")
        (d / "decisions" / "X01-q.md").write_text(
            f"---\nid: X01\ntitle: q\ntype: {typ}\ndoor: two\ndecider: owner\nstatus: open\n"
            f"opened: 2026-10-27T10:00Z\nupdated: 2026-10-27T10:00Z\n---\n## Options\n{options}\n")
        return [w for w in tr.problems(tr.Room("r")) if "fewer than 2 options" in w]

    def test_ask_without_options_is_quiet(self):
        self.assertEqual(self.warnings("ask"), [])

    def test_decision_without_options_warns(self):
        self.assertEqual(len(self.warnings("decision")), 1)

    def test_todo_without_options_still_warns(self):
        self.assertEqual(len(self.warnings("todo")), 1)

    def test_decision_with_two_options_is_quiet(self):
        self.assertEqual(self.warnings("decision", "a) yes\nb) no"), [])


if __name__ == "__main__":
    unittest.main()
