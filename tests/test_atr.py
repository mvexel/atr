"""Tests for the plan operations, the lead's commands and the page's API. Run: python3 -m unittest discover tests"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
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
        self.old = {k: os.environ.get(k) for k in ("ATR_DATA_DIR", "ATR_PROJECT", "ATR_AS")}
        os.environ.update(ATR_DATA_DIR=self.tmp.name, ATR_PROJECT="demo")
        os.environ.pop("ATR_AS", None)
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in self.old.items()])
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
        for op, args in (("goal_edit", {"id": "G1", "title": "x"}), ("goal_remove", {"id": "G1"}), ("goal_accept", {"id": "G1"})):
            with self.assertRaises(atr.Refused):
                self.agent(op, **args)
        self.assertTrue(self.agent("goal_add", title="Proposed")["goals"][-1]["proposed"])

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
        self.assertEqual([t["id"] for t in atr.ready(atr.load("demo"))], ["T4", "T1", "T2"])
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
        self.cli("task", "set", "T1", "status=todo")           # an agent cannot route around the card
        self.assertEqual(self.cli("task", "set", "T1", "status=doing")[0], 2)
        plan = self.you("answer", id="D2", choice="new column")
        d = atr.get(plan, "decisions", "D2")
        self.assertEqual((d["state"], d["chosen"], d["rejected"]), ("accepted", "new column", ["new table"]))
        self.assertEqual(self.cli("task", "set", "T1", "status=doing")[0], 0)

    def test_answer_restores_the_status_the_card_interrupted(self):
        self.cli("task", "add", "G1", "build")
        self.cli("task", "set", "T1", "status=doing")
        self.cli("decide", "T1", "x", "--hard")
        self.assertEqual(self.you("answer", id="D1", choice="x")["tasks"][0]["status"], "doing")

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
        self.assertFalse(self.you("task_prune", id="T1", mode="drop")["tasks"][0]["stopped"])
        code, out = self.cli("task", "set", "T1", "status=doing")
        self.assertEqual(code, 2)
        self.assertIn("atr task stopped T1", out)
        self.assertIn("STOP THESE", self.cli("read")[1])
        self.cli("task", "stopped", "T1", "branch", "kept")
        self.assertTrue(self.task("T1")["stopped"])
        self.assertEqual(self.you("task_restore", id="T1")["tasks"][0]["status"], "todo")

    def test_read_shows_owner_changes_once_and_unread_reports_them(self):
        self.assertEqual(self.cli("unread")[0], 0)                # the goal added in setUp
        self.assertIn("THE OWNER CHANGED", self.cli("read", "--peek")[1])
        self.assertEqual(self.cli("unread")[0], 0)                # peek does not mark
        self.cli("read")
        self.assertEqual(self.cli("unread")[0], 1)
        self.assertNotIn("THE OWNER CHANGED", self.cli("read")[1])
        self.cli("task", "add", "G1", "agent work")               # the agent's own changes are not news to it
        self.assertEqual(self.cli("unread")[0], 1)

    def test_move_reorders_and_changes_goal(self):
        self.you("goal_add", title="Second")
        for title in ("a", "b"):
            self.cli("task", "add", "G1", title)
        self.cli("task", "add", "G2", "c")
        plan = self.you("task_move", id="T3", goal="G1", before="T1")
        self.assertEqual([(t["id"], t["goal"]) for t in plan["tasks"]], [("T3", "G1"), ("T1", "G1"), ("T2", "G1")])
        plan = self.you("task_move", id="T3", goal="G2")
        self.assertEqual(plan["tasks"][-1]["id"], "T3")
        with self.assertRaises(atr.Refused):
            self.agent("task_move", id="T1", goal="G2")

    def test_agree_sets_the_baseline_for_new_tasks(self):
        self.cli("task", "add", "G1", "planned")
        self.you("agree")
        self.cli("task", "add", "G1", "drift")
        self.assertEqual([t.get("agreed") for t in atr.load("demo")["tasks"]], [True, False])

    def test_attach_copies_the_file_into_the_project(self):
        Path("findings.md").write_text("# found\n")
        self.cli("task", "add", "G1", "build")
        self.cli("attach", "T1", "findings.md")
        self.cli("attach", "G1", "https://example.com/pr/1", "--title", "PR 1")
        Path("findings.md").unlink()
        docs = atr.load("demo")["docs"]
        self.assertEqual((Path(self.tmp.name) / "demo/docs" / docs[0]["file"]).read_text(), "# found\n")
        self.assertEqual(docs[1]["url"], "https://example.com/pr/1")
        self.assertEqual(self.cli("attach", "T1", "missing.md")[0], 2)

    def test_pointer_file_selects_the_project(self):
        os.environ.pop("ATR_PROJECT")
        self.assertEqual(Path(".atr").read_text().strip(), "demo")
        self.assertEqual(self.cli("next")[0], 0)
        Path(".atr").unlink()
        self.assertEqual(self.cli("next")[0], 2)


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
        headers = {"Content-Type": "application/json", "X-Atr": "1"} if headers is None else headers
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_page_edits_are_owner_edits_and_stale_ones_are_refused(self):
        rev = self.call("/api/p/demo")[1]["plan"]["rev"]
        self.assertEqual(self.call("/api/p/demo", {"op": "task_add", "rev": rev, "args": {"goal": "G1", "title": "from page"}})[0], 200)
        self.assertEqual(self.task("T1")["added_by"], "you")
        code, body = self.call("/api/p/demo", {"op": "task_add", "rev": rev, "args": {"goal": "G1", "title": "late"}})
        self.assertEqual((code, body["stale"]), (409, True))
        self.assertEqual(len(atr.load("demo")["tasks"]), 1)

    def test_posts_need_the_header_and_a_known_host_and_op(self):
        body = {"op": "goal_add", "rev": 1, "args": {"title": "x"}}
        self.assertEqual(self.call("/api/p/demo", body, {"Content-Type": "application/json"})[0], 403)
        self.assertEqual(self.call("/api/projects", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.call("/api/p/demo", {"op": "attach", "rev": 1, "args": {"on": "G1", "src": "/etc/hosts"}})[0], 404)
        self.assertEqual(self.call("/api/p/demo", {"op": "answer", "rev": 1, "args": {"id": "D9", "choice": "x"}})[0], 400)

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


if __name__ == "__main__":
    unittest.main()
