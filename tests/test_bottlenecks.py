"""Bottleneck checks: fake clock, fake threads, fake sender. No real nudge is ever sent.
Run: python3 -m unittest tests.test_bottlenecks
"""
import importlib.machinery, importlib.util, tempfile, unittest, datetime as dt
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

NOW = dt.datetime(2026, 10, 27, 12, 0, tzinfo=dt.timezone.utc)
LEAD = "lead-thread-0001"

def ago(minutes):
    return NOW - dt.timedelta(minutes=minutes)

def item(iid, state="todo", cap="2", since_min=None, deps="", agent="", extra_log=""):
    """An item that went to `state` since_min minutes before NOW (its last Log line, so updated == that time)."""
    t = ago(since_min if since_min is not None else 0)
    log = f"- {(t - dt.timedelta(hours=30)).strftime('%H:%M')}Z Org: created\n{extra_log}"
    if since_min is not None:
        log += f"- {t.strftime('%H:%MZ')} Dev: set state={state}\n"
    return (f"---\nid: {iid}\ntitle: x\nstate: {state}\nowner: dev\ncap_h: {cap}\ndepends_on: [{deps}]\nagent: {agent}\n"
            f"updated: {tr.stamp(t)}\n---\n## Log\n{log}\n## Result\n")


class Bottlenecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (tr.ROOMS, tr.now, tr.thread_info)
        tr.ROOMS = Path(self.tmp.name) / "rooms"
        self._canonical_root_before = tr.ROOT
        tr.ROOT = tr.ROOMS.parent
        self.addCleanup(setattr, tr, "ROOT", self._canonical_root_before)
        tr.now = lambda: NOW
        self.threads = {}
        tr.thread_info = lambda t: self.threads.get((t or "").strip())
        self.sent = []
        self.send = lambda room, text: (self.sent.append((room.name, text)), True)[1]

    def tearDown(self):
        (tr.ROOMS, tr.now, tr.thread_info) = self.saved
        self.tmp.cleanup()

    def room(self, items, brief="", decisions=(), name="r1"):
        d = tr.ROOMS / name
        (d / "items").mkdir(parents=True, exist_ok=True)
        (d / "decisions").mkdir(exist_ok=True)
        for old in list((d / "items").glob("*.md")) + list((d / "decisions").glob("*.md")):
            old.unlink()
        (d / "BRIEF.md").write_text(f"---\ntitle: t\nlead_thread: {LEAD}\nteam: [lead=Nora (she)]\n{brief}---\n")
        for it in items:
            iid = it.split("id: ")[1].split("\n")[0]
            (d / "items" / f"{iid}-x.md").write_text(it)
        for n, dec in enumerate(decisions):
            (d / "decisions" / f"D{n + 1:02d}-x.md").write_text(dec)
        return tr.Room(name)

    def rules(self, room):
        return sorted((x["id"], x["rule"]) for x in tr.bottlenecks(room, NOW))

    # (a) missing cap
    def test_no_cap(self):
        self.assertEqual(self.rules(self.room([item("T1", "doing", cap="", since_min=10)])), [("T1", "no-cap")])
        self.assertEqual(self.rules(self.room([item("T1", "todo", cap="")])), [])
        self.assertEqual(self.rules(self.room([item("T1", "doing", cap="2h", since_min=10)])), [])

    # (b) overrun at 1.0x, hard at 1.5x
    def test_overrun_thresholds(self):
        for mins, want in [(119, []), (120, ["overrun"]), (179, ["overrun"]), (180, ["hard-overrun"]), (600, ["hard-overrun"])]:
            got = [r for _, r in self.rules(self.room([item("T1", "doing", cap="2", since_min=mins)])) if r != "bottleneck"]
            self.assertEqual(got, want, mins)

    def test_overrun_measured_from_doing_not_last_log(self):
        # went to doing 5h ago, a progress line 10 min ago bumps `updated`; still hard overrun on a 2h cap
        it = item("T1", "doing", cap="2", since_min=300)
        it = it.replace("## Result", f"- {ago(10).strftime('%H:%MZ')} Dev: halfway\n\n## Result").replace(
            f"updated: {tr.stamp(ago(300))}", f"updated: {tr.stamp(ago(10))}")
        self.assertEqual(self.rules(self.room([it])), [("T1", "hard-overrun")])

    def test_log_crossing_midnight(self):
        # doing since 23:30 the previous day, now 12:00 on the 27th = 12.5 h
        it = item("T1", "doing", cap="20", since_min=0).replace(
            f"- {NOW.strftime('%H:%MZ')} Dev: set state=doing", "- 23:30Z Dev: set state=doing\n- 11:59Z Dev: still going")
        it = it.replace(f"updated: {tr.stamp(NOW)}", f"updated: {tr.stamp(ago(1))}")
        r = self.room([it])
        self.assertEqual(tr.state_since(r.items[0], "doing"), dt.datetime(2026, 10, 26, 23, 30, tzinfo=dt.timezone.utc))

    # (c) review
    def test_review_stale_and_late(self):
        self.assertEqual(self.rules(self.room([item("T1", "review", since_min=59)])), [])
        self.assertEqual(self.rules(self.room([item("T1", "review", since_min=61)])), [("T1", "review-stale")])
        self.assertEqual(self.rules(self.room([item("T1", "review", since_min=181)])), [("T1", "review-late")])
        r = self.room([item("T1", "review", since_min=250)])
        b = tr.bottlenecks(r, NOW)[0]
        self.assertEqual(b["level"], "loud")
        self.assertIn("Nora (the lead) flips it to done or dispatches a reviewer", b["text"])

    def test_review_with_running_reviewer_is_skipped(self):
        self.threads["thread:delegated-task:rev12345"] = {"status": "running"}
        self.assertEqual(self.rules(self.room([item("T1", "review", since_min=400, agent="thread:delegated-task:rev12345")])), [])

    # (d) critical path
    def test_bottleneck(self):
        items = [item("T26", "doing", cap="4", since_min=121), item("T43", deps="T26"), item("T18", deps="T43"),
                 item("T9", "done", deps="T26")]
        b = [x for x in tr.bottlenecks(self.room(items), NOW) if x["rule"] == "bottleneck"]
        self.assertEqual(len(b), 1)
        self.assertIn("bottleneck: T26 blocks T43, T18", b[0]["text"])    # T18 only through T43; done T9 not counted
        self.assertEqual(b[0]["level"], "note")

    def test_bottleneck_needs_two_todo_and_half_the_cap(self):
        one = [item("T26", "doing", cap="4", since_min=200), item("T43", deps="T26")]
        self.assertEqual([r for _, r in self.rules(self.room(one))], [])
        early = [item("T26", "doing", cap="4", since_min=119), item("T43", deps="T26"), item("T18", deps="T26")]
        self.assertEqual([r for _, r in self.rules(self.room(early))], [])

    # skips
    def test_skips(self):
        late = item("T1", "doing", cap="1", since_min=500)
        self.assertEqual(self.rules(self.room([item("T1", "dropped", cap="", since_min=500), item("T2", "done", since_min=500)])), [])
        self.assertEqual(self.rules(self.room([late], brief="closed: shipped\n")), [])
        self.assertEqual(self.rules(self.room([late], brief=f"paused: {tr.stamp(ago(5))}\n")), [])
        card = "---\nid: D01\ntitle: q\nstatus: open\ndecider: owner\nblocks: [T1]\ndoor: two\n---\n"
        self.assertEqual(self.rules(self.room([late], decisions=[card])), [])
        self.assertEqual(self.rules(self.room([late])), [("T1", "hard-overrun")])

    # check output
    def test_check_lists_them(self):
        room = self.room([item("T1", "doing", cap="", since_min=5), item("T2", "review", since_min=90)])
        out = [p for p in tr.problems(room) if "no cap_h" in p or "sat in review" in p]
        self.assertEqual(len(out), 2)

    # guarantee: no effect on moving/waiting/stalled
    def test_no_effect_on_continuity(self):
        quiet = [item("T1", "doing", cap="2", since_min=10)]
        loud = [item("T1", "doing", cap="", since_min=900), item("T2", "review", since_min=900),
                item("T3", "doing", cap="1", since_min=900), item("T4", deps="T3"), item("T5", deps="T3")]
        for yielding in (False, True):
            for lead in ("running", "idle"):
                for agent in ("", "thread:delegated-task:kid12345"):
                    self.threads[LEAD] = {"status": lead}
                    self.threads["thread:delegated-task:kid12345"] = {"status": "running"}
                    def state(items):
                        items = [i.replace("agent: \n", f"agent: {agent}\n", 1) if "id: T1\n" in i else i for i in items]
                        return tr.continuity(self.room(items), yielding)
                    a, b = state(quiet), state(loud)
                    self.assertEqual(a[0], b[0], (yielding, lead, agent))
        # and the stall warning appears exactly when it did before
        self.threads[LEAD] = {"status": "idle"}
        self.assertEqual(tr.continuity(self.room(loud), True)[0], "stalled")

    # nudges






    def test_state_json_fields(self):
        j = tr.attention_json(self.room([item("T1", "review", since_min=250)]))
        self.assertTrue(j["attention_loud"])
        self.assertEqual(j["attention"][0]["rule"], "review-late")


if __name__ == "__main__":
    unittest.main()


class StateSinceDates(unittest.TestCase):
    """Log lines carry HH:MMZ only; dates are rebuilt walking forward from `created:`."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (tr.ROOMS, tr.now)
        tr.ROOMS = Path(self.tmp.name) / "rooms"
        self._canonical_root_before = tr.ROOT
        tr.ROOT = tr.ROOMS.parent
        self.addCleanup(setattr, tr, "ROOT", self._canonical_root_before)
        tr.now = lambda: NOW
        d = tr.ROOMS / "r1"
        (d / "items").mkdir(parents=True)
        (d / "decisions").mkdir()
        (d / "BRIEF.md").write_text(f"---\ntitle: t\nlead_thread: {LEAD}\n---\n")
        self.d = d

    def tearDown(self):
        (tr.ROOMS, tr.now) = self.saved
        self.tmp.cleanup()

    def since(self, head, log, state="doing"):
        (self.d / "items" / "T1-x.md").write_text(
            f"---\nid: T1\ntitle: x\nstate: {state}\nowner: dev\ncap_h: 5\n{head}---\n## Log\n{log}\n## Result\n")
        return tr.state_since(tr.Room("r1").items[0], state)

    def utc(self, *a):
        return dt.datetime(*a, tzinfo=dt.timezone.utc)

    def test_stale_updated_does_not_inflate(self):
        # a stale `updated:` case: created 04:43Z, doing 20:04Z and 20:08Z, updated left at 04:43Z, now 21:44Z
        now = self.utc(2026, 10, 27, 21, 44)
        tr.now = lambda: now
        log = "- 04:43Z A: created\n- 20:04Z A: set state=doing cap_h=5\n- 20:08Z A: set state=doing\n"
        for upd in ("2026-10-27T04:43Z", "2026-10-27T20:08Z"):
            t = self.since(f"created: 2026-10-27T04:43Z\nupdated: {upd}\n", log)
            self.assertEqual(t, self.utc(2026, 10, 27, 20, 8))
            self.assertEqual((now - t).total_seconds() / 60, 96)

    def test_overrun_rule_does_not_fire_when_updated_is_stale(self):
        now = self.utc(2026, 10, 27, 21, 44)
        tr.now = lambda: now
        self.since("created: 2026-10-27T04:43Z\nupdated: 2026-10-27T04:43Z\n",
                   "- 04:43Z A: created\n- 20:04Z A: set state=doing cap_h=5\n- 20:08Z A: set state=doing\n")
        self.assertEqual([b["rule"] for b in tr.bottlenecks(tr.Room("r1"), now)], [])

    def test_midnight_gets_two_dates(self):
        log = "- 23:50Z A: created\n- 23:55Z A: set state=doing\n- 00:10Z A: set state=review\n"
        head = "created: 2026-10-26T23:50Z\nupdated: 2026-10-26T23:50Z\n"
        self.assertEqual(self.since(head, log, "doing"), self.utc(2026, 10, 26, 23, 55))
        self.assertEqual(self.since(head, log, "review"), self.utc(2026, 10, 27, 0, 10))

    def test_old_log_with_fresh_updated(self):
        log = "- 08:00Z A: created\n- 09:00Z A: set state=review\n"
        t = self.since("created: 2026-10-24T08:00Z\nupdated: 2026-10-27T11:00Z\n", log, "review")
        self.assertEqual(t, self.utc(2026, 10, 24, 9, 0))

    def test_stale_updated_does_not_inflate_review_age(self):
        log = "- 08:00Z A: created\n- 10:30Z A: set state=review\n"
        r = [b["rule"] for b in tr.bottlenecks(self._room("created: 2026-10-27T08:00Z\nupdated: 2026-10-27T08:00Z\n", log, "review"), NOW)]
        self.assertEqual(r, ["review-stale"])  # 90 min, not late (>180)

    def _room(self, head, log, state):
        self.since(head, log, state)
        return tr.Room("r1")

    def test_created_absent_falls_back_to_updated(self):
        log = "- 06:00Z A: created\n- 11:00Z A: set state=doing\n"
        t = self.since("updated: 2026-10-27T11:30Z\n", log)
        self.assertEqual(t, self.utc(2026, 10, 27, 11, 0))
        self.assertLessEqual(t, NOW)

    def test_anchor_seconds_do_not_push_the_log_back_a_day(self):
        # no created:, anchor with seconds (a commit time); last Log line is this minute, now is a few seconds into it
        now = self.utc(2026, 11, 2, 13, 3, 10)
        tr.now = lambda: now
        log = "- 12:47Z A: created\n- 12:59Z A: set state=doing\n- 13:03Z A: set state=doing\n"
        t = self.since("updated: 2026-11-02T13:03Z\n", log)
        self.assertEqual(t, self.utc(2026, 11, 2, 13, 3))
        self.assertEqual([b["rule"] for b in tr.bottlenecks(tr.Room("r1"), now)], [])

    def test_line_a_minute_ahead_of_now_is_skew_not_yesterday(self):
        now = self.utc(2026, 11, 2, 13, 2, 30)
        tr.now = lambda: now
        t = self.since("updated: 2026-11-02T12:47Z\n", "- 12:47Z A: created\n- 13:04Z A: set state=doing\n")
        self.assertEqual(t, now)

    def test_never_after_now(self):
        log = "- 23:30Z A: set state=doing\n- 11:59Z A: still going\n"
        t = self.since("updated: 2026-10-27T11:59Z\n", log)
        self.assertEqual(t, self.utc(2026, 10, 26, 23, 30))
