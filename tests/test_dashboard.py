"""Read-model fixtures need no live store, T3 or provider access."""
import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace

api = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'bin/atr'))

class Record:
    def __init__(self, rid, state='todo', owner='Maintainer', result='', feedback='', outcome=''):
        self.data = dict(id=rid, state=state, owner=owner, title=rid, outcome=outcome)
        self.parts = {'Result': result, 'Feedback': feedback}
        self.path = Path('/fixture') / rid
        self._version = rid
        self.body = ''
    def __getitem__(self, key):
        return self.data.get(key, '')
    def section(self, name):
        return self.parts.get(name, '')

class Dashboard(unittest.TestCase):
    def room(self, items):
        return SimpleNamespace(name='process', items=items, head=None, brief=None,
                               decisions=[], refinements=[], prd=None)
    def project(self, items):
        return api['dashboard_data']([self.room(items)])['rooms'][0]
    def test_role_and_predecessor_independence(self):
        for role in ('Maintainer', 'Tooling'):
            data = self.project([Record('T06', 'done', result='Done: design\nNext: T07'),
                                 Record('T07', owner=role)])
            self.assertEqual([x['id'] for x in data['next_actions']], ['process/T07'])
            self.assertEqual(data['obligations'][0]['successors'][0]['target'], 'process/T07')
            self.assertEqual(data['obligations'][1]['execution'], 'unknown')
    def test_multiple_dangling_and_cyclic_successors(self):
        data = self.project([Record('T01', result='Next: T02 T99 other/T03'),
                             Record('T02', result='Next: T01')])
        self.assertEqual([x['status'] for x in data['obligations'][0]['successors']],
                         ['cycle', 'missing', 'missing'])
    def test_acceptance_does_not_fulfill_mixed_scope(self):
        prose = 'Done: documentation integrated; code deferred; review pending\nNext: T08 T09'
        data = self.project([Record('T03', 'review', result=prose, feedback='request', outcome='accepted'),
                             Record('T08', 'review'), Record('T09')])
        item = data['obligations'][0]
        self.assertEqual(item['disposition'], 'accepted')
        for field in ('fulfillment', 'integration', 'review', 'execution'):
            self.assertEqual(item[field], 'unknown')
        self.assertEqual(item['result'], prose)
        self.assertTrue(item['reconciliation'])
        self.assertEqual(item['evidence']['freshness'], 'unknown')
        self.assertEqual(data['capacity']['limits'], 'unavailable')
        self.assertEqual(data['capacity']['account_consumption'], 'unknown')

class Assertions(Dashboard):
    def test_scoped_stages_and_stale_result(self):
        r = Record('T03', result='pending original', feedback='request')
        def claim(scope, stage, state, day=1, **extra):
            return dict(scope=scope, stage=stage, state=state, source='manual review',
                        ref='artifact:123', observed_at=f'2026-01-{day:02}T00:00:00Z', **extra)
        claims = [
            claim('doc', 'integration', 'pending', describes_result_sha256=__import__("hashlib").sha256(r.section("Result").encode()).hexdigest()),
            claim('doc', 'integration', 'complete', 2),
            claim('code', 'implementation', 'deferred'),
            claim('T08', 'review', 'complete'),
            claim('T08', 'integration', 'pending'),
            claim('T09', 'fulfillment', 'open'),
            claim('code', 'action', 'open', action='Integrate T08', actor='lead'),
            dict(scope='invalid')]
        r.parts['Evidence assertions'] = __import__('json').dumps(claims)
        data = self.project([r, Record('T08'), Record('T09', result='Next: T08')])
        o = data['obligations'][0]
        self.assertEqual(o['result'], 'pending original')
        self.assertEqual(o['fulfillment'], 'unknown')
        self.assertTrue(any('stale Result' in x for x in o['reconciliation']))
        self.assertIn('invalid evidence assertion', o['reconciliation'])
        self.assertIsNone(data['current_actor'])
        self.assertEqual(len(o['scopes']['doc']['integration']), 2)

    def test_real_markdown_evidence_roundtrip(self):
        import tempfile, json, hashlib
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'T01.md'
            result = 'Done: doc pending'
            claim = dict(scope='doc', stage='integration', state='pending', source='curator', ref='commit:abc', observed_at='2026-01-01T00:00:00Z', describes_result_sha256=hashlib.sha256(result.encode()).hexdigest())
            newer = dict(claim, state='complete', observed_at='2026-01-02T00:00:00Z')
            path.write_text('---\nid: T01\ntitle: Doc\nstate: review\nowner: maintainer\n---\n## Result\n'+result+'\n\n## Evidence assertions\n'+json.dumps([claim,newer])+'\n')
            record = api['Record'](path)
            item = self.project([record])['obligations'][0]
            self.assertEqual(len(item['assertions']), 2)
            self.assertTrue(any('stale Result' in x for x in item['reconciliation']))

    def test_long_cycle_is_bounded(self):
        records = [Record(f'T{i:04}', result=f'Next: T{(i+1)%1100:04}') for i in range(1100)]
        self.assertEqual(self.project(records)['obligations'][0]['successors'][0]['status'], 'cycle')

if __name__ == '__main__':
    unittest.main()

class InvalidEvidence(Dashboard):
    def test_non_mapping_rejected(self):
        r = Record('T01')
        r.parts['Evidence assertions'] = '[null, 3, {}, {"stage":"bogus"}]'
        item = self.project([r])['obligations'][0]
        self.assertEqual(item['assertions'], [])
        self.assertEqual(len(item['reconciliation']), 4)

class RuntimeEvidence(Dashboard):
    def test_s1_fresh_stale_absent_and_mismatch(self):
        import time
        cache = api['dashboard_execution'].__globals__['_thread_cache']
        for status in ('running', 'idle', 'interrupted'):
            cache['fixture-thread'] = (time.time(), {'status': status})
            item = Record('T01', 'doing'); item.data['agent'] = 'fixture-thread'
            data = self.project([item])
            self.assertEqual(data['current_actor'], 'Maintainer')
            self.assertEqual(data['current_work'][0]['runtime']['state'], status)
        cache['fixture-thread'] = (time.time()-61, {'status': 'running'})
        self.assertEqual(self.project([item])['obligations'][0]['execution'], 'unknown')
        cache['fixture-thread'] = (time.time(), {'status': 'running', 'thread': 'other'})
        self.assertEqual(self.project([item])['obligations'][0]['execution'], 'unknown')
        cache.pop('fixture-thread')
        self.assertEqual(self.project([item])['obligations'][0]['execution'], 'unknown')

    def test_s3_multiple_and_s4_structured_wait_pause(self):
        room = self.room([Record('T01', 'doing'), Record('T02', 'doing')])
        project = lambda: api['dashboard_data']([room])['rooms'][0]
        self.assertIsNone(project()['current_action'])
        self.assertEqual(len(project()['current_work']), 2)
        head = Record('head'); head.data.update(wait_actor='vendor', wait_event='shipment')
        room.head = head
        self.assertEqual(project()['activity']['state'], 'external wait')
        head.data['wait_actor'] = ''
        self.assertNotEqual(project()['activity']['state'], 'external wait')
        import datetime
        room.paused = datetime.datetime.now(datetime.timezone.utc)
        self.assertEqual(project()['activity']['state'], 'paused by owner')

class MalformedRuntime(Dashboard):
    def test_scalar_observation_is_unknown(self):
        cache = api['dashboard_execution'].__globals__['_thread_cache']
        for value in (42, True, 'xx', {}, [0, None]):
            cache['malformed-fixture'] = value
            self.assertEqual(api['dashboard_execution']('malformed-fixture')['state'], 'unknown')
        cache.pop('malformed-fixture')
