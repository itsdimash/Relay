"""Optional history limits: off by default, oldest finished chats go first, nothing active is touched."""
import json
from pathlib import Path
import tempfile
import unittest

from unittest.mock import patch

from relay import retention
from relay.application import Application
from relay.history import summarize

ROOT = Path(__file__).resolve().parents[1]


def chat(app, name, when, size=10, status='done'):
    run = app.Run(name, ROOT, mode='observe')
    run.emit('Relay', 'message', 'x')
    run.info.update(status=status, created=when)
    run.finished.set()
    run.save()
    (run.folder / 'blob.bin').write_bytes(b'0' * size)
    # Keep it the way a restart does: only the summary in memory.
    app.RUNS[run.id] = {**summarize(run.info), 'finished_at': when}
    return run.id


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(ROOT, Path(self.temp.name) / 'data')
        self.ids = [chat(self.app, f'Chat {n}', f'2026-01-0{n}T10:00:00+00:00') for n in range(1, 6)]

    def tearDown(self):
        self.temp.cleanup()

    def test_nothing_is_deleted_by_default(self):
        self.assertEqual(self.app.enforce_retention(), [])
        self.assertEqual(len(self.app.RUNS), 5)
        self.assertEqual(self.app.retention_policy(), {'max_chats': None, 'max_mb': None})

    def test_chat_limit_deletes_the_oldest_first(self):
        self.app.set_retention_policy({'max_chats': 25})
        self.assertEqual(len(self.app.RUNS), 5)
        # Fill past the limit with more chats.
        more = [chat(self.app, f'More {n}', f'2026-02-{n:02d}T10:00:00+00:00') for n in range(1, 24)]
        result = self.app.enforce_retention()
        self.assertEqual(result, self.ids[:3])
        self.assertEqual(len(self.app.RUNS), 25)
        self.assertTrue(all(run_id in self.app.RUNS for run_id in more))
        self.assertFalse((self.app.DATA / 'runs' / self.ids[0]).exists())

    def test_size_limit_deletes_oldest_but_keeps_the_newest_chat_even_if_it_is_too_big(self):
        big = chat(self.app, 'Huge', '2026-03-01T10:00:00+00:00', size=2 * 1024 * 1024)
        with patch.object(retention, 'SIZE_CHOICES_MB', (1, 1024)):
            result = self.app.set_retention_policy({'max_mb': 1})
        self.assertEqual(result['deleted'], self.ids)
        self.assertEqual(list(self.app.RUNS), [big])
        self.assertTrue((self.app.DATA / 'runs' / big).is_dir())

    def test_preview_counts_without_saving_or_deleting(self):
        for n in range(1, 24):
            chat(self.app, f'More {n}', f'2026-02-{n:02d}T10:00:00+00:00')
        result = self.app.set_retention_policy({'max_chats': 25, 'preview': True})
        self.assertEqual(result['would_delete'], 3)
        self.assertEqual(len(self.app.RUNS), 28)
        self.assertEqual(self.app.retention_policy(), {'max_chats': None, 'max_mb': None})

    def test_only_listed_limits_are_accepted_from_the_saved_file(self):
        (self.app.DATA / 'retention.json').write_text(json.dumps({'max_chats': 7, 'max_mb': 1}))
        self.assertEqual(self.app.retention_policy(), {'max_chats': None, 'max_mb': None})

    def test_running_chats_and_kept_chats_are_never_deleted(self):
        live = self.app.Run('Live', ROOT, mode='observe')
        live.info['status'] = 'building'
        self.app.RUNS[live.id] = live
        self.app.set_retention_policy({'max_chats': 25})
        for n in range(1, 24):
            chat(self.app, f'More {n}', f'2026-02-{n:02d}T10:00:00+00:00')
        result = self.app.enforce_retention(keep=[self.ids[0]])
        self.assertNotIn(self.ids[0], result)
        self.assertIn(self.ids[0], self.app.RUNS)
        self.assertIn(live.id, self.app.RUNS)

    def test_invalid_limits_are_rejected_and_unknown_files_mean_no_limit(self):
        for bad in ({}, {'max_chats': 7}, {'max_chats': True}, {'max_mb': '1024'}):
            with self.assertRaises(ValueError):
                self.app.set_retention_policy(bad)
        (self.app.DATA / 'retention.json').write_text('not json')
        self.assertEqual(self.app.retention_policy(), {'max_chats': None, 'max_mb': None})
        self.assertEqual(self.app.enforce_retention(), [])

    def test_usage_counts_chats_and_bytes(self):
        usage = self.app.storage_usage()
        self.assertEqual(usage['chats'], 5)
        self.assertGreaterEqual(usage['bytes'], 50)


if __name__ == '__main__':
    unittest.main()
