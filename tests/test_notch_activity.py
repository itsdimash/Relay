from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node is required for frontend checks')
class NotchActivityTests(unittest.TestCase):
    def test_snapshots_never_start_a_task_and_saved_history_stays_stable(self):
        script = r'''
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async()=>{
 const {createActivity}=await import('data:text/javascript;base64,'+fs.readFileSync(process.argv[1]).toString('base64'));
 class Element extends EventTarget {
   dataset={}; textContent=''; hidden=false; disabled=false; children=[]; open=false; attrs={};
   append(...children){this.children.push(...children);}
   replaceChildren(...children){this.children=children;}
   toggleAttribute(key,on){if(on)this.attrs[key]='';else delete this.attrs[key];}
 }
 const elements=new Map();
 const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const doc={getElementById:get,createElement:()=>new Element()};
 let posts=[],opened=[],resolveStart;
 const activity=createActivity({doc,post:(path,body)=>{posts.push([path,body]);return new Promise(resolve=>resolveStart=resolve);},openRun:target=>opened.push(target)});
 const item={id:'brief',task:'Fix signup',project:'/tmp/project',mode:'build',team:{name:'Custom team'}};
 const run={id:'run',recent_events:[{id:'1',agent:'Codex',role:'builder',time:'2026-10-26T00:00:00Z',kind:'message',message:'<script>untrusted</script>'}]};
 activity.update({items:[item],can_start:false},run);
 get('startNextTask').dispatchEvent(new Event('click'));
 assert.equal(posts.length,0);
 assert.equal(get('startNextTask').disabled,true);
 const row=get('notchHistoryList').children[0];
 assert.equal(row.children[1].textContent,'<script>untrusted</script>');
 activity.update({items:[item],can_start:true},run);
 assert.equal(posts.length,0,'An idle snapshot never starts a waiting task');
 assert.equal(get('notchHistoryList').children[0],row,'Identical polling must preserve the expanded list');
 get('startNextTask').dispatchEvent(new Event('click'));
 get('startNextTask').dispatchEvent(new Event('click'));
 assert.deepEqual(posts,[['/api/queue/start',{id:'brief'}]]);
 resolveStart({id:'new-run',queue:{items:[],can_start:false}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(opened,[{runId:'new-run',tab:'feed',step:'inspect'}]);
 assert.equal(get('notchQueue').hidden,true);
 assert.equal(get('startNextTask').disabled,true);
 activity.update({items:[item],can_start:false},run);
 get('notchHistory').open=true;
 get('notchHistory').dispatchEvent(new Event('toggle'));
 assert.equal(get('notchQueue').open,false);
 assert.ok('data-history-open' in get('panel').attrs);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        module = Path(__file__).parents[1] / 'static/js/notch-activity.js'
        subprocess.run(['node', '-e', script, str(module)], check=True, capture_output=True, text=True)
