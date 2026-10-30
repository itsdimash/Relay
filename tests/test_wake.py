"""Saying "Hey Relay" anywhere: packaging/RelayWake.m listens all the time (only when the person turned it on) and the page
(static/notch.js) handles what was said. The native side cannot be built or run here, so its source is checked for the
rules that must not be lost (nothing leaves the Mac, nothing is kept, it waits while the microphone or the speakers are in
use), and the wake phrases it accepts are run in Node from the very patterns in the source."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]
STATIC = ROOT / 'static'
PACKAGING = ROOT / 'packaging'
WAKE = (PACKAGING / 'RelayWake.m').read_text()
PANEL = (PACKAGING / 'RelayNotchPanel.m').read_text()
NOTCH = (STATIC / 'notch.js').read_text()
INDEX = (STATIC / 'index.html').read_text()


def node(script):
    result = subprocess.run(['node', '--input-type=module', '-'], input=script, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout.strip().splitlines()[-1])


def pattern_parts():
    """The two wake phrase patterns, as written in the Objective-C source (its string escapes undone)."""
    found = {}
    for name in ('english', 'russian'):
        literal = re.search(r'NSString \*%s = @"((?:[^"\\]|\\.)*)";' % name, WAKE).group(1)
        found[name] = literal.replace('\\\\', '\\')
    return found


class NativeTests(unittest.TestCase):
    def test_nothing_leaves_the_mac(self):
        self.assertIn('requiresOnDeviceRecognition = YES', WAKE)
        self.assertNotIn('requiresOnDeviceRecognition = NO', WAKE)
        self.assertIn('supportsOnDeviceRecognition', WAKE)              # no on-device recognizer: it refuses, it does not fall back
        self.assertIn('@"ondevice"', WAKE)

    def test_nothing_is_recorded(self):
        for forbidden in ('AVAudioFile', 'writeToURL', 'writeToFile', 'AVAudioRecorder', 'NSFileHandle'):
            self.assertNotIn(forbidden, WAKE)

    def test_both_permissions_are_asked_for_and_a_refusal_is_reported(self):
        self.assertIn('requestAuthorization', WAKE)
        self.assertIn('requestAccessForMediaType:AVMediaTypeAudio', WAKE)
        for code in ('speech-denied', 'mic-denied', 'unavailable', 'ondevice', 'failed'):
            self.assertIn(f'@"{code}"', WAKE)

    def test_the_listener_is_part_of_the_app(self):
        self.assertIn('packaging/RelayWake.m', (ROOT / 'scripts' / 'build_macos_app.sh').read_text())
        self.assertTrue((PACKAGING / 'RelayWake.h').exists())

    def test_it_waits_while_the_microphone_or_the_speakers_are_busy(self):
        self.assertIn('- (void)pause', WAKE)
        self.assertIn('- (void)resume', WAKE)
        update = PANEL.split('- (void)updateWakePause {', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('self.wakeDictating', update)
        self.assertIn('self.wakeSpeaking', update)
        self.assertIn('[self.wake pause]', update)
        self.assertIn('[self.wake resume]', update)
        self.assertIn('self.wakeDictating = YES;', PANEL)
        self.assertIn('self.wakeDictating = NO;', PANEL)
        self.assertIn('self.wakeSpeaking = YES;', PANEL)
        self.assertIn('self.wakeSpeaking = NO;', PANEL)

    def test_the_panel_starts_it_only_when_the_page_asks_and_only_for_known_languages(self):
        handler = PANEL.split('isEqualToString:@"wake"]', 1)[1].split('isEqualToString:@"speak"]', 1)[0]
        self.assertIn('@[ @"en-US", @"ru-RU" ]', handler)
        self.assertIn("[body[@\"on\"] boolValue]", handler)
        self.assertIn('[self.wake stop]', handler)
        self.assertIn('window.relayWake(state, text, error)', PANEL)
        self.assertEqual(PANEL.count('[self.wake startWithLocale:'), 1)   # only here: never at launch

    def test_the_text_is_cut_to_a_sensible_length(self):
        self.assertIn('MaxRequestLength', WAKE)

    def test_the_microphone_is_given_back_when_it_stops(self):
        self.assertIn('- (void)teardownAudio', WAKE)
        stop = WAKE.split('- (void)stop {', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('teardownAudio', stop)
        self.assertIn('AVAudioEngineConfigurationChangeNotification', WAKE)   # a new input device (headphones) restarts it

    def test_the_microphone_texts_mention_it(self):
        plist = (PACKAGING / 'Info.plist').read_text()
        self.assertIn('Hey Relay', plist)


@unittest.skipUnless(shutil.which('node'), 'Node is required for the wake phrase checks')
class PhraseTests(unittest.TestCase):
    def matches(self, phrases):
        parts = pattern_parts()
        source = r'(?<![\p{L}\p{N}])(?:%s|%s)(?![\p{L}\p{N}])' % (parts['english'], parts['russian'])
        script = 'const re = new RegExp(%s, "iu");\nconsole.log(JSON.stringify(%s.map(p => re.test(p))));' % (json.dumps(source), json.dumps(phrases))
        return node(script)

    def test_the_ways_it_is_said_and_written(self):
        said = ['Hey Relay', 'hey relay, translate this', 'Hey, Relay! open music', 'okay relay', 'Hi Relay',
                'Эй, Релей', 'эй релей открой музыку', 'Привет, Релей', 'Окей Релей', 'Хей релей']
        self.assertEqual(self.matches(said), [True] * len(said))

    def test_ordinary_talk_does_not_wake_it(self):
        ordinary = ['I will relay the message', 'hey there', 'relay', 'the relay race', 'they relay', 'hey relayed', 'привет всем',
                    'релей', 'okay relayout', 'oh hey relayers']
        self.assertEqual(self.matches(ordinary), [False] * len(ordinary))

    def test_the_problem_messages(self):
        script = """import * as voice from '%s';
const codes = ['ondevice', 'mic-denied', 'speech-denied', 'unavailable', 'failed'];
console.log(JSON.stringify({ ondevice: voice.wakeProblem('ondevice'), others: codes.slice(1).map(c => voice.wakeProblem(c) === voice.voiceProblem(c)), key: voice.WAKE_KEY }));
""" % (STATIC / 'js/notch-voice.js').as_posix()
        data = node(script)
        self.assertIn('runs on this Mac', data['ondevice'])
        self.assertEqual(data['others'], [True] * 4)
        self.assertEqual(data['key'], 'relay.wake')


class PageTests(unittest.TestCase):
    def test_it_starts_off_and_only_an_explicit_on_enables_it(self):
        self.assertIn("readStored(WAKE_KEY) === 'on'", NOTCH)
        appearance = (STATIC / 'js' / 'appearance.js').read_text()
        self.assertIn("read(WAKE_KEY) === 'on'", appearance)
        self.assertIn("WAKE_KEY = 'relay.wake'", appearance)
        self.assertIn('data-wake="on"', INDEX)
        self.assertIn('aria-checked="false" data-wake="on"', INDEX)

    def test_it_needs_the_microphone_feature_to_be_on(self):
        enabled = NOTCH.split('const wakeEnabled = () =>', 1)[1].split('\n', 1)[0]
        self.assertIn('voiceEnabled()', enabled)

    def test_the_app_is_told_when_the_choice_or_language_changes(self):
        self.assertIn("tell({ type: 'wake', on, locale: voiceLocale() })", NOTCH)
        storage = [part.split('\n});', 1)[0] for part in NOTCH.split("window.addEventListener('storage'")[1:] if 'WAKE_KEY' in part.split('\n});', 1)[0]]
        self.assertEqual(len(storage), 1)
        self.assertIn('syncWake()', storage[0])
        self.assertIn('syncWake()', NOTCH.split("for (const id of ['voiceLang', 'trVoiceLang']) {", 1)[1].split('\n  });', 1)[0])   # either language button
        self.assertIn('syncWake()', NOTCH.split("window.addEventListener('relaylangchange'", 1)[1].split('\n', 1)[0])

    def test_a_request_is_a_command_or_a_note_that_is_saved_only_when_asked(self):
        handler = NOTCH.split('window.relayWake = (state, text, error) => {', 1)[1].split('\nsyncWake();', 1)[0]
        command = handler.split("state === 'command'", 1)[1].split("state === 'error'", 1)[0]
        self.assertIn('routeCommand(spoken)', command)
        self.assertIn('runCommand(command)', command)
        self.assertEqual(command.count('addNote('), 1)
        self.assertIn('heard.save', command)
        self.assertIn('if (!wakeEnabled()) return;', handler)           # a late word after it was turned off is ignored
        self.assertIn('if (voice.on) return;', handler)                 # the microphone button wins

    def test_the_choice_made_in_the_window_reaches_a_hidden_panel(self):
        self.assertIn('setInterval(syncWake, 2000)', NOTCH)                  # the window and the panel are separate pages
        mode = NOTCH.split('window.relayPanelMode', 1)[1].split('applyTabs();', 1)[0]
        self.assertIn('syncWake()', mode)                                    # and whenever the panel appears

    def test_it_says_when_it_is_on_and_why_when_it_cannot_listen(self):
        handler = NOTCH.split('window.relayWake = (state, text, error) => {', 1)[1].split('\nsyncWake();', 1)[0]
        ready = handler.split("state === 'ready'", 1)[1].split("state === 'heard'", 1)[0]
        self.assertIn("toast('done', 'Hey Relay is on'", ready)
        problem = handler.split("state === 'error'", 1)[1]
        self.assertIn("toast('failed', 'Hey Relay is off', message)", problem)
        self.assertNotIn('document.hidden', problem)                         # a problem is shown even when the panel was hidden
        self.assertIn('@"ready"', WAKE)

    def test_recognition_that_keeps_failing_at_once_is_reported_not_looped(self):
        self.assertIn('self.quickFailures >= 5', WAKE)
        self.assertIn('[RelayNowPlaying log:', WAKE)
        self.assertNotIn('formattedString]', WAKE.split('RelayNowPlaying log:', 1)[1].split(']];', 1)[0])   # what was said is never written to the log

    def test_a_problem_is_shown_and_the_listening_look_ends(self):
        handler = NOTCH.split('window.relayWake = (state, text, error) => {', 1)[1].split('\nsyncWake();', 1)[0]
        problem = handler.split("state === 'error'", 1)[1]
        self.assertIn('wakeProblem(error)', problem)
        self.assertIn('endWake()', problem)
        self.assertIn('wake.hearing', NOTCH.split('function paintVoice()', 1)[1].split('\n}\n', 1)[0])

    def test_the_russian_texts_exist(self):
        # the dictionary is plain text: check the entries are present without needing a browser
        ru = (STATIC / 'i18n-ru.js').read_text()
        for english in ('"Hey Relay":', '"Say “Hey Relay” anywhere', '"Hey Relay needs speech recognition'):
            self.assertIn(english, ru)


if __name__ == '__main__':
    unittest.main()
