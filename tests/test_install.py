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

    def run_install(self, shell, *args):
        env = {k: v for k, v in os.environ.items() if k not in ("ATR_DATA_DIR", "XDG_DATA_HOME", "XDG_CONFIG_HOME",
                                                                "ZDOTDIR", "T3CODE_CLI_PATH")}
        env.update(HOME=str(self.home), SHELL=f"/bin/{shell}")
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
        self.assertIn(f"alias atr='", text)
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
        self.assertIn("alias atr '", text)

    def test_no_terminal_without_yes_changes_no_rc(self):
        r = self.run_install("zsh")
        self.assertIn("not changed", r.stdout)
        self.assertFalse((self.home / ".zshrc").exists())


if __name__ == "__main__":
    unittest.main()
