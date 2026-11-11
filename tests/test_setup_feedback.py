"""Feedback: process room, dedupe, nudge, /api/state fields.
Temp atr root and temp HOME; fake launcher, fake T3 lookups and sends: no real thread or room is touched.
Run: python3 -m unittest tests.test_setup_feedback
"""
import argparse, contextlib, importlib.machinery, importlib.util, io, os, shutil, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

TID = "11111111-aaaa-bbbb-cccc-000000000001"


def fb(text, room="quiet", doc="PROTOCOL", **kw):
    return argparse.Namespace(text=text, doc=doc, from_room=room, cites=kw.get("cites"),
                              from_thread=kw.get("from_thread"), by="Tester", blocks=kw.get("blocks"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        shutil.copytree(REPO / "template", root / "template")
        self.saved = (tr.ROOMS, tr.TEMPLATES, tr.ROOT, tr.fetch_thread, tr.tell_thread,
                      os.environ.get("HOME"), os.environ.pop("ATR_MAINTAINER_THREAD", None))
        tr.ROOMS, tr.TEMPLATES, tr.ROOT = root / "rooms", root / "template", root
        tr.ROOMS.mkdir()
        os.environ["HOME"] = str(root / "home")
        self.addCleanup(lambda v=os.environ.get("ATR_SERVICE"): os.environ.__setitem__("ATR_SERVICE", v) if v is not None
                        else os.environ.pop("ATR_SERVICE", None))
        os.environ["ATR_SERVICE"] = "off"     # never touch the real systemd/launchd
        # keep a real T3 CLI on this machine out of the tests: atr also looks for `t3` on PATH
        for k in ("PATH", "T3CODE_CLI_PATH"):
            self.addCleanup(lambda k=k, v=os.environ.get(k): os.environ.__setitem__(k, v) if v is not None
                            else os.environ.pop(k, None))
        os.environ.pop("T3CODE_CLI_PATH", None)
        os.environ["PATH"] = os.pathsep.join(d for d in os.environ.get("PATH", "").split(os.pathsep)
                                             if d and not os.path.exists(os.path.join(d, "t3")))
        self.sent, self.alive = [], {TID}
        tr.fetch_thread = lambda t: {"status": "idle"} if t in self.alive else None
        tr.tell_thread = lambda t, text: self.sent.append((t, text)) or True

    def tearDown(self):
        (tr.ROOMS, tr.TEMPLATES, tr.ROOT, tr.fetch_thread, tr.tell_thread, home, env) = self.saved
        os.environ["HOME"] = home
        if env is not None:
            os.environ["ATR_MAINTAINER_THREAD"] = env
        self.tmp.cleanup()

    def run_cmd(self, fn, arg):
        out = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out):
            try:
                fn(arg)
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    out.write(e.code)
        return code, out.getvalue()

    def bootstrap(self, maintainer=True):
        """The process room and the saved maintainer choice, as `atr setup` used to leave them."""
        d = tr.ROOMS / tr.PROCESS_ROOM
        tr.create_room_files(d, "Maintain the protocol, lead skill and charters from feedback", "", tr.now())
        tr.ensure_standing(d)
        tr.write_setup({"maintainer": maintainer})
        if maintainer:
            self.set_lead(TID)
            tr.durable_write(self.cfg("maintainer_thread"), TID + "\n")

    def set_lead(self, thread):
        b = tr.ROOMS / tr.PROCESS_ROOM / "BRIEF.md"
        b.write_text(tr.re.sub(r"^lead_thread:.*$", f"lead_thread: {thread}", b.read_text(), count=1, flags=tr.re.M))

    def cfg(self, name):
        return tr.config_dir() / name


class FeedbackTests(Base):
    def setUp(self):
        super().setUp()
        self.bootstrap()
        self.sent.clear()

    def test_no_process_room(self):
        shutil.rmtree(tr.ROOMS / "process")
        code, out = self.run_cmd(tr.cmd_feedback, fb("x"))
        self.assertEqual(code, 1)
        self.assertIn("no room process", out)

    def test_creates_item_and_nudges(self):
        code, out = self.run_cmd(tr.cmd_feedback, fb("The lead skill never says when to close a room.", cites="notes/D05"))
        self.assertEqual((code, out.strip()), (0, "T01"))
        r = tr.Room("process").items[0]
        self.assertEqual((r["owner"], r["state"]), ("maintainer", "todo"))
        self.assertIn("never says when to close", r.section("Feedback"))
        self.assertEqual(tr.feedback_field(r, "doc"), "PROTOCOL")
        self.assertEqual(tr.feedback_field(r, "from"), "quiet")
        self.assertEqual(tr.feedback_field(r, "cites"), "notes/D05")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0], TID)

    def test_dedupe_same_room_within_24h_only(self):
        self.run_cmd(tr.cmd_feedback, fb("Same  text"))
        code, out = self.run_cmd(tr.cmd_feedback, fb("same text"))
        self.assertIn("T01", out)
        self.assertEqual(len(tr.Room("process").items), 1)
        self.assertEqual(len(self.sent), 1)                                  # no second nudge
        self.run_cmd(tr.cmd_feedback, fb("same text", room="other"))        # other room: new item
        self.assertEqual(len(tr.Room("process").items), 2)
        r = tr.Room("process").items[0]
        r.set("created", "2020-01-01T00:00Z")
        r.save()
        self.run_cmd(tr.cmd_feedback, fb("same text"))                      # older than 24 h: new item
        self.assertEqual(len(tr.Room("process").items), 3)

    def test_no_nudge_when_setup_said_no(self):
        tr.write_setup({"maintainer": False})
        self.sent.clear()
        self.run_cmd(tr.cmd_feedback, fb("kept anyway"))
        self.assertEqual(len(tr.Room("process").items), 1)
        self.assertEqual(self.sent, [])

    def test_no_nudge_without_thread(self):
        self.cfg("maintainer_thread").unlink()
        self.set_lead("")
        self.run_cmd(tr.cmd_feedback, fb("no one to tell"))
        self.assertEqual(self.sent, [])
        self.assertEqual(len(tr.Room("process").items), 1)

    def test_counts(self):
        for i in range(4):
            self.run_cmd(tr.cmd_feedback, fb(f"point {i}"))
        room = tr.Room("process")
        for rec, o in zip(room.items[:3], ("accepted", "rejected", "deferred")):
            rec.set("outcome", o)
            rec.save()
        old = room.items[0]
        c = tr.feedback_counts(tr.Room("process"))
        self.assertEqual({k: c[k] for k in ("open", "accepted", "rejected", "deferred")},
                         {"open": 1, "accepted": 1, "rejected": 1, "deferred": 1})
        later = tr.now() + __import__("datetime").timedelta(days=8)
        c = tr.feedback_counts(tr.Room("process"), later)
        self.assertEqual((c["accepted"], c["open"]), (0, 1))

    def test_api_state_fields_only_for_process_room(self):
        self.run_cmd(tr.cmd_feedback, fb("one"))
        saved = (tr.thread_info,)
        tr.thread_info = lambda t: None
        try:
            st = tr.room_json(tr.Room("process"))
        finally:
            tr.thread_info, = saved
        self.assertEqual(st["feedback"]["open"], 1)


class BlocksTests(Base):
    """Feedback --blocks room/item."""
    def setUp(self):
        super().setUp()
        self.bootstrap()
        d = tr.ROOMS / "app"
        (d / "items").mkdir(parents=True)
        (d / "decisions").mkdir()
        (d / "BRIEF.md").write_text("---\ntitle: Launch\nlead_thread: LEAD0001abc\n---\n")
        (d / "items" / "T07-ship.md").write_text("---\nid: T07\ntitle: Ship\nstate: doing\nowner: lead\ndepends_on: []\n"
                                                "locks: []\nupdated: 2026-01-01T00:00Z\n---\n## Log\n- 00:00Z x: set state=doing\n")
        self.deferred = []
        self.saved_t = tr.tell_lead_or_defer
        tr.tell_lead_or_defer = lambda room, text, thread=None: (self.deferred.append((room.name, text)) if " reached " not in text else None) or True
        self.run_cmd(tr.cmd_feedback, fb("plain one"))
        self.sent.clear()

    def tearDown(self):
        tr.tell_lead_or_defer = self.saved_t
        super().tearDown()

    def test_records_blocks_and_pings(self):
        code, out = self.run_cmd(tr.cmd_feedback, fb("Accessibility gaps", blocks="app/T07"))
        self.assertEqual((code, out.strip()), (0, "T02"))
        r = tr.Room("process").find("T02")
        self.assertEqual(r["blocks"], ["app/T07"])
        self.assertIn("BLOCKS app/T07", self.sent[0][1])

    def test_rejects_unknown_room_or_item_and_files_nothing(self):
        for bad in ("nope/T07", "launch/T99", "T07"):
            code, out = self.run_cmd(tr.cmd_feedback, fb("x " + bad, blocks=bad))
            self.assertEqual(code, 1, bad)
        self.assertEqual(len(tr.Room("process").items), 1)

    def test_attention_loud_while_blocked_item_open(self):
        self.run_cmd(tr.cmd_feedback, fb("Accessibility gaps", blocks="app/T07"))
        saved = (tr.thread_info, tr.thread_status)
        tr.thread_info = lambda t: None
        tr.thread_status = lambda t: None
        try:
            a = tr.attention_json(tr.Room("process"))
            self.assertTrue(a["attention_loud"])
            self.assertTrue(any(x["rule"] == "blocks" and x["id"] == "T02" for x in a["attention"]))
            b = tr.Room("app").find("T07"); b.set("state", "done"); b.save()
            self.assertFalse(tr.attention_json(tr.Room("process"))["attention_loud"])
        finally:
            tr.thread_info, tr.thread_status = saved

    def test_blocking_items_sort_first_in_status_and_plan(self):
        self.run_cmd(tr.cmd_feedback, fb("Accessibility gaps", blocks="app/T07"))
        p = tr.plan(tr.Room("process"))
        self.assertEqual([x["id"] for x in p["items"]], ["T02", "T01"])
        self.assertEqual(p["items"][0]["blocks"], ["app/T07"])
        self.assertEqual(p["items"][1]["blocks"], [])
        self.assertIn("unstaffed", p["items"][0])
        room = tr.Room("process")
        for i in room.items:
            i.set("state", "doing"); i.save()
        _, lines = tr.render(tr.Room("process"))
        flight = [l for l in lines if l.startswith(("T01", "T02"))]
        self.assertTrue(flight[0].startswith("T02"))

    def test_done_or_outcome_resolves_without_notifying_project_lead(self):
        self.run_cmd(tr.cmd_feedback, fb("Accessibility gaps", blocks="app/T07"))
        for pairs in (["state=done"], ["state=done"]):
            self.run_cmd(tr.cmd_set, argparse.Namespace(room="process", id="T02", pairs=pairs, force=False, by="M"))
        self.assertEqual(self.deferred, [])
        self.run_cmd(tr.cmd_feedback, fb("Another", blocks="app/T07"))
        self.run_cmd(tr.cmd_set, argparse.Namespace(room="process", id="T03", pairs=["outcome=rejected"], force=False, by="M"))
        self.assertEqual(self.deferred, [])

    def test_no_tap_when_blocked_item_already_done(self):
        self.run_cmd(tr.cmd_feedback, fb("Accessibility gaps", blocks="app/T07"))
        b = tr.Room("app").find("T07"); b.set("state", "done"); b.save()
        self.run_cmd(tr.cmd_set, argparse.Namespace(room="process", id="T02", pairs=["state=done"], force=False, by="M"))
        self.assertEqual(self.deferred, [])

    def _resolve(self, rid, next_line=None):
        if next_line:
            r = tr.Room("process").find(rid); r.append_to("Result", next_line); r.save()
        self.run_cmd(tr.cmd_set, argparse.Namespace(room="process", id=rid, pairs=["state=done"], force=False, by="M"))

    def test_successor_named_gets_block_without_project_message(self):
        self.run_cmd(tr.cmd_feedback, fb("Split me", blocks="app/T07"))   # T02
        self.run_cmd(tr.cmd_feedback, fb("Follow-up"))                      # T03
        self._resolve("T02", "Next: process T03")
        self.assertEqual(tr.Room("process").find("T03")["blocks"], ["app/T07"])
        self.assertFalse(tr.Room("process").find("T02")["unblocked_sent"])
        self.assertEqual(self.deferred, [])
        self._resolve("T02")                                                # again: no duplicate
        self.assertEqual(self.deferred, [])
        self._resolve("T03")                                                # successor resolves: usual rule
        self.assertEqual(self.deferred, [])
        self.assertEqual(tr.Room("process").find("T03")["unblocked_sent"], "yes")

    def test_two_successors_both_carry_block(self):
        self.run_cmd(tr.cmd_feedback, fb("Split me", blocks="app/T07"))
        self.run_cmd(tr.cmd_feedback, fb("A")); self.run_cmd(tr.cmd_feedback, fb("B"))
        self._resolve("T02", "Next: T03 and T04")
        self.assertEqual([tr.Room("process").find(x)["blocks"] for x in ("T03", "T04")], [["app/T07"]] * 2)

    def test_no_successor_unchanged(self):
        self.run_cmd(tr.cmd_feedback, fb("Split me", blocks="app/T07"))
        self._resolve("T02", "Next: none (finished)")
        self.assertEqual(self.deferred, [])

    def test_successor_already_done_is_not_a_successor(self):
        self.run_cmd(tr.cmd_feedback, fb("Split me", blocks="app/T07"))
        self.run_cmd(tr.cmd_feedback, fb("Old"))
        o = tr.Room("process").find("T03"); o.set("state", "done"); o.save()
        self._resolve("T02", "Next: T03")
        self.assertEqual(self.deferred, [])
        self.assertEqual(tr.Room("process").find("T03")["blocks"] or [], [])

    def test_check_warns_when_successor_lacks_block(self):
        self.run_cmd(tr.cmd_feedback, fb("Split me", blocks="app/T07"))
        self.run_cmd(tr.cmd_feedback, fb("Follow-up"))
        r = tr.Room("process").find("T02"); r.append_to("Result", "Next: T03"); r.set("state", "done"); r.save()
        w = [p for p in tr.problems(tr.Room("process")) if "is its successor" in p]
        self.assertEqual(w, ["process/T02: resolved, T03 is its successor but does not block app/T07"])


if __name__ == "__main__":
    unittest.main()
