"""`atr start "what you want"` starts a T3 lead thread with `t3 thread start`; no fake success.
Run: python3 -I -m unittest discover -s tests -p test_start_command.py
"""
import os, stat, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ATR = REPO / "bin" / "atr"


class StartCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "store"
        self.log = Path(self.tmp.name) / "t3.log"
        self.env = {**os.environ, "T3CODE_CLI_PATH": "/nonexistent"}

    def fake_t3(self, body):
        p = Path(self.tmp.name) / "t3"
        p.write_text("#!/bin/sh\n" + body)
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
        self.env["T3CODE_CLI_PATH"] = str(p)

    def atr(self, *args):
        return subprocess.run([sys.executable, "-I", str(ATR), "--data-dir", str(self.store), *args],
                              capture_output=True, text=True, env=self.env, cwd=self.tmp.name)

    def test_needs_a_description(self):
        r = self.atr("start")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("say what you want", r.stderr)

    def test_reports_t3_unavailable_without_fake_success(self):
        r = self.atr("start", "a settings page", "--project", "/some/project")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("lead thread not started", r.stderr)
        self.assertNotIn("lead thread started", r.stdout)

    def test_starts_the_thread_with_t3_thread_start(self):
        self.fake_t3(f'echo "$@" >> {self.log}\ncat >> {self.log}\necho \'{{"thread":{{"threadId":"lead-123"}}}}\'\n')
        r = self.atr("start", "a settings page", "--project", "/some/project", "--model", "m1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("lead thread started: lead-123", r.stdout)
        logged = self.log.read_text()
        self.assertIn("thread start /some/project - --json --model m1", logged)
        self.assertIn("atr-lead skill", logged)
        self.assertIn(f"--data-dir {self.store}", logged)
        self.assertIn("What I want:\na settings page", logged)

    def test_project_defaults_to_working_directory(self):
        self.fake_t3(f'echo "$@" >> {self.log}\ncat >/dev/null\necho \'{{"thread":{{"threadId":"x"}}}}\'\n')
        self.atr("start", "x")
        argv = self.log.read_text().split()
        self.assertEqual(Path(argv[2]).resolve(), Path(self.tmp.name).resolve())

    def test_t3_refusal_is_an_error(self):
        self.fake_t3("cat >/dev/null\necho 'no such project' >&2\nexit 3\n")
        r = self.atr("start", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no such project", r.stderr)


if __name__ == "__main__":
    unittest.main()
