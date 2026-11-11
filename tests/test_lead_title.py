"""Warn when the active lead thread is not titled 'Room · ...'; `rooms new` prints the rename hint.
Fake thread_info, temp rooms; no T3 call, no message. Run: python3 -I -m unittest tests.test_lead_title
"""
import argparse, contextlib, importlib.machinery, importlib.util, io, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

LEAD = "lead-thread-0001"


class LeadTitle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (tr.ROOMS, tr.thread_info)
        tr.ROOMS = Path(self.tmp.name) / "rooms"
        self._canonical_root_before = tr.ROOT
        tr.ROOT = tr.ROOMS.parent
        self.addCleanup(setattr, tr, "ROOT", self._canonical_root_before)
        self.th = {}
        tr.thread_info = lambda t: self.th.get((t or "").strip())

    def tearDown(self):
        tr.ROOMS, tr.thread_info = self.saved
        self.tmp.cleanup()

    def room(self, title, extra="", info=True):
        d = tr.ROOMS / "r"
        (d / "items").mkdir(parents=True, exist_ok=True)
        (d / "BRIEF.md").write_text(f"---\ntitle: t\nlead_thread: {LEAD}\n{extra}---\n")
        if info:
            self.th[LEAD] = {"status": "idle", "settled": False, "title": title, "updated": "2026-10-27T11:00:00Z"}
        return tr.Room("r")

    def warns(self, r):
        return [p for p in tr.problems(r, False) if "lead thread is titled" in p]

    def test_good_title(self):
        self.assertEqual(self.warns(self.room("Room · r · lead")), [])

    def test_bad_title(self):
        w = self.warns(self.room("Fix the thing"))
        self.assertEqual(len(w), 1)
        self.assertIn("lead thread is titled 'Fix the thing': rename it to 'Room · r · lead' with t3_thread_update", w[0])

    def test_empty_title_warns(self):
        self.assertEqual(len(self.warns(self.room(""))), 1)

    def test_unknown_thread(self):
        self.assertEqual(self.warns(self.room("x", info=False)), [])

    def test_closed_room(self):
        self.assertEqual(self.warns(self.room("x", extra="closed: 2026-10-27 done\n")), [])

    def test_standing_room(self):
        self.assertEqual(self.warns(self.room("Room · process · Maintainer", extra="standing: true\n")), [])
        self.assertEqual(self.warns(self.room("Maintainer", extra="standing: true\n")), [])

    def test_fetch_thread_returns_title(self):
        import json, subprocess
        saved = subprocess.run
        subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps({"thread": {"title": "T", "status": "idle"}}), "")
        try:
            self.assertEqual(tr.fetch_thread("abc-123")["title"], "T")
        finally:
            subprocess.run = saved

    def test_room_new_last_line(self):
        out = io.StringIO()
        a = argparse.Namespace(name="newroom", title="New", lead_thread="fresh-thread-9")
        tr.ROOMS.mkdir(parents=True)
        saved = tr.create_room_files
        tr.create_room_files = lambda *x, **k: (tr.ROOMS / "newroom").mkdir()
        try:
            with contextlib.redirect_stdout(out):
                tr.cmd_room(a)
        finally:
            tr.create_room_files = saved
        self.assertEqual(out.getvalue().rstrip("\n").splitlines()[-1],
                         "Next: rename your thread to 'Room · newroom · lead' (t3_thread_update, action rename)")

    def test_room_new_without_lead_points_at_atr_lead(self):
        out = io.StringIO()
        a = argparse.Namespace(name="newroom", title="New", lead_thread="")
        tr.ROOMS.mkdir(parents=True)
        saved = tr.create_room_files
        tr.create_room_files = lambda *x, **k: (tr.ROOMS / "newroom").mkdir()
        try:
            with contextlib.redirect_stdout(out):
                tr.cmd_room(a)
        finally:
            tr.create_room_files = saved
        self.assertIn("atr lead newroom", out.getvalue().rstrip("\n").splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
