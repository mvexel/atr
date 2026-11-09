"""A failed background refresh after a good load shows one persistent stale-data line.
Node runs the page's real helper code against a fake DOM; load()'s wiring is checked statically."""
import json, re, shutil, subprocess, tempfile, unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text()
BLOCK = re.search(r"// stale:begin\n(.*?)// stale:end", HTML, re.S).group(1)
LINE = "Can't reach the page's server. Showing data last loaded at %s. Trying again automatically."

DRIVER = """
const ActualDate = Date;
const clock = ActualDate.UTC(2026, 9, 27, 10, 0);
global.Date = class extends ActualDate {
  constructor(...args) { super(...(args.length ? args : [clock])); }
  static now() { return clock; }
};
const els = { stale: { hidden: true, textContent: "" } };
const $ = id => els[id];
const document = { body: { classList: { toggle(c, on) { this.on = on; } } } };
%s
const out = [];
const step = (failed) => { setStale(failed); out.push([els.stale.hidden, els.stale.textContent, document.body.classList.on]); };
step(true);                                   // failure before any good load: no line (initial-load path reports it)
lastOk = new Date(2026, 9, 27, 9, 5); step(true);    // fails: line, with the last good time
const first = els.stale.textContent;
step(true);                                   // repeated failure: same single line
step(false);                                  // 200 or 304 recovery clears it
step(true);                                   // fails again: shown again
lastOk = new Date(2020, 0, 2, 9, 5);                  // an old day: date and zone appear
step(true);
console.log(JSON.stringify({ out, first, other: staleText(new Date(2020, 0, 2, 9, 5), new Date(2026, 9, 27)) }));
"""


class Stale(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_line_text_and_clearing(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "run.js"
            f.write_text(DRIVER % BLOCK)
            r = subprocess.run([shutil.which("node"), str(f)], capture_output=True, text=True, env={"TZ": "UTC", "LANG": "en_US.UTF-8"})
        self.assertEqual(r.returncode, 0, r.stderr)
        j = json.loads(r.stdout)
        out = j["out"]
        self.assertTrue(out[0][0])                                   # hidden with no good load yet
        self.assertFalse(out[1][0])
        self.assertEqual(out[1][1], LINE % "09:05 AM")               # same-day: just the time of the last success
        self.assertEqual(out[2][1], out[1][1])
        self.assertTrue(out[3][0]); self.assertFalse(out[3][2])      # recovery hides it
        self.assertFalse(out[4][0])                                  # and it comes back on the next failure
        self.assertIn("Jan 2", out[5][1]); self.assertIn("UTC", out[5][1])

    def test_load_wiring(self):
        body = HTML[HTML.index("async function load(force)"):HTML.index("load(true).then")]
        # recovery is marked right after the status branch, before the unchanged-signature early return
        self.assertLess(body.index("setStale(false)"), body.index("if (same) return"))
        self.assertLess(body.index("} else if (!res.ok)") if "} else if (!res.ok)" in body else body.index("else if (!res.ok)"), body.index("setStale(false)"))
        self.assertIn("else setStale(true)", body)
        self.assertIn("if (!state) $(\"app\")", body)                # initial-load failure reporting unchanged

    def test_line_sits_outside_app(self):
        self.assertRegex(HTML, r'<p id="stale"[^>]*role="status"[^>]*hidden></p>\s*<main id="app">')


if __name__ == "__main__":
    unittest.main()
