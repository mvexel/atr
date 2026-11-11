"""Plan chips say "ready, no agent".
Node runs the page's real helpers; the server half is checked on tr.plan()."""
import json, re, shutil, subprocess, tempfile, unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text()
BLOCK = re.search(r"// flags:begin.*?\n(.*?)// flags:end", HTML, re.S).group(1)
DRIVER = """
%s
console.log(JSON.stringify({
  plain: flagChips({ id: "T1" }),
  idle: flagChips({ unstaffed: true }),
}));
"""


class Page(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_helpers(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "run.js"
            f.write_text(DRIVER % BLOCK)
            r = subprocess.run([shutil.which("node"), str(f)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        j = json.loads(r.stdout)
        self.assertEqual(j["plain"], [])
        self.assertEqual(j["idle"], [{"text": "ready, no agent", "cls": "unstaffed"}])

    def test_wiring(self):
        self.assertIn("flagEls({ unstaffed: x.unstaffed })", HTML)   # plan boxes


if __name__ == "__main__":
    unittest.main()
