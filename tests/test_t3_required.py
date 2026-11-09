"""T3 is a prerequisite: setup reports it missing, --check fails without it, offers need a yes, decline still finishes."""
import argparse, contextlib, importlib.machinery, importlib.util, io, os, stat, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent


def load():
    loader = importlib.machinery.SourceFileLoader("t3_required_test", str(REPO / "bin/atr"))
    spec = importlib.util.spec_from_loader("t3_required_test", loader)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def ns(**kw):
    base = dict(check=False, yes=False, no_maintainer=True, recreate_maintainer=False, no_skills=True, no_service=True, skip_t3=False)
    base.update(kw)
    return argparse.Namespace(**base)


class T3Required(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.tr = load()
        self.tr.ROOT, self.tr.ROOMS, self.tr.TEMPLATES = root, root / "rooms", REPO / "template"
        self.tr.ROOMS.mkdir()
        self.calls = []
        self.tr.t3_install = lambda: self.calls.append("install") or False
        self.tr.t3_start = lambda wait=20: self.calls.append("start") or False
        self.env = patch.dict(os.environ, {"HOME": str(root / "home"), "ATR_SERVICE": "off", "PATH": "/usr/bin:/bin",
                                           "T3CODE_CLI_PATH": str(root / "no-such-t3")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.env.stop(); self.env.start()
        os.environ.pop("ATR_INSTALLER", None)

    def run_cmd(self, a):
        out = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), patch("sys.stdin.isatty", return_value=False):
            try:
                self.tr.cmd_setup(a)
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        return code, out.getvalue()

    def fake_t3(self):
        p = Path(self.tmp.name) / "t3"
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
        os.environ["T3CODE_CLI_PATH"] = str(p)

    def test_setup_finishes_and_reports_missing(self):
        code, out = self.run_cmd(ns())
        self.assertEqual(code, 0)
        self.assertTrue((self.tr.ROOMS / self.tr.PROCESS_ROOM).exists())
        self.assertIn("T3 is required", out)
        self.assertIn("T3CODE_CLI_PATH", out)
        self.assertIn("docs/SETUP.md", out)
        self.assertLess(len(self.tr.T3_MISSING.splitlines()), 3)
        self.assertEqual(self.calls, [])          # no terminal, no --yes: nothing installed or started

    def test_check_fails_without_t3_and_skip_passes(self):
        self.run_cmd(ns())
        code, out = self.run_cmd(ns(check=True))
        self.assertEqual(code, 1)
        self.assertNotIn("setup ok", out)
        self.assertIn("T3CODE_CLI_PATH", out)
        code, out = self.run_cmd(ns(check=True, skip_t3=True))
        self.assertEqual(code, 0)
        self.assertIn("setup ok", out)

    def test_check_unchanged_with_t3(self):
        self.fake_t3()
        self.run_cmd(ns())
        code, out = self.run_cmd(ns(check=True))
        self.assertEqual(code, 0)
        self.assertIn("setup ok", out)

    def test_yes_offers_install_then_declined_outcome_still_finishes(self):
        code, out = self.run_cmd(ns(yes=True))       # install fails (fake)
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, ["install"])
        self.assertIn("T3 is required", out)

    def test_yes_installs_then_starts(self):
        def install():
            self.calls.append("install"); self.fake_t3(); return True
        self.tr.t3_install = install
        self.tr.t3_responds = lambda: False
        self.tr.t3_start = lambda wait=20: self.calls.append("start") or True
        code, out = self.run_cmd(ns(yes=True))
        self.assertEqual(self.calls, ["install", "start"])
        self.assertNotIn("T3 is required", out)

    def test_interactive_no_declines(self):
        self.tr.ASK = lambda q: "n"
        with patch("sys.stdin.isatty", return_value=True):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.tr.cmd_setup(ns())
        self.assertEqual(self.calls, [])
        self.assertIn("T3 is required", out.getvalue())

    def test_t3_probes_are_false_without_t3(self):
        self.assertFalse(self.tr.t3_configured())
        self.assertFalse(self.tr.t3_responds())


if __name__ == "__main__":
    unittest.main()
