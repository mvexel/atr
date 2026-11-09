"""Without a T3 program the page says so, in words, and the state API reports it.
The page's real helper runs in node when installed; wiring is checked statically."""
import json, os, re, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "index.html").read_text()
BLOCK = re.search(r"// t3note:begin\n(.*?)// t3note:end", HTML, re.S).group(1)


class T3Note(unittest.TestCase):
    def test_wired_into_load_and_markup(self):
        self.assertIn('id="t3note"', HTML)
        self.assertIn("showT3Note(ns)", HTML)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_text_only_when_t3_is_missing(self):
        driver = BLOCK + """
const out = [t3NoteText({ t3: { configured: false } }), t3NoteText({ t3: { configured: true } }), t3NoteText({}), t3NoteText(null)];
console.log(JSON.stringify(out));"""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "run.js"; f.write_text(driver)
            r = subprocess.run([shutil.which("node"), str(f)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        miss, ok, unknown, none = json.loads(r.stdout)
        self.assertIn("will not act on anything you do here", miss[0])
        self.assertIn("Nothing is sent to agents", miss[1])
        self.assertIsNone(ok); self.assertIsNone(unknown); self.assertIsNone(none)   # silent when T3 is present or the field is absent

    def test_banner_sits_above_every_view(self):
        body = HTML.split("<body>", 1)[1]
        self.assertLess(body.index('id="t3note"'), body.index('id="app"'))   # outside #app: no view redraw hides it
        self.assertIn("Setup guide", BLOCK)
        self.assertIn("will not act on anything", BLOCK)

    def test_state_reports_where_atr_looked(self):
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader("atr_t3", str(ROOT / "bin" / "atr"))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("atr_t3", loader)); loader.exec_module(mod)
        old = os.environ.get("T3CODE_CLI_PATH")
        try:
            os.environ["T3CODE_CLI_PATH"] = "/nonexistent/t3"
            st = mod.t3_status()
            self.assertIs(st["configured"], False)
            self.assertEqual(st["location"], "/nonexistent/t3"); self.assertEqual(st["looked"], ["$T3CODE_CLI_PATH"])
            self.assertEqual(st["setting"], "T3CODE_CLI_PATH")
            with tempfile.TemporaryDirectory() as d:
                fake = Path(d) / "t3"; fake.write_text("#!/bin/sh\n"); fake.chmod(0o755)
                os.environ["T3CODE_CLI_PATH"] = str(fake)
                self.assertIs(mod.t3_status()["configured"], True)
        finally:
            if old is None: os.environ.pop("T3CODE_CLI_PATH", None)
            else: os.environ["T3CODE_CLI_PATH"] = old


if __name__ == "__main__":
    unittest.main()
