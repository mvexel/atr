"""BRIEF `code:` line: atr check warnings, atr brief output, page JSON. Declared code locations in a temp dir; no network.
Run: python3 -I -m unittest tests.test_code_line
"""
import importlib.machinery, importlib.util, io, subprocess, sys, tempfile, unittest, contextlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

ITEM = "---\nid: T1\ntitle: x\nstate: doing\nowner: lead\ndepends_on: []\nlocks: []\ncap_h: 2\nupdated: 2026-10-27T17:00Z\n---\n## Acceptance\n- [ ] a\n"




class CodeLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = tr.ROOMS
        tr.ROOMS = t / "rooms"
        self._canonical_root_before = tr.ROOT
        tr.ROOT = tr.ROOMS.parent
        self.addCleanup(setattr, tr, "ROOT", self._canonical_root_before)
        self.repo = t / "prod"
        self.repo.mkdir()
        self.wt = t / "wt"
        self.wt.mkdir()

    def tearDown(self):
        tr.ROOMS = self.saved
        self.tmp.cleanup()

    def room(self, code=None, repos=True, closed="", items=(ITEM,)):
        d = tr.ROOMS / "r"
        (d / "items").mkdir(parents=True, exist_ok=True)
        b = "---\ntitle: t\n" + (f"repos: [{self.repo}#main]\n" if repos else "")
        if code is not None:
            b += f"code: {code}   # note\n"
        b += f"closed: {closed}\n---\n"
        (d / "BRIEF.md").write_text(b)
        for n, it in enumerate(items):
            (d / "items" / f"T{n + 1}-x.md").write_text(it.replace("id: T1", f"id: T{n + 1}"))
        return tr.Room("r")

    def code_warns(self, room):
        return [x for x in tr.problems(room) if "code:" in x or "integration branch" in x]

    def test_missing_line(self):
        w = self.code_warns(self.room())
        self.assertEqual(len(w), 1)
        self.assertIn("no code: line", w[0])

    def test_skipped_when_closed_or_no_repos(self):
        self.assertEqual(self.code_warns(self.room(repos=False)), [])
        self.assertEqual(self.code_warns(self.room(closed="2026-10-27 done")), [])


    def test_worktree_path_missing(self):
        w = self.code_warns(self.room(f"ahead at {self.wt}/gone"))
        self.assertTrue(any("worktree" in x and "doesn't exist" in x for x in w), w)



    def test_healthy(self):
        self.assertEqual(self.code_warns(self.room(f"ahead at {self.wt}")), [])

    def test_brief_prints_code_line(self):
        self.room(f"ahead at {self.wt}")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tr.cmd_brief(type("A", (), {"room": "r"})())
        self.assertIn(f"code: ahead at {self.wt}", out.getvalue())

    def test_page_json_fields(self):
        info = tr.code_info(self.room(f"ahead at {self.wt}"))
        self.assertEqual((info["branch"], info["path"], info["warn"]), ("ahead", str(self.wt), []))
        bad = tr.code_info(self.room(f"nope at {self.wt}"))
        self.assertEqual(bad["warn"], [])  # branch is declared metadata; core does not inspect Git
        self.assertIsNone(tr.code_info(self.room(repos=False)))











if __name__ == "__main__":
    unittest.main()
