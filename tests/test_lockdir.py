"""Locks belong to the selected local store, shared by bin/atr and bin/with-lock.
Run: python3 -I -m unittest discover -s tests -p test_lockdir.py
"""
import os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class LockDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "atr"
        (self.repo / "bin").mkdir(parents=True)
        for f in ("atr", "with-lock"):
            shutil.copy(REPO / "bin" / f, self.repo / "bin" / f)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        self.data = self.tmp / "data"
        self.env = {k: v for k, v in os.environ.items() if k not in ("ATR_LOCKDIR", "ATR_DATA_DIR")}
        self.env["ATR_DATA_DIR"] = str(self.data)

    def lockdir(self, cwd, env=None):
        code = ("import importlib.machinery as m, importlib.util as u, sys;"
                "s=u.spec_from_loader('tr', m.SourceFileLoader('tr', sys.argv[1]));"
                "t=u.module_from_spec(s); s.loader.exec_module(t); print(t.LOCKDIR)")
        return subprocess.run([sys.executable, "-I", "-c", code, str(cwd / "bin" / "atr")],
                              capture_output=True, text=True, check=True, env=env or self.env).stdout.strip()

    def test_locks_are_in_the_selected_store(self):
        self.assertEqual(Path(self.lockdir(self.repo)).resolve(),
                         (self.data / ".atr/locks").resolve())

    def test_a_worktree_shares_the_main_repos_locks(self):
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                        "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "i"], check=True)
        wt = self.tmp / "wt"
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q", "--detach", str(wt)], check=True)
        shutil.copytree(self.repo / "bin", wt / "bin", dirs_exist_ok=True)
        self.assertEqual(Path(self.lockdir(wt)).resolve(), (self.data / ".atr/locks").resolve())

    def test_env_overrides(self):
        env = dict(self.env, ATR_LOCKDIR=str(self.tmp / "elsewhere"))
        self.assertEqual(self.lockdir(self.repo, env), str(self.tmp / "elsewhere"))

    @unittest.skipUnless(shutil.which("flock"), "flock not installed")
    def test_with_lock_uses_the_same_folder(self):
        subprocess.run([str(self.repo / "bin" / "with-lock"), "probe", "--", "true"], check=True, env=self.env,
                       capture_output=True)
        self.assertTrue((self.data / ".atr/locks/probe.lock").exists())

    @unittest.skipUnless(shutil.which("flock"), "flock not installed")
    def test_explicit_store_is_propagated_to_the_child(self):
        data = self.tmp / "explicit"
        result = subprocess.run([str(self.repo / "bin/with-lock"), "--data-dir", str(data), "probe", "--",
                                 sys.executable, "-I", "-c", "import os; print(os.environ['ATR_DATA_DIR'])"],
                                check=True, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), str(data))
        self.assertTrue((data / ".atr/locks/probe.lock").exists())


if __name__ == "__main__":
    unittest.main()
