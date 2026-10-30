"""Answers said out loud: the Mac app speaks (packaging/RelaySpeech.m, a native file that cannot be built here, so its source is
checked for the rules that must not be lost); the page decides what and when (static/js/notch-speech.js, run here)."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]
STATIC = ROOT / 'static'
PACKAGING = ROOT / 'packaging'
SPEECH = (PACKAGING / 'RelaySpeech.m').read_text()
PANEL = (PACKAGING / 'RelayNotchPanel.m').read_text()
NOTCH = (STATIC / 'notch.js').read_text()
HTML = (STATIC / 'notch.html').read_text()


def run_node(body):
    script = "import * as s from '%s';\n%s" % ((STATIC / 'js/notch-speech.js').as_posix(), body)
    result = subprocess.run(['node', '--input-type=module', '-'], input=script, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which('node'), 'Node is required for the speech checks')
class RulesTests(unittest.TestCase):
    def test_what_is_spoken_depends_on_the_setting_and_where_the_task_came_from(self):
        got = run_node("""console.log(JSON.stringify([
  [undefined, null, 'off', 'all', 'weird'].map(s.speakMode),
  [['voice', true], ['voice', false], ['all', false], ['off', true]].map(([mode, voice]) => s.shouldSpeak(mode, voice))]));""")
        self.assertEqual(got[0], ['voice', 'voice', 'off', 'all', 'voice'])    # the default speaks what was asked by voice
        self.assertEqual(got[1], [True, False, True, False])

    def test_the_voice_follows_the_language_of_the_answer(self):
        got = run_node("console.log(JSON.stringify(['Why the build fails', 'Сборка падает из-за теста', 'Fix the тест', '', '123'].map(s.languageOf)));")
        self.assertEqual(got, ['en-US', 'ru-RU', 'en-US', 'en-US', 'en-US'])

    def test_an_answer_is_made_ready_for_the_ear(self):
        got = run_node(r"""console.log(JSON.stringify([
  s.spokenForm('## Result\n\n- **Fixed** the `login` bug, see [the PR](https://x.io/pr/1) and https://x.io/a.\n\n```js\nconst a = 1;\n```\nDone.'),
  s.spokenForm('One. Two. Three. ' + 'Four is long. '.repeat(40), 20),
  s.spokenForm('word '.repeat(200), 50).length <= 50,
  s.spokenForm(null)]));""")
        self.assertEqual(got[0], 'Result Fixed the login bug, see the PR and Done.')   # no markup, no code, no addresses
        self.assertEqual(got[1], 'One. Two. Three.')                      # whole sentences, not cut in the middle
        self.assertTrue(got[2])
        self.assertEqual(got[3], '')

    def test_what_is_said_about_a_run(self):
        got = run_node("""const t = text => '[' + text + ']';
const line = (status, extra = {}) => s.lineForRun({ status, ...extra }, t);
console.log(JSON.stringify([
  line('done', { summary: 'The build fails because a test is flaky.' }), line('done'), line('awaiting_approval'), line('awaiting_clarification'),
  line('needs_attention'), line('failed'), line('building'), line('done', { demo: true }), s.lineForRun(null)]));""")
        self.assertEqual(got, ['The build fails because a test is flaky.', '[The task is finished.]', '[A plan is waiting for your approval.]',
                               '[The Observer has a few questions.]', '[The task needs your decision.]', '[The task stopped with an error.]', None, None, None])

    def test_what_is_said_about_a_reminder(self):
        got = run_node("""const t = text => text.toUpperCase();
console.log(JSON.stringify([s.lineForReminder({ title: 'call mom', detail: 'Reminder' }, t), s.lineForReminder({ title: '3 reminders', detail: 'call mom' }, t), s.lineForReminder(null)]));""")
        self.assertEqual(got, ['REMINDER. CALL MOM', '3 REMINDERS. CALL MOM', ''])

    def test_the_list_of_spoken_requests_stays_short(self):
        got = run_node("""let list = [];
for (let i = 0; i < 50; i++) list = s.remember(list, 'id' + i, 30);
console.log(JSON.stringify([list.length, list[0], list.at(-1), s.remember(['a'], 'a'), s.remember('x', 'b'), s.remember(['a'], undefined)]));""")
        self.assertEqual(got, [30, 'id20', 'id49', ['a'], ['b'], ['a']])


class NativeTests(unittest.TestCase):
    def test_it_is_built_into_the_app(self):
        self.assertIn('packaging/RelaySpeech.m', (ROOT / 'scripts' / 'build_macos_app.sh').read_text())
        self.assertIn('-framework AVFoundation', (ROOT / 'scripts' / 'build_macos_app.sh').read_text())

    def test_a_missing_voice_is_reported_not_read_in_the_wrong_language(self):
        self.assertIn('voiceWithLanguage:localeIdentifier', SPEECH)
        speak = SPEECH.split('- (void)speak:', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('@"unavailable"', speak)
        self.assertLess(speak.index('@"unavailable"'), speak.index('speakUtterance'))

    def test_a_replaced_answer_does_not_switch_the_indicator_off(self):
        speak = SPEECH.split('- (void)speak:', 1)[1].split('\n}\n', 1)[0]
        self.assertLess(speak.index('self.current = utterance'), speak.index('stopSpeakingAtBoundary'))
        self.assertGreaterEqual(SPEECH.count('utterance != self.current'), 2)      # finish and cancel of an old answer are ignored
        self.assertIn('MaxSpokenCharacters', SPEECH)

    def test_the_panel_passes_it_on_and_talking_silences_it(self):
        self.assertIn('isEqualToString:@"speak"', PANEL)
        self.assertEqual(PANEL.count('@[ @"en-US", @"ru-RU" ]'), 3)                 # dictation, speech and Hey Relay: only languages the page offers
        self.assertIn('window.relaySpeech(state)', PANEL)
        start = PANEL.split('if ([action isEqualToString:@"start"]) {', 1)[1].split('[self.dictation startWithLocale:locale]', 1)[0]
        self.assertIn('[self.speech stop]', start)                                  # the microphone must not hear the answer
        hide = PANEL.split('- (void)hideAnimated:(BOOL)animated {', 1)[1].split('\n', 2)[1]
        self.assertNotIn('speech', hide)                                            # a hidden panel still finishes its sentence


class PageTests(unittest.TestCase):
    def test_only_spoken_requests_are_followed_to_their_run(self):
        self.assertIn('createActivity({ post: postTracked, openRun })', NOTCH)
        track = NOTCH.split('async function postTracked', 1)[1].split('\n}\n', 1)[0]
        self.assertIn("'/api/queue/start'", track)
        self.assertIn('storedList(BRIEFS_KEY).includes(body?.id)', track)
        self.assertIn('saveList(BRIEFS_KEY, remember(storedList(BRIEFS_KEY), result.items?.at(-1)?.id))', NOTCH)

    def test_a_run_is_spoken_about_when_its_status_changes(self):
        announce = NOTCH.split('function announce(run) {', 1)[1].split('\nasync function poll', 1)[0]
        self.assertLess(announce.index('announced.first = false'), announce.index('speakRun(run)'))
        self.assertIn('if (run.status === announced.status) return;', announce.split('speakRun(run)', 1)[0])   # not on every poll
        self.assertNotIn('speakRun', announce.split('if (run.id !== announced.id) {', 1)[1].split('return;', 1)[0])  # not about a task already running at start

    def test_reminders_are_spoken_only_when_everything_is(self):
        self.assertIn("if (speechMode() === 'all') speak(lineForReminder(message, translated));", NOTCH)

    def test_the_person_can_silence_it(self):
        self.assertIn('id="speakStop"', HTML)
        self.assertIn("tell({ type: 'speak', action: 'stop' })", NOTCH)
        self.assertIn('stopSpeaking(); // the microphone must not hear the answer', NOTCH)
        self.assertIn("if (!speaking.on || event.key !== 'Escape') return;", NOTCH)

    def test_the_window_has_the_two_choices_and_the_page_can_load_the_module(self):
        index = (STATIC / 'index.html').read_text()
        for choice in ('data-speak="on"', 'data-speak="all"'):
            self.assertIn(choice, index)
        appearance = (STATIC / 'js' / 'appearance.js').read_text()
        self.assertIn("SPEAK_KEY = 'relay.speak'", appearance)
        self.assertIn("SPEAK_KEY = 'relay.speak'", (STATIC / 'js' / 'notch-speech.js').read_text().replace('export const ', 'const '))
        self.assertIn("'notch-speech'", (ROOT / 'relay' / 'http.py').read_text())


@unittest.skipUnless(shutil.which('node'), 'Node is required for the translation check')
class LanguageTests(unittest.TestCase):
    def test_everything_that_is_said_or_shown_has_a_russian_text(self):
        words = ['The task is finished.', 'A plan is waiting for your approval.', 'The Observer has a few questions.', 'The task needs your decision.',
                 'The task stopped with an error.', 'Reminder', 'Stop speaking', 'Stop', 'This Mac has no voice installed for that language.',
                 'Say the answers', 'A task you asked for by voice tells you its result, or that it needs you', 'Say everything', 'Also tasks you start by hand, and reminders']
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
console.log(JSON.stringify(%s.filter(w => window.relayI18n.translate(w) === w)));
""" % ((STATIC / 'i18n.js').as_posix(), (STATIC / 'i18n-ru.js').as_posix(), json.dumps(words))
        result = subprocess.run(['node', '--input-type=module', '-'], input=harness, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), [])
        # and the lines the page can say are all in the list above
        spoken = set(re.findall(r"translate\('([^']+)'\)", (STATIC / 'js' / 'notch-speech.js').read_text()))
        self.assertTrue(spoken <= set(words), spoken - set(words))
