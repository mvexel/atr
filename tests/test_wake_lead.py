"""A worker's review/done reaches the lead; continuity() gives the overview state."""
import argparse, importlib.machinery, importlib.util, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_loader('wake_atr', importlib.machinery.SourceFileLoader('wake_atr', str(REPO / 'bin/atr')))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)
LEAD = 'lead-thread-0001'


class Wake(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.status = 'idle'
        self.sent = []
        for c in (patch.object(tr, 'ROOT', self.root), patch.object(tr, 'ROOMS', self.root / 'rooms'),
                  patch.object(tr, 'thread_info', side_effect=lambda th: {'status': self.status}),
                  patch.object(tr, 'thread_status', side_effect=lambda th: self.status),
                  patch.object(tr, 't3_call', side_effect=lambda kind, target, payload, options=None: self.sent.append((target, payload)) or {'ok': True, 'evidence': 'x', 'thread': None})):
            c.start(); self.addCleanup(c.stop)
        d = self.root / 'rooms/demo'; (d / 'items').mkdir(parents=True)
        (d / 'BRIEF.md').write_text(f'---\ntitle: Demo\nlead_thread: {LEAD}\n---\n')
        (d / 'items/T01-a.md').write_text('---\nid: T01\ntitle: A\nstate: doing\n---\n## Log\n- 00:00Z w: set state=doing\n## Result\n')
        (d / 'now-head.md').write_text('---\nwaiting: T01 and T02\nresume: when T01 reaches review\n---\n')

    def set(self, by, *pairs):
        tr.cmd_set(argparse.Namespace(room='demo', id='T01', pairs=list(pairs), by=by, force=False, expect_version=None))

    def test_worker_review_sends_one_notice_and_repeat_adds_none(self):
        self.set('worker', 'state=review')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0], LEAD)
        self.assertIn('T01', self.sent[0][1])
        self.set('worker', 'state=review')
        self.assertEqual(len(self.sent), 1)

    def test_lead_changes_send_nothing(self):
        self.set('lead', 'state=done')
        self.assertEqual(self.sent, [])

    def test_continuity_overview(self):
        room = lambda: tr.Room('demo')
        self.assertEqual(tr.continuity(room())[0], 'running')
        self.set('worker', 'state=blocked')
        self.assertEqual(tr.continuity(room())[0], 'blocked')
        self.set('worker', 'state=review')
        self.assertEqual(tr.continuity(room())[0], 'idle')


if __name__ == '__main__':
    unittest.main()
