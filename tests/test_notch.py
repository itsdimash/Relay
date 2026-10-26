from http.server import ThreadingHTTPServer
import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

from relay import notch

SPEC = importlib.util.spec_from_file_location('relay_server', Path(__file__).parents[1] / 'server.py')
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)
app = server.application

NOW = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)


def info(status='building', **extra):
    base = {'id': 'run-1', 'status': status, 'mode': 'build', 'task': 'Add validation', 'created': '2026-01-01T11:58:00+00:00',
            'events': [], 'team': {'roles': {'observer': {'provider': 'claude', 'model': 'a'}}}}
    base.update(extra)
    return base


class DescribeTests(unittest.TestCase):
    def test_steps_follow_the_status(self):
        steps = notch.describe_run(info('building'), NOW)['steps']
        states = {step['key']: step['state'] for step in steps}
        self.assertEqual(states['observing'], 'done')
        self.assertEqual(states['awaiting_approval'], 'done')
        self.assertEqual(states['building'], 'current')
        self.assertEqual(states['reviewing'], 'todo')

    def test_done_marks_every_step_done(self):
        steps = notch.describe_run(info('done'), NOW)['steps']
        self.assertTrue(all(step['state'] == 'done' for step in steps))

    def test_actor_for_each_phase(self):
        for status, actor in [('observing', 'observer'), ('building', 'builder'), ('fixing', 'builder'),
                              ('reviewing', 'reviewer'), ('awaiting_approval', 'you'), ('awaiting_clarification', 'you')]:
            self.assertEqual(notch.describe_run(info(status), NOW)['actor'], actor)
        finished = notch.describe_run(info('failed'), NOW)
        self.assertFalse(finished['running'])
        self.assertIsNone(finished['actor'])

    def test_plan_only_while_waiting_for_approval(self):
        plan = {'id': 'p1', 'summary': 'Do it', 'acceptance_checks': ['a', 'b', 'c', 'd']}
        waiting = notch.describe_run(info('awaiting_approval', plan=plan), NOW)
        self.assertEqual(waiting['plan']['id'], 'p1')
        self.assertEqual(len(waiting['plan']['checks']), 3)
        approved = notch.describe_run(info('awaiting_approval', plan=plan, approved_plan_id='p1'), NOW)
        self.assertIsNone(approved['plan'])
        self.assertIsNone(notch.describe_run(info('building', plan=plan), NOW)['plan'])

    def test_elapsed_only_counts_while_running(self):
        self.assertEqual(notch.describe_run(info('building'), NOW)['elapsed'], 120)
        self.assertEqual(notch.describe_run(info('done'), NOW)['elapsed'], 0)

    def test_last_message_skips_stage_events_and_is_clipped(self):
        events = [{'kind': 'note', 'agent': 'Builder', 'message': 'x' * 400}, {'kind': 'stage', 'message': 'Stage changed'}]
        last = notch.describe_run(info(events=events), NOW)['last']
        self.assertEqual(last['agent'], 'Builder')
        self.assertLessEqual(len(last['message']), 160)

    def test_title_prefers_conversation_title(self):
        self.assertEqual(notch.describe_run(info(conversation_title='Signup form'), NOW)['title'], 'Signup form')

    def test_snapshot_prefers_a_running_task(self):
        old_running = info('building', id='a', created='2026-01-01T10:00:00+00:00')
        new_done = info('done', id='b', created='2026-01-01T11:59:00+00:00')
        self.assertEqual(notch.snapshot([old_running, new_done], NOW)['run']['id'], 'a')
        self.assertEqual(notch.snapshot([new_done], NOW)['run']['id'], 'b')
        self.assertIsNone(notch.snapshot([], NOW)['run'])

    def test_finished_task_disappears_after_five_minutes(self):
        def finished(minutes, **extra):
            stamp = (NOW - dt.timedelta(minutes=minutes)).isoformat()
            return info('done', id='f', created='2026-01-01T09:00:00+00:00', events=[{'time': stamp, 'kind': 'stage', 'message': 'Done'}], **extra)
        self.assertEqual(notch.snapshot([finished(4)], NOW)['run']['id'], 'f')
        self.assertIsNone(notch.snapshot([finished(6)], NOW)['run'])
        self.assertIsNone(notch.snapshot([finished(360)], NOW)['run'])
        running = info('building', id='r', created='2026-01-01T08:00:00+00:00')
        self.assertEqual(notch.snapshot([finished(360), running], NOW)['run']['id'], 'r')

    def test_role_activity_keeps_same_provider_roles_distinct_and_reads_structured_updates(self):
        events = [
            {'role': 'observer', 'kind': 'message', 'message': '{"overview":"Inspected the form","summary":"Plan"}', 'time': 'saved'},
            {'role': 'builder', 'kind': 'tool', 'message': 'Run focused tests'},
            {'role': 'reviewer', 'kind': 'review', 'message': 'No remaining findings'},
        ]
        run = notch.describe_run(info(events=events), NOW)
        self.assertEqual(run['activities']['observer']['message'], 'Inspected the form')
        self.assertEqual(run['activities']['observer']['time'], 'saved')
        self.assertEqual(run['activities']['builder']['message'], 'Run focused tests')
        self.assertEqual(run['activities']['reviewer']['message'], 'No remaining findings')

    def test_result_counts_use_latest_builder_round_and_do_not_count_tests_from_prose(self):
        reports = [
            {'round': 1, 'checks': [{'status': 'failed'}]},
            {'round': 2, 'checks': [{'status': 'failed'}]},
            {'round': 2, 'checks': [{'status': 'passed', 'details': '11 tests passed'}, {'status': 'not_run'}]},
        ]
        run = notch.describe_run(info('done', files=['a.py', 'b.py'], findings=[], builder_reports=reports), NOW)
        self.assertEqual(run['result']['files'], 2)
        self.assertEqual(run['result']['checks'], {'passed': 1, 'failed': 0, 'not_run': 1})
        self.assertEqual(run['result']['checks_source'], 'builder')

    def test_older_tasks_do_not_get_invented_checks_or_activity(self):
        run = notch.describe_run(info('done'), NOW)
        self.assertTrue(all(value is None for value in run['activities'].values()))
        self.assertEqual(sum(run['result']['checks'].values()), 0)

    def test_recent_events_are_bounded_deduplicated_and_use_saved_timestamps(self):
        events = [{'kind':'tool','role':'observer','message':'raw command'}]
        events += [{'kind':'message','role':'observer','agent':'Codex','time':f'time-{i}', 'message':json.dumps({'overview':f'Update {i}'})} for i in range(14)]
        events.append(events[-1].copy())
        run = notch.describe_run(info(events=events), NOW)
        self.assertEqual(len(run['recent_events']),12)
        self.assertEqual(run['recent_events'][0]['message'],'Update 13')
        self.assertEqual(run['recent_events'][0]['time'],'time-13')
        self.assertFalse(any(event['kind']=='tool' for event in run['recent_events']))


class NotchHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data = server.application.DATA
        app.DATA = Path(self.temp.name) / 'data'
        self.runs = dict(app.RUNS)
        app.RUNS.clear()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        app.RUNS.clear()
        app.RUNS.update(self.runs)
        app.DATA = self.old_data
        self.temp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as response:
            return response.status, response.headers, response.read()

    def test_feed_is_empty_when_nothing_ran_and_carries_the_token(self):
        _, _, body = self.get('/api/notch')
        data = json.loads(body)
        self.assertIsNone(data['run'])
        self.assertEqual(data['token'], app.TOKEN)

    def test_feed_describes_a_stored_run(self):
        app.RUNS['run-1'] = info('awaiting_approval', plan={'id': 'p1', 'summary': 'Do it', 'acceptance_checks': []})
        data = json.loads(self.get('/api/notch')[2])
        self.assertEqual(data['run']['status'], 'awaiting_approval')
        self.assertEqual(data['run']['plan']['id'], 'p1')

    def test_panel_page_and_assets_are_served(self):
        for path, kind in [('/notch', 'text/html'), ('/notch.css', 'text/css'), ('/notch.js', 'javascript'), ('/js/notch-room.js', 'javascript'), ('/js/notch-collaboration.js', 'javascript'), ('/js/notch-activity.js', 'javascript'), ('/js/task-queue.js', 'javascript')]:
            status, headers, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertIn(kind, headers['Content-Type'])
            self.assertTrue(body)

    def test_panel_page_has_no_inline_script_or_style(self):
        html = self.get('/notch')[2].decode()
        self.assertNotIn('style="', html)
        self.assertNotRegex(html, r'<script(?![^>]*src=)')


if __name__ == '__main__':
    unittest.main()
