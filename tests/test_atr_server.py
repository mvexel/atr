"""Tests for /api/answer: operator authorization, identity, stale revisions and idempotence.
A scratch repo in a temp dir holds a copy of bin/atr and one scratch room; no real room is touched.
Run: python3 -m unittest discover -s tests
"""
import hashlib, json, os, shutil, socket, stat, subprocess, sys, tempfile, time, unittest
import urllib.error, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DECISION = """---
id: D01
title: Which city first?
type: decision
door: two
decider: martijn
status: open
source: test
blocks: []
opened: 2026-10-26T10:00Z
updated: 2026-10-26T10:00Z
---
## Options
a) Zurich
b) Bern

## Why it matters
x

## Answer
"""


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="atr-t10-"))
        (cls.tmp / "bin").mkdir()
        shutil.copy(REPO / "bin" / "atr", cls.tmp / "bin" / "atr")
        shutil.copytree(REPO / "template", cls.tmp / "template")
        (cls.tmp / "web").mkdir()
        (cls.tmp / "web" / "index.html").write_text("<html></html>")
        cls.rooms = cls.tmp / "rooms"
        for n in range(1, 6):
            d = cls.rooms / "scratch" / "decisions"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"D0{n}-which-city-first.md").write_text(DECISION.replace("D01", f"D0{n}"))
        s = socket.socket(); s.bind(("127.0.0.1", 0)); cls.port = s.getsockname()[1]; s.close()
        env = {**os.environ, "ATR_DATA_DIR": str(cls.tmp), "ATR_USERS": "martijn@example.com", "ATR_LOCKDIR": str(cls.tmp / "locks"), "T3CODE_CLI_PATH": "/nonexistent"}
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

    def post(self, body, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/answer", json.dumps(body).encode(), h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def answer_text(self, i):
        return next((self.rooms / "scratch" / "decisions").glob(f"D0{i}-*.md")).read_text().split("## Answer")[1]

    def test_no_secret_rejected(self):
        code, _ = self.post({"room": "scratch", "id": "D01", "choice": "a"})
        self.assertEqual(code, 403)
        self.assertEqual(self.answer_text(1).strip(), "")

    def test_wrong_secret_rejected(self):
        code, _ = self.post({"room": "scratch", "id": "D01", "choice": "a"}, {"X-Notify-Secret": "nope"})
        self.assertEqual(code, 403)
        self.assertEqual(self.answer_text(1).strip(), "")

    def test_page_login_unchanged_and_ignores_by(self):
        code, res = self.post({"room": "scratch", "id": "D04", "choice": "b", "by": "mallory", "quote": "x"},
                              {"Tailscale-User-Login": "martijn@example.com"})
        self.assertEqual(code, 200)
        a = self.answer_text(4)
        self.assertIn("b · martijn ·", a)
        self.assertIn("tapped in atr web", a)
        self.assertNotIn("mallory", a)
        self.assertNotIn('"x"', a)


    def test_already_quote_empty_when_none(self):
        self.post({"room": "scratch", "id": "D03", "choice": "b"}, {"Tailscale-User-Login": "martijn@example.com"})
        _, res = self.post({"room": "scratch", "id": "D03", "choice": "a"}, {"Tailscale-User-Login": "martijn@example.com"})
        self.assertEqual(res["quote"], "")

    def test_already_after_page_tap_reports_page_answer(self):
        self.post({"room": "scratch", "id": "D03", "choice": "b"}, {"Tailscale-User-Login": "martijn@example.com"})
        code, res = self.post({"room": "scratch", "id": "D03", "choice": "a"}, {"Tailscale-User-Login": "martijn@example.com"})
        self.assertTrue(res["already"])
        self.assertEqual(res["choice"], "b")


    def test_stale_revision_returns_conflict_without_saving_an_answer(self):
        path = self.rooms / "scratch/decisions/D05-which-city-first.md"
        revision = hashlib.sha256(path.read_bytes()).hexdigest()
        path.write_text(path.read_text() + "\nNew supporting context.\n")
        code, body = self.post({"room": "scratch", "id": "D05", "choice": "a", "revision": revision},
                               {"Tailscale-User-Login": "martijn@example.com"})
        self.assertEqual(code, 409)
        self.assertTrue(body["conflict"])
        self.assertFalse(body["ok"])
        self.assertIn("status: open", path.read_text())

    def test_local_documents_keep_identity_and_symlink_containment(self):
        path = "rooms/scratch/decisions/D05-which-city-first.md"
        url = f"http://127.0.0.1:{self.port}/doc?file={path}"
        with self.assertRaises(urllib.error.HTTPError) as forbidden:
            urllib.request.urlopen(url)
        self.assertEqual(forbidden.exception.code, 403)
        request = urllib.request.Request(url, headers={"Tailscale-User-Login": "martijn@example.com"})
        with urllib.request.urlopen(request) as response:
            self.assertIn("Which city first?", response.read().decode())
        notes = self.rooms / "scratch/notes"
        notes.mkdir(exist_ok=True)
        outside = self.tmp / "outside.md"
        outside.write_text("synthetic private document")
        link = notes / "escape.md"
        link.symlink_to(outside)
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/doc?file=rooms/scratch/notes/escape.md",
                                         headers={"Tailscale-User-Login": "martijn@example.com"})
        with self.assertRaises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(request)
        self.assertEqual(missing.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
