import shutil
import subprocess
import unittest

class AsyncRecovery(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node unavailable')
    def test_async_recovery(self):
        subprocess.run(['node', 'tests/fixtures/send-recovery.cjs'], check=True, timeout=30)

    @unittest.skipUnless(shutil.which('node'), 'Node unavailable')
    def test_search_races(self):
        subprocess.run(['node', 'tests/fixtures/search-races.cjs'], check=True, timeout=30)

    @unittest.skipUnless(shutil.which("node"), "Node unavailable")
    def test_settings_races(self):
        subprocess.run(["node", "tests/fixtures/settings-races.cjs"], check=True, timeout=30)
