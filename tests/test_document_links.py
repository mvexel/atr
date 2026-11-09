"""Exercise the renderer's link parsing and scheme restrictions in JavaScript."""
import shutil, subprocess, unittest
from pathlib import Path

@unittest.skipUnless(shutil.which('node'), 'node required')
class DocumentLinks(unittest.TestCase):
    def test_document_links_are_clickable_and_unsafe_schemes_stay_text(self):
        html = (Path(__file__).resolve().parent.parent / 'web/index.html').read_text()
        start = html.index('function safeDocumentLink(')
        end = html.index('function linked(', start)
        script = '''const assert = require('node:assert/strict');
const location = {href:'http://localhost:8787/'};
const current = 'process', recs = () => ({});
const el = (tag, attrs, ...children) => ({tag, attrs, children});
''' + html[start:end] + '''
const link = inline('[Read proposal](/doc?file=rooms%2Fprocess%2Fnotes%2Fproposal.md)').find(x => x.tag === 'a');
assert.equal(link.children[0], 'Read proposal');
assert.equal(link.attrs.href, 'http://localhost:8787/doc?file=rooms%2Fprocess%2Fnotes%2Fproposal.md');
for (const href of ['javascript:alert(1)', 'data:text/html,test', '//other.test/doc', '/\\\\other.test', 'https://a.test/\\ntext']) assert.equal(safeDocumentLink(href), null);
assert.equal(safeDocumentLink('https://example.test/doc'), 'https://example.test/doc');
assert.equal(inline('[unsafe](javascript:test)').some(x => x.tag === 'a'), false);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
