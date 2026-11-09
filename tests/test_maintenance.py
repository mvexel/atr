"""Diagnostics stay read-only; self-update fast-forwards only the running source."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest

REPO = Path(__file__).resolve().parent.parent


class Maintenance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.store = self.home / 'data'
        self.env = {**os.environ, 'HOME': str(self.home), 'ATR_DATA_DIR': str(self.store),
                    'XDG_CONFIG_HOME': str(self.home / 'config'), 'SHELL': '/bin/bash',
                    'T3CODE_CLI_PATH': str(self.home / 'missing-t3')}

    def cli(self, *args, source=REPO):
        return subprocess.run([sys.executable, '-I', str(source / 'bin/atr'), *args],
                              env=self.env, capture_output=True, text=True, timeout=30)

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd, env=self.env, capture_output=True,
                              text=True, check=True).stdout.strip()

    def test_doctor_missing_setup_does_not_create_store(self):
        result = self.cli('doctor')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('atr setup', result.stdout)
        self.assertIn('T3 unavailable', result.stdout)
        self.assertFalse(self.store.exists())

    def test_doctor_after_setup_changes_nothing(self):
        self.assertEqual(self.cli('setup', '--no-maintainer').returncode, 0)
        before = {str(p): p.read_bytes() for p in self.store.rglob('*') if p.is_file()}
        result = self.cli('doctor')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('doctor ok', result.stdout)
        self.assertIn('T3 execution has not been verified', result.stdout)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.store.rglob('*') if p.is_file()})

    def test_doctor_reports_invalid_data_path(self):
        self.store.write_text('not a directory')
        result = self.cli('doctor')
        self.assertEqual(result.returncode, 1)
        self.assertIn('data path is not a directory', result.stdout)
        self.assertNotIn('Traceback', result.stderr)

    def checkout(self):
        upstream = self.home / 'upstream'
        upstream.mkdir()
        for name in ('bin', 'template', 'web'):
            shutil.copytree(REPO / name, upstream / name, ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('install.sh', 'PROTOCOL.md'):
            shutil.copy2(REPO / name, upstream / name)
        self.git('init', '-b', 'main', cwd=upstream)
        self.git('config', 'user.email', 'test@example.com', cwd=upstream)
        self.git('config', 'user.name', 'Test', cwd=upstream)
        self.git('add', '.', cwd=upstream)
        self.git('commit', '-m', 'initial', cwd=upstream)
        installed = self.home / 'installed'
        self.git('clone', str(upstream), str(installed))
        return upstream, installed

    def test_self_update_fast_forwards_without_setup_or_rc_changes(self):
        upstream, installed = self.checkout()
        (upstream / 'release').write_text('new version')
        self.git('add', 'release', cwd=upstream)
        self.git('commit', '-m', 'release', cwd=upstream)
        rc = self.home / '.bashrc'
        rc.write_text('# keep me\n')
        result = self.cli('self-update', source=installed)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((installed / 'release').read_text(), 'new version')
        self.assertEqual(rc.read_text(), '# keep me\n')
        self.assertFalse(self.store.exists())

    def test_self_update_refuses_dirty_checkout(self):
        _, installed = self.checkout()
        script = installed / 'bin/atr'
        script.write_text(script.read_text() + '\n# local edit\n')
        result = self.cli('self-update', source=installed)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('local changes', result.stderr)
        self.assertTrue(script.read_text().endswith('# local edit\n'))

    def test_self_update_refuses_diverged_branch(self):
        upstream, installed = self.checkout()
        self.git('config', 'user.email', 'test@example.com', cwd=installed)
        self.git('config', 'user.name', 'Test', cwd=installed)
        for source, name in ((installed, 'local'), (upstream, 'remote')):
            (source / name).write_text(name)
            self.git('add', name, cwd=source)
            self.git('commit', '-m', name, cwd=source)
        before = self.git('rev-parse', 'HEAD', cwd=installed)
        result = self.cli('self-update', source=installed)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=installed), before)
        self.assertEqual((installed / 'local').read_text(), 'local')
        self.assertFalse((installed / 'remote').exists())

    def test_self_update_replaces_tarball_without_touching_data(self):
        installed = self.home / 'installed'
        (installed / 'bin').mkdir(parents=True)
        shutil.copy2(REPO / 'bin/atr', installed / 'bin/atr')
        shutil.copy2(REPO / 'install.sh', installed / 'install.sh')
        (installed / '.atr-tarball').touch()
        archive = self.home / 'release.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(installed, arcname='atr-main')
        fake_bin = self.home / 'fake-bin'
        fake_bin.mkdir()
        curl = fake_bin / 'curl'
        curl.write_text('#!/bin/sh\ncp "$RELEASE_ARCHIVE" "$4"\n')
        curl.chmod(0o755)
        self.env.update(PATH=str(fake_bin) + os.pathsep + os.environ['PATH'],
                        RELEASE_ARCHIVE=str(archive), ATR_HOME=str(self.home / '.atr'))
        (installed / 'old-file').write_text('removed in release')
        self.store.mkdir()
        (self.store / 'record.md').write_text('private record')
        result = self.cli('self-update', source=installed)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((installed / 'old-file').exists())
        self.assertTrue((installed / 'bin/atr').is_file())
        self.assertTrue((installed / '.atr-tarball').is_file())
        self.assertEqual((self.store / 'record.md').read_text(), 'private record')
        self.assertFalse((self.home / '.bashrc').exists())

    def test_tarball_update_refuses_legacy_data(self):
        installed = self.home / 'installed'
        (installed / 'bin').mkdir(parents=True)
        shutil.copy2(REPO / 'bin/atr', installed / 'bin/atr')
        shutil.copy2(REPO / 'install.sh', installed / 'install.sh')
        (installed / '.atr-tarball').touch()
        (installed / 'rooms').mkdir()
        result = self.cli('self-update', source=installed)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('source contains local data', result.stderr)
        self.assertTrue((installed / 'rooms').is_dir())

    def test_self_update_refuses_unmanaged_source(self):
        installed = self.home / 'unmanaged'
        (installed / 'bin').mkdir(parents=True)
        shutil.copy2(REPO / 'bin/atr', installed / 'bin/atr')
        shutil.copy2(REPO / 'install.sh', installed / 'install.sh')
        result = self.cli('self-update', source=installed)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not a Git checkout or installer tarball', result.stderr)


if __name__ == '__main__':
    unittest.main()
