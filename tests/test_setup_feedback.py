"""Setup + feedback: process room, maintainer config, dedupe, nudge, /api/state fields.
Temp atr root and temp HOME; fake launcher, fake T3 lookups and sends: no real thread or room is touched.
Run: python3 -m unittest tests.test_setup_feedback
"""
import argparse, contextlib, importlib.machinery, importlib.util, io, os, shutil, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

TID = "11111111-aaaa-bbbb-cccc-000000000001"


def ns(**kw):
    base = dict(check=False, print_env=False, yes=False, no_maintainer=False, recreate_maintainer=False)
    base.update(kw)
    return argparse.Namespace(**base)


def fb(text, room="quiet", doc="PROTOCOL", **kw):
    return argparse.Namespace(text=text, doc=doc, from_room=room, cites=kw.get("cites"),
                              from_thread=kw.get("from_thread"), by="Tester", blocks=kw.get("blocks"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        shutil.copytree(REPO / "template", root / "template")
        self.saved = (tr.ROOMS, tr.TEMPLATES, tr.ROOT, tr.LAUNCH_MAINTAINER, tr.ASK, tr.fetch_thread, tr.tell_thread,
                      os.environ.get("HOME"), os.environ.pop("ATR_MAINTAINER_THREAD", None))
        tr.ROOMS, tr.TEMPLATES, tr.ROOT = root / "rooms", root / "template", root
        tr.ROOMS.mkdir()
        os.environ["HOME"] = str(root / "home")
        self.addCleanup(lambda v=os.environ.get("ATR_SERVICE"): os.environ.__setitem__("ATR_SERVICE", v) if v is not None
                        else os.environ.pop("ATR_SERVICE", None))
        os.environ["ATR_SERVICE"] = "off"     # never touch the real systemd/launchd
        # keep a real T3 CLI on this machine out of the tests: atr also looks for `t3` on PATH
        for k in ("PATH", "T3CODE_CLI_PATH"):
            self.addCleanup(lambda k=k, v=os.environ.get(k): os.environ.__setitem__(k, v) if v is not None
                            else os.environ.pop(k, None))
        os.environ.pop("T3CODE_CLI_PATH", None)
        os.environ["PATH"] = os.pathsep.join(d for d in os.environ.get("PATH", "").split(os.pathsep)
                                             if d and not os.path.exists(os.path.join(d, "t3")))
        self.launched, self.sent, self.alive = [], [], {TID}
        def launch(prompt):
            self.launched.append(prompt)
            return TID
        tr.LAUNCH_MAINTAINER = launch
        tr.ASK = lambda q: self.answer
        self.answer = "y"
        tr.fetch_thread = lambda t: {"status": "idle"} if t in self.alive else None
        tr.tell_thread = lambda t, text: self.sent.append((t, text)) or True

    def tearDown(self):
        (tr.ROOMS, tr.TEMPLATES, tr.ROOT, tr.LAUNCH_MAINTAINER, tr.ASK, tr.fetch_thread, tr.tell_thread, home, env) = self.saved
        os.environ["HOME"] = home
        if env is not None:
            os.environ["ATR_MAINTAINER_THREAD"] = env
        self.tmp.cleanup()

    def run_cmd(self, fn, arg):
        out = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out):
            try:
                fn(arg)
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    out.write(e.code)
        return code, out.getvalue()

    def cfg(self, name):
        return tr.config_dir() / name


class SetupTests(Base):
    def test_yes_creates_room_thread_and_config(self):
        code, out = self.run_cmd(tr.cmd_setup, ns(yes=True))
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.launched), 1)
        self.assertIn("PROTOCOL.md", self.launched[0])
        self.assertIn("skills/lead/SKILL.md", self.launched[0])
        self.assertNotIn("skills/maintainer", self.launched[0])
        self.assertEqual(self.cfg("maintainer_thread").read_text().strip(), TID)
        self.assertIn('"maintainer": true', self.cfg("setup.json").read_text())
        room = tr.Room("process")
        self.assertEqual(room.brief["lead_thread"], TID)
        self.assertIn("waived", room.brief["prd"])
        self.assertEqual(room.title, tr.PROCESS_TITLE)

    def test_waiver_is_saved_without_optional_template_fields(self):
        template = tr.TEMPLATES / "brief.md"
        template.write_text("\n".join(line for line in template.read_text().split("\n")
                                      if not line.startswith(("slack:", "standing:"))))
        code, output = self.run_cmd(tr.cmd_setup, ns(no_maintainer=True))
        self.assertEqual(code, 0, output)
        room = tr.Room("process")
        self.assertEqual(room.brief["prd"], f"waived ({tr.PROCESS_WAIVE})")
        self.assertFalse(room.build_locked)
        self.assertEqual(room.title, tr.PROCESS_TITLE)

    def test_idempotent(self):
        self.run_cmd(tr.cmd_setup, ns(yes=True))
        code, out = self.run_cmd(tr.cmd_setup, ns())
        self.assertEqual(code, 0)
        self.assertEqual(len(self.launched), 1)          # no second thread
        self.assertEqual(tr.Room("process").brief["lead_thread"], TID)

    def test_no_maintainer_recorded_and_not_asked_again(self):
        self.run_cmd(tr.cmd_setup, ns(no_maintainer=True))
        self.assertEqual(self.launched, [])
        self.assertFalse(self.cfg("maintainer_thread").exists())
        tr.ASK = lambda q: self.fail("asked twice")
        code, _ = self.run_cmd(tr.cmd_setup, ns())
        self.assertEqual(code, 0)
        self.assertEqual(self.run_cmd(tr.cmd_setup, ns(check=True))[0], 0)

    def test_interactive_answer_is_recorded(self):
        tr.sys = type("S", (), {"stdin": type("I", (), {"isatty": lambda s: True})(), "exit": sys.exit, "stderr": sys.stderr, "executable": sys.executable})
        try:
            self.answer = "n"
            self.run_cmd(tr.cmd_setup, ns())
        finally:
            tr.sys = sys
        self.assertIn('"maintainer": false', self.cfg("setup.json").read_text())
        self.assertEqual(self.launched, [])

    def test_no_terminal_and_no_flag_records_nothing(self):
        code, out = self.run_cmd(tr.cmd_setup, ns())
        self.assertEqual(code, 0)
        self.assertIn("not asked", out)
        self.assertFalse(self.cfg("setup.json").exists())

    def test_check_reports_missing_then_ok(self):
        code, out = self.run_cmd(tr.cmd_setup, ns(check=True))
        self.assertEqual(code, 1)
        self.assertIn("room process is missing", out)
        self.assertFalse(tr.ROOMS.joinpath("process").exists())          # --check changes nothing
        self.run_cmd(tr.cmd_setup, ns(yes=True))
        self.assertEqual(self.run_cmd(tr.cmd_setup, ns(check=True))[0], 0)

    def test_check_dead_thread_says_how_to_recreate(self):
        self.run_cmd(tr.cmd_setup, ns(yes=True))
        self.alive.clear()
        code, out = self.run_cmd(tr.cmd_setup, ns(check=True))
        self.assertEqual(code, 0)
        self.assertIn("local records remain usable", out)

    def test_recreate_replaces_thread(self):
        self.run_cmd(tr.cmd_setup, ns(yes=True))
        new = "22222222-aaaa-bbbb-cccc-000000000002"
        tr.LAUNCH_MAINTAINER = lambda prompt: new
        self.run_cmd(tr.cmd_setup, ns(recreate_maintainer=True))
        self.assertEqual(self.cfg("maintainer_thread").read_text().strip(), new)
        self.assertEqual(tr.Room("process").brief["lead_thread"], new)

    def test_launch_failure_exits_nonzero_and_keeps_choice(self):
        def boom(prompt):
            raise RuntimeError("t3 not runnable")
        tr.LAUNCH_MAINTAINER = boom
        code, out = self.run_cmd(tr.cmd_setup, ns(yes=True))
        self.assertEqual(code, 1)
        self.assertIn("--recreate-maintainer", out)
        self.assertFalse(self.cfg("maintainer_thread").exists())

    def test_resolution_order(self):
        self.assertEqual(tr.maintainer_thread(), ("", ""))
        tr.create_room_files(tr.ROOMS / "process", "P", "procthread-001", "x", tr.now())
        self.assertEqual(tr.maintainer_thread()[0], "procthread-001")
        self.cfg("maintainer_thread").parent.mkdir(parents=True)
        self.cfg("maintainer_thread").write_text("filethread-001\n")
        self.assertEqual(tr.maintainer_thread()[0], "filethread-001")
        os.environ["ATR_MAINTAINER_THREAD"] = "envthread-0001"
        try:
            self.assertEqual(tr.maintainer_thread()[0], "envthread-0001")
        finally:
            del os.environ["ATR_MAINTAINER_THREAD"]

    def test_real_launcher_is_not_called(self):
        self.assertIsNot(tr.LAUNCH_MAINTAINER, tr.t3_launch_maintainer)


    def test_path_note_quiet_once_install_sh_wrote_the_rc_block(self):
        self.addCleanup(setattr, tr, "on_path", tr.on_path); tr.on_path = lambda: False
        self.addCleanup(os.environ.__setitem__, "SHELL", os.environ.get("SHELL", ""))
        os.environ["SHELL"] = "/bin/bash"
        self.assertIn("install.sh", tr.path_note()[0])
        home = Path(os.environ["HOME"]); home.mkdir(parents=True, exist_ok=True)
        (home / ".bashrc").write_text(f"{tr.RC_BEGIN}\nalias atr='x'\n# <<< atr <<<\n")
        self.assertEqual(tr.path_note(), [])

    def test_t3_cli_finds_the_cli_installers_symlink(self):
        saved = os.environ.pop("T3CODE_CLI_PATH", None)
        self.addCleanup(lambda: saved is not None and os.environ.__setitem__("T3CODE_CLI_PATH", saved))
        home = Path(os.environ["HOME"])
        (home / ".local/bin").mkdir(parents=True)
        (home / ".local/bin/t3").write_text("")
        self.assertEqual(tr.t3_cli(), str(home / ".local/bin/t3"))
        (home / ".t3/bin").mkdir(parents=True)
        (home / ".t3/bin/t3").write_text("")
        self.assertEqual(tr.t3_cli(), str(home / ".t3/bin/t3"))
        os.environ["T3CODE_CLI_PATH"] = "/explicit/t3"
        self.assertEqual(tr.t3_cli(), "/explicit/t3")
        del os.environ["T3CODE_CLI_PATH"]

    def test_path_note_only_when_atr_is_not_on_path(self):
        import shutil
        saved = shutil.which
        try:
            shutil.which = lambda n: None
            self.assertEqual(len(tr.path_note()), 1)
            shutil.which = lambda n: str(Path(tr.__file__))
            self.assertEqual(tr.path_note(), [])
        finally:
            shutil.which = saved

    def test_print_env_prints_per_shell_lines_and_changes_nothing(self):
        for shell, first in (("fish", "set -gx ATR_DATA_DIR "), ("zsh", "export ATR_DATA_DIR="), ("bash", "export ATR_DATA_DIR=")):
            code, out = self.run_cmd(tr.cmd_setup, ns(print_env=shell))
            self.assertEqual(code, 0)
            self.assertTrue(out.startswith(first), out)
            self.assertIn("atr", out)
            self.assertIn(f"completions/atr.{shell}", out)
        self.assertFalse((tr.ROOMS / tr.PROCESS_ROOM).exists())

    def test_print_env_defaults_to_shell_env_and_bash_for_unknown(self):
        saved = os.environ.get("SHELL")
        try:
            os.environ["SHELL"] = "/usr/bin/fish"
            self.assertTrue(tr.env_snippet()[0].startswith("set -gx"))
            os.environ["SHELL"] = "/bin/tcsh"
            self.assertTrue(tr.env_snippet()[0].startswith("export"))
        finally:
            os.environ.pop("SHELL") if saved is None else os.environ.__setitem__("SHELL", saved)

    def test_check_still_ok_with_path_note(self):
        self.run_cmd(tr.cmd_setup, ns(no_maintainer=True))
        code, out = self.run_cmd(tr.cmd_setup, ns(check=True))
        self.assertEqual(code, 0)
        self.assertIn("setup ok", out)


class FeedbackTests(Base):
    def setUp(self):
        super().setUp()
        self.run_cmd(tr.cmd_setup, ns(yes=True))
        self.sent.clear()

    def test_no_process_room(self):
        shutil.rmtree(tr.ROOMS / "process")
        code, out = self.run_cmd(tr.cmd_feedback, fb("x"))
        self.assertEqual(code, 1)
        self.assertIn("bin/atr setup", out)

    def test_creates_item_and_nudges(self):
        code, out = self.run_cmd(tr.cmd_feedback, fb("The lead skill never says when to close a room.", cites="notes/D05"))
        self.assertEqual((code, out.strip()), (0, "T01"))
        r = tr.Room("process").items[0]
        self.assertEqual((r["owner"], r["state"]), ("maintainer", "todo"))
        self.assertIn("never says when to close", r.section("Feedback"))
        self.assertEqual(tr.feedback_field(r, "doc"), "PROTOCOL")
        self.assertEqual(tr.feedback_field(r, "from"), "quiet")
        self.assertEqual(tr.feedback_field(r, "cites"), "notes/D05")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0], TID)

    def test_dedupe_same_room_within_24h_only(self):
        self.run_cmd(tr.cmd_feedback, fb("Same  text"))
        code, out = self.run_cmd(tr.cmd_feedback, fb("same text"))
        self.assertIn("T01", out)
        self.assertEqual(len(tr.Room("process").items), 1)
        self.assertEqual(len(self.sent), 1)                                  # no second nudge
        self.run_cmd(tr.cmd_feedback, fb("same text", room="other"))        # other room: new item
        self.assertEqual(len(tr.Room("process").items), 2)
        r = tr.Room("process").items[0]
        r.set("created", "2020-01-01T00:00Z")
        r.save()
        self.run_cmd(tr.cmd_feedback, fb("same text"))                      # older than 24 h: new item
        self.assertEqual(len(tr.Room("process").items), 3)

    def test_no_nudge_when_setup_said_no(self):
        self.run_cmd(tr.cmd_setup, ns(no_maintainer=True))
        self.sent.clear()
        self.run_cmd(tr.cmd_feedback, fb("kept anyway"))
        self.assertEqual(len(tr.Room("process").items), 1)
        self.assertEqual(self.sent, [])

    def test_no_nudge_without_thread(self):
        self.cfg("maintainer_thread").unlink()
        tr.set_lead_thread(tr.ROOMS / "process", "")
        self.run_cmd(tr.cmd_feedback, fb("no one to tell"))
        self.assertEqual(self.sent, [])
        self.assertEqual(len(tr.Room("process").items), 1)

    def test_counts(self):
        for i in range(4):
            self.run_cmd(tr.cmd_feedback, fb(f"point {i}"))
        room = tr.Room("process")
        for rec, o in zip(room.items[:3], ("accepted", "rejected", "deferred")):
            rec.set("outcome", o)
            rec.save()
        old = room.items[0]
        c = tr.feedback_counts(tr.Room("process"))
        self.assertEqual({k: c[k] for k in ("open", "accepted", "rejected", "deferred")},
                         {"open": 1, "accepted": 1, "rejected": 1, "deferred": 1})
        later = tr.now() + __import__("datetime").timedelta(days=8)
        c = tr.feedback_counts(tr.Room("process"), later)
        self.assertEqual((c["accepted"], c["open"]), (0, 1))

    def test_api_state_fields_only_for_process_room(self):
        self.run_cmd(tr.cmd_feedback, fb("one"))
        saved = (tr.thread_info,)
        tr.thread_info = lambda t: None
        try:
            st = tr.room_json(tr.Room("process"))
        finally:
            tr.thread_info, = saved
        self.assertEqual(st["feedback"]["open"], 1)


class BlocksTests(Base):
    """Feedback --blocks room/item."""
    def setUp(self):
        super().setUp()
        self.run_cmd(tr.cmd_setup, ns(yes=True))
        d = tr.ROOMS / "app"
        (d / "items").mkdir(parents=True)
        (d / "decisions").mkdir()
        (d / "BRIEF.md").write_text("---\ntitle: Launch\nlead_thread: LEAD0001abc\n---\n")
        (d / "items" / "T07-ship.md").write_text("---\nid: T07\ntitle: Ship\nstate: doing\nowner: lead\ndepends_on: []\n"
                                                "locks: []\nupdated: 2026-01-01T00:00Z\n---\n## Log\n- 00:00Z x: set state=doing\n")
        self.deferred = []
        self.saved_t = tr.tell_lead_or_defer
        tr.tell_lead_or_defer = lambda room, text, thread=None: self.deferred.append((room.name, text)) or True
        self.run_cmd(tr.cmd_feedback, fb("plain one"))
        self.sent.clear()

    def tearDown(self):
        tr.tell_lead_or_defer = self.saved_t
        super().tearDown()

    def test_records_blocks_and_pings(self):
        code, out = self.run_cmd(tr.cmd_feedback, fb("Accessibility gaps", blocks="app/T07"))
        self.assertEqual((code, out.strip()), (0, "T02"))
        r = tr.Room("process").find("T02")
        self.assertEqual(r["blocks"], ["app/T07"])
        self.assertIn("BLOCKS app/T07", self.sent[0][1])

    def test_rejects_unknown_room_or_item_and_files_nothing(self):
        for bad in ("nope/T07", "launch/T99", "T07"):
            code, out = self.run_cmd(tr.cmd_feedback, fb("x " + bad, blocks=bad))
            self.assertEqual(code, 1, bad)
        self.assertEqual(len(tr.Room("process").items), 1)

    def test_attention_loud_while_blocked_item_open(self):
        self.run_cmd(tr.cmd_feedback, fb("Accessibility gaps", blocks="app/T07"))
        saved = (tr.thread_info, tr.thread_status)
        tr.thread_info = lambda t: None
        tr.thread_status = lambda t: None
        try:
            a = tr.attention_json(tr.Room("process"))
            self.assertTrue(a["attention_loud"])
            self.assertTrue(any(x["rule"] == "blocks" and x["id"] == "T02" for x in a["attention"]))
            b = tr.Room("app").find("T07"); b.set("state", "done"); b.save()
            self.assertFalse(tr.attention_json(tr.Room("process"))["attention_loud"])
        finally:
            tr.thread_info, tr.thread_status = saved

    def test_blocking_items_sort_first_in_status_and_plan(self):
        self.run_cmd(tr.cmd_feedback, fb("Accessibility gaps", blocks="app/T07"))
        p = tr.plan(tr.Room("process"))
        self.assertEqual([x["id"] for x in p["items"]], ["T02", "T01"])
        self.assertEqual(p["items"][0]["blocks"], ["app/T07"])
        self.assertEqual(p["items"][1]["blocks"], [])
        self.assertIn("unstaffed", p["items"][0])
        room = tr.Room("process")
        for i in room.items:
            i.set("state", "doing"); i.save()
        _, lines = tr.render(tr.Room("process"))
        flight = [l for l in lines if l.startswith(("T01", "T02"))]
        self.assertTrue(flight[0].startswith("T02"))

    def test_done_or_outcome_taps_blocked_lead_once(self):
        self.run_cmd(tr.cmd_feedback, fb("Accessibility gaps", blocks="app/T07"))
        for pairs in (["state=done"], ["state=done"]):
            self.run_cmd(tr.cmd_set, argparse.Namespace(room="process", id="T02", pairs=pairs, force=False, by="M"))
        self.assertEqual(self.deferred, [("app", "process/T02 resolved: app/T07 may proceed")])
        self.run_cmd(tr.cmd_feedback, fb("Another", blocks="app/T07"))
        self.run_cmd(tr.cmd_set, argparse.Namespace(room="process", id="T03", pairs=["outcome=rejected"], force=False, by="M"))
        self.assertEqual(len(self.deferred), 2)

    def test_no_tap_when_blocked_item_already_done(self):
        self.run_cmd(tr.cmd_feedback, fb("Accessibility gaps", blocks="app/T07"))
        b = tr.Room("app").find("T07"); b.set("state", "done"); b.save()
        self.run_cmd(tr.cmd_set, argparse.Namespace(room="process", id="T02", pairs=["state=done"], force=False, by="M"))
        self.assertEqual(self.deferred, [])

    def _resolve(self, rid, next_line=None):
        if next_line:
            r = tr.Room("process").find(rid); r.append_to("Result", next_line); r.save()
        self.run_cmd(tr.cmd_set, argparse.Namespace(room="process", id=rid, pairs=["state=done"], force=False, by="M"))

    def test_successor_named_gets_block_and_one_message(self):
        self.run_cmd(tr.cmd_feedback, fb("Split me", blocks="app/T07"))   # T02
        self.run_cmd(tr.cmd_feedback, fb("Follow-up"))                      # T03
        self._resolve("T02", "Next: process T03")
        self.assertEqual(tr.Room("process").find("T03")["blocks"], ["app/T07"])
        self.assertFalse(tr.Room("process").find("T02")["unblocked_sent"])
        self.assertEqual(self.deferred, [("app", "process/T02 closed, the block moved to process/T03: app/T07 still waits")])
        self._resolve("T02")                                                # again: no duplicate
        self.assertEqual(len(self.deferred), 1)
        self._resolve("T03")                                                # successor resolves: usual rule
        self.assertEqual(self.deferred[-1], ("app", "process/T03 resolved: app/T07 may proceed"))

    def test_two_successors_both_carry_block(self):
        self.run_cmd(tr.cmd_feedback, fb("Split me", blocks="app/T07"))
        self.run_cmd(tr.cmd_feedback, fb("A")); self.run_cmd(tr.cmd_feedback, fb("B"))
        self._resolve("T02", "Next: T03 and T04")
        self.assertEqual([tr.Room("process").find(x)["blocks"] for x in ("T03", "T04")], [["app/T07"]] * 2)

    def test_no_successor_unchanged(self):
        self.run_cmd(tr.cmd_feedback, fb("Split me", blocks="app/T07"))
        self._resolve("T02", "Next: none (finished)")
        self.assertEqual(self.deferred, [("app", "process/T02 resolved: app/T07 may proceed")])

    def test_successor_already_done_is_not_a_successor(self):
        self.run_cmd(tr.cmd_feedback, fb("Split me", blocks="app/T07"))
        self.run_cmd(tr.cmd_feedback, fb("Old"))
        o = tr.Room("process").find("T03"); o.set("state", "done"); o.save()
        self._resolve("T02", "Next: T03")
        self.assertEqual(self.deferred, [("app", "process/T02 resolved: app/T07 may proceed")])
        self.assertEqual(tr.Room("process").find("T03")["blocks"] or [], [])

    def test_check_warns_when_successor_lacks_block(self):
        self.run_cmd(tr.cmd_feedback, fb("Split me", blocks="app/T07"))
        self.run_cmd(tr.cmd_feedback, fb("Follow-up"))
        r = tr.Room("process").find("T02"); r.append_to("Result", "Next: T03"); r.set("state", "done"); r.save()
        w = [p for p in tr.problems(tr.Room("process")) if "is its successor" in p]
        self.assertEqual(w, ["process/T02: resolved, T03 is its successor but does not block app/T07"])


if __name__ == "__main__":
    unittest.main()
