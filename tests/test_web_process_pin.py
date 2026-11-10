"""The page's pinned Process row and 'How we work' view: static checks on web/index.html,
plus a syntax check of its script when node is available. Behaviour was viewed in headless Chrome (see the item Result)."""
import re, shutil, subprocess, tempfile, unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text()


class ProcessPin(unittest.TestCase):
    def test_pin_and_view_present(self):
        for needle in ['function settingsButton()', "How we work", "processBlocks", "leaveProcess", "r?.standing", "fbk[k]"]:
            self.assertIn(needle, HTML)

    def test_standing_room_is_separate_and_asks_count(self):
        self.assertIn("const reg = state.rooms.filter(x => !x.standing), byName", HTML)
        self.assertIn("state.rooms.reduce((n, x) => n + needN(x), 0)", HTML)   # decisions waiting on the owner

    def test_process_view_is_not_stored_as_the_room(self):
        self.assertIn('let processView = params.get("room") === "process"', HTML)
        self.assertIn("const inStd = processView && !!r?.standing", HTML)

    def test_palette_present_and_guards_redraws(self):
        # Ctrl-K / Cmd-K / "/" palette; behaviour was driven with real keys in headless Chrome
        for needle in ["palOpenSheet", "palChoose", "e.ctrlKey || e.metaKey", 'class: "palbtn"', "return settingsOpen || palOpen ||", 'id="pal"', '"ArrowDown"']:
            self.assertIn(needle, HTML)

    def test_palette_server_hits_and_process_blocks(self):
        # GET /api/search hits, docs chips, cap/agent on tooling rows
        for needle in ["api/search?q=", "palFetch", "PAL_ORDER", "r.docs", "i.cap_h", "h.file", "local documents"]:
            self.assertIn(needle, HTML)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_script_parses(self):
        js = re.search(r"<script>(.*)</script>", HTML, re.S).group(1)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "page.js"
            f.write_text("new Function(require('fs').readFileSync(process.argv[2], 'utf8'))")
            (Path(d) / "src.js").write_text(js)
            r = subprocess.run(["node", str(f), str(Path(d) / "src.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
