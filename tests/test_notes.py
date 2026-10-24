from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

SPEC = importlib.util.spec_from_file_location('relay_server', Path(__file__).parents[1] / 'server.py')
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)
app = server.application


class NotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data = app.DATA
        app.DATA = Path(self.temp.name) / 'data'

    def tearDown(self):
        app.DATA = self.old_data
        self.temp.cleanup()

    def test_starts_empty_and_saves_newest_first(self):
        self.assertEqual(app.read_notes(), [])
        app.add_note('first', 'note')
        notes = app.add_note('second', 'todo')
        self.assertEqual([item['text'] for item in notes], ['second', 'first'])
        self.assertEqual([item['kind'] for item in notes], ['todo', 'note'])
        self.assertFalse(notes[0]['done'])
        self.assertEqual(app.read_notes(), notes)

    def test_text_is_trimmed_collapsed_and_checked(self):
        notes = app.add_note('  buy   milk \n and eggs ', 'note')
        self.assertEqual(notes[0]['text'], 'buy milk and eggs')
        for bad in ('', '   ', None, 5):
            with self.assertRaises(ValueError):
                app.add_note(bad, 'note')
        with self.assertRaises(ValueError):
            app.add_note('x' * 501, 'note')
        with self.assertRaises(ValueError):
            app.add_note('ok', 'task')

    def test_unicode_text_survives(self):
        app.add_note('Сделать отчёт · 日本語', 'todo')
        self.assertEqual(app.read_notes()[0]['text'], 'Сделать отчёт · 日本語')

    def test_list_has_a_limit(self):
        for index in range(200):
            app.add_note(f'item {index}', 'note')
        with self.assertRaises(ValueError):
            app.add_note('one too many', 'note')

    def test_only_todos_can_be_ticked(self):
        app.add_note('a note', 'note')
        todo_id = app.add_note('a todo', 'todo')[0]['id']
        note_id = app.read_notes()[1]['id']
        self.assertTrue(next(item for item in app.set_note_done(todo_id, True) if item['id'] == todo_id)['done'])
        self.assertFalse(next(item for item in app.set_note_done(todo_id, False) if item['id'] == todo_id)['done'])
        with self.assertRaises(ValueError):
            app.set_note_done(note_id, True)
        with self.assertRaises(ValueError):
            app.set_note_done(todo_id, 'yes')
        with self.assertRaises(ValueError):
            app.set_note_done('missing', True)

    def test_remove(self):
        first = app.add_note('one', 'note')[0]['id']
        app.add_note('two', 'note')
        remaining = app.remove_note(first)
        self.assertEqual([item['text'] for item in remaining], ['two'])
        with self.assertRaises(ValueError):
            app.remove_note(first)

    def test_unreadable_file_is_reported_and_never_overwritten(self):
        app.DATA.mkdir(parents=True)
        (app.DATA / 'notes.json').write_text('{not json')
        with self.assertRaises(ValueError):
            app.read_notes()
        with self.assertRaises(ValueError):
            app.add_note('would replace it', 'note')
        self.assertEqual((app.DATA / 'notes.json').read_text(), '{not json')


class NotesHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data = app.DATA
        app.DATA = Path(self.temp.name) / 'data'
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        app.DATA = self.old_data
        self.temp.cleanup()

    def post(self, path, body, token=None):
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method='POST',
                                         headers={'Content-Type': 'application/json', 'X-Relay-Token': app.TOKEN if token is None else token})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_round_trip_through_the_api(self):
        status, data = self.post('/api/notes/add', {'text': 'ship v0.1.5', 'kind': 'todo'})
        self.assertEqual(status, 201)
        note_id = data['notes'][0]['id']
        status, data = self.post('/api/notes/done', {'id': note_id, 'done': True})
        self.assertEqual((status, data['notes'][0]['done']), (200, True))
        with urllib.request.urlopen(self.base + '/api/notes') as response:
            self.assertEqual(json.loads(response.read())['notes'][0]['text'], 'ship v0.1.5')
        status, data = self.post('/api/notes/remove', {'id': note_id})
        self.assertEqual((status, data['notes']), (200, []))

    def test_changes_need_the_token(self):
        status, _ = self.post('/api/notes/add', {'text': 'sneaky', 'kind': 'note'}, token='wrong')
        self.assertEqual(status, 403)
        self.assertEqual(app.read_notes(), [])

    def test_bad_requests_get_a_clear_error(self):
        status, data = self.post('/api/notes/add', {'text': '', 'kind': 'note'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)
        status, _ = self.post('/api/notes/remove', {'id': 'missing'})
        self.assertEqual(status, 400)


if __name__ == '__main__':
    unittest.main()
