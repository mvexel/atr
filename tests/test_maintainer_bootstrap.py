"""First-install lifecycle at the public CLI boundary; no live T3 or browser."""
import subprocess
from unittest.mock import patch
from test_t3_required import T3Required, ns


class Bootstrap(T3Required):
    def result(self, code=0, out='', err=''):
        return subprocess.CompletedProcess([], code, out, err)

    def action(self):
        return dict(id='setup', kind='launch', target=str(self.tr.SOURCE_ROOT), payload='initialize',
                    room='process', options=dict(purpose='maintainer', title='Room · process · lead'))

    def test_project_error_is_not_downtime(self):
        self.fake_t3()
        with patch.object(self.tr.subprocess, 'run', return_value=self.result(1, err='No T3 Code project matches /tmp')):
            self.assertTrue(self.tr.t3_responds())
        with patch.object(self.tr.subprocess, 'run', return_value=self.result(1, err='Connection refused')):
            self.assertFalse(self.tr.t3_responds())

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

    def test_one_consent_installs_and_starts(self):
        asked = []
        def install():
            self.fake_t3()
            return True
        self.tr.t3_install = install
        self.tr.t3_responds = lambda: False
        self.tr.ASK = lambda q: asked.append(q) or 'y'
        with patch('sys.stdin.isatty', return_value=True):
            self.tr.offer_t3(ns(), lambda *a: None)
        self.assertEqual(len(asked), 1)
        self.assertIn('Install and start', asked[0])
        self.assertEqual(self.calls, ['start'])

    def test_standing_maintainer_stays_pinned_without_owner_card(self):
        self.run_cmd(ns())
        self.assertTrue(self.tr.organize_wanted(self.tr.Room('process'))['pinned'])

    def test_nested_cli_receipt_identifies_thread(self):
        with patch.object(self.tr, '_external_run', side_effect=[self.result(), self.result(out='{"thread":{"threadId":"nested-lead"}}')]), patch.object(self.tr, 'open_maintainer') as opened:
            self.assertEqual(self.tr.t3_execute(self.action())['thread'], 'nested-lead')
        opened.assert_called_once_with('nested-lead')
