"""Chat storage: small summaries in memory, events only in the log, details loaded when a chat is opened."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from relay import notch
from relay.application import Application

ROOT = Path(__file__).resolve().parents[1]


def finished_chat(app, task='Inspect', events=3, status='done'):
    run = app.Run(task, ROOT, mode='observe')
    for number in range(events):
        run.emit('Relay', 'message', f'message {number}')
    run.info.update(status=status, summary='A long saved result', diff='x' * 50000)
    run.finished.set()
    run.save()
    app.RUNS[run.id] = run
    return run


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name) / 'data'
        self.app = Application(ROOT, self.data)

    def tearDown(self):
        self.temp.cleanup()

    def reloaded(self):
        app = Application(ROOT, self.data)
        app.load_runs()
        return app

    def test_state_file_has_no_events_but_the_log_does(self):
        run = finished_chat(self.app)
        saved = json.loads((run.folder / 'state.json').read_text())
        self.assertNotIn('events', saved)
        self.assertEqual(len((run.folder / 'events.jsonl').read_text().splitlines()), 3)
        self.assertEqual(self.app.run_info(run.id)['events'][0]['message'], 'message 0')

    def test_restart_keeps_only_summaries_until_a_chat_is_opened(self):
        run = finished_chat(self.app)
        app = self.reloaded()
        stub = app.RUNS[run.id]
        self.assertTrue(stub['light'])
        self.assertNotIn('diff', stub)
        full = app.run_info(run.id)
        self.assertEqual(len(full['diff']), 50000)
        self.assertEqual(len(full['events']), 3)
        self.assertTrue(app.RUNS[run.id]['light'], 'Opening a chat must not keep it in memory')

    def test_states_send_summaries_except_for_the_chat_that_is_open(self):
        first, second = finished_chat(self.app, 'First'), finished_chat(self.app, 'Second')
        app = self.reloaded()
        listed = {item['id']: item for item in app.states()}
        self.assertTrue(all(item.get('light') and 'diff' not in item and item['worker_finished'] for item in listed.values()))
        opened = {item['id']: item for item in app.states(first.id)}
        self.assertNotIn('light', opened[first.id])
        self.assertEqual(len(opened[first.id]['diff']), 50000)
        self.assertEqual(len(opened[first.id]['events']), 3)
        self.assertTrue(opened[second.id]['light'])

    def test_live_runs_are_complete_and_finished_ones_are_summarised(self):
        finished = finished_chat(self.app)
        self.app.RUNS[finished.id] = finished
        live = self.app.Run('Live', ROOT, mode='observe')
        live.info['status'] = 'building'
        self.app.RUNS[live.id] = live
        listed = {item['id']: item for item in self.app.states()}
        self.assertTrue(listed[finished.id]['light'])
        self.assertNotIn('light', listed[live.id])
        self.assertFalse(listed[live.id]['worker_finished'])
        self.assertIn('events', listed[live.id])

    def test_changed_state_file_is_not_trusted_after_restart(self):
        run = finished_chat(self.app)
        saved = json.loads((run.folder / 'state.json').read_text())
        saved['status'] = 'reviewing'
        (run.folder / 'state.json').write_text(json.dumps(saved))
        app = self.reloaded()
        self.assertEqual(app.RUNS[run.id]['status'], 'interrupted')
        self.assertEqual(app.run_info(run.id)['interrupted_stage'], 'reviewing')

    def test_chat_saved_by_an_older_version_still_opens(self):
        run = finished_chat(self.app)
        saved = json.loads((run.folder / 'state.json').read_text())
        del saved['events_start']
        saved['events'] = [json.loads(line) for line in (run.folder / 'events.jsonl').read_text().splitlines()][1:]
        (run.folder / 'state.json').write_text(json.dumps(saved))
        (run.folder / 'summary.json').unlink()
        app = self.reloaded()
        self.assertEqual(app.RUNS[run.id]['finished_at'], saved['events'][-1]['time'])
        self.assertEqual([event['message'] for event in app.run_info(run.id)['events']], ['message 1', 'message 2'])
        self.assertNotIn('events', json.loads((run.folder / 'state.json').read_text()))
        self.assertTrue((run.folder / 'summary.json').is_file())

    def test_each_turn_of_a_chat_keeps_its_own_events(self):
        root = finished_chat(self.app, events=3)
        source = self.app.run_info(root.id)
        follow = self.app.Run('Why?', ROOT, mode='observe', conversation=source)
        follow.emit('Relay', 'message', 'second turn')
        follow.info['status'] = 'done'
        follow.finished.set()
        follow.save()
        self.assertEqual(len((follow.folder / 'events.jsonl').read_text().splitlines()), 4)
        app = self.reloaded()
        self.assertEqual([event['message'] for event in app.run_info(root.id)['events']], ['second turn'])

    def test_half_written_log_line_is_ignored(self):
        run = finished_chat(self.app)
        with (run.folder / 'events.jsonl').open('a') as f:
            f.write('{"time": "broken')
        self.assertEqual(len(self.reloaded().run_info(run.id)['events']), 3)

    def test_notch_reads_a_recent_chat_from_disk_and_hides_an_old_one(self):
        run = finished_chat(self.app)
        app = self.reloaded()
        stub = app.RUNS[run.id]
        now = dt.datetime.fromisoformat(stub['finished_at']) + dt.timedelta(minutes=2)
        shown = notch.snapshot(list(app.RUNS.values()), now, load=app.run_info)['run']
        self.assertEqual(shown['id'], run.id)
        self.assertEqual(len(shown['recent_events']), 3)
        later = now + dt.timedelta(hours=6)
        self.assertIsNone(notch.snapshot(list(app.RUNS.values()), later, load=app.run_info)['run'])


if __name__ == '__main__':
    unittest.main()
