"""install.sh: rc block written once, old block replaced, symlinked dotfile kept, nothing written without a yes.
Runs the real script against a temp HOME with a fake T3 CLI, so nothing is downloaded.
Run: python3 -m unittest tests.test_install
"""
import os, subprocess, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BEGIN = "# >>> atr >>>"


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / ".t3/bin").mkdir(parents=True)
        (self.home / ".t3/bin/t3").write_text("#!/bin/sh\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, shell, *args, piped=False, **extra):
        env = {k: v for k, v in os.environ.items() if k not in ("ATR_DATA_DIR", "XDG_DATA_HOME", "XDG_CONFIG_HOME",
                                                                "ZDOTDIR", "T3CODE_CLI_PATH")}
        env.update(HOME=str(self.home), SHELL=f"/bin/{shell}", **extra)
        if piped:       # like `curl ... | sh -s -- ARGS`, run from an unrelated directory
            return subprocess.run(["sh", "-s", "--", *args], env=env, input=(REPO / "install.sh").read_text(),
                                  cwd=self.home, capture_output=True, text=True, timeout=60)
        return subprocess.run([str(REPO / "install.sh"), *args], env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60)

    def test_yes_writes_block_once_and_runs_setup(self):
        rc = self.home / ".zshrc"
        rc.write_text("# mine\n")
        for _ in range(2):
            r = self.run_install("zsh", "--yes")
            self.assertEqual(r.returncode, 0, r.stderr)
        text = rc.read_text()
        self.assertTrue(text.startswith("# mine\n"))
        self.assertEqual(text.count(BEGIN), 1)
        self.assertIn("function atr { '", text)
        self.assertIn(f". '{REPO}/completions/atr.zsh'", text)
        self.assertIn(str(self.home / ".local/share/atr"), text)
        self.assertTrue((self.home / ".local/share/atr/rooms/process/BRIEF.md").exists())

    def test_old_block_replaced_and_symlink_kept(self):
        real = self.home / "dotfiles-bashrc"
        real.write_text(f"before\n{BEGIN}\nexport ATR_DATA_DIR='/old'\n# <<< atr <<<\nafter\n")
        (self.home / ".bashrc").symlink_to(real)
        self.assertEqual(self.run_install("bash", "--yes").returncode, 0)
        self.assertTrue((self.home / ".bashrc").is_symlink())
        text = real.read_text()
        self.assertNotIn("/old", text)
        self.assertEqual(text.count(BEGIN), 1)
        self.assertTrue(text.startswith("before\n") and text.endswith("after\n"))

    def test_fish_syntax(self):
        self.assertEqual(self.run_install("fish", "--yes").returncode, 0)
        text = (self.home / ".config/fish/config.fish").read_text()
        self.assertIn("set -gx ATR_DATA_DIR ", text)
        self.assertIn("function atr; '", text)
        self.assertIn(f"source '{REPO}/completions/atr.fish'", text)

    def test_no_terminal_without_yes_changes_no_rc(self):
        r = self.run_install("zsh")
        self.assertIn("not changed", r.stdout)
        self.assertFalse((self.home / ".zshrc").exists())

    def test_piped_install_then_uninstall_restores_rc_and_keeps_data(self):
        if subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True).returncode:
            self.skipTest("needs a committed checkout to clone")
        rc = self.home / ".zshrc"
        rc.write_text("# mine\nexport FOO=1\n")
        before = rc.read_text()
        r = self.run_install("zsh", "--yes", piped=True, ATR_REPO=f"file://{REPO}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        src = self.home / ".atr/src"
        self.assertTrue((src / "bin/atr").exists())
        self.assertIn(str(src / "bin/atr"), rc.read_text())
        data = self.home / ".local/share/atr"
        self.assertTrue(data.exists())
        # without a terminal or --yes, uninstall changes nothing
        r = self.run_install("zsh", "--uninstall", piped=True)
        self.assertIn("kept atr", r.stdout)
        self.assertTrue(src.exists())
        r = self.run_install("zsh", "--uninstall", "--yes", piped=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(rc.read_text(), before)
        self.assertFalse(src.exists())
        self.assertTrue(data.exists())

    def test_uninstall_leaves_a_checkout_alone(self):
        self.run_install("bash", "--yes")
        r = self.run_install("bash", "--uninstall", "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((REPO / "bin/atr").exists())
        self.assertNotIn(BEGIN, (self.home / ".bashrc").read_text())


if __name__ == "__main__":
    unittest.main()
