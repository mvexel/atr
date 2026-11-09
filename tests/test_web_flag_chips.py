"""Plan chips say "ready, no agent"; feedback that blocks an open item sorts first and is loud.
Node runs the page's real helpers; the server half is checked on tr.plan()."""
import json, re, shutil, subprocess, tempfile, unittest
from pathlib import Path
from test_dependency_plan import Base, tr

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text()
BLOCK = re.search(r"// flags:begin.*?\n(.*?)// flags:end", HTML, re.S).group(1)
DRIVER = """
%s
const fb = [{ id: "F1" }, { id: "F2" }, { id: "F3" }];
const flags = { F2: { blocks: ["a/T1"], blocks_open: ["a/T1"] }, F3: { blocks: ["a/T0"], blocks_open: [] } };
console.log(JSON.stringify({
  plain: flagChips({ id: "T1" }),
  idle: flagChips({ unstaffed: true }),
  mixed: flagChips({ blocks: ["a/T1", "a/T0"], blocks_open: ["a/T1"] }),
  order: feedbackFirst(fb, flags).map(i => i.id),
  none: feedbackFirst(fb, {}).map(i => i.id),
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
        self.assertEqual(j["mixed"], [{"text": "blocks a/T1", "cls": "blocks loud"}, {"text": "blocks a/T0", "cls": "blocks"}])
        self.assertEqual(j["order"], ["F2", "F1", "F3"])             # open blocker first, others keep their order
        self.assertEqual(j["none"], ["F1", "F2", "F3"])

    def test_wiring(self):
        self.assertIn("flagEls({ unstaffed: x.unstaffed })", HTML)   # plan boxes
        self.assertIn("feedbackFirst(feedback,", HTML)               # process feedback list
        self.assertIn("chip(i, extra(i), pf[i.id] &&", HTML)
        self.assertIn(".flag.loud", HTML)


class Server(Base):
    def test_plan_items_carry_blocks_open(self):
        room = self.room([("T01", {})])
        it = tr.plan(room)["items"][0]
        self.assertEqual(it["blocks"], [])
        self.assertEqual(it["blocks_open"], [])


if __name__ == "__main__":
    unittest.main()
