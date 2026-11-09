"""GET /api/search and the process-room state fields.
search_data is exercised against a scratch root (tr.ROOT/ROOMS patched); the HTTP route is exercised in a scratch repo
with a copy of bin/atr on a free port. No real room is read.
Run: python3 -I -m unittest tests.test_search
"""
import importlib.machinery, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, time, unittest
import urllib.parse, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

ITEM = "---\nid: T01\ntitle: Wake the lead\nstate: todo\nowner: lead\ncap_h: 2\nagent: abc\n---\n## Acceptance\n- [ ] ok\n\n## Result\nThe zebra crossed the road.\n"
DEC = "---\nid: D01\ntitle: Which city?\ntype: decision\nstatus: open\n---\n## Options\na) Zurich\nb) Bern\n"
SECRET = "zebra-outside-secret"


def populate(root):
    for rel, text in {
        "rooms/alpha/items/T01-wake.md": ITEM,
        "rooms/alpha/decisions/D01-city.md": DEC,
        "rooms/alpha/notes/n.md": "# Notes\n\n## Zebra plan\nwe saw a zebra here, with a long tail of words after it.\n",
        "rooms/alpha/wrapup/report.md": "zebra in wrapup (not in the globs)\n",
        "rooms/alpha/BRIEF.md": "zebra in brief (not in the globs)\n",
        "PROTOCOL.md": "# Protocol\n\n## Charters and staffing rules\nEvery zebra has a charter.\n",
        "skills/lead/SKILL.md": "# Lead\n\n## Staffing\nzebra row\n",
        "skills/lead/other.md": "zebra not SKILL.md\n",
        "docs/CHANGELOG.md": "# Changelog\n\nOne line each.\n\n2026-10-27 PROTOCOL.md zebra rule\n2026-10-27 other line\n",
        "rooms/process/notes/watching.md": "# Watching\n\n- First thing seen once.\n- Second thing.\nplain line\n",
    }.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


class SearchData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        populate(self.root)
        self.saved = (tr.ROOT, tr.ROOMS, tr.SOURCE_ROOT)
        tr.ROOT, tr.ROOMS, tr.SOURCE_ROOT = self.root, self.root / "rooms", self.root
        tr._search_cache.clear()

    def tearDown(self):
        tr.ROOT, tr.ROOMS, tr.SOURCE_ROOT = self.saved
        self.tmp.cleanup()

    def files(self, res):
        return {h["file"] for g in res["groups"].values() for h in g}

    def test_only_listed_globs(self):
        self.assertEqual(self.files(tr.search_data("zebra")), {
            "rooms/alpha/items/T01-wake.md", "rooms/alpha/notes/n.md", "PROTOCOL.md",
            "skills/lead/SKILL.md", "docs/CHANGELOG.md"})

    def test_groups_snippets_anchor(self):
        g = tr.search_data("zebra")["groups"]
        self.assertEqual(g["Items"][0]["id"], "T01")
        self.assertEqual(g["Items"][0]["room"], "alpha")
        self.assertEqual(g["Items"][0]["anchor"], "result")
        self.assertIn("zebra", g["Items"][0]["snippet"])
        self.assertEqual(g["Notes"][0]["anchor"], "zebra-plan")
        self.assertEqual(g["Rules"][0]["anchor"], "charters-and-staffing-rules")
        self.assertIn("PROTOCOL.md zebra rule", g["Changelog"][0]["snippet"])
        d = tr.search_data("zurich")["groups"]["Decisions"][0]
        self.assertEqual((d["id"], d["room"]), ("D01", "alpha"))

    def test_snippet_is_about_40_chars_each_side(self):
        s = tr.search_data("zebra")["groups"]["Notes"][0]["snippet"]
        self.assertLessEqual(len(s), 5 + 2 * 40 + 6)

    def test_cap_per_group_and_short_queries(self):
        for n in range(12):
            (self.root / "rooms/alpha/notes" / f"x{n}.md").write_text(f"## H{n}\nzebra {n}\n")
        res = tr.search_data("zebra")
        self.assertEqual(len(res["groups"]["Notes"]), 8)
        self.assertTrue(res["more"]["Notes"])
        self.assertEqual(tr.search_data("z")["groups"], {})
        self.assertEqual(tr.search_data("")["groups"], {})

    def test_title_match_ranks_first_and_is_case_insensitive(self):
        res = tr.search_data("WAKE")
        self.assertEqual(res["groups"]["Items"][0]["id"], "T01")

    def test_symlink_out_of_tree_is_not_read(self):
        outside = Path(tempfile.mkdtemp()) / "o.md"
        outside.write_text(SECRET + "\n")
        try:
            (self.root / "rooms/alpha/notes/link.md").symlink_to(outside)
            (self.root / "rooms/alpha/notes/dirlink").symlink_to(outside.parent)
            res = tr.search_data(SECRET)
            self.assertEqual(res["groups"], {})
        finally:
            shutil.rmtree(outside.parent)

    def test_query_with_path_chars_is_just_text(self):
        for q in ("../../etc/passwd", "/etc/passwd", "rooms/alpha/BRIEF.md", "*", "..\\x"):
            self.assertEqual(tr.search_data(q)["groups"], {})

    def test_cache_follows_file_changes(self):
        self.assertEqual(tr.search_data("quokka")["groups"], {})
        p = self.root / "rooms/alpha/notes/n.md"
        time.sleep(0.01)
        p.write_text("## New\nquokka\n")
        os.utime(p, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
        self.assertIn("Notes", tr.search_data("quokka")["groups"])


class StateFields(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        populate(self.root)
        self.saved = (tr.ROOT, tr.ROOMS, tr.SOURCE_ROOT)
        tr.ROOT, tr.ROOMS, tr.SOURCE_ROOT = self.root, self.root / "rooms", self.root

    def tearDown(self):
        tr.ROOT, tr.ROOMS, tr.SOURCE_ROOT = self.saved
        self.tmp.cleanup()

    def test_changelog_and_watching(self):
        f = tr.process_docs()
        self.assertEqual(f["changelog"], ["2026-10-27 PROTOCOL.md zebra rule", "2026-10-27 other line"])
        self.assertEqual(f["watching"], ["First thing seen once.", "Second thing."])
        self.assertEqual([d["file"] for d in f["docs"]], ["PROTOCOL.md", "skills/lead/SKILL.md", "PROTOCOL.md", "docs/CHANGELOG.md"])
        self.assertEqual(f["docs"][2]["anchor"], "charters-and-staffing-rules")

    def test_missing_files_give_empty_blocks(self):
        (self.root / "docs/CHANGELOG.md").unlink()
        (self.root / "rooms/process/notes/watching.md").unlink()
        f = tr.process_docs()
        self.assertEqual((f["changelog"], f["watching"]), ([], []))

    def test_open_counts_only_feedback_items(self):
        d = self.root / "rooms/process/items"
        d.mkdir(parents=True, exist_ok=True)
        (d / "T01-fb.md").write_text("---\nid: T01\ntitle: fb\nstate: todo\nowner: maintainer\nupdated: 2026-10-27T00:00Z\n---\n## Feedback\nx\n")
        (d / "T02-build.md").write_text("---\nid: T02\ntitle: build\nstate: doing\nowner: Tooling\nupdated: 2026-10-27T00:00Z\n---\n## Acceptance\n- [ ] x\n")
        c = tr.feedback_counts(tr.Room("process"))
        self.assertEqual(c["open"], 1)

    def test_lane_items_carry_cap_and_agent(self):
        st = tr.room_json(tr.Room("alpha"))
        it = st["lanes"][0]["items"][0]
        self.assertEqual((it["cap_h"], it["agent"]), ("2", "abc"))


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="atr-t07-"))
        (cls.tmp / "bin").mkdir()
        shutil.copy(REPO / "bin" / "atr", cls.tmp / "bin" / "atr")
        shutil.copytree(REPO / "template", cls.tmp / "template")
        (cls.tmp / "web").mkdir()
        (cls.tmp / "web" / "index.html").write_text("<html></html>")
        populate(cls.tmp)
        git = lambda *a: subprocess.run(["git", "-C", str(cls.tmp), *a], check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        git("add", "-A")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "scratch")
        s = socket.socket(); s.bind(("127.0.0.1", 0)); cls.port = s.getsockname()[1]; s.close()
        env = {**os.environ, "ATR_LOCKDIR": str(cls.tmp / "locks"), "T3CODE_CLI_PATH": "/nonexistent"}
        cls.proc = subprocess.Popen([sys.executable, str(cls.tmp / "bin" / "atr"), "serve", "--port", str(cls.port)],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port), 0.2).close(); break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate(); cls.proc.wait()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, qs):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/search?{qs}") as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_search_route(self):
        code, res = self.get("q=zebra")
        self.assertEqual(code, 200)
        self.assertIn("Items", res["groups"])

    def test_request_supplied_paths_are_ignored(self):
        code, res = self.get(urllib.parse.urlencode({"q": "zebra", "path": "/etc/passwd", "file": "../../x", "root": "/"}))
        self.assertEqual(code, 200)
        files = {h["file"] for g in res["groups"].values() for h in g}
        self.assertNotIn("rooms/alpha/BRIEF.md", files)
        self.assertNotIn("rooms/alpha/wrapup/report.md", files)
        code, res = self.get("q=" + urllib.parse.quote("../../../etc/passwd"))
        self.assertEqual((code, res["groups"]), (200, {}))
        code, res = self.get("")
        self.assertEqual((code, res["groups"]), (200, {}))

    def test_works_under_the_atr_prefix_and_is_get_only(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/atr/api/search?q=zebra") as r:
            self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()
