"""Refinements to a settled PRD: new/review/agree, frozen once agreed, the BRIEF `binding:` line,
`atr check` warnings, the lighter PRD template. Run: python3 -I -m unittest tests.test_refinements
"""
import contextlib, importlib.machinery, importlib.util, io, tempfile, types, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

PRD = ("---\nid: PRD\ntitle: Walks\nstatus: {status}\n{version}product_lead: product\ntech_lead: techlead\n"
       "agreed:\nupdated: 2026-10-20T10:00Z\n---\n## Purpose\nx\n\n## Sign-off\nProduct lead: Mira\nTech lead: Ravi\nMartijn:\n")
ITEM = "---\nid: T01\ntitle: Build the thing\nstate: {state}\nowner: dev\nupdated: {upd}\ncap_h: 1\n---\n{body}\n## Log\n- 01:00Z dev: created\n"
RF = ("---\nid: {id}\ntitle: {title}\nstatus: {status}\ntouches: [{touches}]\nsupersedes: [{sup}]\nkind: tune\n"
      "agreed: {agreed}\nupdated: 2026-10-26T10:00Z\n---\n## Trigger\nx\n\n## Sign-off\nProduct lead: Mira\nTech lead: n/a\nMartijn:\n")


def ns(**kw):
    return types.SimpleNamespace(**kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (tr.ROOT, tr.ROOMS)
        tr.ROOT = Path(self.tmp.name)
        tr.ROOMS = tr.ROOT / "rooms"
        self.d = tr.ROOMS / "r1"
        for sub in ("items", "decisions", "refinements"):
            (self.d / sub).mkdir(parents=True)
        (self.d / "BRIEF.md").write_text("---\ntitle: t\nlead_thread: abc\n---\n")
        self.published = []
        self.prd("agreed", "version: 2\n")

    def tearDown(self):
        tr.ROOT, tr.ROOMS = self.saved
        self.tmp.cleanup()

    def prd(self, status, version=""):
        (self.d / "PRD.md").write_text(PRD.format(status=status, version=version))

    def rf(self, rid, status="agreed", touches="FR4", sup="", title="Tune", agreed="2026-10-26T12:00Z"):
        (self.d / "refinements" / f"{rid}-x.md").write_text(
            RF.format(id=rid, title=title, status=status, touches=touches, sup=sup, agreed=agreed))

    def item(self, body="", state="doing", upd="2026-10-25T10:00Z", name="T01-x.md"):
        (self.d / "items" / name).write_text(ITEM.format(state=state, upd=upd, body=body))

    def out(self, fn, *a):
        o = io.StringIO()
        with contextlib.redirect_stdout(o):
            fn(*a)
        return o.getvalue()

    def problems(self):
        return tr.problems(tr.Room("r1"))


class New(Base):
    def test_new_creates_next_rf_with_touches(self):
        a = ns(room="r1", what="new", title="Tune the card count", touches=["FR4"], supersedes=None)
        self.out(tr.cmd_refinement, a)
        self.out(tr.cmd_refinement, ns(room="r1", what="new", title="Second", touches=["FR5"], supersedes=["RF01"]))
        files = sorted(p.name for p in (self.d / "refinements").glob("*.md"))
        self.assertEqual([f[:4] for f in files], ["RF01", "RF02"])
        r = tr.Room("r1").refinements
        self.assertEqual(r[0]["status"], "draft")
        self.assertEqual(r[0]["touches"], ["FR4"])
        self.assertEqual(r[1]["supersedes"], ["RF01"])

    def test_new_requires_touches(self):
        with self.assertRaises(SystemExit):
            self.out(tr.cmd_refinement, ns(room="r1", what="new", title="x", touches=None, supersedes=None))

    def test_template_has_sections(self):
        text = (REPO / "template" / "refinement.md").read_text()
        for h in ("Trigger", "Change", "Why this stays inside the PRD", "Effect on work", "Sign-off"):
            self.assertIn(f"## {h}", text)
        self.assertLessEqual(len(text.splitlines()), 60)


class Review(Base):
    def test_review_needs_signoff(self):
        self.rf("RF01", "draft", agreed="")
        p = self.d / "refinements" / "RF01-x.md"
        p.write_text(p.read_text().replace("Product lead: Mira\n", "Product lead:\n"))
        with self.assertRaises(SystemExit) as e:
            self.out(tr.cmd_refinement, ns(room="r1", what="RF01", title="review", touches=None, supersedes=None))
        self.assertIn("Product lead", str(e.exception))

    def test_review_opens_card_publishes_and_blocks_only_citing_items(self):
        self.rf("RF01", "draft", agreed="")
        self.item("cites RF01 here", name="T01-x.md")
        self.item("nothing", name="T02-y.md")
        (self.d / "items" / "T02-y.md").write_text((self.d / "items" / "T02-y.md").read_text().replace("T01", "T02"))
        self.out(tr.cmd_refinement, ns(room="r1", what="RF01", title="review", touches=None, supersedes=None))
        room = tr.Room("r1")
        self.assertEqual(room.refinements[0]["status"], "review")
        d = room.decisions[0]
        self.assertEqual((d["type"], d["title"], d["decider"]), ("refinement", "Agree RF01: Tune?", "martijn"))
        self.assertEqual(d["blocks"], ["T01"])

    def test_agree_card_agrees_and_supersedes(self):
        self.rf("RF01")
        self.rf("RF02", "draft", agreed="", sup="RF01")
        self.out(tr.cmd_refinement, ns(room="r1", what="RF02", title="review", touches=None, supersedes=None))
        room = tr.Room("r1")
        tr.after_answer(room, room.decisions[0], "a")
        room = tr.Room("r1")
        rf = {r["id"]: r for r in room.refinements}
        self.assertEqual(rf["RF02"]["status"], "agreed")
        self.assertTrue(rf["RF02"]["agreed"])
        self.assertIn("Martijn: agreed", rf["RF02"].section("Sign-off"))
        self.assertEqual(rf["RF01"]["status"], "superseded")
        self.assertEqual(tr.binding(room), "PRD.md + RF02")

    def test_other_answer_returns_to_draft(self):
        self.rf("RF01", "draft", agreed="")
        self.out(tr.cmd_refinement, ns(room="r1", what="RF01", title="review", touches=None, supersedes=None))
        room = tr.Room("r1")
        tr.after_answer(room, room.decisions[0], "b")
        self.assertEqual(tr.Room("r1").refinements[0]["status"], "draft")

    def test_local_review_does_not_require_a_remote_snapshot(self):
        self.rf("RF01", "draft", agreed="")
        output = self.out(tr.cmd_refinement, ns(room="r1", what="RF01", title="review", touches=None, supersedes=None))
        self.assertIn("saved locally", output)
        self.assertEqual(tr.Room("r1").refinements[0]["status"], "review")
        self.assertEqual(tr.Room("r1").decisions[0]["status"], "open")


class Frozen(Base):
    def test_agreed_refinement_refuses_edits_except_superseded(self):
        self.rf("RF01")
        for pairs in (["touches=[FR9]"], ["status=draft"], ["status=superseded", "kind=tune"]):
            with self.assertRaises(SystemExit):
                tr.cmd_set(ns(room="r1", id="RF01", pairs=pairs, by="x", force=True))
        tr.cmd_set(ns(room="r1", id="RF01", pairs=["status=superseded"], by="x", force=False))
        self.assertEqual(tr.Room("r1").refinements[0]["status"], "superseded")

    def test_draft_refinement_editable(self):
        self.rf("RF01", "draft", agreed="")
        tr.cmd_set(ns(room="r1", id="RF01", pairs=["kind=tighten"], by="x", force=False))
        self.assertEqual(tr.Room("r1").refinements[0]["kind"], "tighten")


class Binding(Base):
    def test_binding_only_agreed(self):
        self.assertEqual(tr.binding(tr.Room("r1")), "PRD.md")
        self.rf("RF01"); self.rf("RF02", "review", agreed=""); self.rf("RF03", "draft", agreed="")
        self.rf("RF04", "superseded")
        self.assertEqual(tr.binding(tr.Room("r1")), "PRD.md + RF01")

    def test_status_writes_brief_line_once(self):
        self.rf("RF01"); self.rf("RF02")
        self.out(tr.cmd_status, ns(rooms=["r1"]))
        self.assertIn("binding: PRD.md + RF01, RF02", (self.d / "BRIEF.md").read_text())
        before = (self.d / "BRIEF.md").read_text()
        self.out(tr.cmd_status, ns(rooms=["r1"]))
        self.assertEqual(before, (self.d / "BRIEF.md").read_text())

    def test_brief_command_prints_it(self):
        self.rf("RF01")
        self.assertIn("PRD.md + RF01", self.out(tr.cmd_brief, ns(room="r1")))

    def test_drafts_do_not_unlock_building(self):
        self.prd("review")
        self.rf("RF01", "agreed")
        self.assertTrue(tr.Room("r1").build_locked)
        self.prd("agreed")
        self.rf("RF02", "draft", agreed="")
        self.assertFalse(tr.Room("r1").build_locked)

    def test_status_chip_text(self):
        self.rf("RF02")
        self.assertIn("PRD v2 · agreed · RF02", self.out(tr.cmd_status, ns(rooms=["r1"])))
        self.prd("agreed")
        self.assertIn("PRD agreed · RF02", self.out(tr.cmd_status, ns(rooms=["r1"])))


class Check(Base):
    def test_prd_over_120_lines_warns_for_draft_only(self):
        long = "\n".join(["line"] * 130)
        self.prd("draft")
        with open(self.d / "PRD.md", "a") as f:
            f.write(long)
        self.assertTrue(any("over 120" in p for p in self.problems()))
        self.prd("agreed", "version: 2\n")
        with open(self.d / "PRD.md", "a") as f:
            f.write(long)
        self.assertFalse(any("over 120" in p for p in self.problems()))

    def test_refinement_touching_nothing(self):
        self.rf("RF01", "draft", touches="", agreed="")
        self.assertTrue(any("RF01" in p and "touches nothing" in p for p in self.problems()))

    def test_five_refinements_warn(self):
        for n in range(1, 5):
            self.rf(f"RF0{n}")
        self.assertFalse(any("consolidate" in p for p in self.problems()))
        self.rf("RF05")
        self.assertTrue(any("consolidate or confirm pivot" in p for p in self.problems()))

    def test_item_citing_overridden_id(self):
        self.rf("RF01", touches="FR4", agreed="2026-10-26T12:00Z")
        self.item("Shows FR4 cards", upd="2026-10-25T10:00Z")
        self.assertTrue(any("T01" in p and "FR4" in p and "RF01" in p for p in self.problems()))
        self.item("Shows FR4 cards", upd="2026-10-27T10:00Z")        # touched after the agreement
        self.assertFalse(any("overrid" in p for p in self.problems()))
        self.item("Shows FR5 cards", upd="2026-10-25T10:00Z")
        self.assertFalse(any("overrid" in p for p in self.problems()))

    def test_draft_refinement_does_not_override(self):
        self.rf("RF01", "draft", agreed="")
        self.item("Shows FR4 cards", upd="2026-10-25T10:00Z")
        self.assertFalse(any("overrid" in p for p in self.problems()))


class Prd(Base):
    def test_prd_template_short_with_sections(self):
        text = (REPO / "template" / "prd.md").read_text()
        self.assertLessEqual(len(text.splitlines()), 120)
        for h in ("Purpose", "Stakeholders", "Goals and non-goals", "Functional requirements", "Non-functional requirements",
                  "Assumptions", "Constraints", "High-level execution", "Definition of done", "Open questions", "Sign-off"):
            self.assertIn(f"## {h}", text)
        self.assertNotIn("version", text)
        self.assertIn("draft | review | agreed", text)
        text.format(title="x", now="y", ux="z")          # cmd_room fills it this way

    def test_prd_review_card_has_no_version(self):
        self.prd("draft", "version: 3\n")
        self.out(tr.cmd_prd, ns(room="r1", action="review"))
        d = tr.Room("r1").decisions[0]
        self.assertEqual(d["title"], "Agree PRD: Walks?")

    def test_old_prd_answer_b_still_bumps_version_new_does_not(self):
        self.prd("draft", "version: 3\n")
        self.out(tr.cmd_prd, ns(room="r1", action="review"))
        room = tr.Room("r1")
        tr.after_answer(room, room.decisions[0], "b")
        self.assertEqual(tr.Room("r1").prd["version"], "4")
        self.prd("draft")
        (self.d / "decisions" / "D01-agree-prd.md").unlink()
        self.out(tr.cmd_prd, ns(room="r1", action="review"))
        room = tr.Room("r1")
        tr.after_answer(room, room.decisions[0], "b")
        self.assertNotIn("version", tr.Room("r1").prd.head)

    def test_old_prd_still_gates_building(self):
        self.prd("review", "version: 1\n")
        self.assertTrue(tr.Room("r1").build_locked)


if __name__ == "__main__":
    unittest.main()
