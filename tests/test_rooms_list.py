"""`atr room list`: one line per room with state and open counts; read-only; `atr rooms` remains compatible."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path

ATR = Path(__file__).resolve().parent.parent / "bin" / "atr"


class RoomsList(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "store"
        self.env = {**os.environ, "ATR_DATA_DIR": str(self.store), "XDG_CONFIG_HOME": self.tmp.name + "/cfg", "CLAUDE_CONFIG_DIR": self.tmp.name + "/claude", "CODEX_HOME": self.tmp.name + "/codex", "ATR_SERVICE": "off",
                    "T3CODE_CLI_PATH": "/nonexistent"}

    def atr(self, *args):
        r = subprocess.run([sys.executable, "-I", str(ATR), *args], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def snapshot(self):
        return {p: p.read_bytes() for p in (self.store / "rooms").rglob("*") if p.is_file()}

    def test_empty_store(self):
        self.assertIn("no rooms in", self.atr("room", "list"))

    def test_lists_rooms_with_state_and_counts(self):
        self.atr("setup", "--no-maintainer")
        self.atr("room", "new", "demo", "Demo project", "--waive-prd", "not a feature: test")
        self.atr("new", "item", "demo", "first")
        self.atr("new", "item", "demo", "second")
        self.atr("new", "decision", "demo", "pick one", "--option", "a", "--option", "b")
        before = self.snapshot()
        lines = self.atr("room", "list").splitlines()
        self.assertEqual(self.snapshot(), before)                       # writes nothing
        self.assertEqual(lines[0].split(), ["ROOM", "STATE", "ITEMS", "DECISIONS", "TITLE"])
        rows = {l.split()[0]: l.split(None, 4) for l in lines[1:]}
        self.assertEqual(rows["demo"], ["demo", "open", "2", "1", "Demo project"])
        self.assertEqual(rows["process"][1], "standing")

    def test_rooms_alias_still_creates(self):
        self.atr("rooms", "new", "old", "Old spelling", "--waive-prd", "not a feature: test")
        self.assertIn("old", self.atr("room", "list"))


if __name__ == "__main__":
    unittest.main()
