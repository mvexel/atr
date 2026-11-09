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


if __name__ == "__main__":
    unittest.main()
