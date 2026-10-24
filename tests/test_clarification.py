"""Clarification must refine requirements without granting edit approval."""
import json
import shutil
import threading
import time
import unittest
from unittest.mock import patch

import test_relay as fixtures
s = fixtures.s


def question(text='Which sign-in method?', ident='Q1'):
    result=fixtures.review('observed')
    result['questions']=[dict(id=ident,question=text,options=['Email link','Password'])]
    return result


class ClarificationWorkflowTests(unittest.TestCase):
    def setUp(self):
        fixtures.WorkflowTests.setUp(self)
        self.approval_patch.stop()
        self.workers=[];self.tasks=[];self.calls=[]
        self.observations=[question(),fixtures.review('observed')]
        def claude(run,prompt):
            self.calls.append((run.current_role,prompt))
            return self.observations.pop(0) if run.current_role=='observer' else fixtures.review('approved')
        def codex(run,prompt):
            self.calls.append((run.current_role,prompt))
            return 'Implemented; no checks run.\n```relay-checks\n[]\n```'
        self.claude_patch=patch.object(s.Run,'claude',claude);self.claude_patch.start()
        self.codex_patch=patch.object(s.Run,'codex',codex);self.codex_patch.start()

    def tearDown(self):
        for task in self.tasks:task.stop_event.set();task.resume_event.set()
        for worker in self.workers:worker.join(5)
        self.claude_patch.stop();self.codex_patch.stop()
        fixtures.WorkflowTests.tearDown(self)

    def wait_for(self, predicate):
        end=time.monotonic()+5
        while time.monotonic()<end:
            if predicate():return
            time.sleep(.01)
        self.fail('Task did not reach expected state. '+str([t.info['status'] for t in self.tasks]))

    def start_task(self,mode='build'):
        task=s.Run('Add sign-in',self.project,mode=mode)
        self.tasks.append(task)
        worker=threading.Thread(target=task.execute);self.workers.append(worker);worker.start()
        self.wait_for(lambda:task.info['status']=='awaiting_clarification')
        return task

    def test_answers_refine_plan_but_builder_waits_for_separate_approval(self):
        task=self.start_task()
        self.assertIsNone(task.deadline)
        self.assertFalse(task.info.get('approved_plan_id'))
        with self.assertRaises(RuntimeError):task.run_role('builder','Bypass clarification')
        with self.assertRaises(ValueError):task.approve_plan('invented')
        batch=task.info['clarification']['id']
        task.answer_clarification(batch,{'Q1':' Email link '})
        self.wait_for(lambda:task.info['status']=='awaiting_approval')
        self.assertFalse(any(role=='builder' for role,_ in self.calls))
        self.assertFalse(task.approval_event.is_set())
        self.assertFalse(s.git(task.info['workspace'],'status','--porcelain').strip())
        self.assertIn('Email link',self.calls[1][1])
        task.approve_plan(task.info['plan']['id'])
        self.assertTrue(task.finished.wait(5))
        self.assertEqual(task.info['status'],'done')
        builder=next(prompt for role,prompt in self.calls if role=='builder')
        self.assertIn('Email link',builder)
        saved=json.loads((task.folder/'state.json').read_text())
        self.assertEqual(saved['clarifications'][0]['answers'],{'Q1':'Email link'})
        self.assertIn('Email link',s.report_context(saved))
        self.assertIn('Which sign-in method?',s.report_context(saved))
        followup=s.Run('Explain this plan',self.project,mode='observe',conversation=saved)
        self.assertEqual(followup.info['turns'][0]['clarifications'],saved['clarifications'])

    def test_missing_extra_empty_stale_and_duplicate_answers_are_rejected(self):
        task=self.start_task();ident=task.info['clarification']['id']
        for answers in [None,[],{}, {'Q1':''}, {'Q1':'  '}, {'Q1':'x'*2001}, {'Q1':True}, {'Q1':'Email link','Q2':'extra'}]:
            with self.subTest(answers=str(answers)[:40]),self.assertRaises(ValueError):task.answer_clarification(ident,answers)
        with self.assertRaises(ValueError):task.answer_clarification('old',{'Q1':'Email link'})
        self.assertFalse(task.clarification_event.is_set())
        task.answer_clarification(ident,{'Q1':'Email link'})
        with self.assertRaises(ValueError):task.answer_clarification(ident,{'Q1':'Password'})
        self.assertEqual(len(task.info['clarifications']),1)

    def test_multiple_rounds_keep_context_and_can_reject_the_final_plan(self):
        self.observations=[question(),question('Which pages need sign-in?','Q2'),fixtures.review('observed')]
        task=self.start_task();first=task.info['clarification']['id']
        task.answer_clarification(first,{'Q1':'Email link'})
        self.wait_for(lambda:task.info['status']=='awaiting_clarification' and task.info['clarification']['id']!=first)
        with self.assertRaises(ValueError):task.answer_clarification(first,{'Q1':'Password'})
        task.answer_clarification(task.info['clarification']['id'],{'Q2':'Settings only'})
        self.wait_for(lambda:task.info['status']=='awaiting_approval')
        self.assertIn('Email link',self.calls[2][1]);self.assertIn('Settings only',self.calls[2][1])
        task.stop_event.set()
        self.assertTrue(task.finished.wait(5))
        self.assertEqual(task.info['status'],'stopped')
        self.assertFalse(any(role=='builder' for role,_ in self.calls))

    def test_plan_only_can_clarify_and_finish_without_building(self):
        task=self.start_task('plan')
        task.answer_clarification(task.info['clarification']['id'],{'Q1':'Email link'})
        self.assertTrue(task.finished.wait(5));self.assertEqual(task.info['status'],'done')
        self.assertEqual([role for role,_ in self.calls],['observer','observer'])
        self.assertNotIn('approved_plan_id',task.info)

    def test_stop_while_waiting_never_starts_builder(self):
        task=self.start_task();task.stop_event.set()
        self.assertTrue(task.finished.wait(5));self.assertEqual(task.info['status'],'stopped')
        with self.assertRaises(ValueError):task.answer_clarification(task.info['clarification']['id'],{'Q1':'Email link'})
        self.assertEqual([role for role,_ in self.calls],['observer'])

    def test_restart_preserves_questions_without_resuming_or_approving(self):
        task=self.start_task();destination=self.base/'restart-data';shutil.copytree(s.DATA,destination)
        with patch.object(s,'DATA',destination),patch.object(s,'RUNS',{}):
            s.load_runs();saved=s.RUNS[task.id]
            self.assertEqual(saved['status'],'interrupted')
            self.assertEqual(saved['clarification'],task.info['clarification'])
            self.assertNotIn('approved_plan_id',saved)

    def test_deadline_pauses_while_waiting_for_answers(self):
        task=s.Run('Fixture',self.project);self.tasks.append(task)
        task.deadline=time.monotonic()+.1;errors=[]
        def wait():
            try:task.wait_for_clarification(question())
            except Exception as error:errors.append(error)
        worker=threading.Thread(target=wait);self.workers.append(worker);worker.start()
        self.wait_for(lambda:task.info['status']=='awaiting_clarification')
        time.sleep(.2);self.assertIsNone(task.deadline)
        task.answer_clarification(task.info['clarification']['id'],{'Q1':'Email link'})
        worker.join(2);self.assertFalse(errors);self.assertGreater(task.deadline,time.monotonic())

    def test_invalid_question_contract_is_rejected(self):
        invalid=[None,{},[{}], [dict(id='<script>',question='X',options=[])],
                 question()['questions']*2, [dict(id='Q',question='',options=[])],
                 [dict(id='Q',question='X',options=['x']*6)],
                 [dict(id='Q',question='X',options=[False])]]
        for questions in invalid:
            with self.subTest(questions=questions),self.assertRaises(ValueError):s.validate_questions(questions)
        report=fixtures.review('approved');report['questions']=question()['questions']
        with self.assertRaises(ValueError):s.validate_review(report)
        self.assertEqual(s.validate_questions([]),[])
