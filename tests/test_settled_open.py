"""Warn when a lead thread is settled with open items. Fake thread_info, temp rooms; no real T3 call, no message.
Run: python3 -m unittest tests.test_settled_open
"""
import importlib.machinery, importlib.util, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

LEAD = "lead-thread-0001"


class SettledOpen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (tr.ROOMS, tr.thread_info)
        tr.ROOMS = Path(self.tmp.name) / "rooms"
        self._canonical_root_before = tr.ROOT
        tr.ROOT = tr.ROOMS.parent
        self.addCleanup(setattr, tr, "ROOT", self._canonical_root_before)
        self.th = {}
        tr.thread_info = lambda t: self.th.get((t or "").strip())
        self.sent = []

    def tearDown(self):
        tr.ROOMS, tr.thread_info = self.saved
        self.tmp.cleanup()

    def room(self, states=("doing", "todo"), extra="", settled=True):
        d = tr.ROOMS / "r"
        (d / "items").mkdir(parents=True, exist_ok=True)
        (d / "BRIEF.md").write_text(f"---\ntitle: t\nlead_thread: {LEAD}\n{extra}---\n")
        for n, s in enumerate(states, 44):
            (d / "items" / f"T{n}-x.md").write_text(f"---\nid: T{n}\ntitle: x\nstate: {s}\nowner: A\ncap_h: 1\nupdated: 2026-10-27T10:00Z\n---\n")
        self.th[LEAD] = {"status": "idle", "settled": settled, "updated": "2026-10-27T11:00:00Z"}
        return tr.Room("r")

    def entries(self, r):
        return [x for x in tr.attention_json(r)["attention"] if x["rule"] == "settled-open"]

    def test_open_items_warn(self):
        r = self.room()
        e = self.entries(r)
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]["level"], "loud")
        self.assertIn("lead settled with open items: T44, T45", e[0]["text"])
        self.assertIn("unsettle the lead", e[0]["text"])
        self.assertTrue(tr.attention_json(r)["attention_loud"])
        self.assertTrue(any("lead settled with open items: T44, T45" in p for p in tr.problems(r, False)))
        self.assertEqual(self.sent, [])

    def test_no_open_items(self):
        r = self.room(states=("done", "dropped"))
        self.assertEqual(self.entries(r), [])
        self.assertFalse(any("lead settled with open items" in p for p in tr.problems(r, False)))

    def test_not_settled(self):
        self.assertEqual(self.entries(self.room(settled=False)), [])

    def test_closed_room(self):
        self.assertEqual(self.entries(self.room(extra="closed: 2026-10-27 done\n")), [])

    def test_standing_and_paused(self):
        self.assertEqual(self.entries(self.room(extra="standing: true\n")), [])
        self.assertEqual(self.entries(self.room(extra="paused: 2026-10-27T10:00Z\n")), [])



if __name__ == "__main__":
    unittest.main()
