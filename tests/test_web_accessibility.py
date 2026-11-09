"""Page accessibility cluster: static checks on web/index.html.
Contrast is recomputed from the page's own tokens; modal focus and motion are checked by presence (behaviour was driven in headless Chrome, see the item Result)."""
import re, unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text()


def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]


def ratio(a, b):
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + .05) / (lo + .05)


def tokens():
    root = re.search(r":root \{(.*?)\n  \}", HTML, re.S).group(1)
    dark = re.search(r"prefers-color-scheme: dark\) \{\s*:root \{(.*?)\n    \}", HTML, re.S).group(1)
    grab = lambda t: dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", t))
    light = grab(root)
    return light, {**light, **grab(dark)}


# the accessibility inventory: foreground token, background token
PAIRS = [("text-muted", "surface-1"), ("text-muted", "surface-0"), ("text-muted", "track"), ("accent-ink", "accent-fill"),
         ("accent", "surface-1"), ("accent", "surface-0"), ("accent", "accent-soft"), ("critical-text", "surface-1"),
         ("critical-text", "surface-0"), ("critical-text", "critical-soft"), ("good", "surface-1")]


class Contrast(unittest.TestCase):
    def test_every_inventory_pair_is_4_5_in_both_schemes(self):
        for name, toks in zip(("light", "dark"), tokens()):
            for fg, bg in PAIRS:
                self.assertGreaterEqual(ratio(toks[fg], toks[bg]), 4.5, f"{name}: {fg} on {bg}")

    def test_armed_key_is_white_on_a_darkened_fill(self):
        self.assertIn(".opt.armed .k, .opt.chosen .k { background: rgba(0,0,0,.25); color: #fff; }", HTML)
        for toks in tokens():   # 25% black over the fill
            f = toks["accent-fill"]; over = "#" + "".join("%02x" % round(int(f[i:i + 2], 16) * .75) for i in (1, 3, 5))
            self.assertGreaterEqual(ratio("#ffffff", over), 4.5)

    def test_text_uses_critical_text_not_the_fill_colour(self):
        self.assertIsNone(re.search(r"(?<![-\w])color: var\(--critical\)", HTML))


class Modal(unittest.TestCase):
    def test_background_goes_inert_and_focus_is_managed(self):
        for needle in ['setAttribute("inert"', "syncModal", "sheetOpener", 'e.key !== "Tab"', "FOCUSABLE"]:
            self.assertIn(needle, HTML)
        self.assertIn("drawSheetBody();\n  syncModal();", HTML)
        self.assertIn("palOpen = false; clearTimeout(palTimer); $(\"pal\").replaceChildren(); syncModal();", HTML)


class Targets(unittest.TestCase):
    def test_small_controls_get_44px(self):
        for needle in ["font-size: 12px; padding: 0 6px; min-height: 44px", "height: 44px; }\n  .pause.armed",
                       ".sheet .close::after, .pal .in button::after",
                       "button.chip, .addnote, .slotpill", "gap: 6px; width: 100%; min-height: 44px; border: 0; border-top"]:
            self.assertIn(needle, HTML)


class CardFooter(unittest.TestCase):
    """'+ Add a note' and 'Ask a question instead' are both .addnote buttons appended one after the other."""
    def test_adjacent_addnote_buttons_are_stacked_with_a_gap(self):
        body = re.search(r"(?m)^  \.addnote \{(.*?)\}", HTML).group(1)
        self.assertRegex(body, r"display: block")                       # inline buttons ran together as one label
        gap = re.search(r"margin-top: (\d+)px", body)
        self.assertIsNotNone(gap); self.assertGreaterEqual(int(gap.group(1)), 12)
        self.assertRegex(body, r"min-height: 44px")
        self.assertIn(".addnote, .slotpill", HTML)                      # the shared 44px floor still covers it
        self.assertNotRegex(body, r"margin-(left|right): -|position: absolute")   # boxes cannot overlap


class Motion(unittest.TestCase):
    def test_reduced_motion_covers_drain_active_and_spin(self):
        m = re.search(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n  \}", HTML, re.S).group(1)
        for needle in [".opt .spin { animation: none", ".opt .drain { animation: none", ".opt:active { transform: none"]:
            self.assertIn(needle, m)


if __name__ == "__main__":
    unittest.main()
