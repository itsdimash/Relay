from http.server import ThreadingHTTPServer
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
        self.assertEqual(app.deliver_settings(), {'remove_after_drop': False, 'auto_catch': False})
        self.assertEqual(app.set_deliver_settings(True), {'remove_after_drop': True, 'auto_catch': False})
        self.assertEqual(app.deliver_settings(), {'remove_after_drop': True, 'auto_catch': False})
        for bad in ('yes', 1, None):
            with self.assertRaises(ValueError):
                app.set_deliver_settings(bad)
        self.assertTrue(app.deliver_settings()['remove_after_drop'])

    def test_each_choice_changes_alone(self):
        self.assertEqual(app.set_deliver_settings(auto_catch=True), {'remove_after_drop': False, 'auto_catch': True})
        self.assertEqual(app.set_deliver_settings(remove_after_drop=True), {'remove_after_drop': True, 'auto_catch': True})
        self.assertEqual(app.set_deliver_settings(auto_catch=False), {'remove_after_drop': True, 'auto_catch': False})
        for bad in ({'auto_catch': 'yes'}, {'auto_catch': 1}, {'remove_after_drop': True, 'auto_catch': 'no'}, {}):
            with self.assertRaises(ValueError):
                app.set_deliver_settings(**bad)
        self.assertEqual(app.deliver_settings(), {'remove_after_drop': True, 'auto_catch': False})

    def test_a_damaged_settings_file_means_the_defaults(self):
        app.DATA.mkdir(parents=True)
        (app.DATA / 'deliver-settings.json').write_text('{oops')
        self.assertEqual(app.deliver_settings(), {'remove_after_drop': False, 'auto_catch': False})
        (app.DATA / 'deliver-settings.json').write_text('{"remove_after_drop": "yes", "auto_catch": true}')
        self.assertEqual(app.deliver_settings(), {'remove_after_drop': False, 'auto_catch': True})
        self.assertEqual(app.set_deliver_settings(True), {'remove_after_drop': True, 'auto_catch': True})

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
        self.assertEqual((status, data['settings']), (200, {'remove_after_drop': True, 'auto_catch': False}))
        with urllib.request.urlopen(self.base + '/api/deliver') as response:
            listing = json.loads(response.read())
        self.assertEqual(listing['settings'], {'remove_after_drop': True, 'auto_catch': False})
        self.assertEqual([item['id'] for item in listing['items']], ids[2:])
        status, _ = self.post('/api/deliver/settings', {'remove_after_drop': 'yes'})
        self.assertEqual(status, 400)
        status, _ = self.post('/api/deliver/settings', {'remove_after_drop': False}, token='wrong')
        self.assertEqual(status, 403)
        self.assertTrue(app.deliver_settings()['remove_after_drop'])

    def test_auto_catch_is_switched_through_the_api_and_a_problem_is_reported(self):
        status, data = self.post('/api/deliver/settings', {'auto_catch': True})
        self.assertEqual((status, data['settings']), (200, {'remove_after_drop': False, 'auto_catch': True}))
        status, data = self.post('/api/deliver/settings', {'remove_after_drop': True})
        self.assertEqual(data['settings'], {'remove_after_drop': True, 'auto_catch': True})
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
        self.assertIn("(view === 'deliver' || deliverSettings.auto_catch) && mode !== 'pill'", script)

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
