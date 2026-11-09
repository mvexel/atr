"""The web page as a user service: systemd --user and launchd through fake tools that record their calls.
Never touches the real service manager. Run: python3 -I -m unittest discover -s tests -p test_service.py
"""
import contextlib, importlib.machinery, importlib.util, io, os, plistlib, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
spec = importlib.util.spec_from_loader("tr_service", importlib.machinery.SourceFileLoader("tr_service", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)


class Service(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.calls = root / "calls"
        fake = root / "fakectl"
        fake.write_text(f'#!/bin/sh\necho "$@" >> "{self.calls}"\n'
                        'case "$*" in *is-active*) echo active ;; esac\nexit 0\n')
        fake.chmod(0o755)
        env = {"XDG_CONFIG_HOME": str(root / "cfg"), "HOME": str(root / "home"),
               "ATR_SYSTEMCTL": str(fake), "ATR_LAUNCHCTL": str(fake)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("ATR_SERVICE", None)
        self.saved_root = tr.ROOT
        tr.ROOT = root / "store"
        self.addCleanup(setattr, tr, "ROOT", self.saved_root)
        self.alive = True           # the server comes up once the service manager starts it
        self.hand_started = False   # something already answers on the port before any install
        def answers(*a, **k):
            started = any(" restart " in f" {c} " or c.startswith("bootstrap") for c in self.logged())
            return self.hand_started or (self.alive and started)
        for name in ("wait_alive", "web_alive"):
            p = mock.patch.object(tr, name, answers)
            p.start()
            self.addCleanup(p.stop)

    def logged(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def unit(self):
        return Path(os.environ["XDG_CONFIG_HOME"]) / "systemd/user/atr.service"

    def test_systemd_install_writes_unit_enables_and_starts(self):
        with mock.patch.object(tr.sys, "platform", "linux"):
            mark, line = tr.install_service(9001)
        self.assertEqual(mark, "ok", line)
        self.assertIn("http://127.0.0.1:9001/", line)
        text = self.unit().read_text()
        self.assertIn(f'"--data-dir" "{tr.ROOT}" "serve" "--host" "127.0.0.1" "--port" "9001"', text)
        self.assertIn("WantedBy=default.target", text)
        self.assertEqual(self.logged()[-3:], ["--user daemon-reload", "--user enable atr.service", "--user restart atr.service"])
        self.assertEqual(tr.web_port(), 9001)

    def test_install_says_when_a_hand_started_server_holds_the_port(self):
        self.hand_started = True
        with mock.patch.object(tr.sys, "platform", "linux"):
            mark, line = tr.install_service()
        self.assertEqual(mark, "warn")
        self.assertIn("already serves", line)

    def test_install_reports_when_nothing_answers(self):
        self.alive = False
        with mock.patch.object(tr.sys, "platform", "linux"):
            mark, line = tr.install_service()
        self.assertEqual(mark, "warn")
        self.assertIn("nothing answers", line)

    def test_uninstall_and_restart(self):
        with mock.patch.object(tr.sys, "platform", "linux"):
            self.assertIsNone(tr.restart_service())
            tr.install_service()
            self.assertEqual(tr.restart_service()[0], True)
            self.assertEqual(self.logged()[-1], "--user restart atr.service")
            mark, line = tr.uninstall_service()
        self.assertIn("removed", line)
        self.assertFalse(self.unit().exists())
        self.assertIn("--user disable --now atr.service", self.logged())

    def test_off_means_no_service_manager_and_no_files(self):
        os.environ["ATR_SERVICE"] = "off"
        mark, line = tr.install_service()
        self.assertEqual(mark, "warn")
        self.assertIn("atr open", line)
        self.assertFalse(self.unit().exists())
        self.assertEqual(self.logged(), [])

    def test_launchd_install_writes_agent_and_bootstraps(self):
        with mock.patch.object(tr.sys, "platform", "darwin"):
            mark, line = tr.install_service()
        self.assertEqual(mark, "ok", line)
        plist = Path(os.environ["HOME"]) / "Library/LaunchAgents/atr.web.plist"
        data = plistlib.loads(plist.read_bytes())
        self.assertEqual(data["Label"], "atr.web")
        self.assertTrue(data["RunAtLoad"] and data["KeepAlive"])
        self.assertEqual(data["ProgramArguments"][-5:], ["serve", "--host", "127.0.0.1", "--port", "8787"])
        self.assertTrue(any(c.startswith("bootstrap gui/") and c.endswith("atr.web.plist") for c in self.logged()))

    def test_open_prints_the_address_when_running(self):
        self.hand_started = True
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(tr.subprocess, "Popen") as popen:
            tr.cmd_open(type("A", (), {"no_browser": True})())
        popen.assert_not_called()
        self.assertEqual(out.getvalue().strip(), "http://127.0.0.1:8787/")

    def test_open_starts_a_background_server_without_a_service(self):
        self.alive = False
        state = {"n": 0}
        def wait(*a, **k):
            state["n"] += 1
            return True      # comes up after the spawn
        out = io.StringIO()
        os.environ["ATR_SERVICE"] = "off"
        with contextlib.redirect_stdout(out), mock.patch.object(tr.subprocess, "Popen") as popen, \
                mock.patch.object(tr, "wait_alive", wait):
            tr.cmd_open(type("A", (), {"no_browser": True})())
        argv = popen.call_args[0][0]
        self.assertEqual(argv[-5:], ["serve", "--host", "127.0.0.1", "--port", "8787"])
        self.assertIn("atr service install", out.getvalue())


if __name__ == "__main__":
    unittest.main()
