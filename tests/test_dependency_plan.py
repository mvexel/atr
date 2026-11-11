"""`atr need`, plan checks, waves and critical path, the blocked-need attention line. No real message is sent.
Run: python3 -I -m unittest tests.test_dependency_plan
"""
import contextlib, importlib.machinery, importlib.util, io, tempfile, types, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import goal_fixture
spec = importlib.util.spec_from_loader("tr", importlib.machinery.SourceFileLoader("tr", str(REPO / "bin" / "atr")))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

GOOD = "## Acceptance\n- [ ] it works\n\n## Inputs\n- the spec\n\n"

def item(iid, state="todo", deps="", locks="", cap="1", body=GOOD, extra=""):
    return (f"---\nid: {iid}\ntitle: title {iid}\nstate: {state}\nowner: dev\ndepends_on: [{deps}]\nlocks: [{locks}]\n"
            f"cap_h: {cap}\nupdated: 2026-10-27T10:00Z\n{extra}---\n{body}## Log\n- 10:00Z Lead: created\n\n## Result\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (tr.ROOMS, tr.tell_lead_or_defer)
        tr.ROOMS = Path(self.tmp.name) / "rooms"
        self._canonical_root_before = tr.ROOT
        tr.ROOT = tr.ROOMS.parent
        self.addCleanup(setattr, tr, "ROOT", self._canonical_root_before)
        self.told = []
        tr.tell_lead_or_defer = lambda room, text, thread=None: (self.told.append((room.name, text)), True)[1]

    def tearDown(self):
        tr.ROOMS, tr.tell_lead_or_defer = self.saved
        self.tmp.cleanup()

    def room(self, items, brief="---\ntitle: t\n---\n", name="r1"):
        d = tr.ROOMS / name
        (d / "items").mkdir(parents=True, exist_ok=True)
        (d / "decisions").mkdir(exist_ok=True)
        (d / "BRIEF.md").write_text(brief)
        goal_fixture.approve(d)
        for old in (d / "items").glob("*.md"):
            old.unlink()
        for iid, kw in items:
            (d / "items" / f"{iid}-x.md").write_text(item(iid, **kw))
        return tr.Room(name)

    def run_need(self, *args, **kw):
        ns = dict(room="r1", id="T01", text="no fixtures", needs=None, by="dev")
        ns.update(kw)
        return tr.cmd_need(types.SimpleNamespace(**ns))

    def set_(self, *pairs, id="T01", force=False):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            tr.cmd_set(types.SimpleNamespace(room="r1", id=id, pairs=list(pairs), by="dev", force=force))
        return err.getvalue()


class Need(Base):
    def test_blocks_logs_records_need_and_tells_lead_once(self):
        self.room([("T01", dict(state="doing")), ("T07", {})])
        self.run_need(text="needs a fixture set", needs="T07")
        i = tr.Room("r1").find("T01")
        self.assertEqual(i["state"], "blocked")
        self.assertIn("need: needs a fixture set", i.section("Log"))
        self.assertIn("needs a fixture set (needs T07)", i.section("Needs"))
        self.assertEqual(len(self.told), 1)
        self.assertIn("T01", self.told[0][1])
        self.assertIn("needs a fixture set", self.told[0][1])
        self.assertIn("T07", self.told[0][1])

    def test_works_from_todo(self):
        self.room([("T01", {})])
        self.run_need()
        self.assertEqual(tr.Room("r1").find("T01")["state"], "blocked")

    def test_refuses_other_states(self):
        for state in ("review", "done", "blocked", "dropped"):
            self.room([("T01", dict(state=state))])
            with self.assertRaises(SystemExit):
                self.run_need()
            self.assertEqual(tr.Room("r1").find("T01")["state"], state)
        self.assertEqual(self.told, [])

    def test_refuses_closed_room(self):
        self.room([("T01", dict(state="doing"))], brief="---\ntitle: t\nclosed: 2026-10-27T09:00Z\n---\n")
        with self.assertRaises(SystemExit):
            self.run_need()
        self.assertEqual(self.told, [])

    def test_refuses_unknown_needs_id(self):
        self.room([("T01", dict(state="doing"))])
        with self.assertRaises(SystemExit):
            self.run_need(needs="T99")
        self.assertEqual(tr.Room("r1").find("T01")["state"], "doing")

    def test_blocked_with_need_shows_in_attention_until_flipped(self):
        self.room([("T01", dict(state="doing"))])
        self.run_need(text="needs a fixture set")
        a = [x for x in tr.bottlenecks(tr.Room("r1")) if x["rule"] == "need"]
        self.assertEqual(len(a), 1)
        self.assertIn("needs a fixture set", a[0]["text"])
        self.assertIsNone(a[0]["nudge"])           # the lead was already told by `need`
        self.set_("state=todo")
        self.assertEqual([x for x in tr.bottlenecks(tr.Room("r1")) if x["rule"] == "need"], [])

    def test_blocked_without_needs_entry_not_in_attention(self):
        room = self.room([("T01", dict(state="blocked"))])
        self.assertEqual([x for x in tr.bottlenecks(room) if x["rule"] == "need"], [])


class Waves(Base):
    def test_waves(self):
        room = self.room([("T01", dict(state="done")), ("T02", dict(deps="T01", cap="2")), ("T03", dict(deps="T02", cap="3")),
                          ("T04", dict(deps="T02", cap="1")), ("T05", dict(deps="T03,T04", cap="1"))])
        p = tr.plan(room)
        self.assertEqual({x["id"]: x["wave"] for x in p["items"]}, {"T02": 0, "T03": 1, "T04": 1, "T05": 2})
        self.assertEqual(p["critical"], ["T02", "T03", "T05"])
        self.assertEqual(p["critical_h"], 6)
        self.assertEqual(p["waves"], 3)

    def test_long_single_item_can_be_the_critical_path(self):
        room = self.room([("T01", dict(cap="1")), ("T02", dict(deps="T01", cap="1")), ("T03", dict(cap="9"))])
        self.assertEqual(tr.plan(room)["critical"], ["T03"])

    def test_missing_cap_counts_one_hour(self):
        room = self.room([("T01", dict(cap="")), ("T02", dict(deps="T01", cap=""))])
        self.assertEqual(tr.plan(room)["critical_h"], 2)

    def test_cycle_does_not_hang_and_is_reported(self):
        room = self.room([("T01", dict(deps="T02")), ("T02", dict(deps="T01")), ("T03", dict(deps="T02"))])
        p = tr.plan(room)
        self.assertEqual(len(p["items"]), 3)
        self.assertEqual(tr.dependency_cycles(room), [["T01", "T02"]])

    def test_ready_flag(self):
        room = self.room([("T01", {}), ("T02", dict(deps="T01")), ("T03", dict(state="doing"))])
        r = {x["id"]: x["ready"] for x in tr.plan(room)["items"]}
        self.assertEqual(r, {"T01": True, "T02": False, "T03": False})

    def test_room_json_has_plan_with_need(self):
        self.room([("T01", dict(state="doing")), ("T02", dict(deps="T01", locks="gradle"))])
        self.run_need(text="no fixtures")
        j = tr.room_json(tr.Room("r1"))["plan"]
        by = {x["id"]: x for x in j["items"]}
        self.assertEqual(by["T01"]["need"], "no fixtures")
        self.assertEqual(by["T02"]["deps"], ["T01"])
        self.assertEqual(by["T02"]["locks"], ["gradle"])


class Checks(Base):
    def probs(self, room):
        return [p for p in tr.problems(room) if "/T" in p or "dependency plan" in p]

    def test_cycle_warns(self):
        room = self.room([("T01", dict(deps="T02")), ("T02", dict(deps="T01"))])
        self.assertTrue(any("cycle" in p and "T01" in p and "T02" in p for p in tr.problems(room)))

    def test_doing_with_unmet_dependency_warns(self):
        room = self.room([("T01", {}), ("T02", dict(state="doing", deps="T01"))])
        self.assertTrue(any("T02" in p and "T01" in p and "not done" in p for p in tr.problems(room)))

    def test_doing_with_done_dependency_is_quiet(self):
        room = self.room([("T01", dict(state="done")), ("T02", dict(state="doing", deps="T01"))])
        self.assertFalse(any("not done" in p for p in tr.problems(room)))

    def test_four_open_items_without_plan_warn(self):
        room = self.room([(f"T0{n}", {}) for n in range(1, 5)])
        self.assertTrue(any("no dependency plan" in p for p in tr.problems(room)))

    def test_three_items_or_any_edge_or_lock_is_quiet(self):
        self.assertFalse(any("no dependency plan" in p for p in tr.problems(self.room([(f"T0{n}", {}) for n in range(1, 4)]))))
        items = [(f"T0{n}", {}) for n in range(1, 5)]
        items[1] = ("T02", dict(deps="T01"))
        self.assertFalse(any("no dependency plan" in p for p in tr.problems(self.room(items))))
        items[1] = ("T02", dict(locks="gradle"))
        self.assertFalse(any("no dependency plan" in p for p in tr.problems(self.room(items))))

    def test_doing_with_empty_brief_warns_for_existing_rooms(self):
        room = self.room([("T01", dict(state="doing", body="## Acceptance\n- [ ] \n\n## Inputs\n- \n\n"))])
        self.assertTrue(any("T01" in p and "Acceptance" in p for p in tr.problems(room)))


class SetDoingBrief(Base):
    EMPTY_A = "## Acceptance\n- [ ] \n\n## Inputs\n- the spec\n\n"
    EMPTY_I = "## Acceptance\n- [ ] ok\n\n## Inputs\n- \n\n"

    def test_refuses_empty_acceptance(self):
        self.room([("T01", dict(body=self.EMPTY_A))])
        with self.assertRaises(SystemExit) as e:
            self.set_("state=doing")
        self.assertIn("Acceptance", str(e.exception))
        self.assertEqual(tr.Room("r1").find("T01")["state"], "todo")

    def test_refuses_empty_inputs(self):
        self.room([("T01", dict(body=self.EMPTY_I))])
        with self.assertRaises(SystemExit) as e:
            self.set_("state=doing")
        self.assertIn("Inputs", str(e.exception))

    def test_force_overrides(self):
        self.room([("T01", dict(body=self.EMPTY_A))])
        self.set_("state=doing", force=True)
        self.assertEqual(tr.Room("r1").find("T01")["state"], "doing")

    def test_item_already_doing_is_not_refused(self):
        self.room([("T01", dict(state="doing", body=self.EMPTY_A))])
        self.set_("state=doing", "cap_h=2")
        self.assertEqual(tr.Room("r1").find("T01")["cap_h"], "2")

    def test_filled_brief_starts(self):
        self.room([("T01", {})])
        self.set_("state=doing")
        self.assertEqual(tr.Room("r1").find("T01")["state"], "doing")

    def test_second_inputs_section_counts(self):
        body = "## Acceptance\n- [ ] ok\n\n## Inputs\n- real\n\n## Inputs\n- \n\n"
        self.room([("T01", dict(body=body))])
        self.set_("state=doing")


if __name__ == "__main__":
    unittest.main()
