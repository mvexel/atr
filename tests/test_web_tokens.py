"""Page tokens cluster: static checks on web/index.html."""
import re, unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text()
CSS = re.search(r"<style>(.*?)</style>", HTML, re.S).group(1)


class Tokens(unittest.TestCase):
    def test_every_var_reference_is_defined(self):
        defined = set(re.findall(r"(--[\w-]+)\s*:", CSS))
        used = set(re.findall(r"var\((--[\w-]+)", CSS))
        self.assertEqual(sorted(used - defined), [])

    def test_no_selector_is_defined_twice_at_top_level(self):
        # accidental duplicates (.card was defined twice); intentional variants use compound selectors
        top = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*\s*\}", "", CSS)
        sels = re.findall(r"^  (\.card) \{", top, re.M)
        self.assertEqual(sels, [".card"])

    def test_theme_color_follows_scheme(self):
        metas = re.findall(r'<meta name="theme-color"[^>]*>', HTML)
        light = re.search(r"--surface-1: (#\w+)", CSS).group(1)
        dark = re.findall(r"--surface-1: (#\w+)", CSS)[1]
        self.assertTrue(any(light in m and "light" in m for m in metas), metas)
        self.assertTrue(any(dark in m and "dark" in m for m in metas), metas)

    def test_ink_on_accent_fill_uses_token(self):
        for line in CSS.splitlines():
            if "background: var(--accent-fill)" in line and "aria-pressed" in line:
                self.assertNotIn("#fff", line)


if __name__ == "__main__":
    unittest.main()
