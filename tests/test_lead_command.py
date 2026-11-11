"""Copyable take-the-lead text: `atr lead ROOM` without a thread prints it; the state API carries it; the page can copy it."""
import contextlib, importlib.machinery, importlib.util, io, json, os, re, shlex, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HTML = (REPO / "web" / "index.html").read_text()
ATR = REPO / "bin" / "atr"


def load():
    loader = importlib.machinery.SourceFileLoader("atr_lead_cmd", str(ATR))
    spec = importlib.util.spec_from_loader("atr_lead_cmd", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class LeadCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "store with space"
        env = {**os.environ, "ATR_DATA_DIR": str(self.store), "XDG_CONFIG_HOME": self.tmp.name + "/cfg", "CLAUDE_CONFIG_DIR": self.tmp.name + "/claude", "CODEX_HOME": self.tmp.name + "/codex", "ATR_SERVICE": "off", "T3CODE_CLI_PATH": "/nonexistent"}
        self.env = env
        self.run_atr("rooms", "new", "demo", "Demo")

    def run_atr(self, *args):
        return subprocess.run([sys.executable, "-I", str(ATR), *args], capture_output=True, text=True, env=self.env)

    def test_cli_prints_both_forms_without_a_thread(self):
        r = self.run_atr("lead", "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Paste this into the T3 thread", r.stdout)
        self.assertIn("<your-thread-id>", r.stdout)
        self.assertIn("THREAD_ID", r.stdout)
        self.assertIn(shlex.quote(str(self.store)), r.stdout)       # explicit store, safely quoted
        self.assertIn(str(ATR), r.stdout)                            # explicit source, no PATH needed

    def test_unknown_room_is_refused(self):
        r = self.run_atr("lead", "nope")
        self.assertNotEqual(r.returncode, 0)

    def test_api_carries_it_per_room(self):
        mod = load()
        mod.ROOT = self.store
        mod.ROOMS = self.store / "rooms"
        c = mod.lead_commands("demo")
        self.assertTrue(c["terminal"].endswith(" lead demo THREAD_ID"))
        self.assertIn("lead demo <your-thread-id>", c["prompt"])
        self.assertIn("status demo", c["prompt"])

    def test_page_wiring(self):
        self.assertIn("leadCmdBox(r)", HTML)
        self.assertIn("Copy for a T3 thread", HTML)
        self.assertIn("Copy terminal command", HTML)
        self.assertIn('r.lead_thread ? "Hand over the lead" : "Take the lead"', HTML)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_terminal_text_fills_in_the_thread_id(self):
        block = re.search(r"// leadcmd:begin\n(.*?)// leadcmd:end", HTML, re.S).group(1)
        driver = block.split("async function copyText")[0] + """
const lc = { terminal: "python3 -I /a/atr --data-dir /s lead demo THREAD_ID" };
console.log(JSON.stringify([leadTerminal(lc, ""), leadTerminal(lc, "  abc12345 "), leadTerminal(lc, null)]));"""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "run.js"; f.write_text(driver)
            r = subprocess.run([shutil.which("node"), str(f)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        empty, filled, none = json.loads(r.stdout)
        self.assertTrue(empty.endswith("lead demo THREAD_ID"))
        self.assertTrue(filled.endswith("lead demo abc12345"))
        self.assertEqual(none, empty)


if __name__ == "__main__":
    unittest.main()
