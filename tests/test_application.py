"""Exercise instance ownership across the composed backend services."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
import urllib.error
import urllib.request

from relay.application import Application


class ApplicationTests(unittest.TestCase):
    def test_constructing_instances_has_no_storage_side_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = Application(root, root / 'first')
            second = Application(root, root / 'second')
            self.assertEqual(list(root.iterdir()), [])
            self.assertNotEqual(first.TOKEN, second.TOKEN)
            first.SHUTTING_DOWN.set()
            self.assertFalse(second.SHUTTING_DOWN.is_set())

    def test_projects_history_and_rehydrated_runs_keep_their_own_context(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = Application(root, root / 'first')
            second = Application(root, root / 'second')
            first.save_project('First project', str(root))
            self.assertEqual(second.project_choices()['projects'], [])

            task = first.Run('Inspect this folder', root, mode='observe')
            task.info.update(status='done', summary='Saved result')
            task.checkpoint('report')
            first.RUNS[task.id] = task
            task.finished.set()
            first.ACTIVE = task
            self.assertEqual(second.states(), [])
            self.assertIsNone(second.ACTIVE)

            # Startup and checkpoint rehydration must use the supplied data root.
            reloaded = Application(root, first.DATA)
            reloaded.load_runs()
            restored = reloaded.Run.recover(reloaded.run_info(task.id))
            restored.info['summary'] = 'Updated after recovery'
            restored.save()
            saved = json.loads((first.DATA / 'runs' / task.id / 'state.json').read_text())
            self.assertEqual(saved['summary'], 'Updated after recovery')
            self.assertEqual(restored.folder, task.folder)
            self.assertFalse(second.DATA.exists())

    def test_http_handlers_use_their_own_token_and_registry(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Application(folder, Path(folder) / 'first')
            second = Application(folder, Path(folder) / 'second')
            servers = []
            workers = []
            try:
                for app in (first, second):
                    server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
                    servers.append(server)
                    worker = threading.Thread(target=server.serve_forever, daemon=True)
                    workers.append(worker)
                    worker.start()
                for app, server in zip((first, second), servers):
                    url = f'http://127.0.0.1:{server.server_port}'
                    with urllib.request.urlopen(url + '/api/state', timeout=3) as response:
                        self.assertEqual(json.load(response)['token'], app.TOKEN)
                    wrong = second.TOKEN if app is first else first.TOKEN
                    request = urllib.request.Request(
                        url + '/api/projects/save',
                        data=json.dumps({'name': 'Project', 'path': folder}).encode(),
                        headers={'Content-Type': 'application/json', 'X-Relay-Token': wrong},
                    )
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(request, timeout=3)
                    self.assertEqual(error.exception.code, 403)
                    error.exception.close()
                self.assertFalse(first.DATA.exists())
                self.assertFalse(second.DATA.exists())
            finally:
                for server in servers:
                    server.shutdown()
                    server.server_close()
                for worker in workers:
                    worker.join(3)
