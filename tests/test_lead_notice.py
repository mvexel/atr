"""Telling the lead: save first, one send, a marker on failure, one retry after 60 s, then the flag stays."""
import argparse, contextlib, importlib.machinery, importlib.util, io, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)
LEAD = "lead-thread-0001"
DECISION = ("---\nid: D01\ntitle: Pick one\ntype: decision\ndoor: two\ndecider: owner\nstatus: open\nblocks: []\n"
            "created: 2026-01-01T00:00Z\nupdated: 2026-01-01T00:00Z\n---\n## Options\na) yes\nb) no\n\n## Answer\n")


class LeadNotice(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.calls, self.accept, self.info = [], True, {}

        def t3_call(kind, target, payload, options=None):
            self.calls.append((kind, target, payload))
            return {"ok": self.accept, "evidence": "ok" if self.accept else "T3 exited unsuccessfully: boom", "thread": None}
        for c in (patch.object(tr, "ROOT", self.root), patch.object(tr, "ROOMS", self.root / "rooms"),
                  patch.object(tr, "t3_call", side_effect=t3_call),
                  patch.object(tr, "thread_info", side_effect=lambda th: self.info)):
            c.start()
            self.addCleanup(c.stop)
        d = self.root / "rooms/demo"
        (d / "decisions").mkdir(parents=True)
        (d / "items").mkdir()
        (d / "BRIEF.md").write_text(f"---\ntitle: Demo\nlead_thread: {LEAD}\n---\n")
        (d / "decisions/D01-pick.md").write_text(DECISION)

    def answer(self):
        return tr.web_answer(tr.Room("demo"), "D01", "a", "", False)

    def flag(self):
        return tr.read_lead_flag("demo")

    def log(self):
        p = self.root / "rooms/demo/pings.log"
        return p.read_text() if p.exists() else ""

    def test_success_sends_once_logs_sent_and_sets_no_marker(self):
        self.assertTrue(self.answer()["ok"])
        self.assertEqual([c[:2] for c in self.calls], [("message", LEAD)])
        self.assertIn("D01", self.calls[0][2])
        self.assertIsNone(self.flag())
        self.assertIn("sent", self.log())

    def test_success_clears_nothing(self):
        tr._flag_lead("demo", LEAD, "older", "room paused", False)
        self.answer()
        self.assertEqual(self.flag()["text"], "older")

    def test_answer_is_saved_even_when_t3_fails(self):
        self.accept = False
        self.assertTrue(self.answer()["ok"])
        d = tr.Room("demo").find("D01")
        self.assertEqual(d["status"], "final")
        self.assertIn("a · owner", d.section("Answer"))
        self.assertEqual(len(self.calls), 1)

    def test_failure_sets_marker_and_logs(self):
        self.accept = False
        self.answer()
        f = self.flag()
        self.assertEqual((f["retryable"], f["retried"], f["thread"]), (True, False, LEAD))
        self.assertIn("boom", f["reason"])
        self.assertIn("D01", f["text"])
        self.assertIn("not-notified", self.log())

    def test_one_retry_after_60_seconds_then_the_flag_stays(self):
        self.accept = False
        self.answer()
        since = self.flag()["since_epoch"]
        tr.retry_lead_flags(since + 59)
        self.assertEqual(len(self.calls), 1)               # too early
        tr.retry_lead_flags(since + 60)
        self.assertEqual(len(self.calls), 2)               # the one retry, same text
        self.assertEqual(self.calls[1][2], self.calls[0][2])
        f = self.flag()
        self.assertTrue(f["retried"])
        self.assertIn("retry", f["reason"])
        for later in (since + 61, since + 600, since + 86400):
            tr.retry_lead_flags(later)
        self.assertEqual(len(self.calls), 2)               # never a third attempt
        self.assertIsNotNone(self.flag())

    def test_successful_retry_clears_the_marker(self):
        self.accept = False
        self.answer()
        since = self.flag()["since_epoch"]
        self.accept = True
        tr.retry_lead_flags(since + 60)
        self.assertIsNone(self.flag())
        self.assertIn("sent (retry)", self.log())

    def test_paused_room_is_flagged_and_not_sent(self):
        (self.root / "rooms/demo/BRIEF.md").write_text(f"---\ntitle: Demo\nlead_thread: {LEAD}\npaused: 2026-01-01T00:00Z\n---\n")
        self.assertTrue(self.answer()["ok"])
        self.assertEqual(self.calls, [])
        f = self.flag()
        self.assertIn("paused", f["reason"])
        self.assertFalse(f["retryable"])
        tr.retry_lead_flags(f["since_epoch"] + 1000)
        self.assertEqual(self.calls, [])

    def test_pause_notice_itself_is_sent_while_paused(self):
        (self.root / "rooms/demo/BRIEF.md").write_text(f"---\ntitle: Demo\nlead_thread: {LEAD}\npaused: 2026-01-01T00:00Z\n---\n")
        tr.notify_lead(tr.Room("demo"), "paused", allow_paused=True)
        self.assertEqual(len(self.calls), 1)

    def test_settled_lead_is_flagged_not_woken(self):
        self.info = {"settled": True}
        self.answer()
        self.assertEqual(self.calls, [])
        self.assertIn("settled", self.flag()["reason"])
        self.assertIn("not-notified", self.log())

    def test_inbox_shows_the_unsent_message_and_clears_the_marker(self):
        self.accept = False
        self.answer()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tr.cmd_inbox(argparse.Namespace(room="demo"))
        self.assertIn("Not delivered to you", out.getvalue())
        self.assertIn("D01", out.getvalue())
        self.assertIsNone(self.flag())

    def test_room_json_carries_the_flag(self):
        self.accept = False
        self.answer()
        self.assertEqual(tr.room_json(tr.Room("demo"))["lead_flag"]["retryable"], True)


class T3Call(unittest.TestCase):
    def run_call(self, **result):
        out = type("R", (), {"returncode": 0, "stdout": "", "stderr": "", **result})
        with patch.object(tr, "_external_run", return_value=out) as run, patch.object(tr, "t3_cli", return_value="t3"):
            return tr.t3_call("message", "thr", "hi"), run

    def test_message_uses_thread_send_and_accepts_a_response(self):
        r, run = self.run_call(stdout='{"ok": true}')
        self.assertTrue(r["ok"])
        self.assertEqual(run.call_args[0][0][:4], ["t3", "thread", "send", "thr"])

    def test_launch_uses_thread_start_and_returns_the_thread(self):
        out = type("R", (), {"returncode": 0, "stdout": '{"thread":{"threadId":"new-1"}}', "stderr": ""})
        with patch.object(tr, "_external_run", return_value=out) as run, patch.object(tr, "t3_cli", return_value="t3"):
            r = tr.t3_call("launch", "/proj", "go", {"title": "T"})
        self.assertEqual((r["ok"], r["thread"]), (True, "new-1"))
        self.assertEqual(run.call_args[0][0][:4], ["t3", "thread", "start", "/proj"])
        self.assertIn("--title", run.call_args[0][0])

    def test_nonzero_exit_and_empty_response_are_not_accepted(self):
        self.assertFalse(self.run_call(returncode=1, stderr="nope")[0]["ok"])
        self.assertFalse(self.run_call(stdout="")[0]["ok"])


if __name__ == "__main__":
    unittest.main()
