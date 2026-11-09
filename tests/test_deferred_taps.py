"""Busy-lead notices remain durable and coalesce only before their first T3 attempt."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_loader('deferred_atr', importlib.machinery.SourceFileLoader('deferred_atr', str(REPO / 'bin/atr')))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)
LEAD = 'lead-thread-0001'


class Deferred(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.info = {'status': 'running'}
        self.sent = []
        def execute(action):
            self.sent.append(action)
            return {'state': 'confirmed', 'evidence': 'synthetic T3 acceptance'}
        for context in (patch.object(tr, 'ROOT', self.root), patch.object(tr, 'ROOMS', self.root / 'rooms'),
                        patch.object(tr, 'thread_info', side_effect=lambda thread: self.info),
                        patch.object(tr, 't3_execute', side_effect=execute)):
            context.start(); self.addCleanup(context.stop)
        room = self.root / 'rooms/demo'
        room.mkdir(parents=True)
        (room / 'BRIEF.md').write_text(f'---\ntitle: Demo\nlead_thread: {LEAD}\n---\n')
        self.room = tr.Room('demo')

    def retry(self):
        for action_id in list(tr.delivery_actions()):
            tr.attempt_delivery(action_id)

    def test_running_lead_gets_nothing_but_pending(self):
        self.assertFalse(tr.tell_lead_or_defer(self.room, 'first decision answered'))
        self.assertEqual(self.sent, [])
        action = next(iter(tr.delivery_actions().values()))
        self.assertEqual(action['state'], 'pending')
        self.assertEqual(action['attempts'], [])

    def test_idle_unread_wakes_once_with_each_original_obligation_retained(self):
        tr.tell_lead_or_defer(self.room, 'first decision answered')
        tr.tell_lead_or_defer(self.room, 'second decision answered')
        ids = set(tr.delivery_actions())
        self.info['status'] = 'idle'
        self.retry(); self.retry()
        self.assertEqual(len(self.sent), 1)
        self.assertIn('first decision', self.sent[0]['payload'])
        self.assertIn('second decision', self.sent[0]['payload'])
        self.assertEqual(set(tr.delivery_actions()), ids)
        self.assertTrue(all(action['state'] == 'confirmed' for action in tr.delivery_actions().values()))

    def test_idle_after_local_acknowledgement_gets_no_send(self):
        tr.tell_lead_or_defer(self.room, 'decision answered')
        (self.room.dir / 'now-head.md').write_text('---\nsince: 2099-01-01T00:00Z\n---\n')
        self.info['status'] = 'idle'
        self.retry()
        self.assertEqual(self.sent, [])
        self.assertEqual(next(iter(tr.delivery_actions().values()))['state'], 'superseded')

    def test_snoozed_or_settled_lead_is_not_automatically_woken(self):
        tr.tell_lead_or_defer(self.room, 'decision answered')
        self.info.update(status='idle', snoozed=True)
        self.retry()
        self.info.update(snoozed=False, settled=True)
        self.retry()
        self.assertEqual(self.sent, [])
        self.assertEqual(next(iter(tr.delivery_actions().values()))['state'], 'pending')

    def test_idle_lead_accepts_each_new_notice_and_repeated_identity_is_not_resent(self):
        self.info['status'] = 'idle'
        self.assertTrue(tr.tell_lead_or_defer(self.room, 'first decision'))
        self.assertTrue(tr.tell_lead_or_defer(self.room, 'second decision'))
        self.assertTrue(tr.tell_lead_or_defer(self.room, 'first decision'))
        self.assertEqual(len(self.sent), 2)

    def test_pending_notice_survives_without_a_running_refresher(self):
        tr.tell_lead_or_defer(self.room, 'decision answered')
        self.assertEqual(len(tr.delivery_actions()), 1)
        self.assertEqual(self.sent, [])
        self.info['status'] = 'idle'
        self.retry()
        self.assertEqual(len(self.sent), 1)


if __name__ == '__main__':
    unittest.main()
