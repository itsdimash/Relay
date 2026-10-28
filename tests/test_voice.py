"""Talking to the notes: the Mac app listens (packaging/RelayDictation.m, the right Option key in RelayNotchPanel.m) and the
page puts the words in the note field (static/notch.js, static/js/notch-voice.js). The native side cannot be built or run
here, so its source is checked for the rules that must not be lost; the rest is run."""
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]
STATIC = ROOT / 'static'
PACKAGING = ROOT / 'packaging'
DICTATION = (PACKAGING / 'RelayDictation.m').read_text()
PANEL = (PACKAGING / 'RelayNotchPanel.m').read_text()
NOTCH = (STATIC / 'notch.js').read_text()


def run_node(body):
    script = "import * as voice from '%s';\n%s" % ((STATIC / 'js/notch-voice.js').as_posix(), body)
    result = subprocess.run(['node', '--input-type=module', '-'], input=script, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which('node'), 'Node is required for the voice checks')
class RulesTests(unittest.TestCase):
    def test_the_language_to_listen_for(self):
        result = run_node("console.log(JSON.stringify([voice.speechLocale('', 'ru'), voice.speechLocale('en', 'ru'), voice.speechLocale('ru', 'en'), voice.speechLocale(null, 'de'), voice.otherLanguage('ru-RU'), voice.otherLanguage('en-US'), voice.languageCode('ru-RU'), voice.languageCode('en-US')]));")
        self.assertEqual(result, ['ru-RU', 'en-US', 'ru-RU', 'en-US', 'en', 'ru', 'RU', 'EN'])

    def test_spoken_words_follow_what_was_typed(self):
        result = run_node("console.log(JSON.stringify([voice.joinSpeech('call', ' mom '), voice.joinSpeech('', 'mom'), voice.joinSpeech('call ', ''), voice.joinSpeech(null, null)]));")
        self.assertEqual(result, ['call mom', 'mom', 'call', ''])

    def test_saying_save_at_the_end_saves_the_note(self):
        result = run_node("""
const say = text => voice.spokenCommand(text);
console.log(JSON.stringify({
  note: say('buy milk save'),
  asTodo: say('call mom and save as to-do.'),
  addTodo: say('call mom, add it as a to-do'),
  ru: say('купить молоко сохрани'),
  ruTodo: say('позвонить маме и сохрани как дело'),
  middle: say('I need to save the file'),    // only the very end counts
  alone: say('save'),                         // nothing left to save
  plain: say('plain text')
}));""")
        self.assertEqual(result['note'], {'text': 'buy milk', 'save': 'note'})
        self.assertEqual(result['asTodo'], {'text': 'call mom', 'save': 'todo'})
        self.assertEqual(result['addTodo'], {'text': 'call mom', 'save': 'todo'})
        self.assertEqual(result['ru'], {'text': 'купить молоко', 'save': 'note'})
        self.assertEqual(result['ruTodo'], {'text': 'позвонить маме', 'save': 'todo'})
        for key in ('middle', 'alone', 'plain'):
            self.assertIsNone(result[key]['save'], key)

    def test_every_microphone_problem_has_a_message_and_a_russian_text(self):
        harness = """
import * as voice from '%s';
import vm from 'node:vm';
import fs from 'node:fs';
const store = new Map([['relay.lang', 'ru']]);
const window = { addEventListener() {}, dispatchEvent() { return true; } };
const context = { window, document: { documentElement: { lang: '' }, addEventListener() {} }, navigator: { languages: ['en-US'] },
  CustomEvent: class { constructor(t, i) { this.type = t; this.detail = i.detail; } },
  localStorage: { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) } };
vm.runInNewContext(fs.readFileSync('%s', 'utf8'), context);
vm.runInNewContext(fs.readFileSync('%s', 'utf8'), context);
const codes = ['mic-denied', 'speech-denied', 'unavailable', 'failed', 'anything else'];
const messages = codes.map(voice.voiceProblem);
const words = [...messages, 'Listening…', 'Dictate a note', 'Hold to talk, or tap to start and stop', 'Speech language', 'Enter saves a note, ⌘ Enter saves a to-do'];
console.log(JSON.stringify({ distinct: new Set(messages.slice(0, 4)).size, missing: words.filter(w => window.relayI18n.translate(w) === w) }));
""" % ((STATIC / 'js/notch-voice.js').as_posix(), (STATIC / 'i18n.js').as_posix(), (STATIC / 'i18n-ru.js').as_posix())
        result = subprocess.run(['node', '--input-type=module', '-'], input=harness, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(data['distinct'], 4)
        self.assertEqual(data['missing'], [])


class NativeTests(unittest.TestCase):
    def test_the_app_may_use_the_microphone_and_speech_recognition(self):
        plist = plistlib.loads((PACKAGING / 'Info.plist').read_bytes())
        self.assertIn('NSMicrophoneUsageDescription', plist)           # without these macOS ends the app when it asks
        self.assertIn('NSSpeechRecognitionUsageDescription', plist)
        entitlements = plistlib.loads((PACKAGING / 'RelayApp.entitlements').read_bytes())
        self.assertTrue(entitlements['com.apple.security.device.audio-input'])
        build = (ROOT / 'scripts' / 'build_macos_app.sh').read_text()
        self.assertIn('packaging/RelayDictation.m', build)
        for framework in ('Speech', 'AVFoundation'):
            self.assertIn(f'-framework {framework}', build)
        self.assertIn('--entitlements "$PROJECT_ROOT/packaging/RelayApp.entitlements" --sign "$SIGNING_IDENTITY" "$APP"', build)

    def test_the_audio_stays_on_the_mac_when_the_mac_can_do_it(self):
        self.assertIn('if (recognizer.supportsOnDeviceRecognition) request.requiresOnDeviceRecognition = YES', DICTATION)

    def test_both_permissions_are_asked_for_and_a_refusal_is_reported(self):
        self.assertIn('requestAuthorization', DICTATION)
        self.assertIn('requestAccessForMediaType:AVMediaTypeAudio', DICTATION)
        for code in ('speech-denied', 'mic-denied', 'unavailable', 'failed'):
            self.assertIn(f'@"{code}"', DICTATION)

    def test_letting_go_early_and_late_answers_are_handled(self):
        stop = DICTATION.split('- (void)stop {', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('if (!self.engine)', stop)                       # let go before the microphone opened
        self.assertIn('endAudio', stop)                                # otherwise the last words are waited for
        self.assertIn('if (session != self.session || !self.active) return;', DICTATION)  # answers of an older start are ignored
        self.assertIn('MaxListenSeconds', DICTATION)                   # Apple stops listening after about a minute

    def test_the_panel_passes_it_on(self):
        self.assertIn('isEqualToString:@"dictate"', PANEL)
        self.assertIn('@[ @"en-US", @"ru-RU" ]', PANEL)                # only languages the page offers
        self.assertIn('window.relayDictation(state, text, error)', PANEL)
        hide = PANEL.split('- (void)hideAnimated:(BOOL)animated {', 1)[1].split('\n', 2)[1]
        self.assertIn('[self.dictation cancel]', hide)                 # a hidden panel is not listening

    def test_holding_the_right_option_key_alone_means_talk(self):
        check = PANEL.split('- (void)checkVoiceKey {', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('RightOptionMask', check)
        self.assertIn('VoiceKeyHold', check)                           # a short press is just a key
        self.assertIn('kCGEventKeyDown', check)                        # Option + a letter types a character: not "talk"
        self.assertIn('kCGEventFlagMaskCommand', check)
        self.assertIn('[self checkVoiceKey]', PANEL.split('- (void)pointerMoved {', 1)[1].split('\n', 3)[1] + PANEL.split('- (void)pointerMoved {', 1)[1].split('\n', 3)[2])
        self.assertIn('window.relayVoiceKey(down)', PANEL)


class PageTests(unittest.TestCase):
    def test_the_hold_state_is_declared_before_anything_can_use_it(self):
        self.assertLess(NOTCH.index('const voice = {'), NOTCH.index('function syncHold()'))
        self.assertIn('|| voice.on ||', NOTCH)                          # the panel stays open while listening

    def test_the_microphone_button_and_the_language_switch(self):
        html = (STATIC / 'notch.html').read_text()
        for element in ('id="micButton"', 'id="voiceLang"', 'id="voiceLive"'):
            self.assertIn(element, html)
        self.assertIn("tell({ type: 'dictate', action: 'start', locale: voiceLocale() })", NOTCH)
        self.assertIn('window.relayDictation = (state, text, error)', NOTCH)
        self.assertIn('window.relayVoiceKey = down', NOTCH)
        self.assertIn('if (heard.save && heard.text) addNote(heard.save);', NOTCH)
        self.assertIn("event.key !== 'Escape'", NOTCH.split('Escape while listening', 1)[1])

    def test_nothing_is_saved_unless_the_person_says_so(self):
        done = NOTCH.split("} else if (state === 'done') {", 1)[1].split("} else if (state === 'cancelled')", 1)[0]
        self.assertEqual(done.count('addNote('), 1)                    # only after "save"
        self.assertIn('heard.save', done)

    def test_the_microphone_can_be_turned_off_in_the_window(self):
        self.assertIn('data-voice="on"', (STATIC / 'index.html').read_text())
        self.assertIn("'relay.voice'", (STATIC / 'js' / 'appearance.js').read_text())
        self.assertIn("VOICE_KEY = 'relay.voice'", (STATIC / 'js' / 'notch-voice.js').read_text())
        self.assertIn("'notch-voice'", (ROOT / 'relay' / 'http.py').read_text())   # the page may load the module

    def test_the_listening_look_is_there_and_respects_reduced_motion(self):
        css = (STATIC / 'notch.css').read_text()
        self.assertIn('.composer[data-listening]', css)
        self.assertIn('.composer-live i, .composer-mic[aria-pressed="true"]::after, .speak-bars i, .speak-stop { animation: none; }', css)


if __name__ == '__main__':
    unittest.main()
