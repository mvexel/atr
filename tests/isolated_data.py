"""Imported first by every test that loads bin/atr: the default data dir becomes a throwaway one.

bin/atr reads ATR_DATA_DIR (else ~/.local/share/atr) when it is loaded, so without this the module-level
ROOT and LOCKDIR point at the owner's real store, and tests that patch only ROOT still leaked lock files there.
"""
import atexit, os, shutil, tempfile

if not os.environ.get("ATR_TEST_DATA_DIR"):
    _tmp = tempfile.mkdtemp(prefix="atr-test-data-")
    atexit.register(shutil.rmtree, _tmp, True)
    os.environ["ATR_TEST_DATA_DIR"] = _tmp   # children share it and never remove it
else:
    _tmp = os.environ["ATR_TEST_DATA_DIR"]
os.environ["ATR_DATA_DIR"] = _tmp
os.environ.pop("ATR_LOCKDIR", None)
