"""`atr start "what you want"` queues a T3 launch of a lead thread that creates the room; no fake success.
Run: python3 -I -m unittest discover -s tests -p test_start_command.py
"""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ATR = REPO / "bin" / "atr"


class StartCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        self.env = {**os.environ, "XDG_CONFIG_HOME": self.tmp.name + "/cfg", "T3CODE_CLI_PATH": "/nonexistent",
                    "CLAUDE_CONFIG_DIR": self.tmp.name + "/claude", "CODEX_HOME": self.tmp.name + "/codex", "ATR_SERVICE": "off"}

    def tearDown(self):
        self.tmp.cleanup()

    def atr(self, *args):
        return subprocess.run([sys.executable, "-I", str(ATR), "--data-dir", str(self.store), *args],
                              capture_output=True, text=True, env=self.env, cwd=self.tmp.name)

    def test_needs_a_description(self):
        r = self.atr("start")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("say what you want", r.stderr)

    def test_queues_a_lead_launch_and_reports_t3_unavailable(self):
        r = self.atr("start", "a settings page", "--project", "/some/project")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("is failed", r.stdout)
        self.assertNotIn("lead thread started", r.stdout)
        actions = json.loads(self.atr("delivery", "list").stdout)
        (launch,) = [a for a in actions.values() if a["kind"] == "launch"]
        self.assertEqual(launch["target"], "/some/project")
        self.assertEqual(launch["options"]["purpose"], "lead")
        self.assertIn("atr-lead skill", launch["payload"])
        self.assertIn(f"--data-dir {self.store}", launch["payload"])
        self.assertTrue(launch["payload"].endswith("What I want:\na settings page"))

    def test_project_defaults_to_working_directory(self):
        self.atr("start", "x")
        actions = json.loads(self.atr("delivery", "list").stdout)
        (launch,) = [a for a in actions.values() if a["kind"] == "launch"]
        self.assertEqual(Path(launch["target"]).resolve(), Path(self.tmp.name).resolve())


if __name__ == "__main__":
    unittest.main()
