"""Shell completion: `atr __complete` reads the parser and the store; the bash/zsh/fish scripts only relay it.
Run: python3 -m unittest tests.test_completion
"""
import os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ATR = REPO / "bin" / "atr"


class Completion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Path(cls.tmp.name) / "store"
        cls.env = {**os.environ, "ATR_DATA_DIR": str(cls.store), "XDG_CONFIG_HOME": cls.tmp.name + "/cfg", "CLAUDE_CONFIG_DIR": cls.tmp.name + "/claude", "CODEX_HOME": cls.tmp.name + "/codex", "ATR_SERVICE": "off",
                   "T3CODE_CLI_PATH": "/nonexistent"}
        cls.run_atr("setup", "--no-maintainer")
        cls.run_atr("room", "new", "demo", "Demo project", "--waive-prd", "not a feature: test")
        cls.run_atr("new", "item", "demo", "first thing")
        cls.run_atr("new", "item", "demo", "second thing")
        cls.run_atr("new", "decision", "demo", "pick one", "--option", "a", "--option", "b")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def run_atr(cls, *args):
        r = subprocess.run([sys.executable, "-I", str(ATR), *args], capture_output=True, text=True, env=cls.env)
        assert r.returncode == 0, r.stderr
        return r.stdout

    def values(self, *words):
        return [line.split("\t")[0] for line in self.run_atr("__complete", *words).splitlines()]

    def test_commands_canonical_names_with_and_without_help(self):
        commands = self.values("")
        for name in ("new", "set", "room", "doctor", "completion"):
            self.assertIn(name, commands)
        self.assertNotIn("rooms", commands)              # alias still works, but is not offered
        self.assertNotIn("__complete", commands)
        self.assertEqual(self.values("se"), ["set", "serve", "setup", "service", "self-update"])

    def test_descriptions_ride_along(self):
        self.assertIn("room\tlist rooms, or start a feature room", self.run_atr("__complete", "ro").splitlines())

    def test_nested_subcommands_and_alias(self):
        self.assertEqual(self.values("room", ""), ["list", "new"])
        self.assertEqual(self.values("rooms", ""), ["list", "new"])

    def test_rooms_and_record_ids_from_the_store(self):
        self.assertEqual(self.values("set", ""), ["demo", "process"])
        self.assertEqual(self.values("set", "demo", ""), ["T01", "T02", "D01"])
        self.assertEqual(self.values("need", "demo", ""), ["T01", "T02"])
        self.assertEqual(self.values("answer", "demo", ""), ["D01"])
        self.assertIn("T01\tfirst thing", self.run_atr("__complete", "log", "demo", "T").splitlines())
        self.assertEqual(self.values("check", "demo", ""), ["process"])     # rooms already named are left out

    def test_option_values(self):
        self.assertEqual(self.values("new", "item", "demo", "x", "--type", "p"), ["premise", "prd"])
        self.assertEqual(self.values("new", "item", "demo", "x", "--depends", "T01,"), ["T01,T02"])
        self.assertEqual(self.values("--data-dir", "/"), [":dirs"])
        self.assertEqual(self.values("--data-dir", str(self.store), "set", ""), ["demo", "process"])

    def test_options_hide_suppressed_and_used(self):
        self.assertNotIn("--lock-directory", self.values("--"))
        self.assertEqual(self.values("setup", "--yes", "--y"), [])
        self.assertIn("--option", self.values("new", "decision", "demo", "x", "--option", "a", "--op"))

    def test_free_text_offers_nothing_and_unknown_command_is_quiet(self):
        self.assertEqual(self.values("new", "item", "demo", ""), [])
        self.assertEqual(self.values("bogus", ""), [])

    def test_completion_command_prints_each_script(self):
        for shell, name in (("bash", "atr.bash"), ("zsh", "atr.zsh"), ("fish", "atr.fish")):
            self.assertEqual(self.run_atr("completion", shell), (REPO / "completions" / name).read_text())

    def shell_env(self):
        bindir = Path(self.tmp.name) / "bin"
        bindir.mkdir(exist_ok=True)
        shim = bindir / "atr"
        shim.write_text(f"#!/bin/sh\nexec {sys.executable} -I {ATR} \"$@\"\n")
        shim.chmod(0o755)
        return {**self.env, "PATH": f"{bindir}:{os.environ['PATH']}"}

    @unittest.skipUnless(shutil.which("bash"), "bash not installed")
    def test_bash_script(self):
        script = (f"source {REPO / 'completions/atr.bash'}; COMP_WORDS=(atr set demo ''); COMP_CWORD=3; _atr; "
                  'echo "${COMPREPLY[*]}"')
        r = subprocess.run(["bash", "--norc", "-c", script], capture_output=True, text=True, env=self.shell_env())
        self.assertEqual(r.stdout.split(), ["T01", "T02", "D01"], r.stderr)

    @unittest.skipUnless(shutil.which("fish"), "fish not installed")
    def test_fish_script(self):
        script = f"source {REPO / 'completions/atr.fish'}; complete -C 'atr answer demo '"
        r = subprocess.run(["fish", "--no-config", "-c", script], capture_output=True, text=True,
                           env=self.shell_env(), timeout=30)
        self.assertEqual(r.stdout.splitlines(), ["D01\tpick one"], r.stderr)

    @unittest.skipUnless(shutil.which("zsh"), "zsh not installed")
    def test_zsh_script_registers(self):
        script = f"autoload -Uz compinit; compinit -u -d /dev/null; source {REPO / 'completions/atr.zsh'}; print $_comps[atr]"
        r = subprocess.run(["zsh", "-f", "-c", script], capture_output=True, text=True, env=self.shell_env())
        self.assertEqual(r.stdout.strip(), "_atr", r.stderr)


if __name__ == "__main__":
    unittest.main()
