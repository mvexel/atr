"""A worker's review/done reaches the lead; an idle lead behind a finished wait is stalled."""
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
        for c in (patch.object(tr, 'ROOT', self.root), patch.object(tr, 'ROOMS', self.root / 'rooms'),
                  patch.object(tr, 'thread_info', side_effect=lambda th: {'status': self.status}),
                  patch.object(tr, 'thread_status', side_effect=lambda th: self.status),
                  patch.object(tr, 't3_execute', side_effect=lambda a: {'state': 'confirmed', 'evidence': 'x'})):
            c.start(); self.addCleanup(c.stop)
        d = self.root / 'rooms/demo'; (d / 'items').mkdir(parents=True)
        (d / 'BRIEF.md').write_text(f'---\ntitle: Demo\nlead_thread: {LEAD}\n---\n')
        (d / 'items/T01-a.md').write_text('---\nid: T01\ntitle: A\nstate: doing\n---\n## Log\n- 00:00Z w: set state=doing\n## Result\n')
        (d / 'now-head.md').write_text('---\nwaiting: T01 and T02\nresume: when T01 reaches review\n---\n')

    def set(self, by, *pairs):
        tr.cmd_set(argparse.Namespace(room='demo', id='T01', pairs=list(pairs), by=by, force=False, expect_version=None))

    def actions(self):
        return list(tr.delivery_actions().values())

    def test_worker_review_queues_one_notice_and_repeat_adds_none(self):
        self.set('worker', 'state=review')
        self.assertEqual(len(self.actions()), 1)
        self.assertIn('T01', self.actions()[0]['payload'])
        self.set('worker', 'state=review')
        self.assertEqual(len(self.actions()), 1)

    def test_lead_changes_send_nothing(self):
        self.set('lead', 'state=done')
        self.assertEqual(self.actions(), [])

    def test_free_text_wait_on_finished_items_is_stalled_when_lead_idle(self):
        room = tr.Room('demo')
        self.assertEqual(tr.continuity(room, True)[0], 'waiting')   # the second awaited item is unknown: keep today's behaviour
        (self.root / 'rooms/demo/now-head.md').write_text('---\nwaiting: T01\nresume: when T01 reaches review\n---\n')
        self.assertEqual(tr.continuity(tr.Room('demo'), True)[0], 'waiting')  # still doing
        self.set('worker', 'state=review')
        self.assertEqual(tr.continuity(tr.Room('demo'), True)[0], 'stalled')
        self.status = 'running'
        self.assertEqual(tr.continuity(tr.Room('demo'))[0], 'moving')


if __name__ == '__main__':
    unittest.main()
