"""Exercise role selection, handoff deduplication and evidence-based completion UI."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node is required for frontend checks')
class CollaborationTests(unittest.TestCase):
    def test_role_details_handoffs_and_result_destinations(self):
        script = r'''
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const { createCollaboration } = await import('data:text/javascript;base64,' + fs.readFileSync(process.argv[1]).toString('base64'));
  class Element extends EventTarget {
    hidden = true; textContent = ''; disabled = false; dataset = {}; attrs = {};
    setAttribute(key, value) { this.attrs[key] = value; }
    toggleAttribute(key, on) { if (on) this.attrs[key] = ''; else delete this.attrs[key]; }
    focus() {}
  }
  const elements = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const buttons = ['observer','builder','reviewer'].map(agent => Object.assign(new Element(), {dataset:{agent}}));
  const doc = {getElementById:get, querySelectorAll:()=>buttons, querySelector:()=>buttons[0]};
  let timers = new Map(), clock = 0, calls = [];
  global.setTimeout = (fn, delay) => { const id = ++clock; timers.set(id, {fn,delay}); return id; };
  global.clearTimeout = id => timers.delete(id);
  const ui = createCollaboration({doc, openRun: target => calls.push(target)});
  const click = el => el.dispatchEvent(new Event('click'));
  let run = {id:'one', mode:'build', running:true, actor:'observer', status:'observing',
    team:{observer:{provider:'codex'},builder:{provider:'claude'},reviewer:{provider:'codex'}},
    activities:{observer:{message:'<script>untrusted</script>'}},result:{files:3,findings:0,checks:{passed:1,failed:0,not_run:0}}};
  ui.update(run);
  assert.equal(get('handoff').hidden, true, 'Initial snapshots must not announce a handoff');
  click(buttons[0]);
  assert.equal(get('agentCard').hidden, false);
  assert.equal(get('agentCardMessage').textContent, '<script>untrusted</script>');
  click(get('openAgentStep'));
  assert.deepEqual(calls.pop(), {runId:'one',tab:'feed',step:'inspect'});
  click(get('closeAgent'));
  run = {...run, actor:'builder',status:'building'};
  ui.update(run);
  assert.equal(get('handoff').hidden, false);
  assert.equal(get('handoffTitle').textContent, 'Codex → Claude');
  const timer = [...timers.keys()][0];
  ui.update({...run});
  assert.equal([...timers.keys()][0], timer, 'Polling the same actor must not restart the animation');
  ui.update({...run, actor:'reviewer',status:'reviewing'});
  assert.equal(get('handoffTitle').textContent, 'Claude → Codex');
  ui.update({...run,running:false,actor:null,status:'done'});
  assert.equal(get('handoff').hidden, true);
  assert.equal(get('resultCard').hidden, false);
  assert.equal(get('resultTitle').textContent, 'Review approved');
  assert.match(get('resultEvidence').textContent, /1 passed.*builder-reported checks/);
  click(get('openChanges'));
  assert.deepEqual(calls.pop(), {runId:'one',tab:'changes',step:'result'});
  click(get('openResult'));
  assert.deepEqual(calls.pop(), {runId:'one',tab:'feed',step:'result'});
  click(buttons[2]);
  assert.equal(get('resultCard').hidden, true);
  click(get('closeAgent'));
  assert.equal(get('resultCard').hidden, false);
  ui.update({...run,id:'two'});
  assert.equal(get('handoff').hidden, true, 'A different run is not a handoff');
  ui.update({...run,id:'two',running:false,status:'done',demo:true});
  assert.equal(get('resultEvidence').textContent, 'Simulation · no real checks');
  ui.hideHandoff();
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        module = Path(__file__).parents[1] / 'static/js/notch-collaboration.js'
        subprocess.run(['node', '-e', script, str(module)], check=True, capture_output=True, text=True)
