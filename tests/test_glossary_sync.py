"""The page's "What these words mean" kinds must use the signed sentences from docs/ui-language.md section 1
(third column of the vocabulary table), character for character."""
import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "index.html").read_text()
DOC = ROOT / "docs" / "ui-language.md"


def page_defs():
    block = re.search(r"const KIND_DEFS = \[(.*?)\];", HTML, re.S).group(1)
    return dict(re.findall(r'\["((?:[^"\\]|\\.)*)",\s*"((?:[^"\\]|\\.)*)"\]', block))


def doc_rows():
    sec = DOC.read_text().split("## 1. Vocabulary", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in sec.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 3:
            rows[cells[1].strip("*")] = cells[2]
    return rows


@unittest.skipUnless(DOC.exists(), "docs/ui-language.md is absent: glossary sync not checked")
class GlossarySync(unittest.TestCase):
    def test_kind_sentences_match_signed_text(self):
        defs, rows = page_defs(), doc_rows()
        self.assertGreaterEqual(len(defs), 5)
        shared = [k for k in defs if k in rows]
        self.assertEqual(sorted(shared), sorted(defs), "every page kind should be a row in section 1")
        for k in shared:
            self.assertEqual(defs[k], rows[k], "glossary sentence for %r differs from docs/ui-language.md" % k)


if __name__ == "__main__":
    unittest.main()
