"""Rooms with several threads: fake threads, fake sender, temp atr root. No real T3 call or nudge.
Run: python3 -m unittest tests.test_threads
"""
import importlib.machinery, importlib.util, sys, tempfile, unittest, datetime as dt
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

LEAD, FORK, KID = "lead-thread-0001", "fork-thread-00002", "thread:delegated-task:kid1xxxx"
NEW = "new-lead-thread-3"
T0 = dt.datetime(2026, 10, 26, 12, 0, tzinfo=dt.timezone.utc).timestamp()
iso = lambda e: dt.datetime.fromtimestamp(e, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ITEM = "---\nid: {id}\ntitle: x\nstate: {state}\nowner: dev\nagent: {agent}\nupdated: 2026-10-26T11:55Z\n---\n## Result\nDone:\n"


class Threads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (tr.ROOMS, tr.thread_info, tr.t3_call)
        tr.ROOMS = Path(self.tmp.name) / "rooms"
        self._canonical_root_before = tr.ROOT
        tr.ROOT = tr.ROOMS.parent
        self.addCleanup(setattr, tr, "ROOT", self._canonical_root_before)
        self.threads, self.told, self.synced = {}, [], []
        tr.thread_info = lambda t: self.threads.get((t or "").strip())
        tr.t3_call = lambda kind, target, payload, options=None: (self.told.append((target, payload)),
                                                                   {"ok": True, "evidence": "synthetic", "thread": None})[1]

    def tearDown(self):
        tr.ROOMS, tr.thread_info, tr.t3_call = self.saved
        self.tmp.cleanup()

    def room(self, items=(), extra="", name="r1"):
        d = tr.ROOMS / name
        (d / "items").mkdir(parents=True, exist_ok=True)
        for old in (d / "items").glob("*.md"):
            old.unlink()
        (d / "BRIEF.md").write_text(f"---\ntitle: t\nlead_thread: {LEAD}   # lead\n{extra}---\n")
        for iid, state, agent in items:
            (d / "items" / f"{iid}-x.md").write_text(ITEM.format(id=iid, state=state, agent=agent))
        return tr.Room(name)

    def th(self, t, settled=False, status="idle", up=T0, **kw):
        self.threads[t] = {"status": status, "settled": settled, "updated": iso(up), **kw}

    def test_single_thread_room_unchanged(self):
        r = self.room()
        self.th(LEAD, settled=True)
        self.assertTrue(tr.thread_state(r)["settled"])
        self.th(LEAD, settled=False)
        self.assertFalse(tr.thread_state(r)["settled"])
        self.assertEqual(tr.active_lead(r), LEAD)

    def test_set_from_brief_items_and_forks_not_delegate_children(self):
        r = self.room([("T1", "doing", FORK), ("T2", "doing", KID), ("T3", "done", "old-thread-0009")], f"threads: [{NEW}]\n")
        self.th(KID, parent=LEAD, relationship="delegate")
        self.assertEqual(tr.room_threads(r), [LEAD, NEW, FORK])
        r = self.room([("T2", "doing", "plain-child-0003")])
        self.th("plain-child-0003", parent=LEAD, relationship="delegate")
        self.assertEqual(tr.room_threads(r), [LEAD])
        self.th("plain-child-0003", parent=LEAD, relationship="fork")
        self.assertEqual(tr.room_threads(r), [LEAD, "plain-child-0003"])

    def test_lead_settled_fork_active_keeps_room_open(self):
        r = self.room([("T1", "doing", FORK)])
        self.th(LEAD, settled=True); self.th(FORK, status="running")
        st = tr.thread_state(r)
        self.assertEqual((st["settled"], st["lead_settled"], st["others_active"]), (False, True, [FORK]))
        j = tr.room_json(r)
        self.assertEqual((j["lead_settled"], j["lead_settled_others"], j["lead_status"]), (False, 1, "running"))
        self.th(FORK, settled=True)
        self.assertTrue(tr.thread_state(r)["settled"])

    def test_unknown_other_thread_does_not_hold_room(self):
        r = self.room(extra="threads: [ghost-thread-0007]\n")
        self.th(LEAD, settled=True)
        self.assertTrue(tr.thread_state(r)["settled"])

    def test_nudges_go_to_most_recent_live_thread(self):
        r = self.room(extra=f"threads: [{FORK}, {NEW}]\n")
        self.th(LEAD, settled=True); self.th(FORK, up=T0 - 100); self.th(NEW, up=T0)
        self.assertEqual(tr.active_lead(r), NEW)
        tr.notify_lead(r, "hi")
        self.assertEqual(self.told, [(NEW, "hi")])
        self.th(LEAD, settled=False)
        self.assertEqual(tr.active_lead(r), LEAD)

    def test_continuity_follows_live_thread(self):
        r = self.room(extra=f"threads: [{FORK}]\n")
        self.th(LEAD, settled=True); self.th(FORK, status="running")
        self.assertEqual(tr.continuity(r)[0], "moving")




    def handoff(self, *argv):
        ns = type("A", (), {"room": "r1", "thread": NEW, "keep_old": False})()
        for k, v in zip(("thread", "keep_old"), argv):
            setattr(ns, k, v)
        tr.cmd_lead(ns)

    def test_lead_handoff(self):
        self.room()
        self.th(LEAD); self.th(NEW)
        self.handoff()
        r = tr.Room("r1")
        self.assertEqual(r.brief["lead_thread"], NEW)
        self.assertEqual(r.brief["threads"], [LEAD])
        self.assertIn("# lead", (r.dir / "BRIEF.md").read_text())
        self.assertIn("lead-handoff", (r.dir / "pings.log").read_text())
        self.assertEqual(self.told[0][0], NEW); self.assertIn("atr inbox", self.told[0][1])
        self.assertEqual(len(self.told), 1)

    def test_lead_handoff_settled_old_dropped_unless_keep_old(self):
        self.room(); self.th(LEAD, settled=True); self.th(NEW)
        self.handoff()
        self.assertEqual(tr.Room("r1").brief["threads"], [])
        self.room(); self.handoff(NEW, True)
        self.assertEqual(tr.Room("r1").brief["threads"], [LEAD])

    def test_lead_handoff_refuses_unknown_thread(self):
        self.room(); self.th(LEAD)
        with self.assertRaises(SystemExit):
            self.handoff()
        self.assertEqual(tr.Room("r1").brief["lead_thread"], LEAD)
        self.assertEqual(self.told, [])






if __name__ == "__main__":
    unittest.main()
