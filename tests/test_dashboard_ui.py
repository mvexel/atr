"""Exercise owner overview rendering without a browser or canonical-store writes."""
import json
import subprocess
import unittest
from pathlib import Path

NODE = '/home/mvexel/.local/share/mise/installs/node/24/bin/node'
HTML = (Path(__file__).resolve().parent.parent / 'web/index.html').read_text()

class OverviewRendering(unittest.TestCase):
    def test_scoped_history_successors_and_unknown_capacity(self):
        fn = HTML.split('function dashboardView(app, selectedRoom = null) {', 1)[1].split('\nfunction draw(top)', 1)[0]
        room = dict(room='maintenance', goal='Retain obligations', recorded_state='review', latest_evidenced_change=None, owner_attention=[], resume_trigger=None,
                    obligations=[dict(id='T01', action='Deferred code', actor=None, recorded_state='done', open=False, disposition='accepted', successors=['T02'], reconciliation=['explicit stale Result contradiction'], assertions=[], result='Completed documentation; code deferred'),dict(id='T02', action='Deferred code', actor='Maintainer', recorded_state='todo', open=True, disposition='accepted', successors=[], reconciliation=[], assertions=[], result='Follow-up: T02')])
        room['obligations'][1]['unclaimed_ready'] = True
        room['activity'] = dict(state='recorded activity', source='local items', observed_at=None)
        room['current_work'] = [dict(action='Write design', actor='Developer', runtime=dict(state='running', source='T3 thread observation', observed_at='2026-11-10T00:00Z', freshness='fresh'))]
        script = 'function el(tag, attrs, ...children) {return {tag, children, append(...xs){this.children.push(...xs)}}}; let dashboardError=null; let dashboard='+json.dumps(dict(rooms=[room]))+';'+ 'function dashboardView(app, selectedRoom = null) {'+fn+'; const app=el("main",{}); dashboardView(app, "maintenance"); console.log(JSON.stringify(app));'
        output = subprocess.check_output([NODE, '-e', script], text=True)
        self.assertNotIn('T01: Deferred code', output)
        for text in ['Next action unclaimed:', 'Recorded activity: Write design', 'Execution: running', 'T3 thread observation', 'Limits unavailable', 'execution eligibility: unknown', 'account consumption: unknown', 'Completed documentation; code deferred', 'T02', 'explicit stale Result contradiction', 'Owner attention', 'Next actor:', 'Follow-up: T02', 'No recorded owner question', 'Outcome and next handoff']:
            self.assertIn(text, output)

    def test_room_handoff_precedes_administration(self):
        draw = HTML.split('function draw(top)', 1)[1]
        self.assertLess(draw.index('dashboardView(app, r.name)'), draw.index('supporting.append(el("header"'))
        self.assertIn('Room administration and recorded totals', draw)
        self.assertIn('supporting.append(firstUse())', draw)
