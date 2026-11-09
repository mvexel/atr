"""Page empty states: static checks on web/index.html."""
import re, unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text()


class EmptyStates(unittest.TestCase):
    def test_first_run_copy_is_signed_wording_with_setup_link(self):
        for part in ("No rooms yet. A room is one project with its own team of agents and a lead that runs it. Create the first one from the ",
                     "setup guide", " (docs/SETUP.md in the repository), then answer its first card here."):
            self.assertIn(part, HTML)
        self.assertIn('href: docURL("docs/SETUP.md")', HTML)
        self.assertNotIn('"No rooms yet.")', HTML)


if __name__ == "__main__":
    unittest.main()
