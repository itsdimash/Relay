"""Exercise the browser renderer without adding a JavaScript dependency."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node is required for renderer checks')
class MarkdownTests(unittest.TestCase):
    def test_report_formatting_and_untrusted_content(self):
        renderer = Path(__file__).parents[1] / 'static' / 'markdown.js'
        script = r'''
const assert = require('node:assert/strict');
const render = require(process.argv[1]);
assert.match(render('## Report\n\n### Findings\n\n**Important** and `app/main.py`.'), /<h3>Report<\/h3>.*<h4>Findings<\/h4>.*<strong>Important<\/strong>.*<code>app\/main.py<\/code>/s);
assert.match(render('- Parent\n  - Child\n- Next'), /<ul><li>Parent<ul><li>Child<\/li><\/ul><\/li><li>Next<\/li><\/ul>/);
assert.match(render('1. First\n2. Second'), /<ol start="1"><li>First<\/li><li>Second<\/li><\/ol>/);
assert.match(render('```html\n<img src=x onerror=alert(1)>\n```'), /&lt;img src=x onerror=alert\(1\)&gt;/);
assert.ok(!render('<script>alert(1)</script>').includes('<script>'));
assert.ok(!render('[bad](javascript:alert(1))').includes('<a'));
assert.ok(!render('[bad](data:text/html,test)').includes('<a'));
assert.match(render('[Docs](https://example.com/?a=1&b=2)'), /href="https:\/\/example.com\/\?a=1&amp;b=2"/);
assert.match(render('A | B\n--- | ---\n1 | 2'), /<table>.*<th>A<\/th>.*<td>2<\/td>/s);
assert.match(render('> Note'), /<blockquote><p>Note<\/p><\/blockquote>/);
assert.match(render('**<img src=x>**'), /<strong>&lt;img src=x&gt;<\/strong>/);
assert.ok(!render('[x](https://example.com/"onclick="alert)').includes('"onclick="'));
'''
        subprocess.run(['node', '-e', script, str(renderer)], check=True, capture_output=True, text=True)

    def test_change_review_and_overview_escape_provider_content(self):
        renderer=Path(__file__).parents[1]/'static'/'review.js'
        markdown=Path(__file__).parents[1]/'static'/'markdown.js'
        script=r"""
const assert=require('node:assert/strict');
global.renderMarkdown=require(process.argv[2]);
const r=require(process.argv[1]);
const html=r.changeReview({workspace:'/sample',files:['<img>.txt'],file_reviews:[{path:'<img>.txt',status:'new',content:'<script>alert(1)</script>',additions:1,deletions:0}],builder_reports:[{round:1,report:'Result',checks:[{command:'<img src=x>',status:'failed',details:'Check failed'}]}]});
assert.ok(!html.includes('<script>'));assert.ok(html.includes('&lt;script&gt;'));
assert.ok(html.includes('1 failed'));assert.ok(html.includes('not independently rerun'));
const brief=r.summaryCard({status:'done',summary:'Full report',overview:'<img src=x>',next_actions:['Fix <script>'],findings:[{priority:'high'}]});
assert.ok(!brief.includes('<img'));assert.ok(brief.includes('1 high'));assert.ok(brief.includes('Recommended next actions'));
assert.equal(r.priority('invented'),'unrated');
assert.equal((r.diffLines({status:'new',content:'one line\n'}).match(/class="diff-line/g)||[]).length,1);
const latest=r.changeReview({files:[],builder_reports:[{round:1,report:'Earlier',checks:[{command:'test',status:'failed'}]},{round:2,report:'Latest',checks:[{command:'test',status:'passed'}]}]});
assert.ok(latest.includes('1 passed'));assert.ok(latest.includes('0 failed'));
assert.equal(r.summaryCard({status:'failed',summary:'Failure'}),'');
"""
        subprocess.run(['node','-e',script,str(renderer),str(markdown)],check=True,capture_output=True,text=True)
