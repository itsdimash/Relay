"""Recovery preserves approved work and never infers permission to edit."""
import json
from pathlib import Path
import shutil
import threading
import time
import unittest
from unittest.mock import patch
import test_relay as fixtures

s=fixtures.s


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        fixtures.WorkflowTests.setUp(self)
        self.registry=patch.object(s,'RUNS',{});self.registry.start()
        self.active=patch.object(s,'ACTIVE',None);self.active.start()
        self.calls=[];self.fail_review=True;self.fail_builder=False;self.fail_observer=False
        self.stop_after_review=False;self.revisions=False;self.ask=False;self.revise_first=False
        self.tasks=[];self.workers=[]
        def claude(run,prompt):
            self.calls.append((run.current_role,prompt))
            count=sum(role==run.current_role for role,_ in self.calls)
            if run.current_role=='observer':
                if self.fail_observer:
                    self.fail_observer=False;raise RuntimeError('Observer connection lost')
                report=fixtures.review('observed')
                if self.ask and count==1:report['questions']=[dict(id='Q1',question='Which pages?',options=[])]
                return report
            if self.fail_review:
                self.fail_review=False;raise RuntimeError('Reviewer connection lost')
            if self.stop_after_review and count==1:run.stop_event.set()
            return fixtures.review('needs_changes' if (self.revisions and count==2) or (self.revise_first and count==1) else 'approved')
        def codex(run,prompt):
            self.calls.append(('builder',prompt))
            workspace=Path(run.info['workspace'])
            if self.fail_builder:
                self.fail_builder=False;(workspace/'partial.txt').write_text('keep me')
                raise RuntimeError('Builder connection lost')
            (workspace/'new.txt').write_text('completed work\n')
            (workspace/'app.txt').write_text('built round '+str(run.info['round'])+'\n')
            return 'Saved implementation\n```relay-checks\n[]\n```'
        self.provider_a=patch.object(s.Run,'claude',claude);self.provider_a.start()
        self.provider_b=patch.object(s.Run,'codex',codex);self.provider_b.start()

    def tearDown(self):
        for run in self.tasks+[s.ACTIVE]:
            if isinstance(run,s.Run):run.stop_event.set();run.resume_event.set()
        for worker in self.workers:worker.join(5)
        if s.ACTIVE:s.ACTIVE.finished.wait(5)
        self.provider_a.stop();self.provider_b.stop();self.active.stop();self.registry.stop()
        fixtures.WorkflowTests.tearDown(self)

    def wait_for(self,predicate):
        end=time.monotonic()+5
        while time.monotonic()<end:
            if predicate():return
            time.sleep(.01)
        self.fail('Expected recovery state not reached')

    def new_task(self,mode='build',threaded=False):
        run=s.Run('Implement the approved task',self.project,rounds=3,minutes=1,mode=mode)
        self.tasks.append(run);s.RUNS[run.id]=run;s.ACTIVE=run
        if threaded:
            worker=threading.Thread(target=run.execute);self.workers.append(worker);worker.start()
        else:run.execute()
        return run

    def recover(self,run,wait=True):
        ident=s.recover_run(run.id,run.info['workflow']['id'])['id'];recovered=s.RUNS[ident]
        self.tasks.append(recovered)
        if wait:self.assertTrue(recovered.finished.wait(7))
        return recovered

    def counts(self):return {role:sum(r==role for r,_ in self.calls) for role in ['observer','builder','reviewer']}

    def test_retry_review_does_not_repeat_observation_or_build(self):
        run=self.new_task();self.assertEqual(run.info['status'],'failed')
        self.assertEqual(run.info['workflow']['step'],'review')
        old_workspace=run.info['workspace'];old_report=run.info['builder_reports'][0]
        recovered=self.recover(run)
        self.assertEqual(recovered.info['status'],'done');self.assertEqual(self.counts(),dict(observer=1,builder=1,reviewer=2))
        self.assertEqual(recovered.id,run.id);self.assertEqual(recovered.info['workspace'],old_workspace)
        self.assertEqual(recovered.info['builder_reports'],[old_report])
        self.assertEqual(recovered.info['recovery_attempts'][0]['previous_summary'],'Reviewer connection lost')
        self.assertEqual(recovered.info['recovery_attempts'][0]['status'],'done')
        self.assertIn('new.txt',(recovered.folder/'changes.patch').read_text())
        self.assertTrue((self.project/'new.txt').exists())

    def test_a_recovery_attempt_can_choose_its_own_time_limit(self):
        run=self.new_task();self.assertEqual(run.info['minutes'],1)
        ident=run.info['workflow']['id']
        for bad in (-1,500,'10',True):
            with self.assertRaises(ValueError):s.recover_run(run.id,ident,bad)
        self.assertIs(s.RUNS[run.id],run)
        recovered=s.RUNS[s.recover_run(run.id,ident,0)['id']];self.tasks.append(recovered)
        self.assertTrue(recovered.finished.wait(7))
        self.assertEqual(recovered.info['minutes'],0)
        self.assertIsNone(recovered.deadline)

    def test_review_limit_offers_more_rounds_and_continues_from_the_saved_findings(self):
        self.fail_review=False;self.revise_first=True
        run=s.Run('Implement the approved task',self.project,rounds=1,minutes=0)
        self.tasks.append(run);s.RUNS[run.id]=run;s.ACTIVE=run;run.execute()
        self.assertEqual(run.info['status'],'needs_attention')
        self.assertEqual(run.info['workflow']['step'],'limit')
        option=s.recovery_option(run.info)
        self.assertTrue(option['available']);self.assertEqual(option['label'],'Fix the remaining findings')
        ident=run.info['workflow']['id'];builders=self.counts()['builder']
        for bad in (None,-1,6,'2'):
            with self.assertRaises(ValueError):s.recover_run(run.id,ident,None,bad)
        recovered=s.RUNS[s.recover_run(run.id,ident,None,2)['id']];self.tasks.append(recovered)
        self.assertTrue(recovered.finished.wait(7))
        self.assertEqual(recovered.info['max_rounds'],3)
        self.assertEqual(recovered.info['round'],2)
        self.assertEqual(self.counts()['builder'],builders+1)
        self.assertEqual(recovered.info['recovery_attempts'][0]['from_step'],'limit')
        self.assertIn('Trim first',next(p for role,p in reversed(self.calls) if role=='builder'))
        self.assertIn(recovered.info['status'],('done','needs_attention'))

    def test_retry_review_can_request_a_new_fix_round(self):
        self.revisions=True
        recovered=self.recover(self.new_task())
        self.assertEqual(recovered.info['status'],'done')
        self.assertEqual(self.counts(),dict(observer=1,builder=2,reviewer=3))
        self.assertEqual([report['round'] for report in recovered.info['builder_reports']],[1,2])

    def test_failed_builder_keeps_partial_work_and_continues_same_round(self):
        self.fail_review=False;self.fail_builder=True
        run=self.new_task();self.assertEqual(run.info['workflow']['step'],'build')
        recovered=self.recover(run)
        self.assertEqual(recovered.info['status'],'done')
        self.assertEqual((Path(run.info['workspace'])/'partial.txt').read_text(),'keep me')
        self.assertEqual([r['round'] for r in recovered.info['builder_reports']],[1])
        self.assertIn('Do not start over',next(p for role,p in reversed(self.calls) if role=='builder'))
        self.assertEqual(self.counts()['observer'],1)

    def test_restart_rehydrates_review_checkpoint_without_rebuilding(self):
        run=self.new_task();saved=json.loads((run.folder/'state.json').read_text())
        saved['status']='reviewing';(run.folder/'state.json').write_text(json.dumps(saved))
        s.RUNS.clear();s.ACTIVE=None;s.load_runs()
        loaded=s.RUNS[run.id];self.assertEqual(loaded['status'],'interrupted')
        self.assertEqual(loaded['interrupted_stage'],'reviewing')
        s.recover_run(run.id,loaded['workflow']['id']);recovered=s.RUNS[run.id];self.tasks.append(recovered)
        self.assertTrue(recovered.finished.wait(7));self.assertEqual(recovered.info['status'],'done')
        self.assertEqual(self.counts(),dict(observer=1,builder=1,reviewer=2))

    def test_unapproved_plan_still_waits_after_recovery(self):
        self.approval_patch.stop();self.fail_review=False
        run=self.new_task(threaded=True);self.wait_for(lambda:run.info['status']=='awaiting_approval')
        old_plan=run.info['plan']['id'];run.stop_event.set();self.assertTrue(run.finished.wait(5))
        recovered=self.recover(run,wait=False);self.wait_for(lambda:recovered.info['status']=='awaiting_approval')
        self.assertFalse(recovered.approval_event.is_set());self.assertNotIn('approved_plan_id',recovered.info)
        self.assertEqual(self.counts()['builder'],0);self.assertEqual(self.counts()['observer'],1)
        with self.assertRaises(ValueError):recovered.approve_plan(old_plan)
        recovered.approve_plan(recovered.info['plan']['id'])
        self.assertTrue(recovered.finished.wait(7));self.assertEqual(recovered.info['status'],'done')

    def test_questions_and_answers_survive_recovery(self):
        self.approval_patch.stop();self.ask=True;self.fail_review=False
        run=self.new_task(threaded=True);self.wait_for(lambda:run.info['status']=='awaiting_clarification')
        ident=run.info['clarification']['id'];run.stop_event.set();self.assertTrue(run.finished.wait(5))
        recovered=self.recover(run,wait=False);self.wait_for(lambda:recovered.info['status']=='awaiting_clarification')
        self.assertEqual(recovered.info['clarification']['id'],ident)
        recovered.answer_clarification(ident,{'Q1':'Settings only'})
        self.wait_for(lambda:recovered.info['status']=='awaiting_approval')
        self.assertEqual(self.counts()['observer'],2);self.assertEqual(self.counts()['builder'],0)
        self.assertEqual(recovered.info['clarifications'][0]['answers'],{'Q1':'Settings only'})
        recovered.approve_plan(recovered.info['plan']['id']);self.assertTrue(recovered.finished.wait(7))
        self.assertEqual(recovered.info['status'],'done')

    def test_completed_review_is_not_repeated_when_files_are_unchanged(self):
        self.fail_review=False;self.stop_after_review=True
        run=self.new_task();self.assertEqual(run.info['status'],'stopped')
        self.assertEqual(run.info['workflow']['step'],'decide')
        recovered=self.recover(run);self.assertEqual(recovered.info['status'],'done')
        self.assertEqual(self.counts(),dict(observer=1,builder=1,reviewer=1))

    def test_external_edit_invalidates_saved_review_but_keeps_build(self):
        self.fail_review=False;self.stop_after_review=True
        run=self.new_task();(Path(run.info['workspace'])/'manual.txt').write_text('manual change')
        recovered=self.recover(run);self.assertEqual(recovered.info['status'],'done')
        self.assertEqual(self.counts(),dict(observer=1,builder=1,reviewer=2))
        self.assertIn('manual.txt',recovered.info['files'])

    def test_snapshot_error_retries_review_without_repeating_build(self):
        real=s.Run.snapshot;fail=[True]
        def snapshot(run):
            if run.info['status']=='reviewing' and fail[0]:fail[0]=False;raise ValueError('Disk temporarily unavailable')
            return real(run)
        self.fail_review=False
        with patch.object(s.Run,'snapshot',snapshot):run=self.new_task()
        self.assertEqual(run.info['workflow']['step'],'review')
        recovered=self.recover(run);self.assertEqual(recovered.info['status'],'done')
        self.assertEqual(self.counts(),dict(observer=1,builder=1,reviewer=1))

    def test_missing_folder_or_baseline_is_rejected_without_replacing_task(self):
        run=self.new_task();workspace=Path(run.info['workspace']);ident=run.info['workflow']['id']
        moved=workspace.with_name(workspace.name+'-moved');workspace.rename(moved)
        with self.assertRaisesRegex(ValueError,'missing'):s.recover_run(run.id,ident)
        self.assertIs(s.RUNS[run.id],run);moved.rename(workspace)
        # Committing your own work in the folder does not affect recovery; losing the baseline does.
        s.git(workspace,'add','.');s.git(workspace,'commit','-qm','User committed preserved work')
        baseline=Path(run.info['workflow']['baseline']);backup=baseline.with_name('backup.git');baseline.rename(backup)
        with self.assertRaisesRegex(ValueError,'baseline'):s.recover_run(run.id,ident)
        self.assertIs(s.RUNS[run.id],run)

    def test_stale_duplicate_and_active_recovery_requests_are_rejected(self):
        run=self.new_task();ident=run.info['workflow']['id']
        with self.assertRaisesRegex(ValueError,'stale'):s.recover_run(run.id,'old')
        # A saved terminal status is not enough while final writes are pending.
        run.finished.clear()
        with self.assertRaises(ValueError):s.recover_run(run.id,ident)
        run.finished.set()
        recovered=self.recover(run,wait=False)
        with self.assertRaises(ValueError):s.recover_run(run.id,ident)
        self.assertTrue(recovered.finished.wait(7))

    def test_rejected_or_missing_approval_cannot_be_recovered_as_build(self):
        run=self.new_task();run.info['plan_rejected']=True
        with self.assertRaisesRegex(ValueError,'rejected'):self.recover(run)
        del run.info['plan_rejected'];run.info.pop('approved_plan_id')
        with self.assertRaisesRegex(ValueError,'explicitly approved'):self.recover(run)
        self.assertEqual(self.counts()['builder'],1)

    def test_observer_failure_can_be_retried_for_read_only_task(self):
        self.fail_observer=True
        run=self.new_task(mode='plan');self.assertEqual(run.info['workflow']['step'],'observe')
        recovered=self.recover(run);self.assertEqual(recovered.info['status'],'done')
        self.assertEqual(self.counts(),dict(observer=2,builder=0,reviewer=0))
        self.assertEqual(Path(recovered.info['workspace']).resolve(),self.project.resolve())

    def test_original_checkout_changes_are_preserved_during_recovery(self):
        run=self.new_task();(self.project/'app.txt').write_text('Unrelated user edit')
        recovered=self.recover(run);self.assertEqual(recovered.info['status'],'done')
        self.assertEqual((self.project/'app.txt').read_text(),'Unrelated user edit')
        self.assertEqual(self.counts()['builder'],1)

    def test_recovery_does_not_extend_the_review_round_limit(self):
        self.revisions=True
        run=self.new_task();run.info['max_rounds']=1
        recovered=self.recover(run)
        self.assertEqual(recovered.info['status'],'needs_attention')
        self.assertEqual(self.counts(),dict(observer=1,builder=1,reviewer=2))
        self.assertEqual(recovered.info['max_rounds'],1)
        # More rounds are only ever added by the user's explicit choice at the limit.
        self.assertEqual(s.recovery_option(recovered.info)['step'],'limit')

    def test_legacy_tasks_are_not_given_guessed_checkpoints(self):
        run=self.new_task();run.info.pop('workflow')
        self.assertFalse(s.recovery_option(run.info)['available'])
        with self.assertRaises(ValueError):s.recover_run(run.id,'unknown')
