"""Spoken commands (static/js/notch-commands.js) and the card that asks before a request goes to the agents (static/notch.js).
The words are read by a pure module, so they are run; the page wiring is checked in the source."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]
STATIC = ROOT / 'static'
NOTCH = (STATIC / 'notch.js').read_text()
HTML = (STATIC / 'notch.html').read_text()


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
    def test_a_phrase_that_is_only_a_command_opens_a_tab(self):
        got = route('open music', 'Open the Notes tab.', 'show me files', 'go to the office', 'switch to tasks', 'открой заметки', 'Покажи музыку', 'перейди на задачи', 'открой офис')
        self.assertEqual([item['view'] for item in got], ['music', 'notes', 'deliver', 'office', 'task', 'notes', 'music', 'task', 'office'])
        self.assertTrue(all(item['kind'] == 'view' for item in got))

    def test_a_note_that_only_starts_like_a_command_stays_a_note(self):
        # Opening words followed by more words are somebody's note, not an instruction.
        self.assertEqual(route('open notes about the meeting', 'call mom tomorrow at 9', 'buy milk', 'tell me a joke', 'play football at 6'), [None] * 5)

    def test_music_commands(self):
        got = route('pause', 'Pause the music', 'stop the music please', 'play', 'resume', 'next song', 'skip', 'previous track', 'пауза', 'включи музыку', 'следующий трек', 'предыдущая песня')
        self.assertEqual([item['command'] for item in got], ['pause', 'pause', 'pause', 'play', 'play', 'next', 'next', 'previous', 'pause', 'play', 'next', 'previous'])

    def test_a_to_do_names_its_text(self):
        got = route('to-do buy milk', 'add a to-do: call mom tomorrow at 9', 'add milk to my to-do list', 'добавь в список дел купить молоко', 'дело: позвонить маме', 'to-do')
        self.assertEqual([item and item['text'] for item in got], ['buy milk', 'call mom tomorrow at 9', 'milk', 'купить молоко', 'позвонить маме', None])

    def test_a_request_for_the_agents_gets_the_kind_of_work_it_sounds_like(self):
        got = route('ask the agents why the build fails', 'tell the agents to fix the failing tests', 'have the team plan the refactor',
                    'agents, check the ERP parser', 'Relay, fix the login tests', 'ask the agents to plan the release',
                    'спроси у агентов почему падает сборка', 'скажи агентам починить тесты', 'агенты, проверь парсер', 'поручи агентам спланировать релиз')
        self.assertEqual([(item['text'], item['mode']) for item in got], [
            ('why the build fails', 'observe'), ('fix the failing tests', 'build'), ('plan the refactor', 'plan'),
            ('check the ERP parser', 'observe'), ('fix the login tests', 'build'), ('plan the release', 'plan'),
            ('почему падает сборка', 'observe'), ('починить тесты', 'build'), ('проверь парсер', 'observe'), ('спланировать релиз', 'plan')])
        self.assertTrue(all(item['kind'] == 'agents' for item in got))

    def test_a_request_needs_something_to_ask_and_the_name_alone_is_not_one(self):
        self.assertEqual(route('ask the agents', 'tell the agents to', 'Relay', 'agents'), [None] * 4)

    def test_calling_relay_by_name_does_not_hide_a_command(self):
        got = route('Relay, open music', 'hey Relay, next song')
        self.assertEqual([item['kind'] for item in got], ['view', 'media'])

    def test_an_agent_asked_by_name_gets_the_work_it_can_do(self):
        got = route('Observer, why does the build fail', 'observer, fix the login bug', 'ask the builder why you changed the parser',
                    'tell the builder to fix the tests', 'reviewer, check the last changes', 'tell the reviewer to fix the typos',
                    'Codex, find the slow query', 'tell codex to add a retry', 'Claude, plan the migration', 'agents, fix the tests',
                    'наблюдатель, почему падает сборка', 'попроси разработчика починить тесты', 'спроси у ревьюера что не так с логином',
                    'скажи кодексу добавить повтор', 'клод, объясни архитектуру')
        self.assertEqual([(item['agent'], item['mode']) for item in got], [
            ('observer', 'observe'), ('observer', 'plan'),        # the observer cannot change files: a fix becomes a plan
            ('builder', 'observe'), ('builder', 'build'),
            ('reviewer', 'observe'), ('reviewer', 'observe'),     # nor can the reviewer: a fix becomes a question
            ('codex', 'observe'), ('codex', 'build'), ('claude', 'plan'), (None, 'build'),
            ('observer', 'observe'), ('builder', 'build'), ('reviewer', 'observe'), ('codex', 'build'), ('claude', 'observe')])
        self.assertEqual(route('Relay, open music')[0]['kind'], 'view')   # a command is still a command

    def test_who_does_the_work_decides_the_seat_and_never_the_powers(self):
        got = run_node("""
const team = { name: 'T', roles: {
  observer: { provider: 'claude', model: 'opus', effort: 'high', instructions: 'look' },
  builder: { provider: 'codex', model: 'gpt', effort: 'low', instructions: 'build' },
  reviewer: { provider: 'claude', model: 'sonnet', effort: '', instructions: 'review' } } };
const seats = (agent, mode) => { const t = c.teamFor(team, agent, mode); return t && [t.roles.observer, t.roles.builder, t.roles.reviewer].map(r => [r.provider, r.model, r.effort, r.instructions].join('/')); };
console.log(JSON.stringify({
  reviewerLooks: seats('reviewer', 'observe'), builderLooks: seats('builder', 'plan'), observer: seats('observer', 'plan'),
  codexLooks: seats('codex', 'observe'), claudeBuilds: seats('claude', 'build'), codexBuilds: seats('codex', 'build'),
  whole: seats(null, 'build'), nothing: c.teamFor(null, 'codex', 'build'), unchanged: JSON.stringify(team).length,
  fit: [c.fitMode('observer', 'build'), c.fitMode('reviewer', 'build'), c.fitMode('builder', 'build'), c.fitMode('claude', 'build'), c.fitMode('observer', 'observe')],
  brief: c.briefFor('x', '/p', 'observe', team).team.name, plain: 'team' in c.briefFor('x', '/p', 'observe')}));""")
        self.assertEqual(got['reviewerLooks'][0], 'claude/sonnet//review')        # the reviewer's own tool, model and instructions do the looking
        self.assertEqual(got['reviewerLooks'][1:], ['codex/gpt/low/build', 'claude/sonnet//review'])
        self.assertEqual(got['builderLooks'][0], 'codex/gpt/low/build')
        self.assertEqual(got['observer'], ['claude/opus/high/look', 'codex/gpt/low/build', 'claude/sonnet//review'])
        self.assertEqual(got['codexLooks'][0], 'codex//' + '/look')                # another tool: its own default model and effort
        self.assertEqual(got['claudeBuilds'][1], 'claude//' + '/build')
        self.assertEqual(got['codexBuilds'], got['whole'])                         # already the builder's tool: nothing to change
        self.assertIsNone(got['nothing'])
        self.assertEqual(got['fit'], ['plan', 'observe', 'build', 'build', 'observe'])
        self.assertEqual((got['brief'], got['plain']), ('T', False))

    def test_the_teams_made_for_a_named_agent_pass_the_engines_own_check(self):
        from relay import providers
        from relay.contracts import DEFAULT_TEAM
        team = json.dumps(DEFAULT_TEAM)
        for agent in ('observer', 'builder', 'reviewer', 'claude', 'codex'):
            for mode in ('observe', 'plan', 'build'):
                made = json.loads(subprocess.run(['node', '--input-type=module', '-'], capture_output=True, text=True, timeout=60, input=
                    "import * as c from '%s'; console.log(JSON.stringify(c.teamFor(%s, '%s', '%s')));" % ((STATIC / 'js/notch-commands.js').as_posix(), team, agent, mode)).stdout)
                providers.validate_team(made)

    def test_the_brief_that_is_queued(self):
        got = run_node("""console.log(JSON.stringify([
  c.briefFor(' fix it ', '/p', 'build'), c.briefFor('why', '/p', 'observe'), c.briefFor('x', '/p', 'bogus'),
  c.pickProject([{ path: '/gone', exists: false }, { path: '/a' }, { path: '/b' }], '/b'),
  c.pickProject([{ path: '/gone', exists: false }, { path: '/a' }], '/gone'), c.pickProject([], '/a')]));""")
        self.assertEqual(got[0], {'task': 'fix it', 'project': '/p', 'mode': 'build', 'rounds': 3, 'minutes': 20, 'auto': False})
        self.assertEqual((got[1]['mode'], got[1]['rounds']), ('observe', 0))   # a question has nothing to review
        self.assertEqual(got[2]['mode'], 'build')
        self.assertEqual([got[3], got[4], got[5]], [{'path': '/b'}, {'path': '/a'}, None])   # a folder that is gone is never offered

    def test_the_briefs_are_accepted_by_the_queue(self):
        # What the page sends must pass the engine's own checks.
        import tempfile
        from relay import task_queue
        with tempfile.TemporaryDirectory() as folder:
            for mode in ('observe', 'plan', 'build'):
                brief = json.loads(subprocess.run(['node', '--input-type=module', '-'], capture_output=True, text=True, timeout=60, input=
                    "import * as c from '%s'; console.log(JSON.stringify(c.briefFor('look at it', %s, '%s')));" % ((STATIC / 'js/notch-commands.js').as_posix(), json.dumps(folder), mode)).stdout)
                class App:
                    TASK_MODES = ('observe', 'plan', 'build')
                    DEFAULT_TEAM = {'name': 'x'}
                    validate_team = staticmethod(lambda team: team)
                settings = task_queue.parameters(App, brief)
                self.assertEqual((settings['mode'], settings['rounds'], settings['minutes'], settings['auto']), (mode, brief['rounds'], 20, False))


class PageTests(unittest.TestCase):
    def test_commands_are_read_only_when_the_field_was_empty(self):
        self.assertIn("const command = voice.base.trim() ? null : routeCommand(spoken);", NOTCH)

    def test_nothing_reaches_the_agents_without_a_yes_and_nothing_starts_by_itself(self):
        for element in ('id="askCard"', 'id="askTask"', 'id="askModes"', 'id="askProject"', 'id="askQueue"', 'id="askCancel"'):
            self.assertIn(element, HTML)
        self.assertIn("post('/api/queue/add', briefFor(task, project, mode, teamFor(", NOTCH)
        self.assertNotIn("post('/api/queue/start'", NOTCH)           # starting stays a press on Start task (notch-activity.js); the page only watches it
        self.assertNotIn("/api/run'", NOTCH)
        run = NOTCH.split('function runCommand(command) {', 1)[1].split('\nfunction paintAsk', 1)[0]
        self.assertIn('openAsk(command)', run)
        self.assertNotIn('queueAsk', run)
        self.assertIn('activity.update(result, current)', NOTCH)       # the engine answers /api/queue/add with the queue itself                              # a spoken request only opens the card

    def test_the_panel_stays_open_while_the_card_is_open_and_closes_it_with_escape(self):
        self.assertLess(NOTCH.index('const ask = {'), NOTCH.index('function syncHold()'))
        self.assertIn('(ask.open && view === \'task\')', NOTCH)
        self.assertIn("if (!ask.open || event.key !== 'Escape') return;", NOTCH)
        self.assertIn('else closeAsk(false);', NOTCH)                  # a panel that appears again starts without the card
        self.assertIn('if (ask.resizing) ask.resizing = false;', NOTCH)  # ... unless it only changed size for the card

    def test_the_agent_is_chosen_in_the_card_and_never_guessed_when_the_team_is_unknown(self):
        self.assertIn('id="askAgent"', HTML)
        self.assertIn("briefFor(task, project, mode, teamFor(ask.team, ask.agent, mode))", NOTCH)
        self.assertIn("if (ask.agent && !ask.team) throw", NOTCH)                  # an agent was named but the team could not be read
        self.assertIn("ask.mode = fitMode(ask.agent, ask.mode);", NOTCH)           # the observer and the reviewer cannot be given a build
        self.assertIn("fetch('/api/teams'", NOTCH)

    def test_the_agents_belong_to_the_task_page_not_the_notes(self):
        notes = HTML.split('<section id="notes"', 1)[1].split('</section>', 1)[0]
        task = HTML.split('<section class="info"', 1)[1].split('</section>', 1)[0]
        self.assertNotIn('askCard', notes)
        self.assertIn('id="askCard"', task)
        run = NOTCH.split('function runCommand(command) {', 1)[1].split('\nfunction paintAsk', 1)[0]
        self.assertLess(run.index('openAsk(command)'), run.index("pickTab('task')"))   # the card is open before the tab asks for room
        self.assertIn('(!!current?.plan || ask.open)', NOTCH)                          # the big panel, like a plan to approve
        self.assertIn("tell({ type: 'shrink' })", NOTCH.split('function closeAsk', 1)[1][:600])  # and the small one again afterwards

    def test_the_music_commands_press_only_what_is_needed(self):
        self.assertIn("(wanted === 'pause') === playing", NOTCH)      # "pause" while paused presses nothing

    def test_the_page_can_load_the_module(self):
        self.assertIn("'notch-commands'", (ROOT / 'relay' / 'http.py').read_text())


@unittest.skipUnless(shutil.which('node'), 'Node is required for the translation check')
class LanguageTests(unittest.TestCase):
    def test_everything_the_commands_say_has_a_russian_text(self):
        said = __import__('re').findall(r"'([A-Z][^']*\.)'", NOTCH.split('function runCommand', 1)[1].split('function openAsk', 1)[0])
        asked = ['Whole team', 'Who should do it', 'Relay could not read the team. Try again.', 'Claude takes the lead in this task.', 'Codex takes the lead in this task.',
                 'The Observer only looks and plans. Nothing is changed.', 'The Reviewer looks with its own tool and model. Nothing is changed.',
                 'The Builder changes the files, after you approve the plan.', 'The Builder answers with its own tool and model. Nothing is changed.',
                 'Send to the agents', 'Ask', 'Add to queue', 'It waits in the queue until you press Start task.', 'Save a project in the Relay window first, then try again.', 'Relay is not responding.']
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
""" % ((STATIC / 'i18n.js').as_posix(), (STATIC / 'i18n-ru.js').as_posix(), json.dumps(said + asked))
        result = subprocess.run(['node', '--input-type=module', '-'], input=harness, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertGreaterEqual(len(said), 6)                          # the check really found the messages
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), [])
