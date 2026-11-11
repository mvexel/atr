"""T3 test base: temp root, no real T3 CLI."""
import importlib.machinery, importlib.util, os, stat, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent


def load():
    loader = importlib.machinery.SourceFileLoader("t3_required_test", str(REPO / "bin/atr"))
    spec = importlib.util.spec_from_loader("t3_required_test", loader)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class T3Required(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.tr = load()
        self.tr.ROOT, self.tr.ROOMS, self.tr.TEMPLATES = root, root / "rooms", REPO / "template"
        self.tr.ROOMS.mkdir()
        self.calls = []
        self.env = patch.dict(os.environ, {"HOME": str(root / "home"), "ATR_SERVICE": "off", "PATH": "/usr/bin:/bin",
                                           "T3CODE_CLI_PATH": str(root / "no-such-t3")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.env.stop(); self.env.start()
        os.environ.pop("ATR_INSTALLER", None)

    def fake_t3(self):
        p = Path(self.tmp.name) / "t3"
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
        os.environ["T3CODE_CLI_PATH"] = str(p)

    def test_t3_probes_are_false_without_t3(self):
        self.assertFalse(self.tr.t3_configured())


if __name__ == "__main__":
    unittest.main()
