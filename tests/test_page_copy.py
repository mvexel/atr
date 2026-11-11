"""Page copy: public wording, duration and question formats in web/index.html.
Static checks on web/index.html; age() and the question rewrite are evaluated with node when it is installed."""
import json, re, shutil, subprocess, unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text()
NODE = shutil.which("node")


def js_fn(name):
    return re.search(r"^function %s\(.*?^}" % name, HTML, re.S | re.M).group(0)


class PageCopy(unittest.TestCase):
    def test_settled_label(self):
        self.assertNotIn("Closed / settled", HTML)
        self.assertIn("`Settled · ${dead.length}`", HTML)

    def test_public_words(self):
        self.assertIn("<title>agent-rooms</title>", HTML)
        self.assertNotIn('["Lanes", false]', HTML)
        self.assertIn('["Agents", false]', HTML)
        self.assertNotIn("next checkpoint", HTML)
        self.assertNotIn("lead_thread in BRIEF", HTML)
        for gone in ("What these words mean", "KIND_DEFS", "lock store", "}, \"Open record\")", "Other decisions", "waits ${", '"to do"'):
            self.assertNotIn(gone, HTML)

    def test_one_status_vocabulary(self):
        self.assertIn('doing: ["●", "running"]', HTML)
        self.assertIn('todo: ["○", "ready"]', HTML)
        self.assertNotIn('"doing"]', HTML)
        for needle in ("waiting on ${d}", "blocked by ${d} (needs:"):
            self.assertIn(needle, HTML)

    def test_plain_autostart_goal_and_lead_lines(self):
        for needle in ("Auto-start waits for goal approval", "Auto-start paused:", "Offered to the lead:",
                       "approve to start work", "Lead not notified (${f.reason})"):
            self.assertIn(needle, HTML)
        self.assertNotIn("Auto-start: ${a.state}", HTML)
        self.assertNotIn("Goal: not written yet", HTML)

    def test_cards_come_first_and_details_collapse(self):
        self.assertLess(HTML.index("hot(needN(r), \"need you\")"), HTML.index("`Needs you · ${needN(r)}`"))
        self.assertLess(HTML.index("`Needs you · ${needN(r)}`"), HTML.index('el("summary", {}, "Room details")'))
        self.assertIn("Hand over the lead", HTML)

    def test_room_order_is_computed_before_the_tabs(self):
        self.assertLess(HTML.index("roomOrder = computeOrder(roomSort);   // once"), HTML.index("const ordered = orderedRooms();"))

    @unittest.skipUnless(NODE, "node not installed")
    def test_one_duration_format(self):
        cases = {0: "just now", 5: "5m", 61: "1h 1m", 301: "5h 1m", 1440: "1d", 4260: "2d"}
        script = js_fn("age") + "\nconsole.log(JSON.stringify([%s].map(age)))" % ",".join(map(str, cases))
        out = json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out, list(cases.values()))
        self.assertNotIn(" min`", HTML)

    @unittest.skipUnless(NODE, "node not installed")
    def test_question_stamp_keeps_its_hour(self):
        m = re.search(r"const (rewriteQA|QA_REWRITE) = (.*?);\n", HTML, re.S)
        self.assertTrue(m, "question rewrite should be a named function")
        script = "const rewriteQA = " + re.search(r"const rewriteQA = (.*?);\n", HTML, re.S).group(1) + \
            "\nconsole.log(JSON.stringify(rewriteQA('- Q · owner · 16:15: \"Why?\"\\n- A · lead · 16:16: \"Because.\"')))"
        out = json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out, 'You asked at 16:15: "Why?"\nlead replied at 16:16: "Because."')

    def test_save_and_execution_claims_are_distinct(self):
        self.assertIn("Pause saved locally", HTML)
        self.assertIn("agent receipt and execution are unverified", HTML)


if __name__ == "__main__":
    unittest.main()
