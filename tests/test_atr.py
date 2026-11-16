"""Tests for the plan operations, the lead's commands and the page's API. Run: python3 -m unittest discover tests"""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "bin/atr"
loader = importlib.machinery.SourceFileLoader("atr", str(SOURCE))
atr = importlib.util.module_from_spec(importlib.util.spec_from_loader("atr", loader))
loader.exec_module(atr)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = {
            k: os.environ.get(k) for k in ("ATR_DATA_DIR", "ATR_PROJECT", "ATR_AS")
        }
        os.environ.update(ATR_DATA_DIR=self.tmp.name, ATR_PROJECT="demo")
        os.environ.pop("ATR_AS", None)
        self.addCleanup(
            lambda: [
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                for k, v in self.old.items()
            ]
        )
        cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, cwd)
        self.cli("init", "demo", "Demo")
        self.you("goal_add", title="Sign in", done_when="it works")

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = atr.main(list(args)) or 0
        return code, out.getvalue() + err.getvalue()

    def you(self, op, **args):
        return atr.change("demo", "you", atr.OPS[op], args)[0]

    def agent(self, op, **args):
        return atr.change("demo", "agent", atr.OPS[op], args)[0]

    def task(self, ident):
        return atr.get(atr.load("demo"), "tasks", ident)


class Plan(Base):
    def test_task_needs_an_accepted_goal(self):
        self.assertEqual(self.cli("task", "add", "G9", "x")[0], 2)
        self.cli("goal", "propose", "Recovery", "--done", "x")
        code, out = self.cli("task", "add", "G2", "x")
        self.assertEqual(code, 2)
        self.assertIn("only proposed", out)
        self.you("goal_accept", id="G2")
        self.assertEqual(self.cli("task", "add", "G2", "x")[0], 0)

    def test_agents_cannot_touch_goals(self):
        self.assertEqual(self.cli("goal", "add", "Mine")[0], 2)
        for op, args in (
            ("goal_edit", {"id": "G1", "title": "x"}),
            ("goal_remove", {"id": "G1"}),
            ("goal_accept", {"id": "G1"}),
        ):
            with self.assertRaises(atr.Refused):
                self.agent(op, **args)
        self.assertTrue(
            self.agent("goal_add", title="Proposed")["goals"][-1]["proposed"]
        )

    def test_start_waits_for_dependencies_and_loops_are_refused(self):
        self.cli("task", "add", "G1", "first")
        self.cli("task", "add", "G1", "second", "--after", "T1")
        self.assertEqual(self.cli("task", "set", "T2", "status=doing")[0], 2)
        with self.assertRaises(atr.Refused):
            self.you("dep", id="T1", other="T2")
        self.cli("task", "set", "T1", "status=done")
        self.assertEqual(self.cli("task", "set", "T2", "status=doing")[0], 0)

    def test_next_caps_running_and_puts_the_most_depended_on_first(self):
        for title in ("a", "b", "c", "d"):
            self.cli("task", "add", "G1", title)
        self.cli("task", "add", "G1", "needs d", "--after", "T4")
        self.assertEqual(
            [t["id"] for t in atr.ready(atr.load("demo"))], ["T4", "T1", "T2"]
        )
        self.cli("task", "set", "T1", "status=doing")
        self.cli("task", "set", "T2", "status=doing")
        self.assertEqual([t["id"] for t in atr.ready(atr.load("demo"))], ["T4"])

    def test_easy_call_continues_and_hard_call_blocks_until_answered(self):
        self.cli("task", "add", "G1", "build")
        self.cli("task", "set", "T1", "status=doing")
        self.cli("decide", "T1", "library A", "--rejected", "library B")
        self.assertEqual(self.task("T1")["status"], "doing")
        self.assertEqual(atr.load("demo")["decisions"][0]["state"], "to_review")
        self.cli("decide", "T1", "new table", "--hard", "--rejected", "new column")
        self.assertEqual(self.task("T1")["status"], "blocked")
        self.cli(
            "task", "set", "T1", "status=todo"
        )  # an agent cannot route around the card
        self.assertEqual(self.cli("task", "set", "T1", "status=doing")[0], 2)
        plan = self.you("answer", id="D2", choice="new column")
        d = atr.get(plan, "decisions", "D2")
        self.assertEqual(
            (d["state"], d["chosen"], d["rejected"]),
            ("accepted", "new column", ["new table"]),
        )
        self.assertEqual(self.cli("task", "set", "T1", "status=doing")[0], 0)

    def test_answer_restores_the_status_the_card_interrupted(self):
        self.cli("task", "add", "G1", "build")
        self.cli("task", "set", "T1", "status=doing")
        self.cli("decide", "T1", "x", "--hard")
        self.assertEqual(
            self.you("answer", id="D1", choice="x")["tasks"][0]["status"], "doing"
        )

    def test_the_lead_sees_which_of_its_calls_the_owner_reviewed(self):
        self.cli("decide", "project", "use sqlite")
        self.cli("decide", "project", "use tabs")
        self.you("review", id="D1", verdict="accept")
        out = self.cli("read")[1]
        self.assertIn("D1 project: use sqlite", out)
        self.assertIn("D2 project: (not reviewed yet) use tabs", out)

    def test_overturn_and_rejections_reach_the_lead(self):
        self.cli("task", "add", "G1", "build")
        self.cli("decide", "T1", "library A", "--rejected", "library B")
        self.cli("read")
        self.you("review", id="D1", verdict="overturn", note="use C")
        out = self.cli("read")[1]
        self.assertIn("OVERTURNED D1", out)
        self.assertIn("rejected: library B", out)

    def test_pruning_a_running_task_holds_until_the_lead_stops_it(self):
        self.cli("task", "add", "G1", "build")
        self.cli("task", "set", "T1", "status=doing")
        self.assertFalse(
            self.you("task_prune", id="T1", mode="drop")["tasks"][0]["stopped"]
        )
        code, out = self.cli("task", "set", "T1", "status=doing")
        self.assertEqual(code, 2)
        self.assertIn("atr task stopped T1", out)
        self.assertIn("STOP THESE", self.cli("read")[1])
        self.cli("task", "stopped", "T1", "branch", "kept")
        self.assertTrue(self.task("T1")["stopped"])
        self.assertEqual(
            self.you("task_restore", id="T1")["tasks"][0]["status"], "todo"
        )

    def test_read_shows_owner_changes_once_and_unread_reports_them(self):
        self.assertEqual(self.cli("unread")[0], 0)  # the goal added in setUp
        self.assertIn("THE OWNER CHANGED", self.cli("read", "--peek")[1])
        self.assertEqual(self.cli("unread")[0], 0)  # peek does not mark
        self.cli("read")
        self.assertEqual(self.cli("unread")[0], 1)
        self.assertNotIn("THE OWNER CHANGED", self.cli("read")[1])
        self.cli(
            "task", "add", "G1", "agent work"
        )  # the agent's own changes are not news to it
        self.assertEqual(self.cli("unread")[0], 1)

    def test_lead_adds_dependencies_to_an_existing_task(self):
        for title in ("a", "b", "c"):
            self.cli("task", "add", "G1", title)
        code, out = self.cli("task", "set", "T3", "after=T1,T2")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T3")["after"], ["T1", "T2"])
        self.assertEqual(self.cli("task", "set", "T1", "--after", "T3")[0], 2)  # loop
        self.assertEqual(
            self.cli("task", "set", "T3", "after=T1")[1].strip(), "no change"
        )

    def test_owner_said_decision_is_the_owners_but_not_news_to_the_lead(self):
        self.cli("task", "add", "G1", "x")
        self.cli("read")
        code, out = self.cli("decide", "project", "audio comes from the Mac", "--owner")
        self.assertEqual(code, 0, out)
        d = atr.load("demo")["decisions"][-1]
        self.assertEqual((d["by"], d["state"]), ("you", "accepted"))
        self.assertEqual(self.cli("unread")[0], 1)
        self.assertEqual(self.cli("decide", "T1", "x", "--owner", "--hard")[0], 2)

    def test_wait_returns_owner_changes_and_times_out_without_them(self):
        code, out = self.cli(
            "wait", "--json"
        )  # the goal added in setUp is already unread
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out)["unread"][0]["what"], 'added goal G1 "Sign in"'
        )
        self.cli("read")
        self.assertEqual(self.cli("wait", "--timeout", "0")[0], 1)

    def test_a_running_wait_shows_the_lead_is_listening_until_the_owner_acts(self):
        self.cli("read")
        got = []
        th = threading.Thread(target=lambda: got.append(atr.wait("demo", 10)))
        th.start()
        for _ in range(50):
            if atr.waiting("demo"):
                break
            threading.Event().wait(0.05)
        self.assertTrue(atr.waiting("demo"))
        self.assertIn('"lead_waiting": true', self.cli("unread", "--json")[1])
        self.agent(
            "task_add", goal="G1", title="the lead's own change"
        )  # does not wake the lead
        self.you("goal_add", title="Recovery")
        th.join(5)
        self.assertEqual([c["what"] for c in got[0]], ['added goal G2 "Recovery"'])
        self.assertFalse(atr.waiting("demo"))

    def test_now_line_shows_progress_only_while_a_task_runs(self):
        self.cli("task", "add", "G1", "detector")
        self.assertEqual(self.cli("now", "T1", "warming up")[0], 2)  # not running yet
        self.cli("task", "set", "T1", "status=doing")
        self.assertTrue(self.task("T1")["doing_since"])
        code, out = self.cli("now", "T1", "scoring", "run", "2")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task("T1")["now"], "scoring run 2")
        self.assertIn("now: scoring run 2", self.cli("read")[1])
        self.assertEqual(self.cli("unread")[0], 1)  # progress is not owner news
        self.cli("task", "set", "T1", "status=done")
        self.assertNotIn("now", self.task("T1"))

    def test_owner_work_is_never_offered_to_the_lead(self):
        self.cli("task", "add", "G1", "record an hour of TV")
        self.cli("task", "add", "G1", "write the scorer")
        self.cli("task", "set", "T1", "owner=you")
        self.assertEqual([t["id"] for t in atr.ready(atr.load("demo"))], ["T2"])
        self.assertIn("THE OWNER'S TURN", self.cli("read")[1])

    def test_move_reorders_and_changes_goal(self):
        self.you("goal_add", title="Second")
        for title in ("a", "b"):
            self.cli("task", "add", "G1", title)
        self.cli("task", "add", "G2", "c")
        plan = self.you("task_move", id="T3", goal="G1", before="T1")
        self.assertEqual(
            [(t["id"], t["goal"]) for t in plan["tasks"]],
            [("T3", "G1"), ("T1", "G1"), ("T2", "G1")],
        )
        plan = self.you("task_move", id="T3", goal="G2")
        self.assertEqual(plan["tasks"][-1]["id"], "T3")
        with self.assertRaises(atr.Refused):
            self.agent("task_move", id="T1", goal="G2")

    def test_agree_sets_the_baseline_for_new_tasks(self):
        self.cli("task", "add", "G1", "planned")
        self.you("agree")
        self.cli("task", "add", "G1", "drift")
        self.assertEqual(
            [t.get("agreed") for t in atr.load("demo")["tasks"]], [True, False]
        )

    def test_finished_tasks_are_not_counted_as_new(self):
        self.cli("task", "add", "G1", "done already")
        self.cli("task", "add", "G1", "still open")
        self.cli("task", "set", "T1", "status=done")
        plan = atr.change("demo", "you", atr.OPS["agree"], {})[1]
        self.assertEqual(plan, "agreed the plan as it stands (1 new open task)")
        self.assertTrue(all(t["agreed"] for t in atr.load("demo")["tasks"]))

    def test_attach_copies_the_file_into_the_project(self):
        Path("findings.md").write_text("# found\n")
        self.cli("task", "add", "G1", "build")
        self.cli("attach", "T1", "findings.md")
        self.cli("attach", "G1", "https://example.com/pr/1", "--title", "PR 1")
        Path("findings.md").unlink()
        docs = atr.load("demo")["docs"]
        self.assertEqual(
            (Path(self.tmp.name) / "demo/docs" / docs[0]["file"]).read_text(),
            "# found\n",
        )
        self.assertEqual(docs[1]["url"], "https://example.com/pr/1")
        self.assertEqual(self.cli("attach", "T1", "missing.md")[0], 2)

    def test_pointer_file_selects_the_project(self):
        os.environ.pop("ATR_PROJECT")
        self.assertEqual(Path(".atr").read_text().strip(), "demo")
        self.assertEqual(self.cli("next")[0], 0)
        Path(".atr").unlink()
        self.assertEqual(self.cli("next")[0], 2)

    def test_a_lead_written_done_test_stays_a_guess_until_the_owner_confirms(self):
        self.cli("goal", "propose", "Mute ads", "--done", "edges within 5 s")
        self.cli("goal", "propose", "Record", "--done", "a file plays")
        self.assertTrue(atr.get(atr.load("demo"), "goals", "G2")["test_guess"])
        self.you("goal_accept", id="G2")  # accepting the goal is not accepting its test
        self.assertIn("YOUR GUESS", self.cli("read")[1])
        with self.assertRaises(atr.Refused):
            self.agent("goal_confirm_test", id="G2")
        self.you("goal_confirm_test", id="G2")
        self.you("goal_accept", id="G3", test=True)
        self.you("goal_edit", id="G1", done_when="sign-in works")  # the owner's own words
        self.assertNotIn("YOUR GUESS", self.cli("read")[1])

    def test_a_card_on_a_goal_holds_that_goals_tasks(self):
        self.cli("task", "add", "G1", "build it")
        self.cli("decide", "G1", "go on-device", "--hard", "--question", "where does it run?")
        self.assertEqual(atr.ready(atr.load("demo")), [])
        self.assertEqual(self.cli("task", "set", "T1", "status=doing")[0], 2)
        self.you("answer", id="D1", choice="go on-device")
        self.assertEqual([t["id"] for t in atr.ready(atr.load("demo"))], ["T1"])

    def test_a_goal_out_of_tries_holds_until_the_owner_says_how_it_goes_on(self):
        self.cli("goal", "propose", "Detect ads", "--done", "x", "--tries", "2")
        self.you("goal_accept", id="G2")
        self.cli("task", "add", "G2", "tune")
        self.cli("try", "G2", "prompt A: 12 of 33")
        self.you("goal_edit", id="G2", title="Detect ads well", tries=2)  # same budget: not a reset
        self.cli("try", "G2", "prompt B: 15 of 31")
        self.assertEqual(atr.ready(atr.load("demo")), [])
        self.assertEqual(self.cli("task", "set", "T1", "status=doing")[0], 2)
        self.assertIn("OUT OF BUDGET", self.cli("read")[1])
        self.cli("decide", "G2", "change the method", "--hard", "--rejected", "keep going")
        self.assertNotIn("OUT OF BUDGET", self.cli("read")[1])  # asked already
        self.you("answer", id="D1", choice="change the method")
        self.assertEqual([t["id"] for t in atr.ready(atr.load("demo"))], ["T1"])
        self.assertEqual(atr.get(atr.load("demo"), "goals", "G2")["budget"]["used"], 0)

    def test_a_goal_out_of_days_holds(self):
        self.you("goal_edit", id="G1", days=1)
        self.cli("task", "add", "G1", "x")
        def backdate(plan, by, a):
            plan["goals"][0]["budget"]["from"] = "2020-01-01T00:00Z"
            return "backdated"
        atr.change("demo", "agent", backdate)
        self.assertEqual(atr.ready(atr.load("demo")), [])
        self.you("goal_edit", id="G1", days=0)  # the owner lifts the limit
        self.assertNotIn("budget", atr.get(atr.load("demo"), "goals", "G1"))

    def test_the_lead_keeps_an_outlook_per_goal(self):
        self.cli("task", "add", "G1", "x")
        self.assertIn("no outlook yet", self.cli("read")[1])
        self.assertEqual(self.cli("outlook", "G1", "maybe", "x")[0], 2)
        code, out = self.cli("outlook", "G1", "unlikely", "catches", "half")
        self.assertEqual(code, 0, out)
        self.assertIn("your outlook", self.cli("read")[1])
        self.assertEqual(atr.load("demo")["goals"][0]["outlook"]["level"], "unlikely")

    def test_workers_record_their_own_calls_for_the_lead_to_check(self):
        self.cli("task", "add", "G1", "x")
        self.cli("read")
        code, out = self.cli("decide", "T1", "use AAC", "--why", "small", "--by", "w1")
        self.assertEqual(code, 0, out)
        d = atr.load("demo")["decisions"][0]
        self.assertEqual((d["by"], d["state"]), ("worker:w1", "to_review"))
        self.assertEqual(self.cli("unread")[0], 1)  # not owner news
        self.assertIn("FROM YOUR WORKERS", self.cli("read")[1])
        self.assertNotIn("FROM YOUR WORKERS", self.cli("read")[1])  # once
        self.assertEqual(self.cli("decide", "T1", "x", "--by", "W 1")[0], 2)


class Web(Base):
    def setUp(self):
        super().setUp()
        atr.Handler.allowed_hosts = {"127.0.0.1", "localhost"}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), atr.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def call(self, path, body=None, headers=None):
        headers = (
            {"Content-Type": "application/json", "X-Atr": "1"}
            if headers is None
            else headers
        )
        req = urllib.request.Request(
            self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_page_edits_are_owner_edits_and_stale_ones_are_refused(self):
        rev = self.call("/api/p/demo")[1]["plan"]["rev"]
        self.assertEqual(
            self.call(
                "/api/p/demo",
                {
                    "op": "task_add",
                    "rev": rev,
                    "args": {"goal": "G1", "title": "from page"},
                },
            )[0],
            200,
        )
        self.assertEqual(self.task("T1")["added_by"], "you")
        code, body = self.call(
            "/api/p/demo",
            {"op": "task_add", "rev": rev, "args": {"goal": "G1", "title": "late"}},
        )
        self.assertEqual((code, body["stale"]), (409, True))
        self.assertEqual(len(atr.load("demo")["tasks"]), 1)

    def test_posts_need_the_header_and_a_known_host_and_op(self):
        body = {"op": "goal_add", "rev": 1, "args": {"title": "x"}}
        self.assertEqual(
            self.call("/api/p/demo", body, {"Content-Type": "application/json"})[0], 403
        )
        self.assertEqual(
            self.call("/api/projects", headers={"Host": "evil.example"})[0], 403
        )
        self.assertEqual(
            self.call(
                "/api/p/demo",
                {"op": "attach", "rev": 1, "args": {"on": "G1", "src": "/etc/hosts"}},
            )[0],
            404,
        )
        self.assertEqual(
            self.call(
                "/api/p/demo",
                {"op": "answer", "rev": 1, "args": {"id": "D9", "choice": "x"}},
            )[0],
            400,
        )

    def test_signature_changes_when_the_lead_reads(self):
        before = self.call("/api/sig")[1]["demo"]
        self.cli("read")
        self.assertNotEqual(before, self.call("/api/sig")[1]["demo"])
        self.assertEqual(self.call("/api/projects")[1][0]["unread"], 0)

    def test_documents_are_served_as_text(self):
        Path("notes.md").write_text("hello")
        self.cli("attach", "G1", "notes.md")
        self.assertEqual(self.call("/api/doc/demo/A1")[1]["text"], "hello")
        self.assertEqual(self.call("/api/doc/demo/A9")[0], 404)


class ClaudeCodeExtension(Base):
    HOOK = SOURCE.parent.parent / "extensions/claude-code/hooks/atr_hook.py"

    def hook(self, event, cwd=None, **payload):
        env = {**os.environ, "ATR_BIN": str(SOURCE)}
        r = subprocess.run(
            [sys.executable, str(self.HOOK), event],
            input=json.dumps({"cwd": cwd or self.tmp.name, **payload}),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_turn_start_shows_owner_changes_once(self):
        self.assertIn("THE OWNER CHANGED", self.hook("prompt"))
        self.assertEqual(self.hook("prompt"), "")

    def test_session_start_gives_the_plan_and_asks_for_the_doorbell(self):
        out = self.hook("session-start")
        self.assertIn("G1 Sign in", out)
        self.assertIn("atr wait", out)

    def test_turn_end_holds_for_unread_changes_then_for_the_doorbell(self):
        self.assertIn("atr read", json.loads(self.hook("stop"))["reason"])
        self.cli("read")
        self.assertIn("atr wait", json.loads(self.hook("stop"))["reason"])
        self.assertEqual(self.hook("stop", stop_hook_active=True), "")
        th = threading.Thread(target=atr.wait, args=("demo", 10))
        th.start()
        for _ in range(50):
            if atr.waiting("demo"):
                break
            threading.Event().wait(0.05)
        self.assertEqual(self.hook("stop"), "")  # armed: the turn may end
        self.you("goal_add", title="wake up")
        th.join(5)

    def test_silent_outside_an_atr_project(self):
        os.environ.pop("ATR_PROJECT")
        with tempfile.TemporaryDirectory() as elsewhere:
            for event in ("session-start", "prompt", "stop"):
                self.assertEqual(self.hook(event, cwd=elsewhere), "")


if __name__ == "__main__":
    unittest.main()
