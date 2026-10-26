from http.server import ThreadingHTTPServer
import importlib.util
import base64
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error

from relay import notify as notifier

SPEC = importlib.util.spec_from_file_location('relay', Path(__file__).parents[1] / 'server.py')
s = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s)
s = s.application
REAL_WAIT_FOR_PLAN = s.Run.wait_for_plan


PNG_BYTES = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jL1sAAAAASUVORK5CYII=')
def image_payload(name='screenshot.png'):
    return dict(name=name,mime='image/png',data=base64.b64encode(PNG_BYTES).decode())


def review(status='approved'):
    return dict(status=status, summary='Reviewed actual source', findings=[] if status != 'needs_changes' else [dict(id='R1',file='app.txt',problem='Missing trim',evidence='app.txt passes whitespace',requested_change='Trim first')], acceptance_checks=['Empty and whitespace input rejected'])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.old_data = s.DATA
        s.DATA = self.base / 'data'
        self.project = self.base / 'project'
        self.project.mkdir()
        subprocess.run(['git','init','-q',str(self.project)],check=True)
        s.git(self.project,'config','user.email','test@example.com')
        s.git(self.project,'config','user.name','Test')
        (self.project/'app.txt').write_text('initial\n')
        s.git(self.project,'add','app.txt')
        s.git(self.project,'commit','-qm','Initial')
        self.ready = patch.object(s,'tool_status',return_value={n:dict(installed=True,signed_in=True) for n in ['codex','claude']})
        self.ready.start()
        def approved_fixture(run, observation):
            run.info['plan'] = dict(id='fixture-approved-plan', **observation)
            run.info['approved_plan_id'] = 'fixture-approved-plan'
            run.info['plan_approved_at'] = s.now()
        self.approval_patch = patch.object(s.Run,'wait_for_plan',approved_fixture)
        self.approval_patch.start()

    def tearDown(self):
        self.approval_patch.stop()
        self.ready.stop()
        s.DATA = self.old_data
        self.temp.cleanup()

    def test_read_only_modes(self):
        for mode in ('observe', 'plan'):
            for provider in ('claude', 'codex'):
                with self.subTest(mode=mode,provider=provider):
                    team=json.loads(json.dumps(s.DEFAULT_TEAM))
                    team['roles']['observer']['provider']=provider
                    run=s.Run('Inspect only',self.project,mode=mode,team=team)
                    calls=[]
                    def inspect(prompt):
                        calls.append((run.current_role,prompt))
                        return review('observed')
                    statuses={n:dict(installed=n==provider,signed_in=n==provider) for n in ('claude','codex')}
                    with patch.object(s,'tool_status',return_value=statuses),patch.object(run,'claude',side_effect=inspect),patch.object(run,'codex',side_effect=inspect):
                        run.execute()
                    self.assertEqual(run.info['status'],'done')
                    self.assertEqual([role for role,_ in calls],['observer'])
                    self.assertIn('Read-only role',calls[0][1])
                    self.assertIn('implementation plan' if mode=='plan' else 'current behavior',calls[0][1])
                    self.assertEqual(run.info['summary'],'Reviewed actual source')
                    self.assertEqual(run.info['files'],[])
                    self.assertEqual((self.project/'app.txt').read_text(),'initial\n')
                    with self.assertRaises(RuntimeError): run.run_role('builder','Edit')
                    self.assertEqual(json.loads((run.folder/'state.json').read_text())['mode'],mode)

    def test_read_only_modes_accept_current_folders_without_git_operations(self):
        (self.project/'app.txt').write_text('staged content\n')
        s.git(self.project,'add','app.txt')
        (self.project/'app.txt').write_text('current unstaged content\n')
        (self.project/'new.txt').write_text('untracked content\n')
        plain=self.base/'plain'
        plain.mkdir()
        (plain/'notes.txt').write_text('non-Git folder\n')
        nested=self.project/'nested'
        nested.mkdir()
        (nested/'notes.txt').write_text('nested folder\n')
        before=s.git(self.project,'status','--porcelain')
        for mode in ('observe','plan'):
            for folder in (self.project,plain,nested):
                with self.subTest(mode=mode,folder=folder):
                    run=s.Run('Inspect current files',folder,mode=mode)
                    def inspect(prompt):
                        self.assertEqual(Path(run.info['workspace']),folder.resolve())
                        if folder==self.project:
                            self.assertEqual((folder/'app.txt').read_text(),'current unstaged content\n')
                            self.assertEqual((folder/'new.txt').read_text(),'untracked content\n')
                        return review('observed')
                    with patch.object(s,'git',side_effect=AssertionError('Read-only mode must not invoke Git')),patch.object(run,'claude',side_effect=inspect),patch.object(run,'codex',side_effect=AssertionError('Builder must not run')),patch.object(run,'snapshot',side_effect=AssertionError('Do not attribute existing edits to this task')):
                        run.execute()
                    self.assertEqual(run.info['status'],'done')
                    self.assertEqual(run.info['files'],[])
                    self.assertEqual(run.info['diff'],'')
                    self.assertFalse((run.folder/'changes.patch').exists())
        self.assertEqual(s.git(self.project,'status','--porcelain'),before)
        self.assertEqual((self.project/'app.txt').read_text(),'current unstaged content\n')
        self.assertFalse((s.DATA/'workspaces').exists())

    def test_followup_preserves_conversation_and_context_after_reload(self):
        root=s.Run('Inspect validation',self.project,mode='observe')
        root.info.update(status='done',summary='Original report with evidence',findings=review('needs_changes')['findings'])
        root.finished.set();root.save()
        with patch.dict(s.RUNS,{root.id:root},clear=True):
            source=s.report_source(root.id)
            for question in ('Why does this matter?', 'What should I do first?'):
                follow=s.Run(question,self.project,mode='observe',team=source['team'],context=s.report_context(source),conversation=source)
                with patch.object(follow,'claude',return_value=review('observed')),patch.object(follow,'codex',side_effect=AssertionError('Must stay read-only')):
                    follow.execute()
                self.assertEqual(follow.id,root.id)
                self.assertEqual(follow.info['status'],'done')
                self.assertIn('Original report with evidence',follow.info['context'])
                self.assertEqual(follow.info['conversation_title'],'Inspect validation')
                s.RUNS[root.id]=follow
                source=s.report_source(root.id)
            self.assertEqual(len(source['turns']),2)
            self.assertEqual(s.source_findings(source)[0]['id'],'R1')
            s.load_runs()
            self.assertEqual(s.RUNS[root.id]['turns'][0]['summary'],'Original report with evidence')
            s.delete_history(root.id)
            s.restore_history(root.id)
            self.assertEqual(len(s.RUNS[root.id]['turns']),2)

    def test_selected_findings_context_is_validated_and_limited(self):
        source=dict(task='Original',summary='Report',findings=[dict(id='R1',problem='One'),dict(id='R2',problem='Two')])
        context=s.report_context(source,[1])
        self.assertIn('R2',context)
        self.assertNotIn('R1',context)
        for indexes in ([],[-1],[2],[True],[0,0],'R1'):
            with self.assertRaises(ValueError): s.report_context(source,indexes)
        with self.assertRaisesRegex(ValueError,'too long'):
            s.report_context(dict(task='Task',summary='x'*90001))
        with patch.dict(s.RUNS,{},clear=True):
            with self.assertRaises(ValueError): s.report_source('missing')

    def test_builder_waits_for_explicit_plan_approval(self):
        self.approval_patch.stop()
        run=s.Run('Implement validation',self.project,minutes=1)
        calls=[]
        def claude(prompt):
            calls.append(run.current_role)
            return review('observed' if run.current_role=='observer' else 'approved')
        def builder(prompt):
            calls.append('builder')
            return 'Implemented with checks'
        with patch.object(run,'claude',side_effect=claude),patch.object(run,'codex',side_effect=builder):
            worker=threading.Thread(target=run.execute);worker.start()
            try:
                limit=time.monotonic()+5
                while run.info['status']!='awaiting_approval' and time.monotonic()<limit:time.sleep(.01)
                self.assertEqual(run.info['status'],'awaiting_approval')
                self.assertEqual(calls,['observer'])
                self.assertIsNone(run.deadline)
                self.assertEqual(run.info['plan']['summary'],'Reviewed actual source')
                self.assertEqual(run.info['plan']['acceptance_checks'],review()['acceptance_checks'])
                with self.assertRaises(ValueError):run.approve_plan('stale-id')
                with self.assertRaises(RuntimeError):run.run_role('builder','Bypass approval')
                self.assertEqual(calls,['observer'])
                run.approve_plan(run.info['plan']['id'])
                worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(run.info['status'],'done')
                self.assertEqual(calls,['observer','builder','reviewer'])
                self.assertTrue(run.info['plan_approved_at'])
                with self.assertRaises(ValueError):run.approve_plan(run.info['plan']['id'])
            finally:
                run.stop_event.set();worker.join(5)

    def test_reject_plan_stops_without_starting_builder(self):
        self.approval_patch.stop()
        run=s.Run('Implement validation',self.project)
        with patch.object(run,'claude',return_value=review('observed')),patch.object(run,'codex',side_effect=AssertionError('Builder must not start')):
            worker=threading.Thread(target=run.execute);worker.start()
            try:
                limit=time.monotonic()+5
                while run.info['status']!='awaiting_approval' and time.monotonic()<limit:time.sleep(.01)
                self.assertEqual(run.info['status'],'awaiting_approval')
                run.stop_event.set();run.resume_event.set();worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(run.info['status'],'stopped')
                self.assertNotIn('approved_plan_id',run.info)
                self.assertEqual((Path(run.info['workspace'])/'app.txt').read_text(),'initial\n')
            finally:
                run.stop_event.set();worker.join(5)

    def test_file_reviews_capture_new_deleted_binary_and_link_files(self):
        (self.project/'app.txt').write_text('updated\n')
        (self.project/'new file.txt').write_text('new text\n<script>not markup</script>\n')
        (self.project/'binary.bin').write_bytes(b'\0binary')
        outside=self.base/'private.txt';outside.write_text('outside content must not be captured')
        (self.project/'linked.txt').symlink_to(outside)
        files={f['path']:f for f in s.capture_file_reviews(self.project)}
        self.assertEqual(files['app.txt']['status'],'modified')
        self.assertIn('+updated',files['app.txt']['content'])
        self.assertEqual(files['new file.txt']['status'],'new')
        self.assertIn('new text',files['new file.txt']['content'])
        self.assertEqual(files['new file.txt']['additions'],2)
        self.assertIn('Binary',files['binary.bin']['notice'])
        self.assertEqual(files['binary.bin']['content'],'')
        self.assertEqual(files['linked.txt']['content'],'')
        self.assertNotIn('outside content',json.dumps(files))
        (self.project/'app.txt').unlink()
        files={f['path']:f for f in s.capture_file_reviews(self.project)}
        self.assertEqual(files['app.txt']['status'],'deleted')
        self.assertIn('-initial',files['app.txt']['content'])

    def test_file_preview_limits_and_reported_checks(self):
        (self.project/'large.txt').write_text('x'*110000)
        file=next(f for f in s.capture_file_reviews(self.project) if f['path']=='large.txt')
        self.assertLessEqual(len(file['content']),100000)
        self.assertIn('truncated',file['notice'])
        report='Changed validation.\n```relay-checks\n[{"command":"pytest -q", "status":"passed", "details":"2 passed"},{"command":"lint", "status":"not_run", "details":"Not installed"}]\n```'
        checks=s.reported_checks(report)
        self.assertEqual([c['status'] for c in checks],['passed','not_run'])
        self.assertEqual(s.reported_checks('Tests passed, trust me'),[])
        self.assertEqual(s.reported_checks('```relay-checks\nnot json\n```'),[])
        self.assertEqual(s.reported_checks('```relay-checks\n[{"command":"test","status":"invented"}]\n```'),[])
        result=review('needs_changes');result.update(overview='Short overview',next_actions=['Fix the input boundary'])
        result['findings'][0]['priority']='high'
        s.validate_review(result)
        result['findings'][0]['priority']='unknown'
        with self.assertRaises(ValueError):s.validate_review(result)

    def test_image_validation_and_native_provider_inputs(self):
        images=s.decode_images([image_payload('../../screenshot.png')])
        self.assertEqual(images[0]['name'],'screenshot.png')
        self.assertEqual(images[0]['mime'],'image/png')
        run=s.Run('Inspect screenshot',self.project,mode='observe',attachments=images)
        path=s.saved_image_path(run.info,run.info['attachments'][0]['id'])
        self.assertEqual(path.read_bytes(),PNG_BYTES)
        self.assertNotIn('data',run.info['attachments'][0])
        run.info['workspace']=str(self.project);run.current_role='observer'
        def launch(agent,args,prompt,**kwargs):
            if agent=='Claude':
                self.assertIn('--input-format',args)
                message=json.loads(kwargs['input_data'])
                self.assertEqual(message['type'],'user')
                blocks=message['message']['content']
                self.assertEqual(blocks[0]['text'],'Review this image')
                self.assertEqual(base64.b64decode(blocks[1]['source']['data']),PNG_BYTES)
                self.assertEqual(blocks[1]['source']['media_type'],'image/png')
                return review('observed'),''
            self.assertIn('--image',args)
            self.assertEqual(args[args.index('--image')+1],str(path))
            self.assertEqual(args[-2:],['--','-'])
            self.assertEqual(args[args.index('--sandbox')+1],'read-only')
            Path(args[args.index('-o')+1]).write_text(json.dumps(review('observed')))
            return None,''
        with patch.object(run,'launch',side_effect=launch):
            self.assertEqual(run.claude('Review this image')['status'],'observed')
            self.assertEqual(run.codex('Review this image')['status'],'observed')
        original=run.info.copy()
        follow=s.Run('Explain it',self.project,mode='observe',conversation=original,attachments=s.inherited_images(original))
        self.assertEqual(s.saved_image_path(follow.info,images[0]['id']).read_bytes(),PNG_BYTES)
        child=s.Run('Plan a fix',self.project,mode='plan',attachments=s.inherited_images(original))
        self.assertNotEqual(s.saved_image_path(child.info,images[0]['id']),path)
        self.assertEqual(s.saved_image_path(child.info,images[0]['id']).read_bytes(),PNG_BYTES)

    def test_chat_replies_are_plain_text_without_the_structured_report_contract(self):
        for provider in s.PROVIDERS:
            args=s.provider_command(provider,'observer',{'model':'','effort':''},'/workspace','/output','/schema',structured=False)
            self.assertNotIn('--json-schema',args);self.assertNotIn('--output-schema',args)
        self.assertEqual(s.provider_command('codex','observer',{'model':'','effort':''},'/workspace','/output','/schema',structured=False)[3:5],['--sandbox','read-only'])
        self.assertIn('--json-schema',s.provider_command('claude','observer',{'model':'','effort':''},'/workspace','/output','/schema'))
        saved=dict(summary='Earlier plan',findings=[],mode='plan',project=str(self.project),workspace=str(self.project),status='done',created='now',task='Plan it')
        run=s.Run('Write the prompt',self.project,mode='observe',conversation={**saved,'id':'abcdef123456'},chat=True)
        self.assertTrue(run.info['chat'])
        run.info['workspace']=str(self.project);run.current_role='observer'
        def claude_launch(agent,args,prompt,**kwargs):
            self.assertNotIn('--json-schema',args)
            run.final_message='The full prompt'
            return None,'Reading files\n\nThe full prompt'
        with patch.object(run,'launch',side_effect=claude_launch):
            self.assertEqual(run.claude('Q'),'The full prompt')
        def codex_launch(agent,args,prompt,**kwargs):
            Path(args[args.index('-o')+1]).write_text('Codex final answer\n')
            return None,'noise'
        with patch.object(run,'launch',side_effect=codex_launch):
            self.assertEqual(run.codex('Q'),'Codex final answer')
        with patch.object(run,'launch',return_value=(None,'  ')),self.assertRaises(RuntimeError):run.claude('Q')

    def test_plan_from_conversation_uses_the_latest_finished_plan_not_chat_replies(self):
        plan=dict(mode='plan',status='done',summary='Step 1\nStep 2',findings=[],acceptance_checks=['Check A'])
        before=dict(mode='observe',chat=True,status='done',task='Earlier question',summary='Earlier answer')
        chat=dict(mode='observe',chat=True,status='done',task='Skip step 2 please',summary='Sure, dropping step 2')
        broken=dict(mode='observe',chat=True,status='failed',task='Lost message',summary='Agent crashed')
        found=s.plan_from_conversation({**chat,'turns':[before,plan,broken]})
        self.assertTrue(found['summary'].startswith('Step 1\nStep 2'))
        self.assertIn('Skip step 2 please',found['summary']);self.assertIn('Sure, dropping step 2',found['summary'])
        self.assertIn('take precedence over the plan',found['summary'])
        self.assertNotIn('Earlier question',found['summary']);self.assertNotIn('Lost message',found['summary'])
        self.assertEqual(found['acceptance_checks'],['Check A'])
        self.assertEqual(s.plan_from_conversation(plan)['summary'],'Step 1\nStep 2')
        with self.assertRaises(ValueError):s.plan_from_conversation({**chat,'turns':[]})
        with self.assertRaises(ValueError):s.plan_from_conversation({**plan,'status':'failed'})

    def test_building_a_read_plan_skips_planning_and_is_approved_by_the_choice_to_build(self):
        pre=dict(summary='1. Edit app.txt',findings=[],acceptance_checks=['app.txt changed'])
        run=s.Run('Build the plan',self.project,mode='build',pre_plan=pre,context='Previous conversation: the plan')
        roles=[]
        def codex(prompt):
            roles.append(run.current_role)
            self.assertIn('1. Edit app.txt',prompt);self.assertIn('Previous conversation: the plan',prompt)
            (Path(run.info['workspace'])/'app.txt').write_text('built')
            return 'Edited app.txt. Checks passed.'
        def claude(prompt):
            roles.append(run.current_role)
            self.assertIn('app.txt changed',prompt)
            self.assertIn('1. Edit app.txt',prompt)
            return review('approved')
        with patch.object(run,'claude',side_effect=claude),patch.object(run,'codex',side_effect=codex):run.execute()
        self.assertEqual(roles,['builder','reviewer'])
        self.assertEqual(run.info['status'],'done')
        self.assertEqual(run.info['approved_plan_id'],run.info['plan']['id'])
        self.assertTrue(run.info['plan_approved_at'])
        self.assertIsNone(s.require_recovery_approval(run.info))
        self.assertEqual((self.project/'app.txt').read_text(),'built')
        self.assertEqual(run.info['files'],['app.txt'])

    def test_chat_agent_acts_right_away_on_the_real_folder_and_records_what_it_changed(self):
        codex_args=s.provider_command('codex','builder',{'model':'','effort':''},'/w','/o','/s',structured=False,network=True)
        self.assertEqual(codex_args[codex_args.index('--sandbox')+1],'workspace-write')
        self.assertIn('sandbox_workspace_write.network_access=true',codex_args);self.assertNotIn('--output-schema',codex_args)
        claude_args=s.provider_command('claude','builder',{'model':'','effort':''},'/w','','',structured=False)
        self.assertIn('Edit',claude_args[claude_args.index('--tools')+1]);self.assertNotIn('--json-schema',claude_args)
        saved=dict(summary='Earlier plan',findings=[],mode='plan',project=str(self.project),workspace=str(self.project),status='done',created='now',task='Plan it')
        first=s.Run('Create notes.txt',self.project,mode='observe',conversation={**saved,'id':'abcdef123456'},chat=True)
        seen=[]
        def codex(prompt):
            seen.append((first.current_role,prompt));(self.project/'notes.txt').write_text('notes');return 'Created notes.txt.'
        with patch.object(first,'codex',side_effect=codex):first.execute()
        self.assertEqual(first.info['status'],'done',first.info['summary'])
        self.assertEqual(seen[0][0],'builder');self.assertIn('do it now with your tools',seen[0][1]);self.assertIn('not in a read-only mode',seen[0][1])
        self.assertEqual(first.info['summary'],'Created notes.txt.')
        self.assertEqual((self.project/'notes.txt').read_text(),'notes')
        self.assertEqual(first.info['files'],['notes.txt'])
        self.assertIn('notes.txt',(first.folder/'changes.patch').read_text())
        # A later message that changes nothing leaves the earlier changes and their export in place.
        second=s.Run('What did you do?',self.project,mode='observe',conversation={**first.info},chat=True)
        with patch.object(second,'codex',return_value='I created notes.txt.'):second.execute()
        self.assertEqual(second.info['status'],'done');self.assertEqual(second.info['files'],[])
        self.assertIn('notes.txt',(second.folder/'changes.patch').read_text())
        self.assertEqual(second.info['turns'][-1]['files'],['notes.txt'])

    def test_auto_mode_approves_its_own_plan_skips_questions_and_runs_to_completion(self):
        with patch.object(s.Run,'wait_for_plan',REAL_WAIT_FOR_PLAN):
            run=s.Run('Improve validation',self.project,auto=True)
            self.assertTrue(run.info['auto'])
            prompts=[]
            def claude(prompt):
                prompts.append((run.current_role,prompt))
                if run.current_role=='observer':
                    asked=review('observed');asked['questions']=[dict(id='Q1',question='Which pages?',options=['All','One'])];return asked
                return review('approved')
            def codex(prompt):
                (self.project/'app.txt').write_text('done');return 'Edited app.txt.'
            with patch.object(run,'claude',side_effect=claude),patch.object(run,'codex',side_effect=codex):run.execute()
        self.assertEqual(run.info['status'],'done',run.info['summary'])
        self.assertIn('Do not ask questions',prompts[0][1])
        self.assertNotIn('clarification',run.info)
        self.assertEqual(run.info['approved_plan_id'],run.info['plan']['id'])
        self.assertTrue(any(e['kind']=='control' and 'Auto mode approved the plan' in e['message'] for e in run.info['events']))
        self.assertEqual([role for role,_ in prompts],['observer','reviewer'])
        self.assertIsNone(s.require_recovery_approval(run.info))

    def auto_agents(self,run,decisions,reviews):
        """Scripted agents: the observer plans once, then makes Auto mode's decisions; the reviewer follows `reviews`."""
        seen=dict(observer=0,reviewer=0,decisions=0,builds=[])
        def claude(prompt):
            if run.current_role=='observer':
                seen['observer']+=1
                if seen['observer']==1:return review('observed')
                seen['decisions']+=1;return review(decisions[min(seen['decisions']-1,len(decisions)-1)])
            seen['reviewer']+=1;return review(reviews[min(seen['reviewer']-1,len(reviews)-1)])
        def codex(prompt):
            seen['builds'].append(run.info['round']);(self.project/'app.txt').write_text('try '+str(len(seen['builds'])));return 'Tried.'
        return claude,codex,seen

    def test_auto_mode_decides_for_you_when_findings_keep_repeating(self):
        run=s.Run('Improve validation',self.project,rounds=0,minutes=0,auto=True)
        claude,codex,seen=self.auto_agents(run,['approved'],['needs_changes'])
        with patch.object(s.Run,'wait_for_plan',REAL_WAIT_FOR_PLAN),patch.object(s,'notify') as notify:
            with patch.object(run,'claude',side_effect=claude),patch.object(run,'codex',side_effect=codex):run.execute()
        self.assertEqual(seen['builds'],[1,2,3]);self.assertEqual(seen['decisions'],1)
        self.assertEqual(run.info['status'],'done',run.info['summary']);self.assertTrue(run.info['auto_accepted'])
        self.assertIn('Open items Auto mode accepted',run.info['summary']);self.assertIn('R1',run.info['summary'])
        self.assertEqual(len(run.info['findings']),1)
        self.assertTrue(any('accept what is there' in e['message'] for e in run.info['events'] if e['kind']=='control'))
        self.assertEqual(notify.call_args[0][0],'Relay: auto task finished with open items')

    def test_auto_mode_changes_approach_at_most_twice_and_then_finishes_with_what_is_left(self):
        run=s.Run('Improve validation',self.project,rounds=0,minutes=0,auto=True)
        claude,codex,seen=self.auto_agents(run,['needs_changes'],['needs_changes'])
        with patch.object(s.Run,'wait_for_plan',REAL_WAIT_FOR_PLAN),patch.object(s,'notify'):
            with patch.object(run,'claude',side_effect=claude),patch.object(run,'codex',side_effect=codex):run.execute()
        self.assertEqual(seen['decisions'],2);self.assertEqual(seen['builds'],list(range(1,10)))
        self.assertEqual(run.info['status'],'done');self.assertTrue(run.info['auto_accepted'])
        self.assertIn('already changed approach 2 times',run.info['summary'])

    def test_auto_mode_at_a_round_limit_can_grant_itself_more_rounds_but_a_manual_task_still_stops(self):
        run=s.Run('Improve validation',self.project,rounds=2,minutes=0,auto=True)
        claude,codex,seen=self.auto_agents(run,['needs_changes'],['needs_changes','needs_changes','approved'])
        with patch.object(s.Run,'wait_for_plan',REAL_WAIT_FOR_PLAN),patch.object(s,'notify'):
            with patch.object(run,'claude',side_effect=claude),patch.object(run,'codex',side_effect=codex):run.execute()
        self.assertEqual(seen['builds'],[1,2,3]);self.assertEqual(run.info['max_rounds'],4)
        self.assertEqual(run.info['status'],'done');self.assertFalse(run.info.get('auto_accepted'))
        manual=s.Run('Improve validation',self.project,rounds=2,minutes=0)
        with patch.object(manual,'claude',side_effect=lambda p:review('observed') if manual.current_role=='observer' else review('needs_changes')),patch.object(manual,'codex',return_value='Tried.'):manual.execute()
        self.assertEqual(manual.info['status'],'needs_attention');self.assertEqual(manual.info['workflow']['step'],'limit')

    def run_auto(self,claude,codex,auto=True):
        run=s.Run('Improve validation',self.project,auto=auto,minutes=0)
        with patch.object(s.Run,'wait_for_plan',REAL_WAIT_FOR_PLAN),patch.object(s.Run,'RETRY_WAITS',(0,0)),patch.object(s,'notify') as notify:
            with patch.object(run,'claude',side_effect=claude),patch.object(run,'codex',side_effect=codex):run.execute()
        return run,notify

    def test_auto_mode_retries_a_failed_agent_and_tells_you_how_it_ended(self):
        builds=[]
        def codex(prompt):
            builds.append(prompt)
            if len(builds)==1:raise RuntimeError('Codex could not complete this step: connection lost')
            (self.project/'app.txt').write_text('done');return 'Edited app.txt.'
        run,notify=self.run_auto(lambda p:review('observed') if 'observer' in (self.current_role_of(p) or 'observer') else review('approved'),codex)
        self.assertEqual(run.info['status'],'done',run.info['summary'])
        self.assertEqual(len(builds),2);self.assertIn('being retried after an error',builds[1]);self.assertNotIn('being retried',builds[0])
        self.assertEqual(run.info['auto_retries'],1)
        self.assertTrue(any('Auto mode: the builder hit an error' in e['message'] and 'try 2 of 3' in e['message'] for e in run.info['events']))
        notify.assert_called_once();self.assertEqual(notify.call_args[0][0],'Relay: auto task finished')

    def current_role_of(self,prompt):
        return 'reviewer' if 'You are the reviewer' in prompt else 'observer' if 'You are the observer' in prompt else None

    def test_auto_mode_gives_up_after_its_retries_and_a_manual_task_never_retries(self):
        calls=[]
        def claude(prompt):
            calls.append(prompt);raise RuntimeError('Claude could not complete this step: rate limited')
        run,notify=self.run_auto(claude,lambda p:'unused')
        self.assertEqual(len(calls),3);self.assertEqual(run.info['status'],'failed');self.assertIn('rate limited',run.info['summary'])
        self.assertEqual(notify.call_args[0][0],'Relay: auto task stopped with an error');self.assertIn('rate limited',notify.call_args[0][1])
        calls.clear()
        manual,notify=self.run_auto(claude,lambda p:'unused',auto=False)
        self.assertEqual(len(calls),1);self.assertEqual(manual.info['status'],'failed');notify.assert_not_called()

    def test_stopping_during_an_auto_retry_wait_is_respected_and_not_announced(self):
        run=s.Run('Improve validation',self.project,auto=True,minutes=0)
        def claude(prompt):
            run.stop_event.set();raise RuntimeError('Claude could not complete this step: connection lost')
        with patch.object(s.Run,'RETRY_WAITS',(5,5)),patch.object(s,'notify') as notify,patch.object(run,'claude',side_effect=claude):run.execute()
        self.assertEqual(run.info['status'],'stopped');notify.assert_not_called()

    def test_notifications_are_escaped_and_only_sent_on_a_mac(self):
        script=notifier.applescript('Relay: "done"','line one\nCafé \\ end')
        self.assertIn('with title "Relay: \\"done\\""',script);self.assertIn('Café',script);self.assertNotIn('\\u',script)
        with patch.object(notifier.sys,'platform','linux'),patch.object(notifier.subprocess,'run') as run:
            self.assertFalse(notifier.send('t','m'));run.assert_not_called()
        with patch.object(notifier.sys,'platform','darwin'),patch.dict(notifier.os.environ,{'RELAY_NO_NOTIFY':'1'}),patch.object(notifier.subprocess,'run') as run:
            self.assertFalse(notifier.send('t','m'));run.assert_not_called()
        with patch.object(notifier.sys,'platform','darwin'),patch.dict(notifier.os.environ,{},clear=False),patch.object(notifier.subprocess,'run') as run:
            notifier.os.environ.pop('RELAY_NO_NOTIFY',None)
            self.assertTrue(notifier.send('t','m'))
            for thread in threading.enumerate():
                if thread is not threading.current_thread() and thread.daemon:thread.join(2)
            self.assertEqual(run.call_args[0][0][:2],['osascript','-e'])

    def test_invalid_images_are_rejected(self):
        for images in ([image_payload()]*5,{},[dict(name='x',mime='image/png',data='not base64')],[dict(name='x.svg',mime='image/svg+xml',data=base64.b64encode(b'<svg/>').decode())],[dict(image_payload(),mime='image/jpeg')]):
            with self.assertRaises(ValueError):s.decode_images(images)
        with self.assertRaises(ValueError):
            s.decode_images([dict(name='large.png',data=base64.b64encode(b'x'*(s.MAX_IMAGE_BYTES+1)).decode())])
        run=s.Run('Task',self.project,attachments=s.decode_images([image_payload()]))
        image_id=run.info['attachments'][0]['id']
        with self.assertRaises(ValueError):s.saved_image_path(run.info,'../private')
        path=s.saved_image_path(run.info,image_id);path.unlink();path.symlink_to(self.project/'app.txt')
        with self.assertRaises(ValueError):s.saved_image_path(run.info,image_id)

    def test_invalid_mode(self):
        with self.assertRaises(ValueError): s.Run('Task',self.project,mode='unknown')
        self.assertFalse(s.DATA.exists())

    def test_revision_loop_edits_the_folder_directly_and_records_a_baseline(self):
        run = s.Run('Improve validation',self.project)
        calls = []
        def claude(prompt):
            calls.append(('claude',prompt))
            if len(calls)==1: return review('observed')
            return review('needs_changes' if run.info['round']==1 else 'approved')
        def codex(prompt):
            calls.append(('codex',prompt))
            (Path(run.info['workspace'])/'app.txt').write_text('fixed round '+str(run.info['round']))
            return 'Changed app.txt. Checks passed.'
        with patch.object(run,'claude',side_effect=claude),patch.object(run,'codex',side_effect=codex): run.execute()
        self.assertEqual([c[0] for c in calls],['claude','codex','claude','codex','claude'])
        self.assertIn('Missing trim',calls[3][1])
        self.assertEqual(run.info['status'],'done')
        self.assertEqual((self.project/'app.txt').read_text(),'fixed round 2')
        self.assertEqual(run.info['workspace'],str(self.project.resolve()))
        self.assertTrue(Path(run.info['workflow']['baseline']).is_dir())
        self.assertFalse((s.DATA/'workspaces').exists())
        self.assertIn('fixed round 2',run.info['diff'])
        self.assertEqual(run.info['files'],['app.txt'])

    def test_all_provider_role_combinations(self):
        for providers in itertools.product(s.PROVIDERS,repeat=3):
            with self.subTest(providers=providers):
                team=s.validate_team(s.DEFAULT_TEAM)
                for role,provider in zip(s.ROLES,providers):team['roles'][role]['provider']=provider
                team['roles']['builder']['instructions']='Keep the change small.'
                run=s.Run('Task',self.project,team=team)
                calls=[]
                def fake(provider,prompt):
                    role=run.current_role;calls.append((role,provider))
                    if role=='builder':
                        self.assertIn('Keep the change small.',prompt)
                        (Path(run.info['workspace'])/'app.txt').write_text('updated')
                        return 'Updated app.txt. Checks passed.'
                    return review('observed' if role=='observer' else 'approved')
                with patch.object(run,'claude',side_effect=lambda p:fake('claude',p)),patch.object(run,'codex',side_effect=lambda p:fake('codex',p)):
                    run.execute()
                self.assertEqual(run.info['status'],'done')
                self.assertEqual(calls,list(zip(s.ROLES,providers)))
                self.assertEqual(run.info['team'],team)

    def test_only_selected_providers_are_required(self):
        team=s.validate_team(s.DEFAULT_TEAM)
        for profile in team['roles'].values():profile['provider']='codex'
        run=s.Run('Task',self.project,team=team)
        with patch.object(s,'tool_status',return_value={'claude':dict(installed=False,signed_in=False),'codex':dict(installed=True,signed_in=True)}),patch.object(run,'codex',side_effect=lambda p:'Implemented' if run.current_role=='builder' else review('observed' if run.current_role=='observer' else 'approved')):
            run.execute()
        self.assertEqual(run.info['status'],'done')

    def test_codex_review_uses_final_schema_file(self):
        run=s.Run('Task',self.project);run.current_role='reviewer';run.info['workspace']=str(self.project)
        def fake_launch(provider,args,prompt):
            output=Path(args[args.index('-o')+1]);output.write_text(json.dumps(review()))
            return None,'Progress notes are not JSON'
        with patch.object(run,'launch',side_effect=fake_launch):result=run.codex('Review')
        self.assertEqual(result['status'],'approved')

    def test_claude_builder_returns_report(self):
        team=s.validate_team(s.DEFAULT_TEAM);team['roles']['builder']['provider']='claude'
        run=s.Run('Task',self.project,team=team);run.current_role='builder'
        with patch.object(run,'launch',return_value=(None,'Changed code and ran checks')):
            self.assertEqual(run.claude('Build'),'Changed code and ran checks')
        self.assertTrue((run.folder/'builder-0.txt').exists())

    def test_round_limit_preserves_findings(self):
        run=s.Run('Task',self.project,rounds=1)
        with patch.object(run,'claude',side_effect=[review('observed'),review('needs_changes')]),patch.object(run,'codex',return_value='Implemented'):
            run.execute()
        self.assertEqual(run.info['status'],'needs_attention')
        self.assertEqual(run.info['findings'][0]['id'],'R1')

    def test_unlimited_rounds_can_approve_after_five(self):
        run=s.Run('Task',self.project,rounds=0,minutes=0)
        def claude(prompt):
            if run.info['status']=='observing':return review('observed')
            return review('approved' if run.info['round']==7 else 'needs_changes')
        with patch.object(run,'claude',side_effect=claude),patch.object(run,'codex',return_value='Implemented'):
            run.execute()
        self.assertEqual(run.info['status'],'done')
        self.assertEqual(run.info['round'],7)
        self.assertIsNone(run.deadline)

    def test_unlimited_task_still_stops(self):
        run=s.Run('Task',self.project,rounds=0,minutes=0)
        def claude(prompt):
            if run.info['status']=='observing':return review('observed')
            if run.info['round']==6:run.stop_event.set()
            return review('needs_changes')
        with patch.object(run,'claude',side_effect=claude),patch.object(run,'codex',return_value='Implemented'):
            run.execute()
        self.assertEqual(run.info['status'],'stopped')
        self.assertEqual(run.info['round'],6)

    def test_unlimited_rounds_respect_time_limit(self):
        run=s.Run('Task',self.project,rounds=0,minutes=1)
        run.deadline=time.monotonic()-1
        with self.assertRaises(TimeoutError):run.check()

    def test_unlimited_time_respects_round_limit(self):
        run=s.Run('Task',self.project,rounds=1,minutes=0)
        with patch.object(run,'claude',side_effect=[review('observed'),review('needs_changes')]),patch.object(run,'codex',return_value='Implemented'):
            run.execute()
        self.assertEqual(run.info['status'],'needs_attention')
        self.assertEqual(run.info['round'],1)

    def test_uncommitted_work_and_non_git_folders_are_built_in_place_and_not_counted_as_changes(self):
        (self.project/'untracked.txt').write_text('unsaved')
        (self.project/'data').mkdir();(self.project/'data'/'cache.bin').write_bytes(b'0'*(5*1024*1024+1))
        run=s.Run('Task',self.project)
        def codex(prompt):
            (self.project/'app.txt').write_text('edited');return 'Edited app.txt.'
        with patch.object(run,'claude',side_effect=[review('observed'),review('approved')]),patch.object(run,'codex',side_effect=codex):run.execute()
        self.assertEqual(run.info['status'],'done')
        self.assertEqual(run.info['files'],['app.txt'])
        self.assertEqual((self.project/'untracked.txt').read_text(),'unsaved')
        self.assertIn('/data/cache.bin',run.info['baseline_excluded'])
        # A folder that is not a Git repository works too, and a nested repository is left out of the baseline.
        plain=self.base/'plain';plain.mkdir();(plain/'notes.txt').write_text('one')
        nested=plain/'inner';nested.mkdir();subprocess.run(['git','init','-q',str(nested)],check=True);(nested/'x').write_text('x')
        (plain/'.DS_Store').write_text('finder noise')
        commit,skipped=s.create_baseline(plain,self.base/'baseline.git')
        self.assertEqual(skipped,['/inner/'])
        self.assertEqual(s.git(plain,'ls-files',shadow=self.base/'baseline.git').split(),['notes.txt'])
        (plain/'notes.txt').write_text('two')
        self.assertEqual(s.git(plain,'diff','--name-only','HEAD','--',shadow=self.base/'baseline.git').split(),['notes.txt'])

    def launch_script(self, source, agent='Codex'):
        script=self.base/'fake.py'
        script.write_text(source)
        run=s.Run('Task',self.project)
        run.info['workspace']=str(self.project)
        run.info['status']='building'
        return run,[os.sys.executable,str(script)]

    def test_provider_failure_after_text_is_fatal(self):
        events=[dict(type='item.completed',item=dict(type='agent_message',text='Starting')),dict(type='turn.failed',error=dict(message='Limit exceeded'))]
        run,args=self.launch_script('import json\n'+''.join('print('+repr(json.dumps(e))+',flush=True)\n' for e in events))
        with self.assertRaisesRegex(RuntimeError,'Limit exceeded'):
            run.launch('Codex',args,'Task')

    def test_claude_failure_even_with_structured_output(self):
        event=dict(type='result',is_error=True,result='Budget exceeded',structured_output=review())
        run,args=self.launch_script('print('+repr(json.dumps(event))+',flush=True)')
        with self.assertRaisesRegex(RuntimeError,'Budget exceeded'):
            run.launch('Claude',args,'Task')

    def test_stderr_warning_does_not_fail(self):
        run,args=self.launch_script('import sys\nprint("Warning",file=sys.stderr)\nprint('+repr(json.dumps(dict(type='item.completed',item=dict(type='agent_message',text='Done'))))+')')
        _,text=run.launch('Codex',args,'Task')
        self.assertEqual(text,'Done')

    def test_timeout_kills_child_after_leader_exits(self):
        marker=self.base/'terminated.txt'
        child=self.base/'child.py'
        child.write_text('import signal,time,sys\ndef stop(*args):\n open('+repr(str(marker))+',"w").write("stopped")\n sys.exit(0)\nsignal.signal(signal.SIGTERM,stop)\nwhile True:time.sleep(.05)\n')
        source='import subprocess,sys,time\np=subprocess.Popen([sys.executable,'+repr(str(child))+'])\ntime.sleep(.1)\n'
        run,args=self.launch_script(source)
        run.deadline=time.monotonic()+.6
        before=time.monotonic()
        with self.assertRaises(TimeoutError): run.launch('Codex',args,'Task')
        self.assertLess(time.monotonic()-before,5)
        for _ in range(20):
            if marker.exists():break
            time.sleep(.05)
        self.assertTrue(marker.exists(), 'Orphan child did not receive stop signal')

    def test_stop_running_process(self):
        run,args=self.launch_script('import time\ntime.sleep(60)')
        timer=threading.Timer(.2,run.stop_event.set);timer.start()
        with self.assertRaises(s.Stopped):run.launch('Codex',args,'Task')
        timer.join()
        self.assertIsNone(run.process)

    def test_review_validation_rejects_false_approval(self):
        malformed=review('needs_changes');malformed['status']='approved'
        with self.assertRaises(ValueError):s.validate_review(malformed)
        malformed=review('needs_changes');malformed['findings'][0]['evidence']=''
        with self.assertRaises(ValueError):s.validate_review(malformed)

    def test_pause_blocks_next_handoff(self):
        run=s.Run('Task',self.project)
        run.resume_event.clear()
        thread=threading.Thread(target=run.stage,args=('building',));thread.start()
        time.sleep(.1)
        self.assertEqual(run.info['status'],'queued')
        run.resume_event.set();thread.join(2)
        self.assertEqual(run.info['status'],'building')


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.old_data=s.DATA;s.DATA=self.root/'data'
        self.folder=self.root/'Project with spaces';self.folder.mkdir()
    def tearDown(self):
        s.DATA=self.old_data;self.temp.cleanup()
    def test_empty_defaults(self):
        self.assertEqual(s.project_choices(),{'projects':[]})
    def test_save_load_and_remove_preserves_folder(self):
        project=s.save_project(' My app ',str(self.folder))
        self.assertEqual(project['name'],'My app')
        self.assertEqual(s.project_choices()['projects'][0]['path'],str(self.folder.resolve()))
        self.assertTrue(s.project_choices()['projects'][0]['exists'])
        s.remove_project(project['id'])
        self.assertEqual(s.project_choices()['projects'],[])
        self.assertTrue(self.folder.is_dir())
    def test_duplicates_and_missing_folders(self):
        s.save_project('My app',str(self.folder))
        for name,path in [('my APP',str(self.root)),('Different name',str(self.folder)),('',str(self.root)),('Missing',str(self.root/'missing'))]:
            with self.assertRaises(ValueError):s.save_project(name,path)
    def test_browse_lists_only_visible_folders(self):
        (self.folder/'child').mkdir();(self.folder/'.hidden').mkdir();(self.folder/'file.txt').write_text('hello')
        result=s.folder_choices(str(self.folder))
        self.assertEqual([p['name'] for p in result['folders']],['child'])
        self.assertEqual(result['parent'],str(self.root.resolve()))
        self.assertEqual(s.folder_choices(str(self.folder/'.hidden'))['folders'],[])
    def test_one_instance_per_data_folder(self):
        handle=s.acquire_instance_lock()
        script=("import importlib.util;from pathlib import Path;"
                "spec=importlib.util.spec_from_file_location('relay',"+repr(str((s.ROOT / 'server.py')))+");"
                "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
                "m.application.DATA=Path("+repr(str(s.DATA))+");m.application.acquire_instance_lock()")
        try:
            result=subprocess.run([os.sys.executable,'-c',script],capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Relay is already running',result.stderr)
        finally:
            handle.close()
        replacement=s.acquire_instance_lock();replacement.close()

    def test_missing_saved_folder_remains_visible(self):
        s.save_project('My app',str(self.folder));self.folder.rmdir()
        self.assertFalse(s.project_choices()['projects'][0]['exists'])


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_data=s.DATA;s.DATA=Path(self.temp.name)/'data'
    def tearDown(self):s.DATA=self.old_data;self.temp.cleanup()
    def test_presets_save_update_and_snapshot(self):
        team=s.validate_team(s.DEFAULT_TEAM);team['name']='My team'
        entry=s.save_team_preset(team)
        run=s.Run('Task',Path(self.temp.name),team=team)
        team['roles']['builder']['provider']='claude'
        s.save_team_preset(team,entry['id'])
        self.assertEqual(len(s.team_presets()['presets']),1)
        self.assertEqual(s.team_presets()['presets'][0]['team']['roles']['builder']['provider'],'claude')
        self.assertEqual(run.info['team']['roles']['builder']['provider'],'codex')
        self.assertEqual(json.loads((run.folder/'state.json').read_text())['team']['roles']['builder']['provider'],'codex')
    def test_invalid_and_duplicate_presets(self):
        team=s.validate_team(s.DEFAULT_TEAM);team['name']='My team';s.save_team_preset(team)
        with self.assertRaises(ValueError):s.save_team_preset(team)
        for change in ['provider','model','instructions']:
            bad=s.validate_team(s.DEFAULT_TEAM)
            bad['roles']['builder'][change]={'provider':'unknown','model':' -bad','instructions':'x'*4001}[change]
            with self.assertRaises(ValueError):s.validate_team(bad)
        with self.assertRaises(ValueError):s.validate_team({'name':'Incomplete','roles':{}})
    def test_effort_forwarding_and_defaults(self):
        for provider in s.PROVIDERS:
            args=s.provider_command(provider,'builder',{'model':'sonnet' if provider=='claude' else 'gpt-6-luna','effort':'medium'},'/workspace','/output','/schema')
            if provider=='claude':
                self.assertEqual(args[args.index('--effort')+1],'medium')
            else:
                self.assertIn('model_reasoning_effort="medium"',args)
                self.assertNotIn('--effort',args)
            default=s.provider_command(provider,'builder',{'model':'','effort':''},'/workspace','/output','/schema')
            self.assertNotIn('--effort',default)
            self.assertNotIn('--model',default)
            self.assertFalse(any('model_reasoning_effort' in x for x in default if x))
    def test_legacy_presets_get_default_effort(self):
        team=s.validate_team(s.DEFAULT_TEAM)
        for profile in team['roles'].values():profile.pop('effort')
        s.DATA.mkdir();(s.DATA/'teams.json').write_text(json.dumps([{'id':'old','team':team}]))
        loaded=s.team_presets()['presets'][0]['team']
        self.assertTrue(all(p['effort']=='' for p in loaded['roles'].values()))
        run=s.Run('Task',Path(self.temp.name),team=loaded)
        loaded['roles']['builder']['effort']='high'
        self.assertEqual(run.info['team']['roles']['builder']['effort'],'')
    def test_effort_validation(self):
        for provider,model,effort in [('claude','sonnet','ultra'),('codex','gpt-6-luna','ultra'),('codex','','ultra'),('claude','opus','invalid')]:
            team=s.validate_team(s.DEFAULT_TEAM)
            team['roles']['builder'].update(provider=provider,model=model,effort=effort)
            with self.assertRaises(ValueError):s.validate_team(team)
        team=s.validate_team(s.DEFAULT_TEAM);team['roles']['builder'].update(model='gpt-6.1-sol',effort='high')
        self.assertEqual(s.validate_team(team)['roles']['builder']['effort'],'high')
    def test_catalog_hides_internal_models_and_uses_supported_efforts(self):
        cache=Path(self.temp.name)/'codex';cache.mkdir()
        (cache/'models_cache.json').write_text(json.dumps({'models':[
            {'slug':'public-model','display_name':'Public','visibility':'list','supported_reasoning_levels':[{'effort':'low'},{'effort':'high'}]},
            {'slug':'internal-model','visibility':'hide'}]}))
        with patch.dict(os.environ,{'CODEX_HOME':str(cache)}):
            catalog=s.model_catalog()
        self.assertEqual([m['id'] for m in catalog['claude']['models']],['haiku','sonnet','opus','fable'])
        self.assertEqual(catalog['codex']['models'],[{'id':'public-model','label':'Public','efforts':['low','high']}])

    def test_capabilities_follow_role_and_models_are_arguments(self):
        for provider in s.PROVIDERS:
            for role in s.ROLES:
                with self.subTest(provider=provider,role=role):
                    args=s.provider_command(provider,role,{'model':'custom-model'},'/workspace','/output','/schema')
                    self.assertEqual(args[args.index('--model')+1],'custom-model')
                    self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',args)
                    self.assertNotIn('--dangerously-skip-permissions',args)
                    if provider=='codex':
                        self.assertEqual(args[args.index('--sandbox')+1],'workspace-write' if role=='builder' else 'read-only')
                        self.assertEqual('--output-schema' in args,role!='builder')
                    else:
                        tools=args[args.index('--tools')+1].split(',')
                        self.assertEqual('Bash' in tools,role=='builder')
                        self.assertEqual('Write' in tools,role=='builder')
                        self.assertEqual('--json-schema' in args,role!='builder')


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.old_data=s.DATA;s.DATA=self.root/'data'
        self.registry=patch.dict(s.RUNS,{},clear=True);self.registry.start()
        self.id='a'*12;self.folder=s.DATA/'runs'/self.id;self.folder.mkdir(parents=True)
        self.workspace=s.DATA/'workspaces'/self.id;self.workspace.mkdir(parents=True)
        (self.workspace/'code.txt').write_text('preserve changes')
        self.info=dict(id=self.id,status='done',events=[],workspace=str(self.workspace))
        (self.folder/'state.json').write_text(json.dumps(self.info))
        (self.folder/'events.jsonl').write_text('private messages')
        s.RUNS[self.id]=self.info
    def tearDown(self):
        self.registry.stop();s.DATA=self.old_data;self.temp.cleanup()
    def test_delete_restore_preserves_code_and_logs(self):
        s.delete_history(self.id)
        self.assertNotIn(self.id,s.RUNS)
        self.assertFalse(self.folder.exists())
        self.assertEqual((s.DATA/'trash'/self.id/'events.jsonl').read_text(),'private messages')
        self.assertEqual((self.workspace/'code.txt').read_text(),'preserve changes')
        s.restore_history(self.id)
        self.assertIn(self.id,s.RUNS);self.assertTrue(self.folder.exists())
    def test_deleted_chat_stays_hidden_after_restart(self):
        s.delete_history(self.id);s.load_runs()
        self.assertNotIn(self.id,s.RUNS)
    def test_running_chat_cannot_be_deleted(self):
        self.info['status']='reviewing'
        with self.assertRaisesRegex(ValueError,'Stop'):s.delete_history(self.id)
        self.assertTrue(self.folder.exists())
    def test_worker_finishing_cannot_be_deleted(self):
        run=s.Run('Task',self.root);run.info['status']='done';s.RUNS[run.id]=run
        with self.assertRaisesRegex(ValueError,'finishing'):s.delete_history(run.id)
        run.finished.set();s.delete_history(run.id)
        self.assertNotIn(run.id,s.RUNS)
    def test_invalid_ids_and_restore_collision(self):
        with self.assertRaises(ValueError):s.delete_history('../runs')
        with self.assertRaises(ValueError):s.restore_history(self.id)
        self.assertTrue(self.folder.exists())


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old_data=s.DATA
        s.DATA=Path(self.temp.name)/'data'
        self.server=ThreadingHTTPServer(('127.0.0.1',0),s.Handler)
        self.port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        s.DATA=self.old_data
        self.temp.cleanup()
    def test_recovery_endpoint_checks_token_checkpoint_and_preserves_completed_steps(self):
        project=Path(self.temp.name)/'recovery-project';project.mkdir()
        subprocess.run(['git','init','-q',str(project)],check=True)
        s.git(project,'config','user.email','test@example.invalid');s.git(project,'config','user.name','Test')
        (project/'app.txt').write_text('initial');s.git(project,'add','.');s.git(project,'commit','-qm','Initial')
        calls=[];failed=[False]
        def claude(run,prompt):
            calls.append(run.current_role)
            if run.current_role=='observer':return review('observed')
            if not failed[0]:failed[0]=True;raise RuntimeError('Reviewer unavailable')
            return review('approved')
        def codex(run,prompt):calls.append('builder');return 'Saved Builder report'
        def approve(run,observation):
            run.info['plan']=dict(id='approved-fixture',**observation)
            run.info['approved_plan_id']='approved-fixture';run.info['plan_approved_at']=s.now()
        def post(body,token=s.TOKEN):
            req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/recover',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Relay-Token':token})
            return urllib.request.urlopen(req)
        with patch.dict(s.RUNS,{},clear=True),patch.object(s,'ACTIVE',None),patch.object(s,'tool_status',return_value={name:dict(installed=True,signed_in=True) for name in s.PROVIDERS}),patch.object(s.Run,'claude',claude),patch.object(s.Run,'codex',codex),patch.object(s.Run,'wait_for_plan',approve):
            run=s.Run('Task',project);run.execute();s.RUNS[run.id]=run
            body=dict(id=run.id,checkpoint_id=run.info['workflow']['id'])
            with self.assertRaises(urllib.error.HTTPError) as error:post(body,token='wrong')
            self.assertEqual(error.exception.code,403)
            with self.assertRaises(urllib.error.HTTPError) as error:post({**body,'checkpoint_id':'stale'})
            self.assertEqual(error.exception.code,400)
            run.finished.clear()
            with self.assertRaises(urllib.error.HTTPError):post(body)
            run.finished.set()
            with post(body) as response:self.assertEqual(response.status,201)
            recovered=s.RUNS[run.id];self.assertTrue(recovered.finished.wait(7))
            self.assertEqual(recovered.info['status'],'done')
            self.assertEqual(calls,['observer','builder','reviewer','reviewer'])
            with self.assertRaises(urllib.error.HTTPError):post(body)

    def test_clarification_answers_require_current_batch_and_never_approve(self):
        run=s.Run('Clarify',self.temp.name)
        run.info.update(status='awaiting_clarification',clarification=dict(id='batch1',questions=[dict(id='Q1',question='Which method?',options=[])],answers=None))
        s.RUNS[run.id]=run
        def post(body,token=s.TOKEN):
            req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/answer-clarification',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Relay-Token':token})
            return urllib.request.urlopen(req)
        with patch.object(s,'ACTIVE',run):
            body=dict(id=run.id,clarification_id='batch1',answers={'Q1':'Email link'})
            with self.assertRaises(urllib.error.HTTPError) as error:post(body,token='wrong')
            self.assertEqual(error.exception.code,403)
            for changes in [dict(clarification_id='old'),dict(answers={}),dict(answers={'Q1':' '})]:
                with self.assertRaises(urllib.error.HTTPError) as error:post({**body,**changes})
                self.assertEqual(error.exception.code,400)
            with post(body) as response:self.assertEqual(response.status,200)
            self.assertEqual(run.info['status'],'observing')
            self.assertTrue(run.clarification_event.is_set())
            self.assertFalse(run.approval_event.is_set())
            self.assertNotIn('approved_plan_id',run.info)
            with self.assertRaises(urllib.error.HTTPError):post(body)
        self.assertEqual(len(run.info['clarifications']),1)

    def test_frontend_module_graph_loads_with_static_allowlist(self):
        import re
        from urllib.parse import urljoin, urlparse
        base=f'http://127.0.0.1:{self.port}'
        with urllib.request.urlopen(base+'/') as response:
            html=response.read().decode()
        self.assertIn('<script type="module" src="/app.js">',html)
        seen=set();pending=['/app.js']
        while pending:
            path=pending.pop()
            if path in seen:continue
            seen.add(path)
            with urllib.request.urlopen(base+path) as response:
                self.assertIn('javascript',response.headers['Content-Type'])
                source=response.read().decode()
            for match in re.finditer(r"(?:from|import)\s+['\"]([^'\"]+)['\"]",source):
                pending.append(urlparse(urljoin(base+path,match.group(1))).path)
        self.assertIn('/js/notifications.js',seen)
        self.assertIn('/js/history.js',seen)
        self.assertIn('/markdown.js',seen)
        with urllib.request.urlopen(base+'/notifications.css') as response:self.assertEqual(response.status,200)
        for path in ['/js/server.py','/js/state.json','/js/../server.py']:
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+path)
            self.assertEqual(error.exception.code,404)

    def test_export_rejects_active_legacy_and_symlink_records(self):
        run=s.Run('Export fixture',self.temp.name)
        s.RUNS[run.id]=run
        url=f'http://127.0.0.1:{self.port}/api/export?run={run.id}'
        def status(expected):
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(url)
            self.assertEqual(error.exception.code,expected)
        run.info['export_complete']=True
        (run.folder/'changes.patch').write_bytes(b'complete patch')
        status(409)
        run.info['status']='done';run.finished.set()
        run.info['export_complete']=False
        status(409)
        run.info['export_complete']=True
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.read(),b'complete patch')
            self.assertIn('attachment',response.headers['Content-Disposition'])
        # A read-only follow-up keeps the earlier build's export available.
        run.info['mode']='observe';run.info['turns']=[dict(mode='build',export_complete=True)]
        with urllib.request.urlopen(url) as response:self.assertEqual(response.read(),b'complete patch')
        (run.folder/'changes.patch').unlink()
        outside=Path(self.temp.name)/'private';outside.write_text('not an export')
        (run.folder/'changes.patch').symlink_to(outside)
        status(404)

    def test_report_actions_http(self):
        root=s.Run('Original observation',self.temp.name,mode='observe',attachments=s.decode_images([image_payload()]))
        root.info.update(status='done',summary='Original evidence',findings=review('needs_changes')['findings'])
        root.finished.set();root.save()
        prompts=[]
        def observer(run,prompt):
            prompts.append(prompt)
            return 'A plain chat reply' if run.info.get('chat') else review('observed')
        def post(path,body):
            req=urllib.request.Request(f'http://127.0.0.1:{self.port}'+path,data=json.dumps(body).encode(),headers={'X-Relay-Token':s.TOKEN,'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as response: return json.load(response)
        def wait(run_id):
            run=s.RUNS[run_id]
            self.assertTrue(run.finished.wait(5))
            self.assertEqual(run.info['status'],'done')
            return run
        with patch.dict(s.RUNS,{root.id:root},clear=True),patch.object(s,'ACTIVE',None),patch.object(s,'tool_status',return_value={n:dict(installed=True,signed_in=True) for n in s.PROVIDERS}),patch.object(s.Run,'claude',observer),patch.object(s.Run,'codex',observer):
            result=post('/api/followup',dict(source_id=root.id,task='Explain the risk',images=[image_payload('another.png')]))
            self.assertEqual(result['id'],root.id)
            follow=wait(root.id)
            self.assertEqual(follow.info['mode'],'observe')
            self.assertEqual(len(follow.info['attachments']),2)
            self.assertEqual(len(follow.info['turns']),1)
            self.assertIn('Original evidence',prompts[-1])
            self.assertTrue(follow.info['chat'])
            self.assertEqual(follow.info['summary'],'A plain chat reply')
            self.assertEqual(follow.info['workflow']['step'],'complete')
            result=post('/api/run',dict(source_id=root.id,finding_indexes=[0],task='Plan the fix',project=self.temp.name,mode='plan'))
            child=wait(result['id'])
            self.assertNotEqual(child.id,root.id)
            self.assertEqual(len(child.info['attachments']),2)
            self.assertIn('Missing trim',prompts[-1])
            self.assertEqual(child.info['source']['id'],root.id)
            self.assertEqual(child.info['source']['finding_indexes'],[0])
            with self.assertRaises(urllib.error.HTTPError) as error:
                post('/api/run',dict(source_id=root.id,finding_indexes=[99],task='Fix',project=self.temp.name,mode='plan'))
            self.assertEqual(error.exception.code,400)

    def test_follow_ups_can_plan_or_build_in_the_same_conversation(self):
        root=s.Run('Plan the change',self.temp.name,mode='plan')
        # A plan, then a chat message in which the user agreed a change to it.
        root.info.update(status='done',mode='observe',chat=True,task='Name the file notes.txt instead',summary='Agreed: notes.txt',
                         turns=[dict(mode='plan',status='done',task='Plan the change',summary='1. Add built.txt',findings=[],acceptance_checks=['built.txt exists'])])
        root.finished.set();root.save()
        def post(body):
            req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/followup',data=json.dumps(body).encode(),headers={'X-Relay-Token':s.TOKEN,'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as response:return json.load(response)
        def codex(run,prompt):
            self.assertIn('1. Add built.txt',prompt);self.assertIn('Name the file notes.txt instead',prompt)
            self.assertIn('take precedence over the plan',prompt)
            (Path(run.info['workspace'])/'built.txt').write_text('built');return 'Added built.txt.'
        def claude(run,prompt):return review('approved')
        ready={n:dict(installed=True,signed_in=True) for n in s.PROVIDERS}
        with patch.dict(s.RUNS,{root.id:root},clear=True),patch.object(s,'ACTIVE',None),patch.object(s,'tool_status',return_value=ready),patch.object(s.Run,'codex',codex),patch.object(s.Run,'claude',claude):
            with self.assertRaises(urllib.error.HTTPError) as error:post(dict(source_id=root.id,task='Do it',mode='delete'))
            self.assertEqual(error.exception.code,400)
            result=post(dict(source_id=root.id,task='Build the plan',build_plan=True,rounds=0,minutes=0))
            self.assertEqual(result['id'],root.id)
            build=s.RUNS[root.id];self.assertTrue(build.finished.wait(8))
            self.assertEqual(build.info['status'],'done',build.info['summary'])
            self.assertEqual(build.info['mode'],'build');self.assertFalse(build.info['chat'])
            self.assertEqual(build.info['files'],['built.txt'])
            self.assertEqual([turn['mode'] for turn in build.info['turns']],['plan','observe'])
            self.assertEqual((Path(self.temp.name)/'built.txt').read_text(),'built')
            # A second build in the same chat keeps the first build's patch.
            (Path(self.temp.name)/'built.txt').unlink()
            post(dict(source_id=root.id,task='Build the plan',build_plan=True,rounds=0,minutes=0))
            again=s.RUNS[root.id];self.assertTrue(again.finished.wait(8))
            self.assertEqual([turn['mode'] for turn in again.info['turns']],['plan','observe','build'])
            self.assertTrue(list(again.folder.glob('changes-before-turn-*.patch')))

    def test_build_plan_endpoint_requires_a_finished_plan(self):
        root=s.Run('Look around',self.temp.name,mode='observe')
        root.info.update(status='done',summary='Findings only',findings=[],acceptance_checks=[])
        root.finished.set();root.save()
        def post(body):
            req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/run',data=json.dumps(body).encode(),headers={'X-Relay-Token':s.TOKEN,'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as response:return json.load(response)
        body=dict(source_id=root.id,build_plan=True,mode='build',project=self.temp.name,task='Build the plan: Plan it',rounds=3,minutes=20)
        with patch.dict(s.RUNS,{root.id:root},clear=True),patch.object(s,'ACTIVE',None):
            with self.assertRaises(urllib.error.HTTPError) as error:post(body)
            self.assertEqual(error.exception.code,400)
            self.assertIn('no finished plan',json.load(error.exception)['error'])

    def test_plan_approval_endpoint_rejects_stale_and_duplicate_actions(self):
        run=s.Run('Implement',self.temp.name)
        run.info.update(status='awaiting_approval',plan=dict(id='current-plan',summary='Plan',findings=[],acceptance_checks=['Check']))
        def post(path,body):
            req=urllib.request.Request(f'http://127.0.0.1:{self.port}'+path,data=json.dumps(body).encode(),headers={'X-Relay-Token':s.TOKEN,'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as response:return json.load(response)
        with patch.dict(s.RUNS,{run.id:run},clear=True):
            post('/api/resume',dict(id=run.id))
            self.assertFalse(run.approval_event.is_set())
            with self.assertRaises(urllib.error.HTTPError) as error:post('/api/approve-plan',dict(id=run.id,plan_id='old-plan'))
            self.assertEqual(error.exception.code,400)
            self.assertFalse(run.approval_event.is_set())
            post('/api/approve-plan',dict(id=run.id,plan_id='current-plan'))
            self.assertTrue(run.approval_event.is_set())
            self.assertEqual(json.loads((run.folder/'state.json').read_text())['approved_plan_id'],'current-plan')
            with self.assertRaises(urllib.error.HTTPError):post('/api/approve-plan',dict(id=run.id,plan_id='current-plan'))

    def test_image_route_and_attachment_history_lifecycle(self):
        run=s.Run('Inspect screenshot',self.temp.name,mode='observe',attachments=s.decode_images([image_payload()]))
        run.info.update(status='done',summary='Image reviewed');run.finished.set();run.save()
        image_id=run.info['attachments'][0]['id']
        url=f'http://127.0.0.1:{self.port}/api/image?run={run.id}&image={image_id}'
        with patch.dict(s.RUNS,{run.id:run},clear=True):
            with urllib.request.urlopen(url) as response:
                self.assertEqual(response.headers['Content-Type'],'image/png')
                self.assertEqual(response.read(),PNG_BYTES)
            s.delete_history(run.id)
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(url)
            self.assertEqual(error.exception.code,404)
            s.restore_history(run.id)
            with urllib.request.urlopen(url) as response:self.assertEqual(response.read(),PNG_BYTES)
            bad=f'http://127.0.0.1:{self.port}/api/image?run={run.id}&image=../private'
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(bad)
            self.assertEqual(error.exception.code,404)

    def test_image_upload_request_is_saved_before_execution(self):
        def execute(run):
            run.info.update(status='done',summary='Uploaded image received');run.save();run.finished.set()
        def post(body):
            req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/run',data=json.dumps(body).encode(),headers={'X-Relay-Token':s.TOKEN,'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as response:return json.load(response)
        with patch.dict(s.RUNS,{},clear=True),patch.object(s,'ACTIVE',None),patch.object(s.Run,'execute',execute):
            response=post(dict(task='Inspect image',project=self.temp.name,mode='observe',images=[image_payload()]))
            run=s.RUNS[response['id']];self.assertTrue(run.finished.wait(2))
            self.assertEqual(len(run.info['attachments']),1)
            self.assertEqual(s.saved_image_path(run.info,run.info['attachments'][0]['id']).read_bytes(),PNG_BYTES)
            count=len(s.RUNS)
            with self.assertRaises(urllib.error.HTTPError) as error:
                post(dict(task='Bad image',project=self.temp.name,mode='observe',images=[dict(name='x.png',data='invalid')]))
            self.assertEqual(error.exception.code,400)
            self.assertEqual(len(s.RUNS),count)

    def test_state_and_host_protection(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/state') as response:
            self.assertEqual(json.load(response)['token'],s.TOKEN)
        req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/state',headers={'Host':'evil.example'})
        with self.assertRaises(urllib.error.HTTPError) as result:urllib.request.urlopen(req)
        self.assertEqual(result.exception.code,403)
    def test_project_choices_and_tab_icon(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/projects') as response:
            data=json.load(response)
            self.assertEqual(data['projects'],[])
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/relay.svg?v=1') as response:
            self.assertEqual(response.headers['Content-Type'],'image/svg+xml')
            self.assertIn(b'<svg',response.read())

    def test_model_catalog_endpoint(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/models') as response:
            data=json.load(response)
        self.assertEqual([m['id'] for m in data['claude']['models']],['haiku','sonnet','opus','fable'])
        self.assertTrue(data['codex']['models'])
        self.assertTrue(all(m['efforts'] for m in data['codex']['models']))

    def test_invalid_json_shapes_and_limits_return_400(self):
        for body in [[],None,'text',dict(task='Task',project=self.temp.name,rounds=True),
                     dict(task='Task',project=self.temp.name,minutes=1.5),
                     dict(task='Task',project=self.temp.name,rounds='3')]:
            req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/run',data=json.dumps(body).encode(),
                                       headers={'X-Relay-Token':s.TOKEN,'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as result:urllib.request.urlopen(req)
            self.assertEqual(result.exception.code,400)

    def test_mutations_require_token_and_same_origin(self):
        for headers in [{},{'X-Relay-Token':s.TOKEN,'Origin':'https://evil.example'}]:
            req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/run',data=b'{"demo":true}',headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as result:urllib.request.urlopen(req)
            self.assertEqual(result.exception.code,403)


if __name__=='__main__':unittest.main()
