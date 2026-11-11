"""An approved GOAL.md for tests that start work in a room (no worker starts before approval)."""
APPROVED = ("---\nid: GOAL\ntitle: t\nstatus: approved\napproved: 2026-01-01T00:00Z\n---\n"
            "## Architecture\nlocal files\n\n## Minimal viable result\nit runs\n\n## Definition of done\ntests pass\n")


def approve(room_dir):
    (room_dir / "GOAL.md").write_text(APPROVED)
