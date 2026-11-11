"""The web layer reaches room, item, decision, goal and .atr state only through the store layer
(Room/Record, store_transaction, store_guard, the web_* functions). Static check on bin/atr: no web_* function and
no method of the HTTP handler may open files, call Path read/write, or use the durable_* writers or the store roots.
Run: python3 -I -m unittest discover tests -p 'test_state_interface.py'
"""
import ast, re, unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "bin" / "atr"
TREE = ast.parse(SRC.read_text())

# Calls that touch the filesystem directly.
FILE_CALLS = {"open", "durable_write", "durable_append", "durable_unlink", "durable_mkdir", "durable_move"}
FILE_ATTRS = {"read_text", "write_text", "read_bytes", "write_bytes", "unlink", "mkdir", "rename",
              "glob", "rglob", "iterdir", "exists", "is_file", "is_dir", "touch", "rmdir"}
# The store roots: a web function that names them is building a state path itself.
ROOTS = {"ROOT", "ROOMS", "LOCKDIR", "TEMPLATES"}

# Allowlist, (function, name) pairs, each with the reason it is not a state access.
ALLOW = {
    # Prints the record's path relative to the store in the "final in <path>" lead message; no file is touched.
    ("web_answer", "ROOT"), ("_web_answer", "ROOT"),
}


def functions():
    """(qualified name, node) for every web_* function and every method of the handler class H in cmd_serve."""
    out = []
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name.lstrip("_").startswith("web_"):
            out.append((node.name, node))
        if isinstance(node, ast.ClassDef) and node.name == "H":
            out += [(f"H.{m.name}", m) for m in node.body if isinstance(m, ast.FunctionDef)]
    return out


def violations(name, fn):
    short = name.split(".")[-1]
    found = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            called = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if (isinstance(f, ast.Name) and called in FILE_CALLS) or (isinstance(f, ast.Attribute) and called in FILE_ATTRS):
                found.append(f"{name}:{n.lineno} calls {called}()")
        if isinstance(n, ast.Name) and n.id in ROOTS and (short, n.id) not in ALLOW:
            found.append(f"{name}:{n.lineno} uses {n.id}")
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and (".atr/" in n.value or re.fullmatch(r"[\w./-]+\.md", n.value)):
            found.append(f"{name}:{n.lineno} names a state file {n.value!r}")
    return found


class StateInterface(unittest.TestCase):
    def test_found_the_web_layer(self):
        names = {n for n, _ in functions()}
        for expected in ("web_answer", "web_pause", "web_state", "web_record", "H.get_request", "H.post_request"):
            self.assertIn(expected, names)

    def test_web_layer_does_not_touch_state_files(self):
        found = [v for name, fn in functions() for v in violations(name, fn)]
        self.assertEqual(found, [], "web code must go through Room/Record/store_transaction:\n" + "\n".join(found))

    def test_state_reading_web_functions_hold_the_store_lock(self):
        """Each web_* function runs under store_guard (named in the guard list at the bottom) or opens its own transaction."""
        guarded = set()
        for node in ast.walk(TREE):
            if isinstance(node, ast.For) and isinstance(node.target, ast.Name) and node.target.id == "_name" \
                    and isinstance(node.iter, ast.Tuple):
                guarded |= {e.value for e in node.iter.elts if isinstance(e, ast.Constant)}
        for name, fn in functions():
            if name.startswith("H.") or name.startswith("_"):
                continue
            own = any(isinstance(n, ast.Name) and n.id in ("store_transaction", "sync_lock") for n in ast.walk(fn))
            self.assertTrue(name in guarded or own, f"{name} reads or writes state outside the store lock")

    def test_the_check_catches_a_direct_write(self):
        bad = ast.parse("def web_x(room):\n    open(room.dir / 'README.md', 'w')\n    ROOMS.glob('*')\n").body[0]
        self.assertEqual(len(violations("web_x", bad)), 4)


if __name__ == "__main__":
    unittest.main()
