"""Worker title convention in `t3 launch`, t3-thread links on the page payload, skill guidance.
Fake thread_info and queue; no T3 call. Run: python3 -I -m unittest tests.test_t3_titles_links
"""
import argparse, contextlib, importlib.machinery, importlib.util, io, os, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

THREAD = "worker-thread-0001"


class Titles(unittest.TestCase):
    def setUp(self):
        self.saved = tr.thread_info
        self.info = {}
        tr.thread_info = lambda t: self.info.get((t or "").strip())
        self.addCleanup(setattr, tr, "thread_info", self.saved)
        self.addCleanup(os.environ.pop, "ATR_T3_ENVIRONMENT", None)
        os.environ.pop("ATR_T3_ENVIRONMENT", None)

    def test_titles(self):
        self.assertEqual(tr.lead_title("r"), "Room · r · lead")
        self.assertEqual(tr.worker_title("r", "T05", "builder"), "r · T05 · builder")

    def test_role(self):
        self.assertEqual(tr.worker_role({"owner": "builder (Sam)"}), "builder")
        self.assertEqual(tr.worker_role({"owner": ""}), "worker")
        self.assertEqual(tr.worker_role({"owner": "x"}, "Code Reviewer"), "code-reviewer")

    def test_link_needs_env(self):
        self.assertIsNone(tr.t3_thread_link(THREAD))
        self.info[THREAD] = {"env": "env-1"}
        self.assertEqual(tr.t3_thread_link(THREAD), f"https://app.t3.codes/threads/env-1/{THREAD}")

    def test_link_env_fallback_and_bad(self):
        os.environ["ATR_T3_ENVIRONMENT"] = "env-2"
        self.assertEqual(tr.t3_thread_link(THREAD), f"https://app.t3.codes/threads/env-2/{THREAD}")
        self.assertIsNone(tr.t3_thread_link(""))
        os.environ["ATR_T3_ENVIRONMENT"] = "bad/env"
        self.assertIsNone(tr.t3_thread_link(THREAD))

    def test_web_link_encodes_provider_thread_id(self):
        thread = "mcp:11111111-aaaa-bbbb-cccc-000000000001"
        self.info[thread] = {"env": "env-1"}
        self.assertEqual(tr.t3_thread_link(thread), "https://app.t3.codes/threads/env-1/mcp%3A11111111-aaaa-bbbb-cccc-000000000001")

    def test_skill_and_page(self):
        skill = (REPO / "skills/lead/SKILL.md").read_text()
        for needle in ("Room · <room> · lead", "<room> · <item> · <role>", "t3-thread://v2/<env>/<thread>", "absolute path", "regenerate"):
            self.assertIn(needle, skill)
        page = (REPO / "web/index.html").read_text()
        self.assertIn("r.lead_link", page)
        self.assertIn("item.agent_link", page)


if __name__ == "__main__":
    unittest.main()
