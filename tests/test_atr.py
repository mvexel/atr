"""Tests for the plan operations, the lead's commands and the page's API. Run: python3 -m unittest discover tests"""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "bin/atr"  # the checkout launcher
CODE = ROOT / "src/atr/cli.py"
loader = importlib.machinery.SourceFileLoader("atr", str(CODE))
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
        atr.ALIVE.clear()
        self.addCleanup(
            lambda: [
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                for k, v in self.old.items()
            ]
        )
        cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, cwd)
        self.cli("init", "demo", "Demo", "--lead", "none")
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
    providers = staticmethod(atr.lead_providers)

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
        self.assertEqual((d["by"], d["state"], d["said"]), ("you", "to_review", True))
        self.assertIn("said this in chat; not confirmed", self.cli("read")[1])
        self.assertEqual(self.cli("unread")[0], 1)
        self.you("review", id=d["id"], verdict="accept")
        self.assertIn("confirmed D1", self.cli("read")[1])
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

    def test_install_links_atr_onto_the_path(self):
        bindir = Path(self.tmp.name) / "bin"
        code, out = self.cli("install", "--dir", str(bindir))
        self.assertEqual(code, 0, out)
        self.assertEqual((bindir / "atr").resolve(), SOURCE.resolve())
        provider = ROOT / "extensions/claude-code/bin/atr-lead-claude-code"
        self.assertEqual((bindir / provider.name).resolve(), provider.resolve())  # lead providers come along
        self.assertIn("not on your PATH", out)
        self.assertIn("already points", self.cli("install", "--dir", str(bindir))[1])
        (bindir / "atr").unlink()
        (bindir / "atr").write_text("someone else's")
        self.assertEqual(self.cli("install", "--dir", str(bindir))[0], 2)

    def test_the_lead_is_told_when_it_works_from_another_folder(self):
        self.assertNotIn("NOTE: you are in", self.cli("read")[1])
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        os.chdir(elsewhere.name)
        self.assertIn("NOTE: you are in", self.cli("read")[1])

    def test_a_plain_question_has_no_recommendation_and_holds_the_task(self):
        self.cli("task", "add", "G1", "detector")
        code, out = self.cli("ask", "T1", "What do you watch with ads?", "--option", "cable", "--option", "streaming")
        self.assertEqual(code, 0, out)
        d = atr.load("demo")["decisions"][0]
        self.assertEqual((d["recommended"], d["options"], d["state"]), ("", ["cable", "streaming"], "needs_you"))
        self.assertEqual(self.task("T1")["status"], "blocked")
        self.you("answer", id="D1", choice="streaming in the browser")
        self.assertEqual(self.task("T1")["status"], "todo")
        self.assertEqual(self.cli("ask", "T1", "")[0], 2)

    def test_a_task_in_review_counts_only_once_the_owner_checks_it(self):
        self.cli("task", "add", "G1", "mark the test set")
        self.cli("task", "add", "G1", "score it", "--after", "T1")
        self.assertEqual(self.cli("task", "set", "T1", "status=review")[0], 2)  # needs what to check
        self.cli("task", "set", "T1", "status=review", "note=check the break edges")
        self.assertIn("THE OWNER'S TURN", self.cli("read")[1])
        self.assertEqual(self.cli("task", "set", "T1", "status=done")[0], 2)
        self.assertEqual([t["id"] for t in atr.ready(atr.load("demo"))], [])
        self.you("task_check", id="T1", note="break 2 ends at 6:20")
        self.assertEqual(self.task("T1")["status"], "todo")
        self.cli("task", "set", "T1", "status=review")
        self.you("task_check", id="T1", ok=True)
        self.assertEqual([t["id"] for t in atr.ready(atr.load("demo"))], ["T2"])

    def test_a_task_is_not_done_while_its_decisions_wait_for_review(self):
        self.cli("task", "add", "G1", "plan it")
        self.cli("task", "add", "G1", "build", "--after", "T1")
        self.cli("decide", "T1", "spike two paths")
        self.cli("decide", "T1", "stdlib only")
        self.cli("task", "set", "T1", "status=done")
        self.assertEqual((self.task("T1")["status"], self.task("T1")["note"]), ("review", "review D1, D2"))
        self.you("review", id="D1", verdict="accept")
        self.assertEqual(self.task("T1")["status"], "review")
        self.you("review", id="D2", verdict="accept")
        self.assertEqual(self.task("T1")["status"], "done")
        self.assertEqual([t["id"] for t in atr.ready(atr.load("demo"))], ["T2"])

    def test_owner_changes_carry_the_action_as_data(self):
        self.cli("task", "add", "G1", "build")
        self.cli("decide", "T1", "which db?", "--hard")
        self.cli("read")
        self.you("answer", id="D1", choice="sqlite", note="keep it local")
        code, out = self.cli("unread", "--json")
        (c,) = json.loads(out)["unread"]
        self.assertEqual((c["op"], c["args"]), ("answer", {"id": "D1", "choice": "sqlite", "note": "keep it local"}))
        lead = [c for c in atr.load("demo")["changes"] if c["by"] != "you"]
        self.assertTrue(lead and not any("op" in c for c in lead))  # the lead's own changes stay as they were

    def test_an_overturned_decision_sends_its_waiting_task_back(self):
        self.cli("task", "add", "G1", "plan it")
        self.cli("decide", "T1", "spike two paths")
        self.cli("task", "set", "T1", "status=done")
        self.you("review", id="D1", verdict="overturn", note="one is enough")
        self.assertEqual(self.task("T1")["status"], "todo")

    def test_a_dropped_task_holds_nothing_back_a_parked_one_does(self):
        self.cli("task", "add", "G1", "spike A")
        self.cli("task", "add", "G1", "spike B")
        self.cli("task", "add", "G1", "build", "--after", "T1", "--after", "T2")
        self.cli("task", "set", "T1", "status=done")
        self.you("task_prune", id="T2", mode="park")
        self.assertEqual([t["id"] for t in atr.ready(atr.load("demo"))], [])
        self.you("task_restore", id="T2")
        self.cli("task", "set", "T2", "status=dropped")
        self.assertEqual([t["id"] for t in atr.ready(atr.load("demo"))], ["T3"])

    def test_parking_with_a_reason_tells_the_lead_why(self):
        self.cli("task", "add", "G1", "later")
        self.cli("read")
        self.you("task_prune", id="T1", mode="park", why="after the trip")
        out = self.cli("read")[1]
        self.assertIn("parked T1 \"later\": after the trip", out)
        self.assertIn("owner's reason: after the trip", out)
        self.you("task_restore", id="T1")
        self.assertNotIn("pruned_why", self.task("T1"))

    def test_one_thread_leads_a_project_and_leads_only_one(self):
        self.assertEqual(self.cli("lead", "--claim", "aaaa-1")[0], 0)
        code, out = self.cli("lead", "--claim", "bbbb-2", "--json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["id"], "aaaa-1")
        self.assertEqual(self.cli("lead", "--claim", "aaaa")[0], 0)  # a short id names the same thread
        self.assertEqual(atr.read_claim("demo")["id"], "aaaa-1")  # and the full id is kept
        self.cli("init", "other", "Other", "--lead", "none")
        code, out = self.cli("-p", "other", "lead", "--claim", "aaaa-1", "--json")
        self.assertEqual((code, json.loads(out)["project"]), (1, "demo"))  # it already leads demo
        self.assertEqual(self.cli("-p", "other", "lead", "--claim", "bbbb-2")[0], 0)

    def test_a_lead_lets_go_at_session_end_or_when_the_owner_says(self):
        self.cli("lead", "--claim", "aaaa-1")
        self.assertIn("does not lead", self.cli("lead", "--release", "bbbb-2")[1])
        self.cli("lead", "--release", "aaaa-1")
        self.assertEqual(self.cli("lead", "--claim", "bbbb-2")[0], 0)
        with self.assertRaises(atr.Refused):
            self.agent("lead_release")  # only the owner takes the lead from a thread
        self.you("lead_release")
        self.assertEqual(atr.read_claim("demo"), {})
        self.assertEqual(self.cli("lead", "--claim", "cccc-3")[0], 0)

    def age_claim(self, seconds, **extra):
        c = {**json.loads(atr.claim_file("demo").read_text()), **extra}
        c["seen"] = time.time() - seconds
        atr.claim_file("demo").write_text(json.dumps(c))

    def test_a_lead_is_gone_after_ten_minutes_without_a_turn_or_a_listener(self):
        atr.lead_providers = dict  # no provider to ask: an unknown thread counts as gone
        self.addCleanup(vars(atr).__setitem__, "lead_providers", type(self).providers)
        self.cli("lead", "--claim", "aaaa-1")
        self.age_claim(atr.GONE_AFTER - 60)
        self.assertEqual(atr.lead_status("demo")["state"], "working")
        self.assertEqual(self.cli("lead", "--claim", "bbbb-2")[0], 1)  # not gone yet
        (Path(self.tmp.name) / "demo/.waiting").write_text(str(os.getpid()))  # its listener is there
        self.age_claim(atr.GONE_AFTER + 60)
        self.assertEqual(atr.lead_status("demo")["state"], "listening")
        (Path(self.tmp.name) / "demo/.waiting").unlink()
        (Path(self.tmp.name) / "demo/.listened").write_text(str(time.time() - 120))  # it listened 2 min ago
        self.assertEqual(atr.lead_status("demo")["state"], "working")
        (Path(self.tmp.name) / "demo/.listened").write_text(str(time.time() - atr.GONE_AFTER - 1))
        st = atr.lead_status("demo")
        self.assertEqual((st["state"], st["why"]), ("gone", "silent"))
        self.assertTrue(atr.summary(atr.load("demo"))["lead_gone"])
        self.assertEqual(self.cli("lead", "--claim", "bbbb-2")[0], 0)  # a gone lead's claim blocks no one

    def test_a_lead_its_tool_says_is_running_is_not_gone(self):
        atr.lead_providers = lambda: {"tool": Path("/x/atr-lead-tool")}
        self.addCleanup(vars(atr).__setitem__, "lead_providers", type(self).providers)
        asked = []
        real = atr.run_provider
        self.addCleanup(vars(atr).__setitem__, "run_provider", real)
        atr.run_provider = lambda name, tool, args, timeout=0: (asked.append(args), (0, ["working"], ""))[1]
        self.cli("lead", "--claim", "aaaa-1")
        self.age_claim(atr.GONE_AFTER + 60)
        self.assertEqual(self.cli("lead", "--claim", "bbbb-2")[0], 1)
        self.assertEqual(asked, [["alive", "aaaa-1"]])
        self.assertEqual(atr.lead_status("demo")["state"], "running")  # the answer is kept a minute
        self.assertEqual(len(asked), 1)

    def test_a_lead_whose_session_ended_is_gone_at_once(self):
        self.cli("lead", "--claim", "aaaa-1")
        self.assertIn("released", self.cli("ended", "aaaa-1")[1])
        st = atr.lead_status("demo")
        self.assertEqual((st["state"], st["why"], st["id"]), ("gone", "ended", "aaaa-1"))
        self.assertEqual(self.cli("lead", "--claim", "aaaa-1")[0], 0)  # resumed, it leads again
        self.assertEqual(atr.lead_status("demo")["state"], "working")
    def test_a_silent_task_is_news_for_the_lead_once(self):
        self.cli("task", "add", "G1", "long run")
        self.cli("task", "set", "T1", "status=doing", "thread=w-1")
        self.cli("read")
        self.assertEqual(atr.check_silence("demo"), 0)
        plan = atr.load("demo")
        plan["tasks"][0]["doing_since"] = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(time.time() - atr.SILENT_AFTER - 120))
        atr.save(plan)
        self.assertEqual(atr.check_silence("demo"), 1)
        self.assertEqual(atr.check_silence("demo"), 0)  # once per silence
        code, out = self.cli("unread")
        self.assertEqual(code, 0)  # it wakes the lead
        self.assertRegex(out, r"no news for 3[23] min")
        self.assertIn("atr alive T1", out)
        read = self.cli("read")[1]
        self.assertIn("FROM ATR", read)
        self.assertIn("SILENT", read)
        self.cli("now", "T1", "still going")  # news: the silence is over
        self.assertNotIn("silent_at", self.task("T1"))

    def test_a_workers_first_report_gives_its_thread_and_its_end_is_news(self):
        self.cli("task", "add", "G1", "build")
        self.cli("task", "set", "T1", "status=doing")
        self.assertIn("no thread", self.cli("read")[1])
        self.cli("now", "T1", "starting", "--thread", "w-1234")
        self.cli("now", "T1", "later", "--thread", "other")  # only the first sets it
        self.assertEqual(self.task("T1")["thread"], "w-1234")
        self.assertIn("nothing ran", self.cli("ended", "zzzz")[1])
        self.cli("read")
        out = self.cli("ended", "w-1234")[1]
        self.assertIn("the worker of T1", out)
        self.assertTrue(self.task("T1")["ended_at"])
        self.assertEqual(self.cli("unread")[0], 0)
        self.assertIn("WORKER ENDED", self.cli("read")[1])
        self.cli("task", "set", "T1", "status=todo")
        self.assertNotIn("ended_at", self.task("T1"))

    def test_a_lead_outside_the_repo_is_told_to_lead_from_it(self):
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        self.cli("read")
        os.chdir(elsewhere.name)
        out = self.cli("-p", "demo", "read")[1]
        self.assertIn("NOTE: you are in", out)
        self.assertNotIn("atr watch", out)

    def test_only_the_owner_says_a_goal_is_met_and_met_goals_take_no_new_work(self):
        self.cli("goal", "propose", "Mute ads", "--done", "most ads muted")
        self.you("goal_accept", id="G2")
        self.cli("task", "add", "G2", "build")
        with self.assertRaises(atr.Refused):
            self.you("goal_met", id="G2")  # an open task
        self.cli("task", "set", "T1", "status=done")
        self.assertIn("say whether G2 is met", self.cli("read")[1])
        with self.assertRaises(atr.Refused):
            self.agent("goal_met", id="G2")
        self.you("goal_met", id="G2")
        g = atr.get(atr.load("demo"), "goals", "G2")
        self.assertNotIn("test_guess", g)
        out = self.cli("read")[1]
        self.assertIn("MET (the owner closed these)", out)
        self.assertNotIn("say whether G2", out)
        self.assertEqual(self.cli("task", "add", "G2", "more")[0], 2)
        self.you("goal_reopen", id="G2", why="edges still late")
        self.assertEqual(self.cli("task", "add", "G2", "more")[0], 0)


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

    def test_the_page_shows_a_gone_lead_and_its_button_brings_it_back(self):
        atr.write_claim("demo", "lead-1", c={"id": "lead-1", "seen": time.time(), "ended": time.time()})
        _, body = self.call("/api/p/demo")
        self.assertEqual((body["lead"]["state"], body["lead"]["why"]), ("gone", "ended"))
        calls = []
        real = atr.bring_back_lead
        self.addCleanup(vars(atr).__setitem__, "bring_back_lead", real)
        atr.bring_back_lead = lambda name, auto=False: calls.append((name, auto)) or "back"
        self.assertEqual(self.call("/api/resume/demo", {}), (200, {"ok": True, "said": "back"}))
        self.assertEqual(self.call("/api/resume/demo", {}, headers={})[0], 403)
        self.call("/api/p/demo", {"op": "goal_add", "args": {"title": "x"}})
        for _ in range(50):  # the owner acted: atr tries to bring the lead back, in the background
            if len(calls) > 1:
                break
            time.sleep(0.02)
        self.assertEqual(calls, [("demo", False), ("demo", True)])

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

    def test_the_page_hears_when_the_server_runs_older_code(self):
        atr.Handler.started_with = atr.code_stamp()
        self.assertFalse(self.call("/api/sig")[1][""]["outdated"])
        atr.Handler.started_with = (0, 0)  # as if the code changed after the server started
        self.assertTrue(self.call("/api/sig")[1][""]["outdated"])

    def test_the_page_hears_of_a_newer_release_only(self):
        self.addCleanup(setattr, atr.Handler, "latest", {})
        atr.Handler.latest = {"version": atr.version(), "url": "u"}
        self.assertIsNone(self.call("/api/sig")[1][""]["latest"])
        atr.Handler.latest = {"version": "99.0.0", "url": "u"}
        info = self.call("/api/sig")[1][""]
        self.assertEqual((info["latest"]["version"], info["version"]), ("99.0.0", atr.version()))

    def test_upgrade_needs_a_newer_release_and_the_header(self):
        self.addCleanup(setattr, atr.Handler, "latest", {})
        self.assertEqual(self.call("/api/upgrade", {}, {"Content-Type": "application/json"})[0], 403)
        code, body = self.call("/api/upgrade", {})
        self.assertEqual(code, 400)
        self.assertIn("no newer atr", body["error"])

    def test_upgrade_runs_the_servers_command_then_restarts(self):
        from unittest import mock

        self.addCleanup(setattr, atr.Handler, "latest", {})
        self.addCleanup(setattr, atr.Handler, "restart", atr.Handler.restart)
        atr.Handler.latest = {"version": "99.0.0", "url": "u"}
        restarted = threading.Event()
        atr.Handler.restart = restarted.set
        with mock.patch.object(atr, "upgrade", return_value=(False, ["atr: failed (no network)"])):
            code, body = self.call("/api/upgrade", {"command": "rm -rf /"})
        self.assertEqual(code, 500)
        self.assertIn("no network", body["error"])
        self.assertFalse(restarted.is_set())
        with mock.patch.object(atr, "upgrade", return_value=(True, ["atr: upgraded"])) as up:
            code, body = self.call("/api/upgrade", {"command": "rm -rf /"})
        up.assert_called_once_with()  # the page's body names no command
        self.assertEqual((code, body["restarting"], body["log"]), (200, True, ["atr: upgraded"]))
        self.assertTrue(restarted.wait(5))

    def test_restart_answers_then_restarts(self):
        restarted = threading.Event()
        self.addCleanup(setattr, atr.Handler, "restart", atr.Handler.restart)
        atr.Handler.restart = restarted.set
        code, body = self.call("/api/restart", {})
        self.assertEqual((code, body["restarting"]), (200, True))
        self.assertTrue(restarted.wait(5))

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


class Service(Base):
    cmd = ["/py", "/my atr/atr", "serve", "--port", "9"]

    def test_launchd_agent_runs_the_command_and_restarts_it(self):
        path, text, start, stop = atr.service_files(self.cmd, {"ATR_DATA_DIR": "/d&d"}, Path("/h"), "Darwin")
        self.assertEqual(path, Path("/h/Library/LaunchAgents/atr.serve.plist"))
        for want in ("<string>/my atr/atr</string>", "<key>KeepAlive</key><true/>", "<string>/d&amp;d</string>"):
            self.assertIn(want, text)
        self.assertEqual(start[-1][:2], ["launchctl", "bootstrap"])
        self.assertEqual(stop[0][:2], ["launchctl", "bootout"])

    def test_systemd_unit_quotes_the_command(self):
        path, text, start, stop = atr.service_files(self.cmd, {}, Path("/h"), "Linux")
        self.assertEqual(path, Path("/h/.config/systemd/user/atr.service"))
        self.assertIn('ExecStart="/py" "/my atr/atr" "serve" "--port" "9"', text)
        self.assertIn("Restart=on-failure", text)
        self.assertIn("enable", start[-1])

    def test_the_service_keeps_the_shells_path(self):
        # launchd gives a service PATH /usr/bin:/bin, where atr serve would find no gh and never see a PR merge
        self.assertEqual(atr.service_env({"PATH": "/opt/bin:/usr/bin", "HOME": "/h"}), {"PATH": "/opt/bin:/usr/bin"})
        self.assertEqual(atr.service_env({"PATH": "/b", "ATR_DATA_DIR": "/d"}), {"PATH": "/b", "ATR_DATA_DIR": "/d"})
        text = atr.service_files(self.cmd, atr.service_env({"PATH": "/opt/bin"}), Path("/h"), "Darwin")[1]
        self.assertIn("<key>PATH</key><string>/opt/bin</string>", text)

    def test_a_throwaway_uvx_environment_is_refused(self):
        real = atr.sys.executable
        self.addCleanup(setattr, atr.sys, "executable", real)
        atr.sys.executable = "/c/uv/archive-v0/abc/bin/python"
        with self.assertRaises(atr.Refused):
            atr.serve_command()


class LeadProviders(Base):
    """atr init starts the lead through an atr-lead-<tool> program on PATH and stores the link it prints."""

    def setUp(self):
        super().setUp()
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        old = os.environ["PATH"]
        # only the providers this test makes, and a python3 for the Claude Code provider's shebang
        python = self.bin.parent / "python"
        python.mkdir()
        (python / "python3").symlink_to(sys.executable)
        os.environ["PATH"] = os.pathsep.join((str(self.bin), str(python)))
        self.addCleanup(os.environ.__setitem__, "PATH", old)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        os.chdir(self.repo)

    def provider(self, tool, body):
        exe = self.bin / f"atr-lead-{tool}"
        exe.write_text(f"#!{sys.executable}\nimport os, sys\n{body}\n")
        exe.chmod(0o755)

    def fake_claude(self, body):
        claude = self.bin / "claude"
        claude.write_text(f"#!{sys.executable}\nimport sys, json, pathlib\n{body}\n")
        claude.chmod(0o755)
        (self.bin / "atr-lead-claude-code").symlink_to(ROOT / "extensions/claude-code/bin/atr-lead-claude-code")

    def init(self, *args):
        code, out = self.cli("init", "fresh", "Fresh", *args)
        self.assertEqual(code, 0, out)
        return out, atr.load("fresh")["lead"]["thread"]

    def test_init_starts_the_one_provider_and_stores_its_link(self):
        self.provider("tool", "print('starting'); print(f'tool://{sys.argv[1]}/{sys.argv[2]}/{os.environ[\"ATR_PROJECT\"]}/{os.getcwd()}')")
        out, link = self.init()
        self.assertEqual(link, f"tool://fresh/Fresh/fresh/{Path.cwd().resolve()}")
        self.assertIn("started the lead in tool", out)
        self.assertFalse(atr.unread(atr.load("fresh")))  # storing the link is not news for the new lead

    def test_init_works_as_before_without_a_provider(self):
        out, link = self.init()
        self.assertEqual(link, "")
        self.assertIn("No lead provider", out)
        self.assertTrue(Path(".atr").exists())

    def test_several_providers_start_none_until_one_is_picked(self):
        self.provider("one", "print('one://x')")
        self.provider("two", "print('two://x')")
        out, link = self.init()
        self.assertEqual(link, "")
        self.assertIn("one, two", out)
        self.cli("-p", "fresh", "lead", "--start", "two")
        self.assertEqual(atr.load("fresh")["lead"]["thread"], "two://x")

    def test_a_failing_provider_never_fails_init(self):
        self.provider("tool", "print('Workspace not trusted', file=sys.stderr); sys.exit(1)")
        out, link = self.init()
        self.assertEqual(link, "")
        self.assertIn("did not start the lead: Workspace not trusted", out)

    def test_lead_none_skips_and_an_unknown_tool_is_named(self):
        self.provider("tool", "print('tool://x')")
        self.assertEqual(self.init("--lead", "none")[1], "")
        self.assertIn("No atr-lead-other", self.cli("-p", "fresh", "lead", "--start", "other")[1])

    def test_claude_code_provider_starts_a_background_session(self):
        self.fake_claude(
            f"pathlib.Path({self.tmp.name!r}, 'claude-args').write_text(json.dumps(sys.argv[1:]))\n"
            "print('backgrounded · 85aade68 · fresh · lead')"
        )
        out, link = self.init()
        self.assertEqual(link, "claude attach 85aade68")
        args = json.loads((Path(self.tmp.name) / "claude-args").read_text())
        self.assertEqual(args[:3], ["--bg", "-n", "fresh · lead"])
        self.assertIn("atr rules", args[3])
        self.assertEqual(atr.read_claim("fresh")["id"], "85aade68")  # the session it started is the lead

    def test_claude_code_provider_passes_claudes_complaint_on(self):
        self.fake_claude("print('Workspace not trusted. Run claude once.'); raise SystemExit(1)")
        out, link = self.init()
        self.assertEqual(link, "")
        self.assertIn("Workspace not trusted", out)


    def gone_lead(self, project="fresh", **extra):
        atr.write_claim(project, "lead-1234", c={"id": "lead-1234", "seen": time.time() - 3 * atr.GONE_AFTER, "ended": time.time() - 2 * atr.GONE_AFTER, **extra})

    def test_a_gone_lead_is_resumed_through_its_provider(self):
        self.provider("tool", "pathlib = __import__('pathlib'); pathlib.Path(os.environ['ATR_DATA_DIR'], 'args').write_text(repr(sys.argv[1:]))\n"
                      "print('thread-id: lead-1234'); print('tool://lead-1234')")
        self.init("--lead", "none")
        with self.assertRaises(atr.Refused):
            atr.bring_back_lead("fresh")  # no thread has led it
        self.gone_lead()
        said = atr.bring_back_lead("fresh")
        self.assertIn("resumed thread lead-1234", said)
        args = eval((Path(self.tmp.name) / "args").read_text())
        self.assertEqual(args[:2], ["resume", "lead-1234"])
        self.assertIn("atr read", args[2])
        self.assertEqual(atr.lead_status("fresh")["state"], "working")
        self.assertIn("brought the lead back", atr.render(atr.load("fresh"), atr.unread(atr.load("fresh"))))
        self.assertTrue(atr.last_resume("fresh")["ok"])

    def test_a_lead_that_will_not_resume_is_started_fresh(self):
        self.provider("tool", "if sys.argv[1] == 'resume': print('no such session', file=sys.stderr); sys.exit(1)\n"
                      "print('thread-id: new-9'); print('tool://new-9')")
        self.init("--lead", "none")
        self.gone_lead()
        said = atr.bring_back_lead("fresh")
        self.assertIn("could not resume", said)
        self.assertIn("no such session", said)
        self.assertEqual(atr.load("fresh")["lead"]["thread"], "tool://new-9")
        self.assertEqual(atr.read_claim("fresh")["id"], "new-9")

    def test_the_owner_acting_brings_a_gone_lead_back_at_most_once_an_hour(self):
        self.provider("tool", "print('thread-id: lead-1234'); print('tool://x')")
        self.init("--lead", "none")
        atr.write_claim("fresh", "lead-1234", c={"id": "lead-1234", "seen": time.time(), "ended": time.time() - 60})
        self.assertEqual(atr.bring_back_lead("fresh", auto=True), "")  # gone only a minute
        self.gone_lead()
        self.assertIn("on its own", atr.bring_back_lead("fresh", auto=True))
        self.gone_lead()
        self.assertEqual(atr.bring_back_lead("fresh", auto=True), "")  # tried under an hour ago
        self.assertIn("resumed", atr.bring_back_lead("fresh"))  # the page's button is not limited

    def test_a_worker_is_checked_and_resumed_through_the_provider(self):
        self.provider("tool", "if sys.argv[1] == 'alive': sys.exit(0 if sys.argv[2] == 'w-1' else 1)\n"
                      "print('thread-id: ' + sys.argv[2])")
        self.init("--lead", "none")
        os.environ["ATR_PROJECT"] = "fresh"
        self.cli("-p", "fresh", "goal", "propose", "x")
        atr.change("fresh", "you", atr.OPS["goal_accept"], {"id": "G1"})
        self.cli("task", "add", "G1", "a")
        self.cli("task", "add", "G1", "b")
        self.cli("task", "set", "T1", "status=doing", "thread=w-1")
        self.cli("task", "set", "T2", "status=doing", "thread=w-2")
        self.assertEqual(self.cli("alive", "T1"), (0, "thread w-1 is running\n"))
        self.assertEqual(self.cli("alive", "T2")[0], 1)
        self.cli("ended", "w-2")
        code, out = self.cli("resume", "T2")
        self.assertEqual(code, 0, out)
        self.assertIn("resumed the worker of T2", out)
        self.assertNotIn("ended_at", atr.get(atr.load("fresh"), "tasks", "T2"))

    def test_claude_code_provider_resumes_and_checks_a_session(self):
        self.fake_claude(
            "if sys.argv[1] == 'agents': print(json.dumps([{'id': '85aade68', 'sessionId': '85aade68-1', 'state': 'blocked'}]))\n"
            f"else: pathlib.Path({self.tmp.name!r}, 'claude-args').write_text(json.dumps(sys.argv[1:])); print('backgrounded · 85aade68')"
        )
        exe = str(self.bin / "atr-lead-claude-code")

        def run(*a):
            return subprocess.run([exe, *a], capture_output=True, text=True, check=False)

        self.assertEqual(run("alive", "85aade68-1").returncode, 0)
        self.assertEqual(run("alive", "ffff").returncode, 1)
        r = run("resume", "85aade68-1", "carry on")
        self.assertEqual(r.stdout.splitlines(), ["thread-id: 85aade68", "claude attach 85aade68"])
        self.assertEqual(json.loads((Path(self.tmp.name) / "claude-args").read_text()), ["--bg", "--resume", "85aade68-1", "carry on"])


class SideQuestions(LeadProviders):
    """G10: the owner asks about the project; a provider thread answers it, and can only read (D32-D34)."""

    def setUp(self):
        super().setUp()
        self.cli("-p", "demo", "read")  # the lead is up to date
        self.addCleanup(os.environ.pop, "ATR_SIDE", None)

    def answered(self, name="demo", qid="Q1"):
        for _ in range(200):
            e = next(x for x in atr.side_load(name) if x["id"] == qid)
            if e["turns"][-1]["state"] != "thinking":
                return e
            time.sleep(0.02)
        self.fail("the side question was never answered")

    def test_a_side_thread_reads_the_plan_but_changes_nothing(self):
        self.you("goal_add", title="Unread by the lead")
        os.environ["ATR_SIDE"] = "1"
        code, out = self.cli("-p", "demo", "read")
        self.assertEqual(code, 0)
        self.assertIn("Unread by the lead", out)
        for args in (("task", "add", "G1", "sneaky"), ("now", "T1", "x"), ("lead", "--claim", "s9"), ("wait", "--timeout", "0")):
            code, out = self.cli("-p", "demo", *args)
            self.assertEqual(code, 2, args)
            self.assertIn("side question", out)
        with self.assertRaises(atr.Refused):
            self.agent("task_add", goal="G1", title="through the back door")
        os.environ.pop("ATR_SIDE")
        self.assertTrue(atr.unread(atr.load("demo")))  # the lead still has the owner's change to read

    def test_a_side_question_is_answered_and_followed_up_in_its_thread(self):
        self.provider("tool", (
            "import json, pathlib\n"
            f"log = pathlib.Path({self.tmp.name!r}, 'asks')\n"
            "log.write_text((log.read_text() if log.exists() else '') + json.dumps([sys.argv[1:], os.environ.get('ATR_SIDE')]) + '\\n')\n"
            "print('thread-id: side-1'); print('Two goals.'); print(); print('- G1 is open')"
        ))
        rev = atr.load("demo")["rev"]
        self.assertEqual(atr.side_ask("demo", " How far along is it? "), "Q1")
        e = self.answered()
        self.assertEqual((e["thread"], e["turns"][0]["a"]), ("side-1", "Two goals.\n\n- G1 is open"))
        self.assertEqual(atr.side_ask("demo", "And G1?", "Q1"), "Q1")
        e = self.answered()
        self.assertEqual([t["q"] for t in e["turns"]], ["How far along is it?", "And G1?"])
        asks = [json.loads(x) for x in (Path(self.tmp.name) / "asks").read_text().splitlines()]
        self.assertEqual(asks, [[["ask", "demo", "How far along is it?"], "1"], [["ask", "demo", "And G1?", "side-1"], "1"]])
        plan = atr.load("demo")
        self.assertEqual(plan["rev"], rev)  # not a change to the plan, and nothing for the lead to read
        self.assertFalse(atr.unread(plan))
        with self.assertRaises(atr.Refused):
            atr.side_ask("demo", "   ")

    def test_a_failed_answer_says_why_and_a_lost_one_is_not_left_thinking(self):
        self.provider("tool", "print('not logged in', file=sys.stderr); sys.exit(1)")
        atr.side_ask("demo", "Anything?")
        e = self.answered()
        self.assertEqual(e["turns"][0]["state"], "failed")
        self.assertIn("not logged in", e["turns"][0]["a"])
        with self.assertRaises(atr.Refused):  # no thread came back to follow up in
            atr.side_ask("demo", "again?", "Q1")
        atr.side_update("demo", lambda items: items.append(
            {"id": "Q2", "thread": "", "tool": "tool", "turns": [{"q": "old", "at": "2020-01-01T00:00Z", "state": "thinking", "a": ""}]}))
        self.assertEqual(self.answered(qid="Q2")["turns"][0]["state"], "failed")

    def test_without_a_provider_nothing_is_asked(self):
        with self.assertRaises(atr.Refused):
            atr.side_ask("demo", "Anything?")
        self.assertEqual(atr.side_load("demo"), [])

    def test_claude_code_provider_answers_read_only_and_resumes_for_a_follow_up(self):
        self.fake_claude(
            f"pathlib.Path({self.tmp.name!r}, 'claude-args').write_text(json.dumps(sys.argv[1:]))\n"
            "print('{\"type\": \"system\"}')\n"
            "print(json.dumps({'type': 'result', 'is_error': False, 'session_id': 'abc-123', 'result': 'It is **fine**.'}))"
        )
        exe = str(self.bin / "atr-lead-claude-code")
        def args():
            return json.loads((Path(self.tmp.name) / "claude-args").read_text())

        r = subprocess.run([exe, "ask", "demo", "How is it?"], capture_output=True, text=True, check=False)
        self.assertEqual((r.returncode, r.stdout), (0, "thread-id: abc-123\nIt is **fine**.\n"))
        a = args()
        self.assertEqual(a[:5], ["-p", "--output-format", "json", "--permission-mode", "plan"])
        self.assertIn("Edit", a[a.index("--disallowedTools"):])
        self.assertNotIn("--resume", a)
        self.assertIn("How is it?", a[-1])
        self.assertIn("change nothing", a[-1])
        subprocess.run([exe, "ask", "demo", "Sure?", "abc-123"], capture_output=True, text=True, check=False)
        a = args()
        self.assertEqual(a[a.index("--resume") + 1], "abc-123")
        self.assertEqual(a[-1], "Sure?")

    def test_claude_code_provider_passes_an_error_on(self):
        self.fake_claude("print(json.dumps({'type': 'result', 'is_error': True, 'result': 'Credit balance is too low'}))")
        r = subprocess.run([str(self.bin / "atr-lead-claude-code"), "ask", "demo", "Hm?"], capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Credit balance is too low", r.stderr)

    def test_the_page_asks_and_shows_side_questions(self):
        self.provider("tool", "print('thread-id: t1'); print('Yes.')")
        atr.Handler.allowed_hosts = {"127.0.0.1", "localhost"}
        server = ThreadingHTTPServer(("127.0.0.1", 0), atr.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"

        def call(path, body=None, headers=None):
            req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "X-Atr": "1"} if headers is None else headers)
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                with e:
                    return e.code, json.loads(e.read())

        sig = call("/api/sig")[1]["demo"]
        self.assertEqual(call("/api/side/demo", {"question": "Done?"}, headers={})[0], 403)
        self.assertEqual(call("/api/side/demo", {"question": "Done?"}), (200, {"ok": True, "id": "Q1"}))
        self.assertEqual(call("/api/side/demo", {"question": ""})[0], 400)
        self.answered()
        _, body = call("/api/p/demo")
        self.assertEqual(body["side"][0]["turns"][0]["a"], "Yes.")
        self.assertNotEqual(call("/api/sig")[1]["demo"], sig)  # the page redraws when an answer comes
        self.assertEqual(body["sig"], call("/api/sig")[1]["demo"])


class Versions(unittest.TestCase):
    def test_release_tags_compare_as_versions(self):
        self.assertTrue(atr.newer("v0.10.0", "0.4.0"))
        self.assertTrue(atr.newer("0.4.1", "0.4.0"))
        self.assertFalse(atr.newer("v0.4.0", "0.4.0"))
        self.assertFalse(atr.newer("v0.3.0", "0.4.0"))
        self.assertFalse(atr.newer(None, "0.4.0"))

    def test_the_plugin_and_the_package_share_one_version(self):
        plugin = json.loads((ROOT / "extensions/claude-code/.claude-plugin/plugin.json").read_text())["version"]
        market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"][0]["version"]
        self.assertEqual({atr.version(), plugin, market}, {atr.version()})
        self.assertGreater(atr.vtuple(atr.version()), (0, 3, 0))  # past the last release before versions were kept

    def test_every_push_to_main_releases_the_next_version(self):
        spec = importlib.util.spec_from_file_location("release_version", ROOT / "scripts/release_version.py")
        rv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rv)
        self.assertEqual(rv.next_version("0.4.1", {"v0.4.0", "v0.4.1"}), "0.4.2")  # released: bump the patch
        self.assertEqual(rv.next_version("0.5.0", {"v0.4.1"}), "0.5.0")  # bumped by hand in a PR: as is
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, _ in rv.FILES:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text((ROOT / name).read_text())
            rv.write(root, "9.8.7")
            self.assertEqual(rv.current(root), "9.8.7")
            plugin = json.loads((root / "extensions/claude-code/.claude-plugin/plugin.json").read_text())["version"]
            market = json.loads((root / ".claude-plugin/marketplace.json").read_text())["plugins"][0]["version"]
            self.assertEqual((plugin, market), ("9.8.7", "9.8.7"))
            self.assertIn('name = "atr"\nversion = "9.8.7"', (root / "uv.lock").read_text())

    def test_the_command_line_reports_the_version(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            atr.main(["--version"])
        self.assertEqual(out.getvalue().strip(), f"atr {atr.version()}")

    def test_a_checkout_upgrades_with_a_fast_forward_pull(self):
        self.assertEqual(atr.install_kind(), "checkout")
        try:
            steps = atr.upgrade_steps()
        except atr.Refused as e:  # a branch or local changes: the owner upgrades by hand
            self.assertIn("by hand", str(e))
            return
        self.assertEqual(steps[0][1][-2:], ["pull", "--ff-only"])

    def git(self, branch, status):
        """subprocess.run for upgrade_steps, as if the checkout is on `branch` with `git status` saying `status`."""

        def run(argv, **kw):
            out = branch if "branch" in argv else status if "status" in argv else "atr@atr  ✔ enabled"
            return subprocess.CompletedProcess(argv, 0, out + "\n", "")

        return run

    def steps(self, kind, branch="main", status="", claude=None):
        from unittest import mock

        with (
            mock.patch.object(atr, "install_kind", return_value=kind),
            mock.patch.object(atr.subprocess, "run", side_effect=self.git(branch, status)),
            mock.patch.object(atr.shutil, "which", side_effect=lambda c: {"claude": claude, "uv": "/bin/uv"}.get(c)),
        ):
            return atr.upgrade_steps()

    def test_each_install_upgrades_its_own_way(self):
        pull = self.steps("checkout")
        self.assertEqual([(w, a[-2:], n) for w, a, n in pull], [("atr", ["pull", "--ff-only"], True)])
        self.assertEqual(self.steps("uv")[0][1], ["/bin/uv", "tool", "upgrade", "atr"])
        with_plugin = self.steps("uv", claude="/bin/claude")
        self.assertEqual(with_plugin[1], ("the Claude Code plugin", ["/bin/claude", "plugin", "update", "atr@atr"], False))

    def test_a_checkout_off_main_or_with_changes_is_left_alone(self):
        for branch, status, why in (("g5", "", "not on main"), ("main", " M src/atr/cli.py", "local changes")):
            with self.assertRaises(atr.Refused) as e:
                self.steps("checkout", branch, status)
            self.assertIn(why, str(e.exception))
        with self.assertRaises(atr.Refused):
            self.steps("")  # uvx or something atr does not know

    def test_a_failed_plugin_update_does_not_fail_the_upgrade(self):
        from unittest import mock

        steps = [("atr", ["true"], True), ("the Claude Code plugin", ["false"], False)]
        with mock.patch.object(atr, "upgrade_steps", return_value=steps):
            ok, lines = atr.upgrade()
        self.assertTrue(ok)
        self.assertEqual(lines, ["atr: upgraded", "the Claude Code plugin: failed"])
        with mock.patch.object(atr, "upgrade_steps", return_value=[("atr", ["false"], True)]):
            self.assertFalse(atr.upgrade()[0])


class ReleaseCheck(Base):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, atr.Handler, "latest", {})

    def github(self, answer):
        """Stand in for GitHub: urlopen answers with `answer` (a dict) or raises it (an exception)."""
        from unittest import mock

        self.asked = 0

        def urlopen(req, timeout):
            self.asked += 1
            self.assertEqual(req.full_url, atr.RELEASES)
            if isinstance(answer, Exception):
                raise answer
            return io.BytesIO(json.dumps(answer).encode())

        return mock.patch.object(urllib.request, "urlopen", urlopen)

    def test_reads_the_latest_release(self):
        with self.github({"tag_name": "v9.1.0", "html_url": "https://x/v9.1.0"}):
            self.assertEqual(atr.latest_release(), {"version": "9.1.0", "url": "https://x/v9.1.0"})

    def test_silent_when_github_does_not_answer(self):
        for answer in (urllib.error.URLError("offline"), TimeoutError(), {"message": "rate limited"}):
            with self.github(answer):
                self.assertIsNone(atr.latest_release())
                self.assertEqual(atr.check_release(now=1000), atr.CHECK_EVERY)
            (Path(self.tmp.name) / ".release.json").unlink()
            self.assertEqual(atr.Handler.latest, {})

    def test_asks_at_most_every_six_hours_even_across_restarts(self):
        with self.github({"tag_name": "v9.1.0", "html_url": "u"}):
            self.assertEqual(atr.check_release(now=1000), atr.CHECK_EVERY)
            atr.Handler.latest = {}  # a restarted server
            self.assertEqual(atr.check_release(now=1000 + 3600), atr.CHECK_EVERY - 3600)
            self.assertEqual(self.asked, 1)
            self.assertEqual(atr.Handler.latest["version"], "9.1.0")  # remembered, not asked again
            atr.check_release(now=1000 + atr.CHECK_EVERY)
            self.assertEqual(self.asked, 2)


URL = "https://github.com/mvexel/atr/pull/23"


class PullRequests(Base):
    """atr pr puts a PR on its goal; atr serve's poller asks gh (mocked here: no network, no real gh)."""

    def setUp(self):
        super().setUp()
        self.cli("task", "add", "G1", "build it")
        self.cli("task", "add", "G1", "other")
        self.cli("read")
        self.calls = []

    def poll(self, *answers):
        """Run one poll round per answer, with gh patched in: each round's gh call answers with the next of
        `answers` (a dict of PR number to pullRequest fields, an Exception, or raw stdout). self.calls collects
        the argv of each gh call. Returns what each round said to wait."""
        from unittest import mock

        answers = list(answers)
        rounds = len(answers)

        def run(argv, **kw):
            self.calls.append(argv)
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            if isinstance(a, str):
                return subprocess.CompletedProcess(argv, 1, a, "")
            query = argv[-1]
            data = {"rateLimit": a.pop("rateLimit", {"limit": 5000, "remaining": 4000})}
            for i, num in enumerate(int(x) for x in re.findall(r"pullRequest\(number: (\d+)\)", query)):
                data[f"p{i}"] = {"pullRequest": a[num]} if num in a else None
            return subprocess.CompletedProcess(argv, 0, json.dumps({"data": data}), "")

        with (
            mock.patch.object(atr.shutil, "which", side_effect=lambda c: "/usr/bin/gh" if c == "gh" else None),
            mock.patch.object(atr.subprocess, "run", side_effect=run),
        ):
            return [atr.check_prs() for _ in range(rounds)]

    @staticmethod
    def pr(state="OPEN", ci="SUCCESS", mergeable="MERGEABLE", draft=False):
        return {"state": state, "isDraft": draft, "mergeable": mergeable,
                "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": ci} if ci else None}}]}}

    def prs(self):
        return atr.load("demo")["goals"][0].get("prs", [])

    def test_a_pr_sits_on_its_goal_for_its_tasks_and_is_the_owners_turn(self):
        code, out = self.cli("pr", "G1", URL + "/files", "--for", "T1")
        self.assertEqual(code, 0, out)
        self.assertIn("PR #23 on G1 for T1", out)
        p = self.prs()[0]
        self.assertEqual((p["url"], p["for"], p["state"], p["known"]), (URL, ["T1"], "open", False))
        read = self.cli("read")[1]
        self.assertIn("PR #23 for T1: open, state unknown", read)
        self.assertIn("merge PR #23 on G1", read)
        self.assertEqual(atr.summary(atr.load("demo"))["needs_you"], 1)
        self.assertIn("no change", self.cli("pr", "G1", URL, "--for", "T1")[1])
        self.assertIn("also for T2", self.cli("pr", "G1", URL, "--for", "T2")[1])

    def test_a_pr_needs_a_github_link_and_tasks_of_its_goal(self):
        self.assertIn("not a GitHub pull request", self.cli("pr", "G1", "https://example.com/x/y/pull/1")[1])
        self.assertIn("not a GitHub pull request", self.cli("pr", "G1", 'https://github.com/a"b/c/pull/1')[1])
        self.you("goal_add", title="Other")
        self.assertIn("T1 is under G1, not G2", self.cli("pr", "G2", URL, "--for", "T1")[1])
        self.assertIn("no task T9", self.cli("pr", "G1", URL, "--for", "T9")[1])

    def test_one_query_per_round_for_all_open_prs_of_all_projects(self):
        self.cli("pr", "G1", URL, "--for", "T1")
        self.cli("pr", "G1", "https://github.com/mvexel/atr/pull/24")
        os.environ.pop("ATR_PROJECT")
        repo = Path(self.tmp.name) / "repo2"
        repo.mkdir()
        os.chdir(repo)
        self.cli("init", "second", "Second", "--lead", "none")
        atr.change("second", "you", atr.op_goal_add, {"title": "x"})
        self.cli("-p", "second", "pr", "G1", "https://github.com/o/r/pull/7")
        self.assertEqual(self.poll({23: self.pr(), 24: self.pr(), 7: self.pr()}), [atr.PR_EVERY])
        self.assertEqual(len(self.calls), 1)
        argv = self.calls[0]
        self.assertEqual(argv[1:4], ["api", "graphql", "-f"])
        for bit in ("rateLimit", "pullRequest(number: 23)", "pullRequest(number: 24)", 'owner: "o", name: "r"', "statusCheckRollup", "mergeable", "isDraft"):
            self.assertIn(bit, argv[-1])
        p = atr.load("second")["goals"][0]["prs"][0]
        self.assertEqual((p["known"], p["ci"], p["mergeable"], p["draft"]), (True, "passing", "mergeable", False))

    def test_no_open_prs_no_gh(self):
        self.assertEqual(self.poll(), [])
        self.assertEqual(atr.check_prs(), atr.PR_EVERY)  # no PRs: gh is not asked (no patch, so a call would fail)

    def test_it_slows_down_when_the_rate_limit_runs_low(self):
        self.cli("pr", "G1", URL)
        low = {23: self.pr(), "rateLimit": {"limit": 5000, "remaining": 999}}
        ok = {23: self.pr(), "rateLimit": {"limit": 5000, "remaining": 1000}}
        self.assertEqual(self.poll(low, ok), [atr.PR_SLOW, atr.PR_EVERY])

    def test_without_gh_or_when_it_fails_the_pr_is_a_link_with_state_unknown(self):
        self.cli("pr", "G1", URL)
        self.poll({23: self.pr(ci="FAILURE")})
        self.cli("read")
        rev = atr.load("demo")["rev"]
        self.poll(OSError("gh gone"), "not json", '{"data": null, "errors": [{"message": "bad credentials"}]}')
        self.assertFalse(self.prs()[0]["known"])
        self.assertEqual(atr.load("demo")["rev"], rev)  # stored silently: no news, no revision
        self.assertEqual(atr.unread(atr.load("demo")), [])
        from unittest import mock

        with mock.patch.object(atr.shutil, "which", return_value=None):
            self.assertIsNone(atr.gh_graphql("query { x }"))
        # gh back, still failing: not news again
        self.poll({23: self.pr(ci="FAILURE")})
        self.assertEqual(atr.unread(atr.load("demo")), [])

    def test_ci_failing_and_a_conflict_are_news_other_changes_are_silent(self):
        self.cli("pr", "G1", URL, "--for", "T1")
        self.poll({23: self.pr(ci="PENDING")}, {23: self.pr(ci="SUCCESS", draft=True)})
        self.assertEqual(atr.unread(atr.load("demo")), [])
        self.assertIn("draft", self.cli("read", "--peek")[1])
        before = atr.sig(atr.load("demo"))
        self.poll({23: self.pr(ci="FAILURE")})
        self.assertNotEqual(before, atr.sig(atr.load("demo")))  # the page redraws
        news = atr.unread(atr.load("demo"))
        self.assertEqual([c["by"] for c in news], ["github"])
        self.assertIn("PR #23 on G1: its CI is failing", news[0]["what"])
        self.poll({23: self.pr(ci="FAILURE", mergeable="CONFLICTING")})
        read = self.cli("read")[1]
        self.assertIn("FROM GITHUB", read)
        self.assertIn("conflicts with its base branch", read)
        self.assertNotIn("THE OWNER CHANGED", read)
        self.assertNotIn("merge PR #23", read)  # failing and conflicting: not the owner's turn yet
        self.assertEqual(atr.summary(atr.load("demo"))["unread"], 0)  # the page's "your changes" count
        self.poll({23: self.pr(ci="FAILURE", mergeable="CONFLICTING")})
        self.assertEqual(atr.unread(atr.load("demo")), [])  # unchanged: nothing written

    def test_news_from_github_wakes_a_waiting_lead(self):
        self.cli("pr", "G1", URL)
        self.poll({23: self.pr(ci="FAILURE")})
        self.assertIn("CI is failing", atr.wait("demo", 0)[0]["what"])

    def test_a_merge_moves_the_pr_to_history_and_its_reviewed_tasks_to_done(self):
        self.cli("pr", "G1", URL, "--for", "T1,T2")
        self.cli("task", "set", "T1", "status=review", "note=" + URL)
        self.poll({23: self.pr(state="MERGED")})
        plan = atr.load("demo")
        p = plan["goals"][0]["prs"][0]
        self.assertEqual(p["state"], "merged")
        self.assertTrue(p["merged_at"])
        self.assertEqual([t["status"] for t in plan["tasks"]], ["done", "todo"])  # T2 was not in review
        self.assertFalse(plan["goals"][0].get("met_at"))  # never the goal: that is the owner's call
        news = atr.unread(plan)
        self.assertIn("PR #23 on G1 was merged on GitHub; T1 done", news[0]["what"])
        read = self.cli("read")[1]
        self.assertNotIn("PR #23 for", read)
        self.assertNotIn("merge PR #23", read)
        self.poll()  # a merged PR is not asked about again
        self.assertEqual(self.calls, [self.calls[0]])
        self.assertIn("already merged", self.cli("pr", "G1", URL)[1])

    def test_a_closed_pr_leaves_quietly(self):
        self.cli("pr", "G1", URL, "--for", "T1")
        self.cli("read")
        self.poll({23: self.pr(state="CLOSED")})
        self.assertEqual(self.prs()[0]["state"], "closed")
        self.assertEqual(atr.unread(atr.load("demo")), [])

    def test_a_bad_round_never_reaches_the_page(self):
        self.cli("pr", "G1", URL)
        self.poll({})  # GitHub has no such PR: null beside the others
        self.assertFalse(self.prs()[0]["known"])


class ClaudeCodeExtension(Base):
    HOOK = ROOT / "extensions/claude-code/hooks/atr_hook.py"

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

    def test_session_start_gives_the_plan(self):
        self.assertIn("G1 Sign in", self.hook("session-start"))

    def test_a_side_question_session_hears_nothing_and_claims_nothing(self):
        os.environ["ATR_SIDE"] = "1"
        self.addCleanup(os.environ.pop, "ATR_SIDE", None)
        for event in ("session-start", "prompt", "stop", "listen", "session-end"):
            self.assertEqual(self.hook(event, session_id="side-1"), "", event)
        os.environ.pop("ATR_SIDE")
        self.assertFalse(atr.read_claim("demo"))

    def test_turn_end_holds_only_for_unread_changes(self):
        self.assertIn("atr read", json.loads(self.hook("stop"))["reason"])
        self.assertEqual(self.hook("stop", stop_hook_active=True), "")
        self.cli("read")
        self.assertEqual(self.hook("stop"), "")

    def listener(self, session="s1", cwd=None):
        return subprocess.Popen(
            [sys.executable, str(self.HOOK), "listen"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, "ATR_BIN": str(SOURCE)},
        ), json.dumps({"cwd": cwd or self.tmp.name, "session_id": session})

    def until_listening(self):
        for _ in range(100):
            if atr.waiting("demo"):
                return
            threading.Event().wait(0.05)
        self.fail("the listener never started waiting")

    def test_the_listener_wakes_the_lead_with_the_owners_action(self):
        self.cli("read")
        proc, payload = self.listener()
        proc.stdin.write(payload)
        proc.stdin.close()
        self.until_listening()
        self.you("goal_add", title="wake up", done_when="it pushes")
        out, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 2)  # asyncRewake: exit 2 wakes the session, stderr is the message
        self.assertIn('added goal G2 "wake up"', err)
        self.assertIn('"op": "goal_add"', err)

    def test_a_new_listener_replaces_the_one_before(self):
        self.cli("read")
        first, payload = self.listener()
        first.stdin.write(payload)
        first.stdin.close()
        self.until_listening()
        second, payload = self.listener()
        second.stdin.write(payload)
        second.stdin.close()
        first.communicate(timeout=10)
        self.assertEqual(first.returncode, 0)  # stopped quietly: no second wake for one action
        self.you("goal_add", title="once")
        second.communicate(timeout=10)
        self.assertEqual(second.returncode, 2)

    def test_session_start_asks_the_lead_to_confirm_running_tasks(self):
        self.cli("task", "add", "G1", "long run")
        self.cli("task", "set", "T1", "status=doing")
        self.assertIn("no news since it started", self.cli("read")[1])
        out = self.hook("session-start")
        self.assertIn("may be gone", out)
        self.assertIn("T1 long run", out)

    def test_only_the_lead_session_hears_the_owner(self):
        self.assertIn("you are its lead", self.hook("session-start", session_id="lead-1"))
        out = self.hook("session-start", session_id="other-2")
        self.assertIn("Its lead is another session (lead-1)", out)
        self.assertNotIn("G1 Sign in", out)
        self.assertEqual(self.hook("prompt", session_id="other-2"), "")
        self.assertEqual(self.hook("stop", session_id="other-2"), "")
        self.you("goal_add", title="More")
        self.assertEqual(self.hook("prompt", session_id="other-2"), "")
        self.assertIn("THE OWNER CHANGED", self.hook("prompt", session_id="lead-1"))

    def test_a_non_lead_listener_stays_quiet(self):
        self.hook("session-start", session_id="lead-1")
        proc, payload = self.listener(session="other-2")
        out, err = proc.communicate(payload, timeout=10)
        self.assertEqual((proc.returncode, err), (0, ""))

    def test_a_session_that_leads_one_project_is_not_the_lead_of_another(self):
        self.hook("session-start", session_id="lead-1")
        os.environ.pop("ATR_PROJECT")
        repo = Path(self.tmp.name) / "repo2"
        repo.mkdir()
        os.chdir(repo)
        self.cli("init", "second", "Second", "--lead", "none")
        out = self.hook("session-start", cwd=str(repo), session_id="lead-1")
        self.assertIn("already leads demo", out)
        self.hook("session-end", session_id="lead-1")  # it ends: it no longer leads demo
        self.assertIn("you are its lead", self.hook("session-start", cwd=str(repo), session_id="lead-1"))

    def test_a_worker_session_ending_tells_the_lead(self):
        self.hook("session-start", session_id="lead-1")
        self.assertIn("--thread other-2", self.hook("session-start", session_id="other-2"))
        self.cli("task", "add", "G1", "build")
        self.cli("task", "set", "T1", "status=doing", "thread=other-2")
        self.cli("read")
        self.hook("session-end", session_id="other-2")
        self.assertIn("the worker of T1", self.hook("prompt", session_id="lead-1"))
        self.hook("session-end", session_id="lead-1")
        self.assertEqual(atr.lead_status("demo")["why"], "ended")

    def test_silent_outside_an_atr_project(self):
        os.environ.pop("ATR_PROJECT")
        with tempfile.TemporaryDirectory() as elsewhere:
            for event in ("session-start", "prompt", "stop", "listen"):
                self.assertEqual(self.hook(event, cwd=elsewhere), "")


if __name__ == "__main__":
    unittest.main()
