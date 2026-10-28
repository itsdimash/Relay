"""Reminders in the notch notes: the engine keeps the time (relay/notes.py), the page reads it from the words and announces it
(static/js/notch-reminders.js), and the app opens the small panel on the Notes (packaging/RelayNotchPanel.m)."""
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).parents[1]
STATIC = ROOT / 'static'
SPEC = importlib.util.spec_from_file_location('relay_server', ROOT / 'server.py')
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)
app = server.application


def stamp(minutes):
    return int(time.time() * 1000) + minutes * 60000


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data = app.DATA
        app.DATA = Path(self.temp.name) / 'data'

    def tearDown(self):
        app.DATA = self.old_data
        self.temp.cleanup()

    def make_due(self, note_id):
        notes = app.read_notes()
        next(item for item in notes if item['id'] == note_id)['due'] = stamp(-5)
        app.write_notes(notes)

    def test_a_note_keeps_its_time_and_a_plain_note_has_none(self):
        app.add_note('plain', 'note')
        notes = app.add_note('call mom', 'todo', stamp(30))
        self.assertNotIn('due', notes[1])
        self.assertIsInstance(notes[0]['due'], int)
        self.assertFalse(notes[0]['reminded'])
        self.assertEqual(app.read_notes(), notes)

    def test_bad_times_are_refused(self):
        for bad in (stamp(-10), stamp(60 * 24 * 400), 'tomorrow', 1.5, True, -1):
            with self.assertRaises(ValueError, msg=repr(bad)):
                app.add_note('x', 'note', bad)
        self.assertEqual(app.read_notes(), [])

    def test_nothing_is_due_until_its_time_comes(self):
        app.add_note('later', 'note', stamp(30))
        app.add_note('no time', 'note')
        self.assertEqual(app.due_reminders(), [])

    def test_a_due_note_is_reported_until_it_is_marked(self):
        note_id = app.add_note('call mom', 'note', stamp(30))[0]['id']
        self.make_due(note_id)
        due = app.due_reminders()
        self.assertEqual([(item['id'], item['text']) for item in due], [(note_id, 'call mom')])
        self.assertEqual(app.due_reminders(), due)               # asking twice does not consume it
        notes = app.mark_reminded([note_id])
        self.assertTrue(notes[0]['reminded'])
        self.assertEqual(app.due_reminders(), [])
        app.mark_reminded([note_id])                             # marking again is harmless
        self.assertEqual(len(app.read_notes()), 1)

    def test_a_ticked_off_todo_does_not_remind(self):
        note_id = app.add_note('pay rent', 'todo', stamp(30))[0]['id']
        self.make_due(note_id)
        app.set_note_done(note_id, True)
        self.assertEqual(app.due_reminders(), [])

    def test_snooze_sets_a_new_time_and_the_reminder_goes_off_again(self):
        note_id = app.add_note('call mom', 'note', stamp(30))[0]['id']
        self.make_due(note_id)
        app.mark_reminded([note_id])
        before = int(time.time() * 1000)
        note = app.snooze_note(note_id, 10)[0]
        self.assertFalse(note['reminded'])
        self.assertTrue(before + 10 * 60000 <= note['due'] <= int(time.time() * 1000) + 10 * 60000)
        self.assertEqual(app.due_reminders(), [])               # quiet until the ten minutes are over
        self.make_due(note_id)
        self.assertEqual([item['id'] for item in app.due_reminders()], [note_id])

    def test_snooze_checks_what_it_is_given(self):
        plain = app.add_note('plain', 'note')[0]['id']
        for note_id, minutes in ((plain, 10), ('missing', 10)):
            with self.assertRaises(ValueError):
                app.snooze_note(note_id, minutes)
        timed = app.add_note('timed', 'note', stamp(5))[0]['id']
        for bad in (0, -5, 24 * 60 + 1, '10', 1.5, True, None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                app.snooze_note(timed, bad)

    def test_marking_checks_what_it_is_given(self):
        for bad in ('abc', [1], None, ['x'] * 51):
            with self.assertRaises(ValueError):
                app.mark_reminded(bad)
        self.assertEqual(app.mark_reminded(['missing']), [])     # an unknown id changes nothing

    def test_a_broken_notes_file_does_not_stop_the_poll(self):
        app.DATA.mkdir(parents=True)
        (app.DATA / 'notes.json').write_text('{not json')
        self.assertEqual(app.due_reminders(), [])


class HTTPTests(unittest.TestCase):
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

    def post(self, path, body):
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method='POST',
                                         headers={'Content-Type': 'application/json', 'X-Relay-Token': app.TOKEN})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def poll(self):
        with urllib.request.urlopen(self.base + '/api/notch') as response:
            return json.loads(response.read())

    def test_the_poll_carries_due_reminders_until_they_are_marked(self):
        self.assertEqual(self.poll()['reminders'], [])
        status, data = self.post('/api/notes/add', {'text': 'standup', 'kind': 'note', 'due': stamp(30)})
        self.assertEqual(status, 201)
        note_id = data['notes'][0]['id']
        notes = app.read_notes()
        notes[0]['due'] = stamp(-1)
        app.write_notes(notes)
        self.assertEqual([item['id'] for item in self.poll()['reminders']], [note_id])
        status, data = self.post('/api/notes/reminded', {'ids': [note_id]})
        self.assertEqual((status, data['notes'][0]['reminded']), (200, True))
        self.assertEqual(self.poll()['reminders'], [])

    def test_snoozing_through_the_api(self):
        note_id = self.post('/api/notes/add', {'text': 'standup', 'kind': 'note', 'due': stamp(30)})[1]['notes'][0]['id']
        status, data = self.post('/api/notes/snooze', {'id': note_id, 'minutes': 10})
        self.assertEqual((status, data['notes'][0]['reminded']), (200, False))
        self.assertEqual(self.post('/api/notes/snooze', {'id': note_id, 'minutes': 0})[0], 400)

    def test_a_past_time_gets_a_clear_error(self):
        status, data = self.post('/api/notes/add', {'text': 'late', 'kind': 'note', 'due': stamp(-120)})
        self.assertEqual(status, 400)
        self.assertIn('passed', data['error'])


HARNESS = """
import { parseReminder, dueLabel, createReminderWatcher, quickChoices, startingMoment, stepMoment, canSet, dayLabel, hourText, minuteText } from '%s';
const now = new Date(2026, 9, 29, 15, 0, 0).getTime();   // Thursday 29 October 2026, 15:00 in the Mac's own zone
const when = (day, hour, minute = 0) => new Date(2026, 9, day, hour, minute).getTime();
%s
"""


def run_node(body):
    script = HARNESS % ((STATIC / 'js/notch-reminders.js').as_posix(), body)
    result = subprocess.run(['node', '--input-type=module', '-'], input=script, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which('node'), 'Node is required for the reminder checks')
class ReadingTimesTests(unittest.TestCase):
    def test_english_and_russian_phrases(self):
        cases = {
            'call mom in 30 min': ('call mom', 'now + 30 * 60000'),
            'in 2 hours check the build': ('check the build', 'now + 120 * 60000'),
            'in 1h30 stand up': ('stand up', 'now + 90 * 60000'),
            'tea in half an hour': ('tea', 'now + 30 * 60000'),
            'tomorrow at 9:00 send report': ('send report', 'when(30, 9)'),
            'send report tomorrow 9:00': ('send report', 'when(30, 9)'),
            'gym tomorrow at 9am': ('gym', 'when(30, 9)'),
            'today at 17:30 dinner': ('dinner', 'when(29, 17, 30)'),
            'remind me to pay rent on friday at 18:00': ('pay rent', 'when(30, 18)'),
            'homework after 10 min': ('homework', 'now + 10 * 60000'),
            'after half an hour tea': ('tea', 'now + 30 * 60000'),
            'через 30 мин позвонить': ('позвонить', 'now + 30 * 60000'),
            'через полчаса чай': ('чай', 'now + 30 * 60000'),
            'созвон через 2 часа': ('созвон', 'now + 120 * 60000'),
            'через 1 час 30 минут отчёт': ('отчёт', 'now + 90 * 60000'),
            'завтра в 9:00 отчёт': ('отчёт', 'when(30, 9)'),
            'отчёт завтра в 9': ('отчёт', 'when(30, 9)'),
            'напомни мне позвонить маме завтра в 8 утра': ('позвонить маме', 'when(30, 8)'),
            'в 11 ночи спать': ('спать', 'when(29, 23)'),
            'в 2 дня обед': ('обед', 'when(30, 14)'),
            'в пятницу в 18:00 футбол': ('футбол', 'when(30, 18)'),
        }
        lines = ',\n'.join(f'{json.dumps(text)}: (() => {{ const r = parseReminder({json.dumps(text)}, now); return r && [r.text, r.due === ({expected})]; }})()'
                           for text, (_, expected) in cases.items())
        result = run_node(f'console.log(JSON.stringify({{ {lines} }}));')
        for text, (note, _) in cases.items():
            self.assertEqual(result[text], [note, True], text)

    def test_a_lone_time_depends_on_the_hour(self):
        result = run_node("""
const at = (text, current) => { const r = parseReminder(text, current); return r && r.due; };
console.log(JSON.stringify({
  soon: at('meet at 5', now) === when(29, 17),                // 15:00, so 5 means five in the evening
  far: at('wake at 7', now) === when(30, 7),                  // too far to be this evening: tomorrow morning
  nine: at('at 9:00 standup', now) === when(30, 9),
  later: at('call at 18:00', now) === when(29, 18),
  evening: at('в 9 вечера кино', now) === when(29, 21),
  monday: at('monday at 9', now) === new Date(2026, 10, 2, 9).getTime(),
  nextWeek: at('thursday at 10', now) === new Date(2026, 10, 5, 10).getTime(),
  sameDay: at('thursday at 16:00', now) === when(29, 16)
}));""")
        self.assertEqual(result, {key: True for key in result}, result)

    def test_ordinary_notes_are_left_alone(self):
        result = run_node("""
const texts = ['buy milk tomorrow', 'ratio 3:30 is fine', 'I have 2 apples', 'tomorrow 2 apples', 'meeting at 25:00', 'in 0 min', 'in 400 days', 'Call at 9:75', 'через пять минут', ''];
console.log(JSON.stringify(texts.map(text => parseReminder(text, now))));""")
        self.assertEqual(result, [None] * 10)

    def test_a_note_that_is_only_a_time_keeps_its_words(self):
        result = run_node("const r = parseReminder('in 10 minutes', now); console.log(JSON.stringify([r.text, r.due === now + 600000]));")
        self.assertEqual(result, ['in 10 minutes', True])

    def test_the_ready_made_times(self):
        result = run_node("""
const ids = now2 => quickChoices(now2).map(c => c.id).join(',');
const week = quickChoices(now).find(c => c.id === 'week');
console.log(JSON.stringify({
  afternoon: ids(now),
  lateEvening: ids(when(29, 22)),                                 // 18:00 has gone by: no "Tonight"
  almostSix: ids(when(29, 17, 30)),                               // less than an hour away: no "Tonight" either
  tonight: quickChoices(now).find(c => c.id === 'tonight').at === when(29, 18),
  tomorrow: quickChoices(now).find(c => c.id === 'tomorrow').at === when(30, 9),
  monday: week.at === new Date(2026, 10, 2, 9).getTime(),         // the coming Monday, 2 November
  mondayOnMonday: quickChoices(new Date(2026, 10, 2, 8).getTime()).find(c => c.id === 'week').at === new Date(2026, 10, 9, 9).getTime(),
  relative: quickChoices(now).filter(c => c.minutes).map(c => c.minutes)
}));""".replace('import', ''))
        self.assertEqual(result['afternoon'], 'in10,in30,in60,in180,tonight,tomorrow,week')
        self.assertEqual(result['lateEvening'], 'in10,in30,in60,in180,tomorrow,week')
        self.assertEqual(result['almostSix'], 'in10,in30,in60,in180,tomorrow,week')
        for key in ('tonight', 'tomorrow', 'monday', 'mondayOnMonday'):
            self.assertTrue(result[key], key)
        self.assertEqual(result['relative'], [10, 30, 60, 180])

    def test_the_time_steppers(self):
        result = run_node("""
const start = startingMoment(now);                                // 15:00 -> 16:00 today
const text = ms => `${dayLabel(ms, now)} ${hourText(ms)}:${minuteText(ms)}`;
console.log(JSON.stringify({
  start: text(start),
  hour: text(stepMoment(start, 'hour', 1, now)),
  wrap: text(stepMoment(when(29, 23), 'hour', 1, now)),           // 23 -> 00 stays on the same day
  minute: text(stepMoment(start, 'minute', 1, now)),
  minuteBack: text(stepMoment(start, 'minute', -1, now)),         // 16:00 -> 16:55, still the 16th hour
  nextDay: text(stepMoment(start, 'day', 1, now)),
  noPast: text(stepMoment(start, 'day', -1, now)),                // never before today
  far: text(stepMoment(start, 'day', 3, now)),
  tooFar: stepMoment(new Date(2027, 10, 20, 9).getTime(), 'day', 1, now) === new Date(2027, 10, 20, 9).getTime(),
  can: [canSet(now + 10000, now), canSet(now + 60000, now), canSet(now + 400 * 86400000, now)],
  late: startingMoment(when(29, 23, 50)) === new Date(2026, 9, 30, 1).getTime()
}));""")
        self.assertEqual(result['start'], 'Today 16:00')
        self.assertEqual(result['hour'], 'Today 17:00')
        self.assertEqual(result['wrap'], 'Today 00:00')
        self.assertEqual(result['minute'], 'Today 16:05')
        self.assertEqual(result['minuteBack'], 'Today 16:55')
        self.assertEqual(result['nextDay'], 'Tomorrow 16:00')
        self.assertEqual(result['noPast'], 'Today 16:00')
        self.assertEqual(result['far'], '01.11 16:00')
        self.assertTrue(result['tooFar'])
        self.assertEqual(result['can'], [False, True, False])
        self.assertTrue(result['late'])

    def test_labels(self):
        result = run_node("console.log(JSON.stringify([dueLabel(when(29, 17, 5), now), dueLabel(when(30, 9), now), dueLabel(new Date(2026, 10, 3, 9).getTime(), now)]));")
        self.assertEqual(result, ['17:05', 'Tomorrow 09:00', '03.11 09:00'])

    def test_each_reminder_is_said_once_and_the_engine_is_told_until_it_answers(self):
        result = run_node("""
const said = [], told = [];
let fails = 1;
const watcher = createReminderWatcher({ announce: m => said.push(m), acknowledge: ids => { told.push(ids); if (fails-- > 0) throw new Error('offline'); } });
const one = [{ id: 'a', text: 'call mom', due: 1 }];
watcher.update(one);
await new Promise(r => setTimeout(r, 10));
watcher.update(one);                                   // still listed: not said again, but the engine is told again
await new Promise(r => setTimeout(r, 10));
watcher.update([]);                                    // taken by the engine
watcher.update([{ id: 'a', text: 'call mom', due: 1 }]); // the same id coming back later is a new reminder
watcher.update([{ id: 'a', text: 'call mom', due: 1 }, { id: 'b', text: 'x'.repeat(100), due: 1 }]);
watcher.update([{ id: 'c', text: 'one', due: 1 }, { id: 'd', text: 'two', due: 1 }]);
console.log(JSON.stringify({ said, told }));""")
        self.assertEqual([m['title'] for m in result['said']][:1], ['call mom'])
        self.assertEqual(result['said'][0]['kind'], 'reminder')
        self.assertEqual(len(result['said']), 4)                              # a, a again after it was taken, b, then c and d together
        self.assertEqual(len(result['said'][2]['title']), 60)                 # a long note is shortened
        self.assertTrue(result['said'][2]['title'].endswith('…'))
        self.assertEqual(result['said'][3], {'kind': 'reminder', 'title': '2 reminders', 'detail': 'one'})
        self.assertEqual(result['told'][0], ['a'])
        self.assertEqual(result['told'][1], ['a'])


@unittest.skipUnless(shutil.which('node'), 'Node is required for the language check')
class WordsTests(unittest.TestCase):
    def test_everything_the_panel_says_about_reminders_has_a_russian_text(self):
        harness = """
import vm from 'node:vm';
import fs from 'node:fs';
const store = new Map([['relay.lang', 'ru']]);
const window = { addEventListener() {}, dispatchEvent() { return true; } };
const context = { window, document: { documentElement: { lang: '' }, addEventListener() {} }, navigator: { languages: ['en-US'] },
  CustomEvent: class { constructor(t, i) { this.type = t; this.detail = i.detail; } },
  localStorage: { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) } };
vm.runInNewContext(fs.readFileSync('%s', 'utf8'), context);
vm.runInNewContext(fs.readFileSync('%s', 'utf8'), context);
const said = ['Set a reminder', 'Remove reminder', 'In 10 min', 'In 30 min', 'In 1 hour', 'In 3 hours', 'Tonight', 'Tomorrow', 'Today', 'Next week', 'Set',
  'Earlier day', 'Later day', 'Earlier hour', 'Later hour', 'Fewer minutes', 'More minutes', 'Reminder', '+10 min', 'Snooze 10 minutes', 'Snooze: call mom', 'Reminder · 17:30', 'Reminder · Tomorrow 09:00', 'Reminder · 03.11 09:00', 'Tomorrow 09:00', '2 reminders', '5 reminders',
  'note', 'to-do', 'Try “call mom in 30 min” and Relay will remind you.'];
console.log(JSON.stringify(said.filter(text => window.relayI18n.translate(text) === text)));
console.log(JSON.stringify(['Reminder · Tomorrow 09:00', '2 reminders', '5 reminders', '21 reminders'].map(text => window.relayI18n.translate(text))));
""" % ((STATIC / 'i18n.js').as_posix(), (STATIC / 'i18n-ru.js').as_posix())
        result = subprocess.run(['node', '-'], input=harness, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        missing, sample = [json.loads(line) for line in result.stdout.strip().splitlines()[-2:]]
        self.assertEqual(missing, [])
        self.assertEqual(sample[0], 'Напоминание · Завтра 09:00')
        self.assertEqual(sample[1], 'Напоминаний: 2')


class WiringTests(unittest.TestCase):
    NOTCH = (STATIC / 'notch.js').read_text()
    PANEL = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
    HTTP = (ROOT / 'relay' / 'http.py').read_text()

    def test_the_panel_parses_what_is_typed_and_shows_the_time(self):
        self.assertIn('parseReminder(typed)', self.NOTCH)
        self.assertIn('due: reminder.due', self.NOTCH)
        self.assertIn("addEventListener('input', showNoteHint)", self.NOTCH)
        self.assertIn('dueLabel(note.due)', self.NOTCH)
        self.assertIn('id="noteHint"', (STATIC / 'notch.html').read_text())

    def test_a_due_reminder_opens_the_small_panel_on_the_notes(self):
        self.assertIn('reminderWatcher.update(data.reminders)', self.NOTCH)
        self.assertIn("tell({ type: 'reminder' })", self.NOTCH)
        self.assertIn("reminder: { icon: 'bell' }", self.NOTCH)
        self.assertIn('isEqualToString:@"reminder"', self.PANEL)
        peek = self.PANEL.split('- (void)peekReminder', 1)[1].split('}', 1)[0]
        self.assertIn('@"notes"', peek)
        self.assertIn("'notch-reminders'", self.HTTP)                    # the page may load the module

    def test_a_gone_off_reminder_has_a_snooze_button(self):
        self.assertIn("'/api/notes/snooze', { id: note.id, minutes: 10 }", self.NOTCH)
        self.assertIn('note.reminded && !note.done', self.NOTCH)
        self.assertIn('.note-snooze', (STATIC / 'notch.css').read_text())

    def test_the_picker_beside_the_field(self):
        html = (STATIC / 'notch.html').read_text()
        for element in ('id="remindButton"', 'id="remindPop"', 'id="remindQuick"', 'id="remindSet"', 'data-field="day"', 'data-field="hour"', 'data-field="minute"'):
            self.assertIn(element, html)
        self.assertIn('const picked = pendingDue()', self.NOTCH)           # a picked time wins over the words
        self.assertIn('pending = null;', self.NOTCH)                       # and is forgotten once the note is saved
        self.assertIn('setRemind(false);\n  if (ask.resizing)', self.NOTCH)       # a freshly shown panel starts with it closed
        self.assertIn("event.key !== 'Escape'", self.NOTCH)
        self.assertIn('overflow: clip', (STATIC / 'notch.css').read_text())  # focus can no longer slide the page sideways

    def test_the_toast_has_its_colour(self):
        css = (STATIC / 'notch.css').read_text()
        self.assertIn('.toast[data-kind="reminder"]', css)
        self.assertIn('.panel[data-flash="reminder"]', css)
        self.assertIn('.note-due', css)


if __name__ == '__main__':
    unittest.main()
