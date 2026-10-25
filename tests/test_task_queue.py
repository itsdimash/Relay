import base64
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from relay.application import Application
from relay import task_queue

ROOT = Path(__file__).parents[1]


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / 'project'
        self.project.mkdir()
        self.app = Application(ROOT, Path(self.temp.name) / 'data')

    def tearDown(self):
        self.temp.cleanup()

    def brief(self, **extra):
        return {'task': 'Improve validation', 'project': str(self.project), 'mode': 'build', 'rounds': 2, 'minutes': 40, **extra}

    def test_can_save_while_busy_and_restart_never_starts_workers(self):
        self.app.ACTIVE = SimpleNamespace(finished=threading.Event())
        snapshot = self.app.add_queued_task(self.brief())
        self.assertFalse(snapshot['can_start'])
        self.assertEqual(self.app.RUNS, {})
        reloaded = Application(ROOT, self.app.DATA)
        queued = reloaded.queue_snapshot()
        self.assertEqual(queued['items'], snapshot['items'])
        self.assertEqual(queued['items'][0]['rounds'], 2)
        self.assertEqual(queued['items'][0]['minutes'], 40)
        self.assertIsNone(reloaded.ACTIVE)
        self.assertEqual(reloaded.RUNS, {})

    def test_start_is_explicit_single_and_keeps_approval_gate(self):
        entry = self.app.add_queued_task(self.brief())['items'][0]
        active = SimpleNamespace(finished=threading.Event(), info={'status':'done'})
        self.app.ACTIVE = active
        with self.assertRaises(ValueError):
            self.app.start_queued_task(entry['id'])
        self.assertEqual(len(self.app.queue_snapshot()['items']), 1)
        active.finished.set()
        with patch.object(task_queue.threading, 'Thread') as worker:
            result = self.app.start_queued_task(entry['id'])
        worker.return_value.start.assert_called_once()
        run = self.app.RUNS[result['id']]
        self.assertEqual(run.info['status'], 'queued')
        self.assertNotIn('approved_plan_id', run.info)
        self.assertEqual(run.info['max_rounds'], 2)
        self.assertEqual(run.info['minutes'], 40)
        self.assertEqual(self.app.queue_snapshot()['items'], [])
        with self.assertRaises(ValueError):
            self.app.start_queued_task(entry['id'])

    def test_concurrent_start_requests_admit_one_worker(self):
        entry = self.app.add_queued_task(self.brief())['items'][0]
        def start():
            try:
                return self.app.start_queued_task(entry['id'])['id']
            except ValueError:
                return None
        with patch.object(self.app.Run, 'execute', lambda run: None):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: start(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.app.RUNS), 1)

    def test_reorder_remove_and_fifo_are_persistent(self):
        first = self.app.add_queued_task(self.brief())['items'][0]
        second = self.app.add_queued_task(self.brief(task='Second task'))['items'][1]
        with self.assertRaises(ValueError):
            self.app.start_queued_task(second['id'])
        self.app.move_queued_task(second['id'], -1)
        reloaded = Application(ROOT, self.app.DATA)
        self.assertEqual(reloaded.queue_snapshot()['items'][0]['id'], second['id'])
        reloaded.remove_queued_task(first['id'])
        self.assertEqual(len(reloaded.queue_snapshot()['items']), 1)
        self.assertTrue((self.app.DATA/'queue'/'removed'/(first['id']+'.json')).is_file())

    def test_missing_project_and_shutdown_do_not_consume_task(self):
        entry = self.app.add_queued_task(self.brief())['items'][0]
        self.project.rmdir()
        with self.assertRaises(ValueError):
            self.app.start_queued_task(entry['id'])
        self.assertEqual(len(self.app.queue_snapshot()['items']), 1)
        self.project.mkdir()
        self.app.SHUTTING_DOWN.set()
        with self.assertRaises(ValueError):
            self.app.start_queued_task(entry['id'])
        self.assertEqual(len(self.app.queue_snapshot()['items']), 1)

    def test_attachments_are_validated_saved_privately_and_carried_into_run(self):
        raw = b'\x89PNG\r\n\x1a\n' + bytes(4) + b'IHDR' + bytes(8)
        entry = self.app.add_queued_task(self.brief(images=[{'name':'screen.png','data':base64.b64encode(raw).decode()}]))['items'][0]
        self.assertEqual(entry['image_count'], 1)
        self.assertNotIn('data', (self.app.DATA/'queue.json').read_text())
        with patch.object(task_queue.threading, 'Thread'):
            result = self.app.start_queued_task(entry['id'])
        run = self.app.RUNS[result['id']]
        self.assertEqual(run.info['attachments'][0]['size'], len(raw))
        self.assertEqual(len(list((run.folder/'attachments').iterdir())), 1)

    def test_invalid_tasks_and_corrupt_queue_are_preserved_without_worker(self):
        for extra in ({'task':''}, {'minutes':True}, {'rounds':6}, {'images':[{}]}, {'demo':True}):
            with self.assertRaises(ValueError):
                self.app.add_queued_task(self.brief(**extra))
        self.app.DATA.mkdir(exist_ok=True)
        (self.app.DATA/'queue.json').write_text('broken')
        self.assertTrue(self.app.queue_snapshot()['error'])
        with self.assertRaises(ValueError):
            self.app.add_queued_task(self.brief())
        self.assertEqual((self.app.DATA/'queue.json').read_text(), 'broken')
        self.assertEqual(self.app.RUNS, {})

    def test_selected_finding_context_is_frozen_with_the_brief(self):
        source = {'id':'aaaaaaaaaaaa','project':str(self.project),'status':'done','summary':'Saved report',
                  'findings':[{'id':'F1','problem':'Missing validation'},{'id':'F2','problem':'Unrelated issue'}]}
        self.app.RUNS[source['id']] = source
        entry = self.app.add_queued_task(self.brief(source_id=source['id'], finding_indexes=[0]))['items'][0]
        source['findings'][0]['problem'] = 'Changed after the queue snapshot'
        del self.app.RUNS[source['id']]
        with patch.object(task_queue.threading, 'Thread'):
            result = self.app.start_queued_task(entry['id'])
        run = self.app.RUNS[result['id']]
        self.assertIn('Missing validation', run.info['context'])
        self.assertNotIn('Unrelated issue', run.info['context'])
        self.assertEqual(run.info['source']['finding_indexes'],[0])


class QueueHTTPTests(unittest.TestCase):
    setUp = QueueTests.setUp
    tearDown = QueueTests.tearDown
    brief = QueueTests.brief
    def test_queue_actions_need_token_and_do_not_start_on_read(self):
        server = ThreadingHTTPServer(('127.0.0.1',0), self.app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        def post(path, body, token='wrong'):
            request = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={'X-Relay-Token':token,'Content-Type':'application/json'})
            with urllib.request.urlopen(request, timeout=3) as response:
                return json.load(response)
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                post('/api/queue/add', self.brief())
            self.assertEqual(error.exception.code,403)
            error.exception.close()
            saved = post('/api/queue/add', self.brief(), self.app.TOKEN)
            with urllib.request.urlopen(base+'/api/state', timeout=3) as response:
                self.assertEqual(json.load(response)['queue']['items'][0]['id'], saved['items'][0]['id'])
            self.assertEqual(self.app.RUNS,{})
            with self.assertRaises(urllib.error.HTTPError) as error:
                post('/api/queue/start',{'id':saved['items'][0]['id']})
            self.assertEqual(error.exception.code,403)
            error.exception.close()
            with patch.object(self.app.Run, 'execute', lambda run: None):
                result=post('/api/queue/start',{'id':saved['items'][0]['id']},self.app.TOKEN)
            self.assertIn(result['id'], self.app.RUNS)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)
