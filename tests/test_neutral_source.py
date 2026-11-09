"""Source text describes behaviour, not the room or item that asked for it.

Comments, docstrings and test names must not cite our own room or item ids
(T27, R14, D05, rooms/org). Generic fixture data is let through by
tests/neutral_source_allow.txt, one `path:regex` per line.
"""
import ast
import glob
import io
import os
import re
import tokenize
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ID = re.compile(
    r"\b[RDT]\d{2}\b|rooms/org"
    r"|\b(?:C0[1-9]|E0[1-9]|A0[1-9]|F[0-9])\b"
    r"|(?i:\bcluster [a-z]\b|\bpublic build\b)"
)
NAME_ID = re.compile(r"(?:^|_)(?:[rdt]\d{2}|c0[1-9]|e0[1-9]|a0[1-9]|f\d)(?:_|$)|cluster_[a-z](?:_|$)")
ALLOW = os.path.join(ROOT, "tests", "neutral_source_allow.txt")


def _allowed():
    rules = []
    with open(ALLOW, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                path, _, pat = line.partition(":")
                rules.append((path.strip(), re.compile(pat.strip())))
    return rules


def _py_hits(path, text):
    """(line, text) for comments, docstrings and def/class names citing an id."""
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT and ID.search(tok.string):
            out.append((tok.start[0], tok.string))
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if NAME_ID.search(node.name.lower()):
                out.append((node.lineno, node.name))
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc and node.body:
                first = node.body[0].lineno
                for i, ln in enumerate(doc.splitlines()):
                    if ID.search(ln):
                        out.append((first + i, ln.strip()))
    return out


def _is_python(path, text):
    return path.endswith(".py") or text.startswith("#!") and "python" in text.split("\n", 1)[0]


def _files():
    pats = ["bin/*", "web/index.html", "template/*", "deploy/*", "README.md", "tests/*.py"]
    for p in pats:
        for f in sorted(glob.glob(os.path.join(ROOT, p))):
            if os.path.isfile(f) and os.path.abspath(f) != os.path.abspath(__file__):
                yield f


def find_hits():
    rules = _allowed()
    hits = []
    for f in _files():
        rel = os.path.relpath(f, ROOT)
        try:
            with open(f, encoding="utf-8") as source:
                text = source.read()
        except UnicodeDecodeError:
            continue
        if _is_python(rel, text):
            found = _py_hits(rel, text)
        else:
            found = [(n, l) for n, l in enumerate(text.splitlines(), 1) if ID.search(l)]
        for n, l in found:
            if not any(rel == p and r.search(l) for p, r in rules):
                hits.append(f"{rel}:{n}: {l.strip()}")
    return hits


class NeutralSource(unittest.TestCase):
    def test_no_room_or_item_ids_in_comments_docstrings_or_names(self):
        hits = find_hits()
        self.assertEqual(hits, [], "room/item ids in source text:\n" + "\n".join(hits))

    def test_core_does_not_reintroduce_private_integration_references(self):
        from pathlib import Path
        roots = ["bin", "web", "template", "skills", "docs"]
        paths = [Path(ROOT) / name for name in ("README.md", "PROTOCOL.md")]
        for name in roots:
            paths.extend(p for p in (Path(ROOT) / name).rglob("*")
                         if p.is_file() and "__pycache__" not in p.parts)
        pattern = re.compile(r"\b(?:live" + r"map|a" + r"ri)\b", re.I)
        hits = []
        for path in paths:
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            hits.extend(f"{path.relative_to(ROOT)}:{n}" for n, line in enumerate(text.splitlines(), 1)
                        if pattern.search(line))
        self.assertEqual(hits, [])

    def test_scanner_flags_finding_ids_and_build_phrases(self):
        for bad in ("# C03 copy", "# (F4)", "# E02 empty", "# A07 a11y", "# cluster D",
                    '"""the public build"""'):
            src = f"{bad}\n" if bad.startswith("#") else f"{bad}\n"
            self.assertTrue(_py_hits("x.py", src) or _py_hits("x.py", "def f():\n    " + bad + "\n"), bad)
        names = "def test_c01_x():\n    pass\nclass ClusterD:\n    pass\ndef test_f4_y():\n    pass\n"
        self.assertEqual(len(_py_hits("x.py", names)), 2)
        self.assertEqual(_py_hits("x.py", "# in cluster mode, F10 and CA01\nx = 'C01'\n"), [])

    def test_scanner_flags_a_citing_comment_and_test_name(self):
        src = 'def test_r14_x():\n    """T42: why."""\n    # T27: because\n    x = "T04"\n'
        got = [l for _, l in _py_hits("x.py", src)]
        self.assertEqual(len(got), 3)
        self.assertFalse(any('"T04"' in g for g in got))


if __name__ == "__main__":
    unittest.main()
