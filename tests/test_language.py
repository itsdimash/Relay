"""Russian: the language switch, the engine, and the dictionary. The English text stays the source of truth;
these tests fail when a new sentence is added to the page or the engine without a Russian counterpart."""
import ast
from html.parser import HTMLParser
from pathlib import Path
import json
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]
STATIC = ROOT / 'static'
ATTRIBUTES = ('title', 'aria-label', 'placeholder', 'alt')
# Names and codes that are the same in every language.
SAME = {'relay', 'Relay', 'Claude', 'Codex', 'Cl', 'Cx', 'EN', 'RU', 'Claude Code'}


class Strings(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.skip, self.hidden = [], 0, 0

    def add(self, text):
        text = re.sub(r'\s+', ' ', text).strip()
        if text and re.search(r'[A-Za-z]{2}', text) and text not in SAME and text not in self.found:
            self.found.append(text)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in ('script', 'style', 'code', 'pre'):
            self.skip += 1
        if values.get('translate') == 'no':
            self.hidden += 1
            self.stack = getattr(self, 'stack', []) + [tag]
        for name in ATTRIBUTES:
            if values.get(name) and not self.hidden:
                self.add(values[name])

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'code', 'pre'):
            self.skip -= 1
        stack = getattr(self, 'stack', [])
        if stack and stack[-1] == tag:
            stack.pop()
            self.hidden -= 1

    def handle_data(self, data):
        if not self.skip and not self.hidden:
            self.add(data)


def page_strings(name):
    parser = Strings()
    parser.feed((STATIC / name).read_text(encoding='utf-8'))
    return parser.found


def literal_messages():
    """The fixed English sentences the engine raises or shows in a chat, found in the Python source."""
    found = set()
    for path in sorted((ROOT / 'relay').glob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                argument = node.exc.args[0]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    found.add(argument.value)
            pairs = []
            if isinstance(node, ast.Dict):
                pairs = [(key.value, value) for key, value in zip(node.keys, node.values) if isinstance(key, ast.Constant)]
            elif isinstance(node, ast.keyword):
                pairs = [(node.arg, node.value)]
            elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Subscript) and isinstance(node.targets[0].slice, ast.Constant):
                pairs = [(node.targets[0].slice.value, node.value)]
            for key, value in pairs:
                if key in ('message', 'reason', 'error', 'label', 'summary') and isinstance(value, ast.Constant) and isinstance(value.value, str):
                    found.add(value.value)
            if isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'emit' and len(node.args) >= 3:
                argument = node.args[2]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str) and node.args[0].value == 'Relay':
                    found.add(argument.value)
    return sorted(found)


@unittest.skipUnless(shutil.which('node'), 'Node is required for the language checks')
class LanguageTests(unittest.TestCase):
    def run_node(self, body, stored='ru', languages=('en-US',), blocked=False):
        engine = json.dumps((STATIC / 'i18n.js').read_text(encoding='utf-8'))
        russian = json.dumps((STATIC / 'i18n-ru.js').read_text(encoding='utf-8'))
        harness = f"""
const assert = (await import('node:assert/strict')).default;
const vm = await import('node:vm');
function load({{ stored = {json.dumps(stored)}, languages = {json.dumps(list(languages))}, blocked = {json.dumps(blocked)} }} = {{}}) {{
  const store = new Map(stored === null ? [] : [['relay.lang', stored]]);
  const listeners = {{}};
  const events = [];
  const documentElement = {{ lang: '' }};
  const window = {{
    addEventListener: (type, fn) => (listeners[type] ||= []).push(fn),
    dispatchEvent: event => {{ events.push(event); return true; }},
  }};
  const context = {{
    window, document: {{ documentElement, addEventListener() {{}} }}, navigator: {{ languages }},
    CustomEvent: class {{ constructor(type, init) {{ this.type = type; this.detail = init.detail; }} }},
    get localStorage() {{ if (blocked) throw new Error('blocked'); return {{ getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) }}; }},
  }};
  vm.runInNewContext({engine}, context);
  vm.runInNewContext({russian}, context);
  return {{ i18n: window.relayI18n, store, events, documentElement, listeners }};
}}
{body}
"""
        result = subprocess.run(['node', '--input-type=module', '-'], input=harness, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return result.stdout

    def missing(self, strings):
        output = self.run_node(f"""
const {{ i18n }} = load();
const missing = {json.dumps(strings)}.filter(text => i18n.translate(text) === text);
console.log(JSON.stringify(missing));
""")
        return json.loads(output)

    def test_every_fixed_sentence_on_the_dashboard_has_a_russian_text(self):
        self.assertEqual(self.missing(page_strings('index.html')), [])

    def test_every_fixed_sentence_in_the_notch_panel_has_a_russian_text(self):
        self.assertEqual(self.missing(page_strings('notch.html')), [])

    def test_every_fixed_engine_message_has_a_russian_text(self):
        messages = [message for message in literal_messages() if re.search(r'[A-Za-z]{3}', message)]
        self.assertGreater(len(messages), 100)
        self.assertEqual(self.missing(messages), [])

    def test_the_language_is_chosen_from_the_saved_choice_or_the_mac(self):
        self.run_node("""
assert.equal(load({ stored: 'ru' }).i18n.language, 'ru');
assert.equal(load({ stored: 'en', languages: ['ru-RU'] }).i18n.language, 'en');
assert.equal(load({ stored: 'auto', languages: ['ru-RU', 'en-US'] }).i18n.language, 'ru');
assert.equal(load({ stored: null, languages: ['ru'] }).i18n.language, 'ru');
assert.equal(load({ stored: null, languages: ['de-DE', 'ru'] }).i18n.language, 'ru');   // the first language Relay has
assert.equal(load({ stored: null, languages: ['de-DE'] }).i18n.language, 'en');
assert.equal(load({ stored: 'klingon', languages: ['ru'] }).i18n.language, 'ru');        // a bad value means automatic
assert.equal(load({ stored: 'klingon', languages: ['fr'] }).i18n.choice, 'auto');
assert.equal(load({ blocked: true, languages: ['ru'] }).i18n.language, 'ru');             // blocked storage still works
const page = load({ stored: 'ru' });
assert.equal(page.documentElement.lang, 'ru');
""", stored=None)

    def test_choosing_a_language_saves_it_and_tells_the_page(self):
        self.run_node("""
const page = load({ stored: 'en', languages: ['en-US'] });
assert.equal(page.i18n.translate('Cancel'), 'Cancel');
page.i18n.set('ru');
assert.equal(page.store.get('relay.lang'), 'ru');
assert.equal(page.i18n.translate('Cancel'), 'Отмена');
assert.equal(page.documentElement.lang, 'ru');
assert.equal(page.events.at(-1).type, 'relaylangchange');
assert.equal(page.events.at(-1).detail.language, 'ru');
page.i18n.set('klingon');                               // ignored
assert.equal(page.i18n.choice, 'ru');
page.i18n.set('en');
assert.equal(page.i18n.translate('Cancel'), 'Cancel');
assert.equal(page.i18n.locale(), undefined);            // English keeps the browser's own date format
page.i18n.set('ru');
assert.equal(page.i18n.locale(), 'ru-RU');
// The notch panel is another page: a change made there arrives as a storage event.
const other = load({ stored: 'en' });
other.store.set('relay.lang', 'ru');
other.listeners.storage[0]({ key: 'relay.lang', newValue: 'ru' });
assert.equal(other.i18n.language, 'ru');
""", stored=None)

    def test_russian_plurals_and_numbers(self):
        self.run_node("""
const { i18n } = load();
const plural = i18n.plural;
for (const [n, form] of [[0, 'many'], [1, 'one'], [2, 'few'], [4, 'few'], [5, 'many'], [11, 'many'], [12, 'many'], [14, 'many'], [21, 'one'], [22, 'few'], [25, 'many'], [101, 'one'], [111, 'many']]) {
  assert.equal(plural(n, 'one', 'few', 'many'), form, String(n));
}
assert.equal(i18n.translate('20 minute limit'), 'Лимит: 20 минут');
assert.equal(i18n.translate('21 minute limit'), 'Лимит: 21 минута');
assert.equal(i18n.translate('22 minute limit'), 'Лимит: 22 минуты');
assert.equal(i18n.translate('In 1 seconds · try 2 of 3'), 'Через 1 секунду · попытка 2 из 3');
assert.equal(i18n.translate('Round 2 of 3'), 'Раунд 2 из 3');
""")

    def test_lists_and_lines_are_translated_piece_by_piece(self):
        self.run_node("""
const { i18n } = load();
assert.equal(i18n.translate('59% left · week 76%'), 'осталось 59% · неделя: 76%');
assert.equal(i18n.translate('5-hour limit: 70% left, resets in 2 h 10 min\\nWeekly limit: 20% left'),
  'Лимит (5 часов): осталось 70%, сброс через 2 ч 10 мин\\nЛимит (За неделю): осталось 20%');
const line = i18n.translate('Build & review · Auto mode · Round 1 of 3 · 20 minute limit\\nTeam name: Mine · observer: Claude / builder: Codex / reviewer: Claude\\nEdited folder: /a/b');
assert.equal(line, 'Сборка и ревью · Авто-режим · Раунд 1 из 3 · Лимит: 20 минут\\nНазвание команды: Mine · наблюдатель: Claude / разработчик: Codex / ревьюер: Claude\\nИзменённая папка: /a/b');
// Names the person chose stay as they wrote them.
assert.equal(i18n.translate('Team name: Rocket Crew · observer: Claude'), 'Название команды: Rocket Crew · наблюдатель: Claude');
assert.equal(i18n.translate('Nothing we know · Cancel'), 'Nothing we know · Отмена');
assert.equal(i18n.translate('Something unknown'), 'Something unknown');
""")

    def test_what_people_and_agents_wrote_is_only_matched_as_a_whole_sentence(self):
        self.run_node("""
const { i18n } = load();
// In a chat title, a report or an agent's message, a free-text template must not rewrite the text...
assert.equal(i18n.translate('Open dashboard', true), 'Open dashboard');
assert.equal(i18n.translate('Done: fixed the bug', true), 'Done: fixed the bug');
assert.equal(i18n.translate('Cancel · Save', true), 'Cancel · Save');
// ...but Relay's own whole sentences and numeric ones still are.
assert.equal(i18n.translate('Stop requested.', true), 'Запрошена остановка.');
assert.equal(i18n.translate('3 min ago', true), '3 мин назад');
assert.equal(i18n.translate('Open dashboard'), 'Открыть dashboard');
""")

    def test_every_template_fills_in_only_holes_it_has(self):
        text = (STATIC / 'i18n-ru.js').read_text(encoding='utf-8')
        start = text.index('var templates = [')
        templates = json.loads('[' + text[start + len('var templates = ['):text.index('\n  ];', start)].rstrip().rstrip(',') + ']')
        self.assertGreater(len(templates), 100)
        for source, target in templates:
            holes = set(re.findall(r'\{[#*]?(\w+)\}', source))
            used = set(re.findall(r'\{(\w+)(?:!|\?[^}]*)?\}', target))
            self.assertLessEqual(used, holes, source)
            self.assertTrue(re.search(r'[А-Яа-я]', target) or '!}' in target, source)

    def test_no_entry_is_empty_or_left_in_english(self):
        text = (STATIC / 'i18n-ru.js').read_text(encoding='utf-8')
        start = text.index('var exact = {')
        end = text.index('\n  };', start)
        exact = json.loads('{' + text[start + len('var exact = {'):end].rstrip().rstrip(',') + '}')
        self.assertGreater(len(exact), 500)
        for english, russian in exact.items():
            self.assertTrue(russian.strip(), english)
            if re.search(r'[A-Za-z]{4}', english) and english not in SAME:
                self.assertTrue(re.search(r'[А-Яа-я]', russian) or english == russian and len(english) < 12, english)


class WiringTests(unittest.TestCase):
    def test_both_pages_load_the_language_files_before_anything_else(self):
        for name in ('index.html', 'notch.html'):
            html = (STATIC / name).read_text(encoding='utf-8')
            engine, russian = html.index('<script src="/i18n.js"></script>'), html.index('<script src="/i18n-ru.js"></script>')
            self.assertLess(engine, russian, name)
            self.assertLess(russian, html.index('type="module"'), name)
            self.assertNotIn('type="module" src="/i18n', html)  # they run before the page is built

    def test_the_files_are_served(self):
        http = (ROOT / 'relay' / 'http.py').read_text()
        self.assertIn("files['/i18n.js'] = ('i18n.js'", http)
        self.assertIn("files['/i18n-ru.js'] = ('i18n-ru.js'", http)

    def test_the_language_menu_is_accessible_and_offers_automatic_english_and_russian(self):
        html = (STATIC / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="langButton" aria-haspopup="menu" aria-expanded="false" aria-controls="langMenu"', html)
        menu = html.split('id="langMenu"', 1)[1].split('<button type="button" class="theme-button" id="themeButton"', 1)[0]
        self.assertEqual(re.findall(r'role="menuitemradio" aria-checked="false" data-lang="(\w+)"', menu), ['auto', 'en', 'ru'])
        self.assertIn('<span translate="no">Русский</span>', menu)   # a language is always named in itself
        self.assertIn('<span translate="no">English</span>', menu)
        script = (STATIC / 'js' / 'appearance.js').read_text()
        for needle in ("'langButton'", "'langMenu'", "relaylangchange", "i18n.set(value)"):
            self.assertIn(needle, script)

    def test_dates_follow_the_page_language_and_a_change_redraws_the_open_chat(self):
        for name in ('conversation.js', 'history.js'):
            source = (STATIC / 'js' / name).read_text()
            self.assertNotIn('toLocaleTimeString([]', source)
            self.assertNotIn('toLocaleString([]', source)
            self.assertIn('locale()', source)
        app = (STATIC / 'app.js').read_text()
        self.assertIn("window.addEventListener('relaylangchange'", app)
        self.assertIn("state.rendered = ''", app)

    def test_agents_own_messages_are_marked_so_only_relays_own_are_translated(self):
        source = (STATIC / 'js' / 'conversation.js').read_text()
        self.assertIn("event.agent === 'Relay' ? '' : ' data-i18n-strict'", source)


if __name__ == '__main__':
    unittest.main()
