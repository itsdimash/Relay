from http.server import ThreadingHTTPServer
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
from unittest import mock
import zipfile
import urllib.error
import urllib.request

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('relay_server', ROOT / 'server.py')
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)
app = server.application
deliver = importlib.import_module('relay.deliver')


class DeliverTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data = app.DATA
        self.folder = Path(self.temp.name) / 'files'
        self.folder.mkdir()
        app.DATA = Path(self.temp.name) / 'data'

    def tearDown(self):
        app.DATA = self.old_data
        self.temp.cleanup()

    def make(self, name, text='hello'):
        path = self.folder / name
        path.write_text(text)
        return str(path)


class DeliverShelfTests(DeliverTestCase):
    def test_starts_empty_and_keeps_newest_first(self):
        self.assertEqual(app.deliver_list(), [])
        app.add_deliver([self.make('a.pdf')])
        items = app.add_deliver([self.make('b.png'), self.make('c.txt')])
        self.assertEqual([item['name'] for item in items], ['b.png', 'c.txt', 'a.pdf'])
        self.assertEqual([item['name'] for item in app.deliver_list()], ['b.png', 'c.txt', 'a.pdf'])

    def test_only_paths_are_saved_and_the_files_are_left_alone(self):
        path = self.make('report.docx', 'secret words')
        app.add_deliver([path])
        saved = json.loads((app.DATA / 'deliver.json').read_text())
        self.assertEqual([item['path'] for item in saved], [path])
        self.assertNotIn('secret words', (app.DATA / 'deliver.json').read_text())
        self.assertEqual(Path(path).read_text(), 'secret words')
        self.assertEqual(sorted(entry.name for entry in app.DATA.iterdir()), ['deliver.json'])

    def test_describes_size_kind_and_a_missing_file(self):
        path = self.make('five.txt', '12345')
        sub = self.folder / 'sub'
        sub.mkdir()
        app.add_deliver([path, str(sub)])
        items = {item['name']: item for item in app.deliver_list()}
        self.assertEqual((items['five.txt']['kind'], items['five.txt']['size'], items['five.txt']['missing']), ('file', 5, False))
        self.assertEqual((items['sub']['kind'], items['sub']['size'], items['sub']['missing']), ('folder', None, False))
        Path(path).unlink()
        items = {item['name']: item for item in app.deliver_list()}
        self.assertTrue(items['five.txt']['missing'])  # the shelf shows it greyed out; the person removes it

    def test_the_same_file_is_not_added_twice(self):
        path = self.make('once.txt')
        app.add_deliver([path])
        items = app.add_deliver([path, path])
        self.assertEqual(len(items), 1)
        items = app.add_deliver([str(self.folder / 'sub' / '..' / 'once.txt')])  # the same file by another spelling
        self.assertEqual(len(items), 1)

    def test_bad_drops_are_refused(self):
        for bad in (None, [], 'file', [5], [None]):
            with self.assertRaises(ValueError):
                app.add_deliver(bad)
        with self.assertRaises(ValueError):
            app.add_deliver([str(self.folder / 'nothing-here.txt')])
        with self.assertRaises(ValueError):
            app.add_deliver(['relative/path.txt'])  # only real, absolute paths on this Mac
        self.assertEqual(app.deliver_list(), [])

    def test_missing_files_in_a_drop_do_not_spoil_the_others(self):
        good = self.make('good.txt')
        items = app.add_deliver([str(self.folder / 'gone.txt'), good])
        self.assertEqual([item['name'] for item in items], ['good.txt'])

    def test_shelf_has_a_limit(self):
        paths = [self.make(f'f{index}.txt') for index in range(100)]
        app.add_deliver(paths)
        with self.assertRaises(ValueError):
            app.add_deliver([self.make('one-too-many.txt')])
        self.assertEqual(len(app.deliver_list()), 100)

    def test_remove_and_clear(self):
        first = app.add_deliver([self.make('a.txt')])[0]['id']
        app.add_deliver([self.make('b.txt')])
        remaining = app.remove_deliver(first)
        self.assertEqual([item['name'] for item in remaining], ['b.txt'])
        with self.assertRaises(ValueError):
            app.remove_deliver(first)
        self.assertEqual(app.clear_deliver(), [])
        self.assertEqual(app.deliver_list(), [])

    def test_several_items_come_off_the_shelf_at_once(self):
        items = app.add_deliver([self.make('a.txt'), self.make('b.txt'), self.make('c.txt')])
        ids = [item['id'] for item in items]
        remaining = app.remove_deliver(ids[:2])
        self.assertEqual([item['id'] for item in remaining], ids[2:])
        for bad in ([], [5], None, 7):
            with self.assertRaises(ValueError):
                app.remove_deliver(bad)
        with self.assertRaises(ValueError):
            app.remove_deliver(ids[:2])  # already gone
        self.assertEqual([item['id'] for item in app.deliver_list()], ids[2:])

    def test_the_after_drop_choice_is_kept_and_defaults_to_keeping_files(self):
        self.assertEqual(app.deliver_settings(), {'remove_after_drop': False, 'auto_catch': False, 'expire_hours': 0})
        self.assertEqual(app.set_deliver_settings(True), {'remove_after_drop': True, 'auto_catch': False, 'expire_hours': 0})
        self.assertEqual(app.deliver_settings(), {'remove_after_drop': True, 'auto_catch': False, 'expire_hours': 0})
        for bad in ('yes', 1, None):
            with self.assertRaises(ValueError):
                app.set_deliver_settings(bad)
        self.assertTrue(app.deliver_settings()['remove_after_drop'])

    def test_each_choice_changes_alone(self):
        self.assertEqual(app.set_deliver_settings(auto_catch=True), {'remove_after_drop': False, 'auto_catch': True, 'expire_hours': 0})
        self.assertEqual(app.set_deliver_settings(remove_after_drop=True), {'remove_after_drop': True, 'auto_catch': True, 'expire_hours': 0})
        self.assertEqual(app.set_deliver_settings(auto_catch=False), {'remove_after_drop': True, 'auto_catch': False, 'expire_hours': 0})
        for bad in ({'auto_catch': 'yes'}, {'auto_catch': 1}, {'remove_after_drop': True, 'auto_catch': 'no'}, {}):
            with self.assertRaises(ValueError):
                app.set_deliver_settings(**bad)
        self.assertEqual(app.deliver_settings(), {'remove_after_drop': True, 'auto_catch': False, 'expire_hours': 0})

    def test_a_damaged_settings_file_means_the_defaults(self):
        app.DATA.mkdir(parents=True)
        (app.DATA / 'deliver-settings.json').write_text('{oops')
        self.assertEqual(app.deliver_settings(), {'remove_after_drop': False, 'auto_catch': False, 'expire_hours': 0})
        (app.DATA / 'deliver-settings.json').write_text('{"remove_after_drop": "yes", "auto_catch": true}')
        self.assertEqual(app.deliver_settings(), {'remove_after_drop': False, 'auto_catch': True, 'expire_hours': 0})
        self.assertEqual(app.set_deliver_settings(True), {'remove_after_drop': True, 'auto_catch': True, 'expire_hours': 0})

    def test_unicode_names_survive(self):
        app.add_deliver([self.make('Отчёт · 日本語.pdf')])
        self.assertEqual(app.deliver_list()[0]['name'], 'Отчёт · 日本語.pdf')

    def test_unreadable_file_is_reported_and_never_overwritten(self):
        app.DATA.mkdir(parents=True)
        (app.DATA / 'deliver.json').write_text('{not json')
        with self.assertRaises(ValueError):
            app.deliver_list()
        with self.assertRaises(ValueError):
            app.add_deliver([self.make('would-replace-it.txt')])
        with self.assertRaises(ValueError):
            app.clear_deliver()
        self.assertEqual((app.DATA / 'deliver.json').read_text(), '{not json')


class DeliverZipTests(DeliverTestCase):
    """Several files become one zip that sits on the shelf like any other file."""

    def ids(self):
        return [item['id'] for item in app.deliver_list()]

    def test_files_and_a_folder_are_packed_into_one_zip_on_the_shelf(self):
        a, b = self.make('a.txt', 'first'), self.make('b.txt', 'second')
        sub = self.folder / 'Photos'
        (sub / 'deep').mkdir(parents=True)
        (sub / 'one.jpg').write_text('jpg')
        (sub / 'deep' / 'two.jpg').write_text('jpg2')
        (self.folder / 'Empty').mkdir()
        app.add_deliver([a, b, str(sub), str(self.folder / 'Empty')])
        result = app.zip_deliver(self.ids())
        zip_path = Path(result['zip'])
        self.assertTrue(zip_path.is_file())
        self.assertEqual(result['items'][0]['path'], str(zip_path))  # the newest item on the shelf
        self.assertEqual(len(result['items']), 5)  # the originals stay on the shelf
        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
            self.assertEqual(archive.read('a.txt'), b'first')
            self.assertEqual(archive.read('Photos/deep/two.jpg'), b'jpg2')
        self.assertTrue({'a.txt', 'b.txt', 'Photos/', 'Photos/one.jpg', 'Photos/deep/', 'Empty/'} <= names)
        self.assertEqual((self.folder / 'a.txt').read_text(), 'first')

    def test_a_single_file_gets_its_own_name_and_a_group_a_dated_one(self):
        app.add_deliver([self.make('report.pdf'), self.make('other.txt')])
        single = Path(app.zip_deliver([app.deliver_list()[0]['id']])['zip'])
        self.assertEqual(single.name, 'report.pdf.zip')
        group = Path(app.zip_deliver(self.ids()[:3])['zip'])
        self.assertRegex(group.name, r'^Files \d{4}-\d\d-\d\d \d\d\.\d\d\.\d\d\.zip$')
        self.assertNotEqual(single.parent, group.parent)

    def test_files_with_the_same_name_from_different_folders_both_go_in(self):
        other = self.folder / 'other'
        other.mkdir()
        (other / 'same.txt').write_text('two')
        app.add_deliver([self.make('same.txt', 'one'), str(other / 'same.txt')])
        with zipfile.ZipFile(app.zip_deliver(self.ids())['zip']) as archive:
            self.assertEqual(sorted(archive.namelist()), ['same (2).txt', 'same.txt'])

    def test_a_file_dated_before_1980_does_not_stop_the_zip(self):
        path = self.make('ancient.txt')
        os.utime(path, (0, 0))
        app.add_deliver([path])
        with zipfile.ZipFile(app.zip_deliver(self.ids())['zip']) as archive:
            self.assertEqual(archive.namelist(), ['ancient.txt'])

    def test_missing_files_are_skipped_and_nothing_to_zip_is_an_error(self):
        gone, kept = self.make('gone.txt'), self.make('kept.txt')
        app.add_deliver([gone, kept])
        both = self.ids()
        os.remove(gone)
        with zipfile.ZipFile(app.zip_deliver(both)['zip']) as archive:
            self.assertEqual(archive.namelist(), ['kept.txt'])
        for bad in (None, [], [1], 'abc', ['no-such-id']):
            with self.assertRaises(ValueError):
                app.zip_deliver(bad)
        os.remove(kept)
        with self.assertRaises(ValueError):
            app.zip_deliver(both)

    def test_the_zip_is_deleted_when_it_leaves_the_shelf_but_other_files_never_are(self):
        original = self.make('keep.txt')
        app.add_deliver([original])
        zip_path = Path(app.zip_deliver(self.ids())['zip'])
        zip_item = next(item for item in app.deliver_list() if item['path'] == str(zip_path))
        app.remove_deliver(zip_item['id'])
        self.assertFalse(zip_path.exists())
        self.assertFalse(zip_path.parent.exists())
        app.clear_deliver()
        self.assertTrue(Path(original).exists())

    def test_clearing_the_shelf_deletes_its_zips_and_a_moved_zip_is_left_alone(self):
        app.add_deliver([self.make('a.txt')])
        first = Path(app.zip_deliver(self.ids())['zip'])
        second = Path(app.zip_deliver(self.ids()[1:])['zip'])
        moved = self.folder / 'moved.zip'
        second.rename(moved)  # a drop in Finder moved it away
        app.clear_deliver()
        self.assertFalse(first.exists())
        self.assertTrue(moved.exists())
        self.assertFalse(second.parent.exists())

    def test_a_full_shelf_leaves_no_zip_behind(self):
        app.add_deliver([self.make('a.txt')])
        app.write_deliver_items(app.read_deliver_items() + [{'id': str(n), 'path': str(self.folder), 'added': ''} for n in range(deliver.MAX_ITEMS - 1)])
        with self.assertRaises(ValueError):
            app.zip_deliver([app.read_deliver_items()[0]['id']])
        self.assertEqual(list((app.DATA / 'deliver-zips').iterdir()), [])


class DeliverExpiryTests(DeliverTestCase):
    """Items can leave the shelf by themselves after a chosen time; the files stay where they are."""

    def put(self, name, hours_ago):
        path = self.make(name)
        app.add_deliver([path])
        items = app.read_deliver_items()
        items[0]['added'] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)).isoformat()
        app.write_deliver_items(items)
        return path

    def test_the_choices_are_checked_and_kept(self):
        self.assertEqual(app.deliver_settings()['expire_hours'], 0)
        for hours in (1, 6, 24, 168, 0):
            self.assertEqual(app.set_deliver_settings(expire_hours=hours)['expire_hours'], hours)
        for bad in (2, -1, '24', 1.5, True, 10_000):
            with self.assertRaises(ValueError):
                app.set_deliver_settings(expire_hours=bad)
        self.assertEqual(app.deliver_settings()['expire_hours'], 0)
        (app.DATA / 'deliver-settings.json').write_text('{"expire_hours": 5}')
        self.assertEqual(app.deliver_settings()['expire_hours'], 0)

    def test_nothing_expires_unless_a_time_is_chosen(self):
        self.put('old.txt', 1000)
        self.assertEqual(app.expire_deliver(), [])
        self.assertEqual([item['name'] for item in app.deliver_list()], ['old.txt'])

    def test_items_older_than_the_time_leave_the_shelf_and_the_files_stay(self):
        old = self.put('old.txt', 30)
        fresh = self.put('fresh.txt', 2)
        recent = self.put('recent.txt', 0)
        app.set_deliver_settings(expire_hours=24)
        self.assertEqual(len(app.expire_deliver()), 1)
        self.assertEqual(sorted(item['name'] for item in app.deliver_list()), ['fresh.txt', 'recent.txt'])
        for path in (old, fresh, recent):
            self.assertTrue(Path(path).exists())
        app.set_deliver_settings(expire_hours=1)
        self.assertEqual(len(app.expire_deliver()), 1)
        self.assertEqual([item['name'] for item in app.deliver_list()], ['recent.txt'])

    def test_an_item_without_a_readable_time_is_never_expired(self):
        path = self.make('odd.txt')
        app.write_deliver_items([{'id': 'x', 'path': path}, {'id': 'y', 'path': path, 'added': 'not a date'}, {'id': 'z', 'path': path, 'added': None}])
        app.set_deliver_settings(expire_hours=1)
        self.assertEqual(app.expire_deliver(), [])
        self.assertEqual(len(app.read_deliver_items()), 3)

    def test_an_old_zip_is_deleted_with_its_item(self):
        app.add_deliver([self.make('a.txt')])
        zip_path = Path(app.zip_deliver([app.read_deliver_items()[0]['id']])['zip'])
        items = app.read_deliver_items()
        items[0]['added'] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).isoformat()
        app.write_deliver_items(items)
        app.set_deliver_settings(expire_hours=1)
        app.expire_deliver()
        self.assertFalse(zip_path.exists())

    def test_a_shelf_list_that_cannot_be_read_is_left_alone(self):
        app.DATA.mkdir(parents=True)
        (app.DATA / 'deliver.json').write_text('{oops')
        app.set_deliver_settings(expire_hours=1)
        self.assertEqual(app.expire_deliver(), [])
        self.assertEqual((app.DATA / 'deliver.json').read_text(), '{oops')

    def test_the_watcher_thread_lets_old_items_go(self):
        self.put('old.txt', 5)
        app.set_deliver_settings(expire_hours=1)
        app.SHUTTING_DOWN.clear()
        try:
            thread = app.watch_downloads(interval=0.02)
            for _ in range(100):
                if not app.deliver_list():
                    break
                time.sleep(0.05)
            self.assertEqual(app.deliver_list(), [])
        finally:
            app.SHUTTING_DOWN.set()
            thread.join(2)
            app.SHUTTING_DOWN.clear()


class DeliverCatchTests(DeliverTestCase):
    """Finished downloads reach the shelf by themselves when Auto-catch is on."""

    def setUp(self):
        super().setUp()
        self.downloads = Path(self.temp.name) / 'Downloads'
        self.downloads.mkdir()
        self.catcher = deliver.Catcher(app, self.downloads)

    def arrive(self, name, text='hello'):
        path = self.downloads / name
        path.write_text(text)
        return str(path)

    def shelf(self):
        return [item['name'] for item in app.deliver_list()]

    def look_twice(self):
        """Two looks: a new file is only taken once it has held still between them."""
        self.catcher.step()
        return self.catcher.step()

    def test_nothing_is_taken_until_it_is_switched_on(self):
        self.arrive('a.pdf')
        self.assertEqual(self.look_twice(), [])
        self.assertEqual(self.shelf(), [])

    def test_what_was_already_there_is_left_alone(self):
        self.arrive('old.pdf')
        app.set_deliver_settings(auto_catch=True)
        self.assertEqual(self.look_twice(), [])
        self.assertEqual(self.shelf(), [])

    def test_a_new_file_is_taken_once_it_holds_still(self):
        app.set_deliver_settings(auto_catch=True)
        self.catcher.step()
        path = self.arrive('report.pdf')
        self.assertEqual(self.catcher.step(), [])  # first seen
        self.assertEqual(self.catcher.step(), [path])  # unchanged since
        self.assertEqual(self.shelf(), ['report.pdf'])
        self.assertEqual(self.catcher.step(), [])  # and not taken twice
        self.assertEqual(self.shelf(), ['report.pdf'])

    def test_a_file_that_is_still_growing_waits(self):
        app.set_deliver_settings(auto_catch=True)
        self.catcher.step()
        path = self.arrive('big.zip', 'a')
        self.catcher.step()
        Path(path).write_text('a bit more')
        self.assertEqual(self.catcher.step(), [])
        self.assertEqual(self.catcher.step(), [path])

    def test_files_still_being_downloaded_and_hidden_ones_are_skipped(self):
        app.set_deliver_settings(auto_catch=True)
        self.catcher.step()
        for name in ('movie.mp4.crdownload', 'x.zip.DOWNLOAD', 'y.iso.part', 'z.tmp', '.DS_Store', '.hidden.pdf'):
            self.arrive(name)
        (self.downloads / 'Unpacked folder').mkdir()
        self.assertEqual(self.look_twice(), [])
        self.assertEqual(self.shelf(), [])

    def test_a_download_that_is_renamed_when_it_finishes_is_taken_then(self):
        app.set_deliver_settings(auto_catch=True)
        self.catcher.step()
        partial = Path(self.arrive('movie.mp4.crdownload', 'video'))
        self.look_twice()
        self.assertEqual(self.shelf(), [])
        partial.rename(self.downloads / 'movie.mp4')
        self.assertEqual(self.look_twice(), [str(self.downloads / 'movie.mp4')])
        self.assertEqual(self.shelf(), ['movie.mp4'])

    def test_several_files_arrive_newest_first(self):
        app.set_deliver_settings(auto_catch=True)
        self.catcher.step()
        older, newer = self.arrive('older.txt'), self.arrive('newer.txt')
        os.utime(older, ns=(1_000_000_000, 1_000_000_000))
        os.utime(newer, ns=(2_000_000_000, 2_000_000_000))
        self.assertEqual(self.look_twice(), [newer, older])
        self.assertEqual(self.shelf(), ['newer.txt', 'older.txt'])

    def test_a_file_taken_off_the_shelf_does_not_come_back(self):
        app.set_deliver_settings(auto_catch=True)
        self.catcher.step()
        self.arrive('a.txt')
        self.look_twice()
        app.clear_deliver()
        self.assertEqual(self.look_twice(), [])
        self.assertEqual(self.shelf(), [])

    def test_the_same_name_downloaded_again_later_counts_as_new(self):
        app.set_deliver_settings(auto_catch=True)
        self.catcher.step()
        path = self.arrive('a.txt')
        self.look_twice()
        app.clear_deliver()
        os.remove(path)
        self.catcher.step()
        self.arrive('a.txt', 'second time')
        os.utime(path, ns=(5_000_000_000, 5_000_000_000))
        self.assertEqual(self.look_twice(), [path])

    def test_switching_off_and_on_forgets_what_came_in_between(self):
        app.set_deliver_settings(auto_catch=True)
        self.catcher.step()
        app.set_deliver_settings(auto_catch=False)
        self.arrive('while-off.txt')
        self.assertEqual(self.look_twice(), [])
        app.set_deliver_settings(auto_catch=True)
        self.assertEqual(self.look_twice(), [])
        self.assertEqual(self.shelf(), [])

    def test_a_full_shelf_is_retried_not_forgotten(self):
        app.set_deliver_settings(auto_catch=True)
        self.catcher.step()
        app.write_deliver_items([{'id': str(number), 'path': str(self.downloads), 'added': ''} for number in range(deliver.MAX_ITEMS)])
        path = self.arrive('late.txt')
        self.assertEqual(self.look_twice(), [])
        app.clear_deliver()
        self.assertEqual(self.catcher.step(), [path])

    def test_a_folder_that_cannot_be_read_is_reported_and_recovers(self):
        app.set_deliver_settings(auto_catch=True)
        with mock.patch.object(os, 'scandir', side_effect=PermissionError):
            self.assertEqual(self.catcher.step(), [])
        self.assertEqual(self.catcher.problem, 'denied')
        with mock.patch.object(os, 'scandir', side_effect=OSError):
            self.catcher.step()
        self.assertEqual(self.catcher.problem, 'unreadable')
        self.catcher.step()
        self.assertIsNone(self.catcher.problem)

    def test_a_missing_downloads_folder_is_not_a_problem(self):
        app.set_deliver_settings(auto_catch=True)
        missing = deliver.Catcher(app, Path(self.temp.name) / 'nowhere')
        self.assertEqual(missing.step(), [])
        self.assertIsNone(missing.problem)

    def test_the_watcher_thread_does_the_looking(self):
        app.set_deliver_settings(auto_catch=True)
        old = app.catcher
        app.catcher = self.catcher
        app.SHUTTING_DOWN.clear()
        try:
            thread = app.watch_downloads(interval=0.02)
            time.sleep(0.2)  # the folder is noted
            self.arrive('thread.txt')
            for _ in range(100):
                if self.shelf():
                    break
                time.sleep(0.05)
            self.assertEqual(self.shelf(), ['thread.txt'])
        finally:
            app.SHUTTING_DOWN.set()
            thread.join(2)
            app.SHUTTING_DOWN.clear()
            app.catcher = old
        self.assertFalse(thread.is_alive())

    def test_the_engine_starts_the_watcher(self):
        self.assertIn('app.watch_downloads()', (ROOT / 'relay' / 'lifecycle.py').read_text())


class DeliverHTTPTests(DeliverTestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        super().tearDown()

    def post(self, path, body, token=None):
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method='POST',
                                         headers={'Content-Type': 'application/json', 'X-Relay-Token': app.TOKEN if token is None else token})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_round_trip_through_the_api(self):
        status, data = self.post('/api/deliver/add', {'paths': [self.make('a.txt'), self.make('b.txt')]})
        self.assertEqual(status, 201)
        self.assertEqual([item['name'] for item in data['items']], ['a.txt', 'b.txt'])
        with urllib.request.urlopen(self.base + '/api/deliver') as response:
            listed = json.loads(response.read())['items']
        self.assertEqual(listed, data['items'])
        status, data = self.post('/api/deliver/remove', {'id': listed[0]['id']})
        self.assertEqual((status, [item['name'] for item in data['items']]), (200, ['b.txt']))
        status, data = self.post('/api/deliver/clear', {})
        self.assertEqual((status, data['items']), (200, []))

    def test_several_items_and_the_setting_through_the_api(self):
        _, data = self.post('/api/deliver/add', {'paths': [self.make('a.txt'), self.make('b.txt'), self.make('c.txt')]})
        ids = [item['id'] for item in data['items']]
        status, data = self.post('/api/deliver/remove', {'ids': ids[:2]})
        self.assertEqual((status, [item['id'] for item in data['items']]), (200, ids[2:]))
        status, data = self.post('/api/deliver/settings', {'remove_after_drop': True})
        self.assertEqual((status, data['settings']), (200, {'remove_after_drop': True, 'auto_catch': False, 'expire_hours': 0}))
        with urllib.request.urlopen(self.base + '/api/deliver') as response:
            listing = json.loads(response.read())
        self.assertEqual(listing['settings'], {'remove_after_drop': True, 'auto_catch': False, 'expire_hours': 0})
        self.assertEqual([item['id'] for item in listing['items']], ids[2:])
        status, _ = self.post('/api/deliver/settings', {'remove_after_drop': 'yes'})
        self.assertEqual(status, 400)
        status, _ = self.post('/api/deliver/settings', {'remove_after_drop': False}, token='wrong')
        self.assertEqual(status, 403)
        self.assertTrue(app.deliver_settings()['remove_after_drop'])

    def test_auto_catch_is_switched_through_the_api_and_a_problem_is_reported(self):
        status, data = self.post('/api/deliver/settings', {'auto_catch': True})
        self.assertEqual((status, data['settings']), (200, {'remove_after_drop': False, 'auto_catch': True, 'expire_hours': 0}))
        status, data = self.post('/api/deliver/settings', {'remove_after_drop': True})
        self.assertEqual(data['settings'], {'remove_after_drop': True, 'auto_catch': True, 'expire_hours': 0})
        self.assertEqual(self.post('/api/deliver/settings', {'auto_catch': 'yes'})[0], 400)
        self.assertEqual(self.post('/api/deliver/settings', {})[0], 400)
        with urllib.request.urlopen(self.base + '/api/deliver') as response:
            self.assertIsNone(json.loads(response.read())['problem'])
        old = app.catcher.problem
        app.catcher.problem = 'denied'
        try:
            with urllib.request.urlopen(self.base + '/api/deliver') as response:
                self.assertEqual(json.loads(response.read())['problem'], 'denied')
        finally:
            app.catcher.problem = old

    def test_zip_and_expiry_through_the_api(self):
        _, data = self.post('/api/deliver/add', {'paths': [self.make('a.txt'), self.make('b.txt')]})
        ids = [item['id'] for item in data['items']]
        status, data = self.post('/api/deliver/zip', {'ids': ids})
        self.assertEqual(status, 201)
        self.assertTrue(data['zip'].endswith('.zip') and Path(data['zip']).is_file())
        self.assertEqual(data['items'][0]['path'], data['zip'])
        self.assertEqual(self.post('/api/deliver/zip', {'ids': []})[0], 400)
        self.assertEqual(self.post('/api/deliver/zip', {})[0], 400)
        self.assertEqual(self.post('/api/deliver/zip', {'ids': ids}, token='wrong')[0], 403)
        status, data = self.post('/api/deliver/settings', {'expire_hours': 24})
        self.assertEqual((status, data['settings']['expire_hours']), (200, 24))
        self.assertEqual(self.post('/api/deliver/settings', {'expire_hours': 7})[0], 400)
        self.assertEqual(self.post('/api/deliver/settings', {'expire_hours': 6, 'auto_catch': True})[1]['settings']['expire_hours'], 6)

    def test_changes_need_the_token(self):
        status, _ = self.post('/api/deliver/add', {'paths': [self.make('sneaky.txt')]}, token='wrong')
        self.assertEqual(status, 403)
        status, _ = self.post('/api/deliver/clear', {}, token='wrong')
        self.assertEqual(status, 403)
        self.assertEqual(app.deliver_list(), [])

    def test_bad_requests_get_a_clear_error(self):
        status, data = self.post('/api/deliver/add', {'paths': []})
        self.assertEqual(status, 400)
        self.assertIn('error', data)
        status, _ = self.post('/api/deliver/remove', {'id': 'missing'})
        self.assertEqual(status, 400)


class DeliverPanelTests(unittest.TestCase):
    """The page keeps the list; the app does the real dragging, because a web page never sees a dropped file's path."""

    def test_page_has_the_tab_and_the_shelf(self):
        html = (ROOT / 'static' / 'notch.html').read_text()
        for element in ('id="tabDeliver"', 'aria-label="Deliver"', 'id="deliver"', 'id="deliverList"', 'id="deliverAll"',
                        'id="deliverClear"', 'id="deliverCount"', 'id="deliverError"'):
            self.assertIn(element, html)
        self.assertNotIn('style="', html)
        script = (ROOT / 'static' / 'notch.js').read_text()
        self.assertIn("'deliver'", script)
        for name in ('relayDeliverDrop', 'relayDeliverDragState', 'relayDeliverDragEnded'):
            self.assertIn(f'window.{name}', script)

    def test_rows_can_be_picked_together_and_dragged_as_one_group(self):
        html = (ROOT / 'static' / 'notch.html').read_text()
        self.assertIn('id="deliverAuto"', html)
        self.assertIn('aria-pressed=', html)
        script = (ROOT / 'static' / 'notch.js').read_text()
        press = script.split('function pressRow', 1)[1].split('function clickRow', 1)[0]
        for needle in ('event.shiftKey', 'event.metaKey', 'selected.has(item.id)', 'carryOut('):
            self.assertIn(needle, press)
        # A picked row that goes away is no longer picked.
        render = script.split('function renderDeliver', 1)[1].split('async function loadDeliver', 1)[0]
        self.assertIn('selected = new Set([...selected].filter', render)

    def test_auto_catch_has_a_switch_and_says_when_the_folder_cannot_be_read(self):
        html = (ROOT / 'static' / 'notch.html').read_text()
        for element in ('id="deliverCatch"', 'id="deliverNotice"'):
            self.assertIn(element, html)
        script = (ROOT / 'static' / 'notch.js').read_text()
        self.assertIn("{ auto_catch: !deliverSettings.auto_catch }", script)
        self.assertIn("setAttribute('aria-pressed', String(!!deliverSettings.auto_catch))", script)
        for problem in ('denied', 'unreadable'):
            self.assertIn(f'{problem}:', script)
        # New downloads arrive on any tab, so the shelf is refreshed whenever Auto-catch is on.
        self.assertIn("(view === 'deliver' || deliverSettings.auto_catch || deliverSettings.expire_hours) && mode !== 'pill'", script)

    def test_zip_and_the_time_limit_have_their_controls(self):
        html = (ROOT / 'static' / 'notch.html').read_text()
        for element in ('id="deliverZip"', 'id="deliverExpire"', 'id="deliverOptionsButton"', 'id="deliverOptions"'):
            self.assertIn(element, html)
        # The folded options are reachable by keyboard and say whether they are open; the icon button has a name.
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('aria-label="Shelf options"', html)
        self.assertRegex(html, r'id="deliverOptions" class="deliver-options" hidden')
        script = (ROOT / 'static' / 'notch.js').read_text()
        zipper = script.split("$('deliverZip').addEventListener", 1)[1].split("$('deliverCatch').addEventListener", 1)[0]
        self.assertIn("post('/api/deliver/zip', { ids: picked.map(item => item.id) })", zipper)
        self.assertIn('selected.size ? ready.filter', zipper)  # the picked files, or all of them when none is picked
        self.assertIn('if (zipping || !picked.length) return;', zipper)
        self.assertIn('zipping = false;', zipper)  # whatever happens, the button is usable again
        # The choices offered match what the engine accepts.
        engine = importlib.import_module('relay.deliver')
        offered = [int(hours) for hours in re.findall(r'\[(\d+), \'', script.split('const EXPIRY', 1)[1].split('\n', 1)[0])]
        self.assertEqual(tuple(offered), engine.EXPIRY_CHOICES)

    def test_the_native_panel_keeps_only_its_warnings_in_the_log(self):
        native = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        self.assertEqual(native.count('deliver:'), 1)
        self.assertIn('the end of a drag out was never reported', native)

    def test_files_leave_the_shelf_when_they_were_moved_or_when_the_person_asked_for_that(self):
        script = (ROOT / 'static' / 'notch.js').read_text()
        ended = script.split('window.relayDeliverDragEnded', 1)[1].split('\n};', 1)[0]
        self.assertIn('accepted && ids.length && (moved || deliverSettings.remove_after_drop)', ended)
        self.assertIn("'/api/deliver/remove', { ids }", ended)
        native = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        self.assertIn('window.relayDeliverDragEnded(accepted, moved)', native)
        self.assertIn('operation != NSDragOperationNone', native)
        self.assertIn('operation & NSDragOperationMove', native)

    def test_a_drop_makes_deliver_the_tab_the_panel_comes_back_to(self):
        script = (ROOT / 'static' / 'notch.js').read_text()
        drop = script.split('window.relayDeliverDrop', 1)[1].split('window.relayDeliverDragEnded', 1)[0]
        self.assertIn("pickTab('deliver')", drop)
        self.assertIn("if (name !== 'office') chosenView = name;", script)

    def test_the_page_only_asks_the_app_to_drag_paths_from_the_shelf(self):
        script = (ROOT / 'static' / 'notch.js').read_text()
        self.assertEqual(script.count("type: 'deliverArm'"), 1)  # one helper tells the app, for a row, several rows or all
        self.assertGreaterEqual(script.count('carryOut('), 3)
        native = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        arm = native.split('isEqualToString:@"deliverArm"', 1)[1].split('\n    }', 1)[0]
        self.assertIn('hasPrefix:@"/"', arm)

    def test_native_side_takes_files_in_and_drags_them_out(self):
        native = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        for needle in ('draggingEntered:', 'performDragOperation:', 'NSPasteboardURLReadingFileURLsOnlyKey', 'beginDraggingSessionWithItems:',
                       'NSDraggingSource', 'NSDragOperationMove', 'NSPasteboardNameDrag', 'relayDeliverDrop'):
            self.assertIn(needle, native)
        # Files dragged out are never taken back in, and the panel stays while they are being carried.
        self.assertIn('RelayDragOwn', native)
        move = native.split('- (void)pointerMoved', 1)[1].split('- (void)scheduleShow', 1)[0]
        self.assertIn('self.draggingOut', move)

    def test_a_drag_with_files_over_the_notch_zone_opens_the_shelf_whatever_app_it_comes_from(self):
        native = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        self.assertIn('RelayDragCatcherView', native)
        update = native.split('- (void)updateDragCatcher', 1)[1].split('\n}\n', 1)[0]
        # The catcher is out only while the left button is held in the zone with the panel closed, so it never takes a click.
        self.assertIn('NSEvent.pressedMouseButtons & 1', update)
        self.assertIn('!self.shown', update)
        self.assertIn('orderOut', update)
        self.assertIn('openForFileDrag', native.split('- (void)buildCatcher', 1)[1])
        move = native.split('- (void)pointerMoved', 1)[1].split('- (void)scheduleShow', 1)[0]
        self.assertIn('updateDragCatcher', move)

    def test_a_lost_end_of_a_drag_out_cannot_lock_the_shelf_for_good(self):
        native = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        move = native.split('- (void)pointerMoved', 1)[1].split('- (void)scheduleShow', 1)[0]
        self.assertIn('dragOutIdleTicks', move)
        self.assertIn('self.draggingOut = NO', move)

    def test_files_promised_by_another_app_are_received_into_a_folder_of_ours(self):
        native = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        for needle in ('NSFilePromiseReceiver', 'receivePromisedFilesAtDestination:', 'NSCachesDirectory'):
            self.assertIn(needle, native)

    def test_a_file_drag_opens_the_shelf_but_a_moving_window_does_not(self):
        native = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
        move = native.split('- (void)pointerMoved', 1)[1].split('- (void)scheduleShow', 1)[0]
        self.assertIn('NSEvent.pressedMouseButtons == 0 || fileDrag', move)
        board = native.split('- (BOOL)fileDragInProgress', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('changeCount', board)
        self.assertIn('CarriesFiles(board.types)', board)
        # A drag from Finder carries paths; one from Telegram, Safari or Mail may carry only a promise of a file.
        carries = native.split('static BOOL CarriesFiles', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('NSPasteboardTypeFileURL', carries)
        self.assertIn('NSFilePromiseReceiver.readableDraggedTypes', carries)
        show = native.split('- (void)scheduleShow', 1)[1].split('- (void)scheduleHide', 1)[0]
        self.assertIn('view:@"deliver"', show)
        # The pointer holds a dragged file by its icon, so the zone that opens the shelf is larger than the hover zone.
        self.assertIn('pointerIsInDragZone', move)
        self.assertIn('pointerIsInDragZone', show)


if __name__ == '__main__':
    unittest.main()
