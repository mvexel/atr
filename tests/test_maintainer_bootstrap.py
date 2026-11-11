"""Maintainer launch through t3_execute; no live T3 or browser."""
import subprocess
from unittest.mock import patch
from test_t3_required import T3Required


class Bootstrap(T3Required):
    def result(self, code=0, out='', err=''):
        return subprocess.CompletedProcess([], code, out, err)

    def action(self):
        return dict(id='setup', kind='launch', target=str(self.tr.SOURCE_ROOT), payload='initialize',
                    room='process', options=dict(purpose='maintainer', title='Room · process · lead'))

    def test_register_before_launch_and_open_exact_thread(self):
        calls = []
        def run(args, **kw):
            calls.append(args)
            if args[1:3] == ['thread', 'list']:
                return self.result(1, err='No T3 Code project matches /tmp')
            if args[1:3] == ['project', 'add']:
                return self.result()
            return self.result(out='{"threadId":"lead-123"}')
        with patch.object(self.tr, '_external_run', side_effect=run), patch.object(self.tr, 'open_maintainer') as opened:
            result = self.tr.t3_execute(self.action())
        self.assertEqual([a[1:3] for a in calls], [['thread','list'], ['project','add'], ['thread','start']])
        self.assertEqual(result['state'], 'confirmed')
        opened.assert_called_once_with('lead-123')

    def test_existing_project_reused(self):
        with patch.object(self.tr, '_external_run', side_effect=[self.result(), self.result(out='{"threadId":"lead-123"}')]) as run, patch.object(self.tr, 'open_maintainer'):
            self.assertEqual(self.tr.t3_execute(self.action())['state'], 'confirmed')
        self.assertEqual(run.call_count, 2)

    def test_preflight_failure_never_launches_thread(self):
        with patch.object(self.tr, '_external_run', return_value=self.result(1, err='Connection refused')) as run:
            result = self.tr.t3_execute(self.action())
        self.assertEqual(result['state'], 'failed')
        self.assertIn('no thread launch attempted', result['evidence'])
        self.assertEqual(run.call_count, 1)

    def test_nested_cli_receipt_identifies_thread(self):
        with patch.object(self.tr, '_external_run', side_effect=[self.result(), self.result(out='{"thread":{"threadId":"nested-lead"}}')]), patch.object(self.tr, 'open_maintainer') as opened:
            self.assertEqual(self.tr.t3_execute(self.action())['thread'], 'nested-lead')
        opened.assert_called_once_with('nested-lead')
