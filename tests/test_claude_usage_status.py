"""Fresh shared-plan quota, with no inference or credential handling."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from relay.application import Application
from relay.limits import ClaudeUsage, Limits, _usage_report, claude_usage_status_reading, read_claude_usage_status
from relay.providers import claude_desktop_cli

REPORT = {'type':'result','subtype':'success','local_command':'usage','is_error':False,
          'num_turns':0,'total_cost_usd':0,
          'result':'You are currently using your subscription to power your Claude Code usage\n\nCurrent session: 44% used · resets Nov 1 at 6:20pm (Asia/Almaty)\nCurrent week (all models): 74% used · resets Nov 2 at 4am (Asia/Almaty)\n\nLast 7d · 514 requests'}

class ClaudeUsageStatusTests(unittest.TestCase):
    def test_account_used_percentages_are_converted_once(self):
        reading=claude_usage_status_reading(REPORT)
        self.assertEqual(reading['session']['left'],56)
        self.assertEqual(reading['week']['left'],26)
        self.assertEqual(reading['session']['reset_label'],'Nov 1 at 6:20pm (Asia/Almaty)')

    def test_model_answers_errors_and_unverified_results_are_not_quotas(self):
        for updates in [{'local_command':None},{'num_turns':1},{'total_cost_usd':0.01},{'is_error':True},{'result':'Current session: 101% used'},{'result':'Current week (Sonnet): 74% used'}]:
            self.assertIsNone(claude_usage_status_reading({**REPORT,**updates}))
        self.assertIsNone(claude_usage_status_reading(None))
        reading=claude_usage_status_reading({**REPORT,'result':'Current week (all models): 74% used'})
        self.assertEqual(set(reading),{'week'})

    def test_status_command_is_isolated_and_contains_no_model_prompt(self):
        calls=[]
        def run(args,**kwargs):
            calls.append((args,kwargs))
            self.assertTrue(Path(kwargs['cwd']).is_dir())
            self.assertEqual(list(Path(kwargs['cwd']).iterdir()),[])
            return type('Result',(),{'returncode':0,'stdout':json.dumps(REPORT)})()
        with patch.dict(os.environ,{'RELAY_NO_CLAUDE_USAGE_POLL':'','CLAUDECODE':'nested'}):
            self.assertEqual(read_claude_usage_status('/bin/claude',run=run)['session']['left'],56)
        args,kwargs=calls[0]
        self.assertEqual(args[:4],['/bin/claude','-p','/usage','--output-format'])
        self.assertIn('--restricted',args)
        self.assertEqual(args[args.index('--tools')+1],'')
        self.assertEqual(args[args.index('--setting-sources')+1],'')
        self.assertNotIn('input',kwargs)
        self.assertNotIn('CLAUDECODE',kwargs['env'])

    def test_missing_cli_unsupported_output_and_failures_produce_no_current_reading(self):
        def fail(*args,**kwargs):raise OSError('missing')
        with patch.dict(os.environ,{'RELAY_NO_CLAUDE_USAGE_POLL':''}):
            self.assertIsNone(read_claude_usage_status('/no/cli',run=fail))
            self.assertIsNone(read_claude_usage_status('/bin/cli',run=lambda *a,**k:type('Result',(),{'returncode':0,'stdout':'not-json'})()))

    def test_app_refreshes_each_minute_instead_of_waiting_fifteen(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Application(folder,Path(folder)/'data')
            now=[1000];jobs=[]
            app.limits.clock=lambda:now[0]
            app.limits.start=jobs.append
            app.limits.executable=lambda _:'/bin/claude'
            app.limits.next['codex']=float('inf')
            app.limits._store('claude',claude_usage_status_reading(REPORT),source='claude-usage-command')
            now[0]=1059;app.limits.snapshot();self.assertEqual(jobs,[])
            now[0]=1061;app.limits.snapshot();self.assertEqual([job.args[0] for job in jobs],['claude'])
            self.assertEqual(app.limits.snapshot()['claude']['source'],'claude-usage-command')


class ClaudeUsageResilienceTests(unittest.TestCase):
    def result(self, stdout='', code=0, stderr=''):
        return lambda *a, **k: type('Result', (), {'returncode': code, 'stdout': stdout, 'stderr': stderr})()

    def test_wording_colours_and_missing_counters_do_not_hide_the_percentages(self):
        text = ('\x1b[1mCurrent session\x1b[0m\n  \u2588\u2588\u2588\u2591\u2591 44% used\n  Resets Nov 1 at 6:20pm\n\n'
                'Current week (Sonnet): 10% used\n\nCurrent week (all models): 74% used \u00b7 Resets Nov 2 at 4am')
        reading = claude_usage_status_reading({'local_command': 'usage', 'result': text})
        self.assertEqual((reading['session']['left'], reading['week']['left']), (56, 26))
        self.assertEqual(reading['week']['reset_label'], 'Nov 2 at 4am')
        self.assertIsNone(claude_usage_status_reading({**REPORT, 'num_turns': 2}))
        self.assertIsNone(claude_usage_status_reading({**REPORT, 'total_cost_usd': 0.5}))

    def test_a_notice_or_event_list_around_the_report_is_tolerated(self):
        self.assertEqual(_usage_report('Update available\n' + json.dumps(REPORT))['local_command'], 'usage')
        self.assertEqual(_usage_report(json.dumps([{'type': 'system'}, REPORT]))['local_command'], 'usage')
        self.assertIsNone(_usage_report('nothing useful'))

    def test_every_failure_says_why(self):
        cases = [(self.result('', 1, 'error: unknown option --restricted'), 'unknown option'),
                 (self.result('not-json'), 'Update Claude Code'),
                 (self.result(json.dumps({**REPORT, 'result': 'Plan usage unavailable'})), 'could not read')]
        with patch.dict(os.environ, {'RELAY_NO_CLAUDE_USAGE_POLL': ''}):
            for run, expected in cases:
                self.assertIsNone(read_claude_usage_status('/bin/claude', run=run))
                self.assertIn(expected, read_claude_usage_status.problem)
            self.assertEqual(read_claude_usage_status('/bin/claude', run=self.result(json.dumps(REPORT)))['session']['left'], 56)
            self.assertEqual(read_claude_usage_status.problem, '')

    def test_screen_data_carries_the_reason_and_the_raw_report_is_kept_for_debugging(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'RELAY_NO_CLAUDE_USAGE_POLL': ''}):
            path = Path(folder) / 'limits.json'
            binary = [None]
            store = Limits(path, lambda _: binary[0], read_codex=lambda _: None, read_claude=read_claude_usage_status, start=lambda job: job())
            store.refresh('claude')
            self.assertIn('could not find', store.snapshot()['claude']['problem'])
            binary[0] = '/bin/claude'
            with patch('relay.limits.subprocess.run', self.result('not-json', 0, 'boom')):
                store.refresh('claude')
            self.assertIn('Update Claude Code', store.snapshot()['claude']['problem'])
            self.assertIn('not-json', (Path(folder) / 'limits-claude-debug.txt').read_text())
            with patch('relay.limits.subprocess.run', self.result(json.dumps(REPORT))):
                store.refresh('claude')
            shot = store.snapshot()['claude']
            self.assertNotIn('problem', shot)
            self.assertEqual(shot['session']['left'], 56)
            self.assertFalse((Path(folder) / 'limits-claude-debug.txt').exists())

    def test_the_claude_desktop_apps_own_copy_is_found_when_nothing_else_is(self):
        with tempfile.TemporaryDirectory() as home:
            base = Path(home) / 'Library/Application Support/Claude/claude-code'
            for version, layout in [('2.1.9', 'claude'), ('2.1.10', 'claude.app/Contents/MacOS/claude')]:
                binary = base / version / layout
                binary.parent.mkdir(parents=True)
                binary.write_text('#!/bin/sh\n')
                binary.chmod(0o755)
            self.assertIn('2.1.10', claude_desktop_cli(home))
            self.assertIsNone(claude_desktop_cli(Path(home) / 'empty'))

    def test_newer_claude_without_the_local_command_marker_is_still_accepted_only_with_zero_model_evidence(self):
        newer = {k: v for k, v in REPORT.items() if k != 'local_command'}
        newer.update({'usage': {'input_tokens': 0, 'output_tokens': 0}, 'modelUsage': {}})
        self.assertEqual(claude_usage_status_reading(newer)['session']['left'], 56)
        self.assertEqual(claude_usage_status_reading([newer][0])['week']['left'], 26)
        for broken in [{'modelUsage': {'haiku': {}}}, {'usage': {'input_tokens': 5, 'output_tokens': 0}}, {'num_turns': 1}, {'is_error': True}]:
            self.assertIsNone(claude_usage_status_reading({**newer, **broken}))
        no_evidence = {k: v for k, v in newer.items() if k not in ('usage', 'modelUsage')}
        self.assertIsNone(claude_usage_status_reading(no_evidence))

    def test_text_under_another_key_is_found_and_a_rejected_report_keeps_a_useful_sample(self):
        newer = {'num_turns': 0, 'total_cost_usd': 0, 'usage': {'input_tokens': 0, 'output_tokens': 0}, 'modelUsage': {},
                 'report': {'text': 'Current session: 10% used\nCurrent week (all models): 20% used'}}
        self.assertEqual(claude_usage_status_reading(newer)['week']['left'], 80)
        odd = {**newer, 'report': {'text': 'Something else entirely'}, 'result': 'Plan usage is not available'}
        with patch.dict(os.environ, {'RELAY_NO_CLAUDE_USAGE_POLL': ''}):
            run = lambda *a, **k: type('Result', (), {'returncode': 0, 'stdout': json.dumps(odd), 'stderr': ''})()
            self.assertIsNone(read_claude_usage_status('/bin/claude', run=run))
        self.assertIn('Plan usage is not available', read_claude_usage_status.sample)
        self.assertIn('keys:', read_claude_usage_status.sample)


# The real answer of a newer Claude Code to `claude -p /usage`: session costs, no plan limits.
COSTS_ONLY = {'is_error': False, 'num_turns': 0, 'total_cost_usd': 0, 'usage': {'input_tokens': 0, 'output_tokens': 0}, 'modelUsage': {},
              'subtype': 'success', 'type': 'result', 'local_command': 'usage',
              'result': 'Total cost:            $0.0000\nTotal duration (API):  0s\nTotal duration (wall): 0s\n'
                        'Total code changes:    0 lines added, 0 lines removed\nUsage:                 0 input, 0 output, 0 cache read, 0 cache write'}
PROBE = {'session': {'left': 70, 'resets_at': 99999}, 'week': {'left': 80, 'resets_at': 999999}}


class ClaudeCostsOnlyTests(unittest.TestCase):
    def fake_status(self, answer, costs_only=False):
        calls = []

        def status(binary):
            calls.append(binary)
            status.problem, status.sample, status.costs_only = ('lists costs' if answer is None else ''), 'sample', costs_only
            return answer
        status.problem = status.sample = ''
        return status, calls

    def test_the_costs_only_report_is_recognised_and_is_never_a_quota(self):
        self.assertIsNone(claude_usage_status_reading(COSTS_ONLY))
        run = lambda *a, **k: type('Result', (), {'returncode': 0, 'stdout': json.dumps(COSTS_ONLY), 'stderr': ''})()
        with patch.dict(os.environ, {'RELAY_NO_CLAUDE_USAGE_POLL': ''}):
            self.assertIsNone(read_claude_usage_status('/bin/claude', run=run))
        self.assertTrue(read_claude_usage_status.costs_only)
        self.assertIn('costs', read_claude_usage_status.problem)

    def test_plan_limits_from_usage_are_preferred_and_no_question_is_asked(self):
        status, _ = self.fake_status(claude_usage_status_reading(REPORT))
        asked = []
        reader = ClaudeUsage(status=status, probe=lambda b: asked.append(b), clock=lambda: 100)
        self.assertEqual(reader('/bin/claude')['session']['left'], 56)
        self.assertEqual((reader.source, reader.delays, asked), ('claude-usage-command', (60, 120), []))

    def test_when_usage_lists_costs_only_claude_is_asked_a_question_and_usage_is_skipped_for_hours(self):
        status, calls = self.fake_status(None, costs_only=True)
        now = [1000]
        reader = ClaudeUsage(status=status, probe=lambda b: PROBE, clock=lambda: now[0])
        self.assertEqual(reader('/bin/claude'), PROBE)
        self.assertEqual((reader.source, reader.delays, reader.problem), ('claude-code-probe', (900, 1800), ''))
        now[0] += 900
        reader('/bin/claude')
        self.assertEqual(len(calls), 1)
        now[0] += 6 * 3600
        reader('/bin/claude')
        self.assertEqual(len(calls), 2)

    def test_when_both_ways_fail_the_reason_is_given_and_the_retry_is_slow(self):
        status, _ = self.fake_status(None, costs_only=True)
        reader = ClaudeUsage(status=status, probe=lambda b: None, clock=lambda: 5)
        with patch.dict(os.environ, {'RELAY_NO_CLAUDE_PROBE': ''}):
            self.assertIsNone(reader('/bin/claude'))
        self.assertIn('lists costs', reader.problem)
        self.assertIn('did not return plan limits', reader.problem)
        self.assertEqual(reader.delays, (900, 600))
        with patch.dict(os.environ, {'RELAY_NO_CLAUDE_PROBE': '1'}):
            reader('/bin/claude')
        self.assertIn('RELAY_NO_CLAUDE_PROBE', reader.problem)

    def test_a_signed_out_claude_is_reported_as_such_and_retried_soon(self):
        from relay.limits import CLAUDE_SIGNED_OUT
        status, _ = self.fake_status(None, costs_only=True)

        def probe(binary):
            return None
        probe.problem = CLAUDE_SIGNED_OUT
        reader = ClaudeUsage(status=status, probe=probe, clock=lambda: 5)
        self.assertIsNone(reader('/bin/claude'))
        self.assertEqual(reader.problem, CLAUDE_SIGNED_OUT)
        self.assertEqual(reader.delays, (900, 90))

    def test_a_reading_from_a_question_stays_current_for_its_whole_refresh_interval(self):
        with tempfile.TemporaryDirectory() as folder:
            now = [1000]
            status, _ = self.fake_status(None, costs_only=True)
            store = Limits(Path(folder) / 'limits.json', lambda _: '/bin/claude', clock=lambda: now[0], read_codex=lambda _: None,
                           read_claude=ClaudeUsage(status=status, probe=lambda b: PROBE if now[0] < 2000 else None, clock=lambda: now[0]), start=lambda job: job())
            store.next['codex'] = float('inf')
            store.snapshot()
            now[0] += 600
            shot = store.snapshot()['claude']
            self.assertEqual((shot['session']['left'], shot['stale'], shot['source']), (70, False, 'claude-code-probe'))
            self.assertNotIn('problem', shot)
            now[0] += 700
            self.assertTrue(store.snapshot()['claude']['stale'])
