"""Opening an app, typing into another app, and a Telegram draft by voice.
The words are read by a pure module, so they are run; the page and the Mac app are checked in the source."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]
STATIC = ROOT / 'static'
NOTCH = (STATIC / 'notch.js').read_text()
HTML = (STATIC / 'notch.html').read_text()
PANEL = (ROOT / 'packaging' / 'RelayNotchPanel.m').read_text()
ACTIONS = (ROOT / 'packaging' / 'RelayActions.m').read_text()
HEADER = (ROOT / 'packaging' / 'RelayActions.h').read_text()
BUILD = (ROOT / 'scripts' / 'build_macos_app.sh').read_text()


def run_node(body):
    script = "import * as c from '%s';\n%s" % ((STATIC / 'js/notch-commands.js').as_posix(), body)
    result = subprocess.run(['node', '--input-type=module', '-'], input=script, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout.strip().splitlines()[-1])


def route(*phrases):
    return run_node('console.log(JSON.stringify(%s.map(c.routeCommand)));' % json.dumps(list(phrases), ensure_ascii=False))


@unittest.skipUnless(shutil.which('node'), 'Node is required for the command checks')
class RouterTests(unittest.TestCase):
    def test_an_app_is_opened_by_the_name_it_was_called(self):
        got = route('open Safari', 'Open the Telegram app', 'launch Slack please', 'открой телеграм', 'запусти Хром', 'открой настройки', 'launch Visual Studio Code')
        self.assertTrue(all(item['kind'] == 'app' for item in got))
        self.assertEqual([item['names'] for item in got], [['Safari'], ['Telegram'], ['Slack'], ['Telegram'], ['Google Chrome'],
                                                          ['System Settings', 'System Preferences'], ['Visual Studio Code']])

    def test_the_tabs_of_relay_are_not_apps(self):
        got = route('open music', 'открой заметки', 'open files', 'открой офис')
        self.assertEqual([item['kind'] for item in got], ['view'] * 4)

    def test_a_long_sentence_is_not_an_app_name_and_an_unknown_name_keeps_its_words(self):
        self.assertEqual(route('open the report about last month sales', 'open notes about the meeting'), [None, None])
        got = route('open the door')[0]                      # the Mac will say there is no such app, and the words become a note
        self.assertEqual((got['kind'], got['spoken']), ('app', 'open the door'))

    def test_words_to_type_are_one_line_and_start_after_the_verb(self):
        got = route('type hello world', 'type: see you at five', 'Relay, type thanks a lot', 'напечатай привет мир', 'набери: добрый день', 'введи текст спасибо')
        self.assertTrue(all(item['kind'] == 'type' for item in got))
        self.assertEqual([item['text'] for item in got], ['hello world', 'see you at five', 'thanks a lot', 'привет мир', 'добрый день', 'спасибо'])
        self.assertEqual(run_node("console.log(JSON.stringify(c.typedText('  one\\n two\\t three  ')));"), 'one two three')
        self.assertEqual(run_node("console.log(JSON.stringify(c.typedText('x'.repeat(900)).length));"), 500)

    def test_a_note_that_only_starts_with_type_stays_a_note(self):
        self.assertEqual(route('type of coffee I like', 'type', 'type:'), [None] * 3)

    def test_a_telegram_draft_names_its_words(self):
        got = route('telegram: I will be late', 'write in Telegram that dinner is ready', 'send a message to Telegram, see you soon',
                    'в телеграм: буду через час', 'напиши в телеграм что опоздаю', 'телеграм, уже еду')
        self.assertTrue(all(item['kind'] == 'telegram' for item in got))
        self.assertEqual([item['text'] for item in got], ['I will be late', 'dinner is ready', 'see you soon', 'буду через час', 'опоздаю', 'уже еду'])

    def test_a_note_about_telegram_stays_a_note_and_opening_it_is_opening_an_app(self):
        self.assertEqual(route('Telegram channel needs a new logo', 'телеграм канал нужно обновить'), [None, None])
        self.assertEqual(route('open Telegram')[0]['names'], ['Telegram'])

    def test_a_name_without_a_comma_still_asks_that_agent_because_speech_rarely_writes_one(self):
        got = route('Observer what did you observe?', 'reviewer check the last changes', 'Codex find the slow query',
                    'наблюдатель почему падает сборка', 'клод объясни архитектуру', 'agents what is wrong with the parser')
        self.assertEqual([(item['agent'], item['mode']) for item in got], [
            ('observer', 'observe'), ('reviewer', 'observe'), ('codex', 'observe'), ('observer', 'observe'), ('claude', 'observe'), (None, 'observe')])
        self.assertEqual(got[0]['text'], 'what did you observe')

    def test_a_note_that_merely_starts_with_a_name_stays_a_note(self):
        self.assertEqual(route('Claude is down again', 'team meeting at 5', 'Observer', 'codex', 'builder was late today'), [None] * 5)

    def test_the_older_commands_still_win_where_they_always_did(self):
        got = route('open music', 'to-do call mom', 'pause', 'ask the agents why the build fails', 'Relay, open the login page in the browser please')
        self.assertEqual([item['kind'] for item in got], ['view', 'todo', 'media', 'agents', 'agents'])


class PageTests(unittest.TestCase):
    def test_the_typing_card_belongs_to_the_notes_and_is_never_the_agents_card(self):
        notes = HTML.split('<section id="notes"', 1)[1].split('</section>', 1)[0]
        self.assertIn('id="typeCard"', notes)
        self.assertNotIn('askCard', notes)
        self.assertEqual(len(re.findall(r'id="typeCard"', HTML)), 1)

    def test_nothing_is_typed_before_a_press_and_a_cancel_gives_the_words_back(self):
        self.assertIn("tell({ type: 'type', text })", NOTCH)
        self.assertEqual(NOTCH.count("type: 'type'"), 1)                       # only sendType() asks for typing
        self.assertIn("document.addEventListener('keydown', event => {\n  if (!typing.open || event.key !== 'Escape') return;", NOTCH)
        self.assertIn("$('typeCancel').addEventListener('click', () => closeType(true));", NOTCH)
        self.assertIn('if (keepWords && !$(\'noteInput\').value.trim())', NOTCH)  # never over words already in the field
        self.assertIn("if (!typing.open || !typing.app || !text) return;", NOTCH)  # no app to type into: no press does anything

    def test_the_panel_stays_open_while_the_words_wait_and_forgets_them_when_it_reappears(self):
        self.assertLess(NOTCH.index('const typing = {'), NOTCH.index('function syncHold()'))
        self.assertIn("(typing.open && view === 'notes')", NOTCH)
        self.assertIn("if (name !== 'notes') closeType();", NOTCH)
        self.assertRegex(NOTCH, r"else closeAsk\(false\);[^\n]*\n  closeType\(\);")

    def test_an_unknown_app_name_gives_the_words_back_as_a_note(self):
        reply = NOTCH.split('window.relayAction = ', 1)[1]
        self.assertIn("state === 'missing' && openingApp", reply)
        self.assertIn("$('noteInput').value = openingApp.spoken;", reply)

    def test_every_answer_the_app_can_give_is_said(self):
        reply = NOTCH.split('window.relayAction = ', 1)[1].split('\n};', 1)[0]
        for state in ('access', 'gone', 'changed', 'failed', 'missing'):
            self.assertIn("'%s'" % state, reply)

    def test_the_page_module_for_commands_is_still_served(self):
        self.assertIn("'notch-commands'", (ROOT / 'relay' / 'http.py').read_text())


class NativeTests(unittest.TestCase):
    def test_the_app_is_built_with_the_new_file(self):
        self.assertIn('packaging/RelayActions.m', BUILD)
        self.assertIn('#import "RelayActions.h"', PANEL)

    def test_the_panel_answers_only_the_messages_it_knows_and_checks_what_it_is_given(self):
        for message in ('app', 'front', 'type', 'telegram'):
            self.assertIn('[type isEqualToString:@"%s"]' % message, PANEL)
        self.assertIn('names.count < 4', PANEL)                  # a few names, each of limited length
        self.assertIn('text.length > 2000', PANEL)
        self.assertIn('prepare:^{ [weakSelf hideAnimated:YES]; }', PANEL)  # the panel steps away before the first key
        self.assertIn('window.relayAction', PANEL)

    def test_typing_asks_macos_first_and_never_presses_return_or_a_shortcut(self):
        self.assertIn('AXIsProcessTrustedWithOptions', ACTIONS)
        self.assertLess(ACTIONS.index('accessAllowedAsking:YES'), ACTIONS.index('[self postText:line]'))
        self.assertIn('CGEventSetFlags(event, 0)', ACTIONS)       # no Command or Option can ride along
        self.assertNotIn('kVK_Return', ACTIONS)
        self.assertNotIn('kVK_Command', ACTIONS)
        self.assertIn('oneLine:', ACTIONS)                        # line breaks never become Return

    def test_typing_goes_only_to_the_app_that_was_shown(self):
        self.assertIn('target.processIdentifier', ACTIONS)
        self.assertIn('@"changed"', ACTIONS)
        self.assertIn('@"gone"', ACTIONS)
        self.assertIn('self.typeTarget = [RelayActions workingApplication]', PANEL)

    def test_an_app_is_found_by_name_among_the_installed_apps_only(self):
        self.assertIn('[wanted containsString:@"/"]', ACTIONS)    # a name is never a path
        self.assertIn('partial.count == 1', ACTIONS)              # two apps that both fit: no guess

    def test_telegram_gets_a_draft_and_never_sends_it(self):
        self.assertIn('tg://msg_url?url=', ACTIONS)               # the documented share link, not tg://msg
        self.assertIn('URLForApplicationToOpenURL', ACTIONS)      # Telegram not installed: said, not guessed
        self.assertIn('setString:words forType:NSPasteboardTypeString', ACTIONS)  # and on the clipboard, for a Telegram that ignores the link's words
        self.assertIn('on your clipboard', NOTCH)                                 # which the person is told
        self.assertNotIn('api.telegram.org', ACTIONS)
        self.assertNotIn('api.telegram.org', NOTCH)

    def test_a_spoken_request_gets_a_wide_short_panel_and_anything_else_gets_the_full_one(self):
        self.assertIn('static const CGFloat CardWidth', PANEL)
        self.assertIn('self.cardSize ? NSMakeSize(CardWidth, band + CardBodyHeight)', PANEL)
        self.assertIn("{ type: 'expand', card: true }", NOTCH)
        self.assertIn('ask.open && !current?.plan', NOTCH)                   # a plan to approve still gets the tall panel
        self.assertIn('[self useCardSize:!view && [body[@"card"] boolValue]]', PANEL)
        self.assertEqual(PANEL.count('[self useCardSize:NO];'), 2)           # the Office key and a plan that needs the person
        self.assertRegex(PANEL, r'self\.shown = NO;\n\s+self\.cardSize = NO;')   # a hidden panel forgets the card size
        self.assertIn('self.cardSize != self.laidOutCard', PANEL)            # an open panel really changes size between the two

    def test_the_header_names_what_the_page_may_rely_on(self):
        for word in ('opened', 'missing', 'failed', 'typed', 'access', 'gone', 'changed'):
            self.assertIn('"%s"' % word, HEADER)


@unittest.skipUnless(shutil.which('node'), 'Node is required for the translation check')
class LanguageTests(unittest.TestCase):
    def test_everything_the_new_commands_say_has_a_russian_text(self):
        said = re.findall(r"say\('([^']+)'\)", NOTCH.split('window.relayAction = ', 1)[1].split('\n};', 1)[0])
        said += re.findall(r"say\('([^']+)'\)", NOTCH.split('function runCommand', 1)[1].split('// "type hello"', 1)[0])
        said += ['Type into another app', 'The words to type', 'Type', 'The words are only typed. Nothing is sent or submitted.',
                 'No app to type into. Switch to one first.', 'Type into Safari', 'Type into Google Chrome']
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
""" % ((STATIC / 'i18n.js').as_posix(), (STATIC / 'i18n-ru.js').as_posix(), json.dumps(said))
        result = subprocess.run(['node', '--input-type=module', '-'], input=harness, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertGreaterEqual(len(said), 14)
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), [])


if __name__ == '__main__':
    unittest.main()
