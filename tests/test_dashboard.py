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

if __name__ == '__main__':
    unittest.main()
