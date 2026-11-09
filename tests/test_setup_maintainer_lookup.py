"""`atr setup` asks T3 about the maintainer thread before it takes the store lock, so a thread T3 knows is not
reported missing. Real CLI, fake `t3`. Run: python3 -I -m unittest discover -s tests -p test_setup_maintainer_lookup.py
"""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ATR = REPO / "bin" / "atr"
THREAD = "mcp:00000000-maintainer-thread"


class SetupMaintainerLookup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = root / "store"
        self.t3 = root / "t3"
        self.env = {**os.environ, "XDG_CONFIG_HOME": str(root / "cfg"), "CLAUDE_CONFIG_DIR": str(root / "claude"),
                    "CODEX_HOME": str(root / "codex"), "ATR_SERVICE": "off", "T3CODE_CLI_PATH": str(self.t3),
                    "ATR_MAINTAINER_THREAD": THREAD}
        self.atr("setup", "--no-maintainer")
        (self.store / ".atr/operator/setup.json").write_text(json.dumps({"maintainer": True, "asked": "2026-11-08T00:00Z"}))

    def atr(self, *args):
        r = subprocess.run([sys.executable, "-I", str(ATR), "--data-dir", str(self.store), *args],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def fake_t3(self, knows):
        reply = json.dumps({"thread": {"threadId": THREAD, "status": "idle", "settled": False}})
        body = f"echo '{reply}'" if knows else "echo 'not found' >&2; exit 1"
        self.t3.write_text(f"#!/bin/sh\ncase \"$1 $2\" in 'thread show') {body} ;; esac\n")
        self.t3.chmod(0o755)

    def test_known_thread_is_not_reported_missing(self):
        self.fake_t3(knows=True)
        out = self.atr("setup")
        self.assertIn(f"maintainer thread {THREAD}", out)
        self.assertNotIn("T3 does not find it", out)

    def test_unknown_thread_is_still_reported(self):
        self.fake_t3(knows=False)
        self.assertIn("T3 does not find it", self.atr("setup"))


if __name__ == "__main__":
    unittest.main()
