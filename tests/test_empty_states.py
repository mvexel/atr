"""Page empty states: static checks on web/index.html."""
import re, unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text()


class EmptyStates(unittest.TestCase):
    def test_first_run_copy_points_to_starting_a_room(self):
        self.assertIn("No rooms yet. A room is one project with its own team of agents and a lead that runs it. "
                      "Start the first one from a T3 thread or with atr start, then answer its first card here.", HTML)
        self.assertNotIn('"No rooms yet.")', HTML)


if __name__ == "__main__":
    unittest.main()
