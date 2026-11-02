"""How much of each tool's usage limits is left (the 5-hour and weekly windows).

Claude Code reports them with every request it makes (a rate_limit_event in its stream), so Relay records the
last one it saw. Codex answers a direct question through its app-server, which Relay asks now and then.
Both only exist on subscription sign-ins, and a reading can be old, so each carries the time it was taken.
"""
import functools
import json
import os
import re
import subprocess
import tempfile
import threading
import time

CODEX_REFRESH_SECONDS = 90
CODEX_RETRY_SECONDS = 600
CLAUDE_REFRESH_SECONDS = 900   # Claude only reports usage when asked a question, so a reading is taken at most this often
CLAUDE_RETRY_SECONDS = 1800
CLAUDE_FRESH_SECONDS = 120
CLAUDE_PROBE_FRESH_SECONDS = 1200   # a reading taken by asking Claude a question is renewed every 15 minutes
CLAUDE_STATUS_RECHECK_SECONDS = 6 * 3600   # how long to skip /usage once this Claude version is known to list costs only
CLAUDE_SIGNED_OUT = 'Claude is signed out. Run `claude auth login` in a terminal, then check again.'
SESSION_MINUTES = 720  # windows up to 12 hours are the "session" window, longer ones the weekly one


def _left(used, percent=False):
    """Percent left, 0 to 100. Claude reports a fraction (0.91); Codex reports a plain percent, so 1 means 1% used.

    With percent=False a value above 1 is also read as a percent, in case Claude ever changes its format.
    """
    try:
        used = float(used)
    except (TypeError, ValueError):
        return None
    if used != used or used < 0:  # NaN or negative
        return None
    used_percent = used if (percent or used > 1) else used * 100
    return max(0, min(100, int(round(100 - used_percent))))


def _window(used, resets_at, percent=False):
    left = _left(used, percent)
    if left is None:
        return None
    try:
        resets_at = int(resets_at)
    except (TypeError, ValueError):
        resets_at = None
    return {'left': left, 'resets_at': resets_at}


def claude_reading(event):
    """Windows from a Claude rate_limit_event, or None when it carries no usable numbers."""
    info = event.get('rate_limit_info') if isinstance(event, dict) else None
    if not isinstance(info, dict):
        return None
    windows = info.get('unifiedWindows') if isinstance(info.get('unifiedWindows'), dict) else {}
    result = {}
    for key, name in (('five_hour', 'session'), ('seven_day', 'week')):
        item = windows.get(key)
        if isinstance(item, dict):
            window = _window(item.get('utilization'), item.get('resetsAt'))
            if window:
                result[name] = window
    if not result:  # an older shape: one window named by rateLimitType
        name = {'five_hour': 'session', 'seven_day': 'week'}.get(info.get('rateLimitType'))
        window = _window(info.get('utilization'), info.get('resetsAt'))
        if name and window:
            result[name] = window
    return result or None


def codex_reading(result):
    """Windows from the answer to account/rateLimits/read."""
    if not isinstance(result, dict):
        return None
    limits = result.get('rateLimits') if isinstance(result.get('rateLimits'), dict) else result
    found = {}
    for key in ('primary', 'secondary'):
        item = limits.get(key)
        if not isinstance(item, dict):
            continue
        window = _window(item.get('usedPercent', item.get('used_percent')), item.get('resetsAt', item.get('resets_at')), percent=True)
        if not window:
            continue
        minutes = item.get('windowDurationMins', item.get('window_minutes'))
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            minutes = SESSION_MINUTES if key == 'primary' else SESSION_MINUTES + 1
        found['session' if minutes <= SESSION_MINUTES else 'week'] = window
    return found or None


def read_codex_limits(binary, timeout=10, popen=subprocess.Popen):
    """Ask `codex app-server` for the rate limits. Returns the windows, or None if it cannot answer."""
    try:
        process = popen([binary, 'app-server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    except OSError:
        return None
    answer = {}

    def read():
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if isinstance(message, dict) and message.get('id') == 2:
                    answer['message'] = message
                    return
        except (OSError, ValueError):
            pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        for message in (
            {'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'relay', 'title': 'Relay', 'version': '1'}}},
            {'method': 'initialized', 'params': {}},
            {'id': 2, 'method': 'account/rateLimits/read'},
        ):
            process.stdin.write(json.dumps(message) + '\n')
            process.stdin.flush()
        reader.join(timeout)
    except (OSError, ValueError):
        pass
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        process.kill()
        try:
            process.wait(timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass
    message = answer.get('message')
    if not message or message.get('error'):
        return None
    return codex_reading(message.get('result'))


def read_claude_limits(binary, timeout=60, run=None):
    """Ask Claude one tiny question and read the usage it reports along with the answer.

    Claude Code only reports its limits while answering. The question is the cheapest model, no tools and an empty
    folder, so it reads nothing of yours. Returns the windows, or None if Claude did not report them.
    """
    reader = read_claude_limits
    reader.problem = ''
    if os.environ.get('RELAY_NO_CLAUDE_PROBE'):
        return None
    run = run or subprocess.run
    env = os.environ.copy()
    env.pop('CLAUDECODE', None)
    args = [binary, '-p', '--output-format', 'stream-json', '--verbose', '--restricted', '--tools', 'Read',
            '--allowedTools', 'Read', '--permission-mode', 'dontAsk', '--strict-mcp-config',
            '--mcp-config', '{"mcpServers":{}}', '--setting-sources', '', '--model', 'haiku']
    try:
        with tempfile.TemporaryDirectory(prefix='relay-limits-') as folder:
            result = run(args, input='Reply with the single word ok.', capture_output=True, text=True,
                         timeout=timeout, cwd=folder, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    found = None
    for line in (result.stdout or '').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get('type') == 'rate_limit_event':
            found = claude_reading(event) or found
        elif event.get('error') == 'authentication_failed' or (event.get('type') == 'result' and event.get('is_error')
                                                              and 'authenticate' in str(event.get('result'))):
            reader.problem = CLAUDE_SIGNED_OUT
    return found


ANSI_ESCAPES = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')
USAGE_LABELS = (('session', r'Current session'), ('week', r'Current week(?: \(all models\))?(?!\s*\()'))


def _is_local_report(report):
    """True only for a report that came from Claude itself, with no model involved.

    Older versions mark it `local_command: usage`. Newer ones drop the marker, so zero turns, zero cost, an empty
    model list and zero tokens count as the same proof: a model cannot have written the text.
    """
    if not isinstance(report, dict) or report.get('is_error'):
        return False
    if report.get('num_turns') not in (0, None) or report.get('total_cost_usd') not in (0, None):
        return False
    if report.get('local_command') == 'usage':
        return True
    usage, models = report.get('usage'), report.get('modelUsage')
    if report.get('num_turns') != 0 or report.get('total_cost_usd') != 0 or models != {} or not isinstance(usage, dict):
        return False
    return all(usage.get(key) == 0 for key in ('input_tokens', 'output_tokens'))


def _usage_text(report):
    """The report's text: its `result`, or else any text in it that carries the usage lines."""
    if isinstance(report.get('result'), str):
        return report['result']
    found = []

    def walk(value):
        if isinstance(value, str):
            if 'Current session' in value or 'Current week' in value:
                found.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(report)
    return '\n'.join(found) or None


def claude_usage_status_reading(report):
    """Accept only Claude's built-in /usage report, never a model-authored answer.

    The marker is `local_command: usage` with no model turn and no cost. The wording around the numbers has
    changed between Claude versions, so the percentages are found inside each labelled block rather than on one
    exact line, and colour codes are ignored.
    """
    if not _is_local_report(report):
        return None
    text = _usage_text(report)
    if not text:
        return None
    text = ANSI_ESCAPES.sub('', text)
    windows = {}
    for name, label in USAGE_LABELS:
        found = re.search(r'^[ \t]*' + label + r'[^\r\n]*', text, re.MULTILINE)
        if not found:
            continue
        following = re.search(r'^[ \t]*Current ', text[found.end():], re.MULTILINE)
        block = text[found.start(): found.end() + (following.start() if following else 400)]
        match = re.search(r'(\d+(?:\.\d+)?)\s*%\s*used', block)
        if not match:
            continue
        used = float(match.group(1))
        if not 0 <= used <= 100:
            continue
        windows[name] = {'left': round(100 - used), 'resets_at': None}
        reset = re.search(r'[Rr]esets?\s*:?\s*([^\r\n]+)', block[match.end():])
        if reset:
            windows[name]['reset_label'] = reset.group(1).strip()[:120]
    return windows or None


def _usage_report(stdout):
    """The JSON report from Claude's output, even when a notice or a list of events surrounds it."""
    text = (stdout or '').strip()
    candidates = [text] + [line for line in reversed(text.splitlines()) if line.lstrip().startswith(('{', '['))]
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, list):
            value = next((item for item in value if isinstance(item, dict) and (item.get('local_command') == 'usage' or item.get('type') == 'result')), None)
        if isinstance(value, dict):
            return value
    return None


def read_claude_usage_status(binary, timeout=30, run=None):
    """The official local /usage command performs zero model turns and reads plan limits.

    Keep provider authentication inside Claude. No credentials, user prompts, project
    tools, settings, MCP servers, or conversational history are read by Relay.
    Unsupported versions and failed/unverified reports return no current reading, and
    `read_claude_usage_status.problem` says in plain words why (empty after a success).
    """
    reader = read_claude_usage_status
    reader.problem, reader.sample, reader.costs_only = '', '', False
    run = run or subprocess.run
    if os.environ.get('RELAY_NO_CLAUDE_USAGE_POLL'):
        reader.problem = 'Claude usage checks are turned off (RELAY_NO_CLAUDE_USAGE_POLL).'
        return None
    environment = os.environ.copy()
    environment.pop('CLAUDECODE', None)
    environment['LANG'] = 'en_US.UTF-8'
    environment['LC_ALL'] = 'en_US.UTF-8'
    args = [binary, '-p', '/usage', '--output-format', 'json', '--restricted',
            '--setting-sources', '', '--tools', '', '--permission-mode', 'dontAsk',
            '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}']
    try:
        with tempfile.TemporaryDirectory(prefix='relay-usage-status-') as folder:
            result = run(args, cwd=folder, env=environment, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        reader.problem = 'Claude did not answer the usage check in time.'
        return None
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as error:
        reader.problem = 'Relay could not start Claude to check usage (%s).' % (str(error)[:80] or type(error).__name__)
        return None
    stdout, stderr = getattr(result, 'stdout', '') or '', getattr(result, 'stderr', '') or ''
    reader.sample = ('stdout: ' + ANSI_ESCAPES.sub('', stdout)[:900] + '\nstderr: ' + ANSI_ESCAPES.sub('', stderr)[:600])
    if result.returncode != 0:
        first = next((line.strip() for line in ANSI_ESCAPES.sub('', stderr or stdout).splitlines() if line.strip()), '')
        reader.problem = 'Claude refused the usage check%s.' % (': ' + first[:100] if first else ' (exit code %s)' % result.returncode)
        return None
    report = _usage_report(stdout)
    if report is None:
        reader.problem = 'This version of Claude did not return a usage report. Update Claude Code.'
        return None
    windows = claude_usage_status_reading(report)
    if not windows:
        # Some versions answer `-p /usage` with session costs only (a local report that has no plan limits in it).
        reader.costs_only = _is_local_report(report) and 'Total cost' in (_usage_text(report) or '')
        reader.problem = ('This version of Claude lists costs, not plan limits, in /usage.' if reader.costs_only
                          else 'Claude returned a usage report Relay could not read.')
        # The start of the raw output is mostly counters; keep what matters for fixing the parser.
        reader.sample = 'keys: %s\nlocal_command: %r\nresult: %s' % (', '.join(map(str, report))[:400], report.get('local_command'),
                                                                   ANSI_ESCAPES.sub('', repr(_usage_text(report) or report.get('result')))[:1200])
    return windows


class ClaudeUsage:
    """Claude's plan usage: the free /usage report when it lists plan limits, otherwise a tiny question.

    Newer Claude versions answer `-p /usage` with session costs only. Claude still reports the plan windows
    alongside any answer, so the fallback asks one tiny question (see read_claude_limits) and reads them from that.
    That costs a little of your Claude usage, so it is done at most every 15 minutes, and /usage is not tried again
    for hours once a version is known to list costs only. `source`, `delays`, `problem` and `sample` describe the
    last reading for Limits.
    """

    def __init__(self, status=None, probe=None, clock=time.time):
        self.status = status or read_claude_usage_status
        self.probe = probe or read_claude_limits
        self.clock = clock
        self.status_after = 0
        self.source, self.delays, self.problem, self.sample = None, None, '', ''

    def __call__(self, binary):
        now = self.clock()
        self.problem = self.sample = ''
        if now >= self.status_after:
            windows = self.status(binary)
            if windows:
                self.source, self.delays = 'claude-usage-command', (60, 120)
                return windows
            self.problem, self.sample = getattr(self.status, 'problem', ''), getattr(self.status, 'sample', '')
            if getattr(self.status, 'costs_only', False):
                self.status_after = now + CLAUDE_STATUS_RECHECK_SECONDS
        windows = self.probe(binary)
        if windows:
            self.source, self.delays, self.problem = 'claude-code-probe', (CLAUDE_REFRESH_SECONDS, CLAUDE_RETRY_SECONDS), ''
            return windows
        self.delays = (CLAUDE_REFRESH_SECONDS, 600)
        if getattr(self.probe, 'problem', '') == CLAUDE_SIGNED_OUT:
            self.problem = CLAUDE_SIGNED_OUT   # the cause, not the symptom: nothing else will work until Claude is signed in
            self.delays = (CLAUDE_REFRESH_SECONDS, 90)   # so the numbers return soon after signing in
        elif os.environ.get('RELAY_NO_CLAUDE_PROBE'):
            self.problem = (self.problem or 'Claude did not list plan limits.') + ' Asking Claude a question is turned off (RELAY_NO_CLAUDE_PROBE).'
        else:
            self.problem = (self.problem + ' ' if self.problem else '') + 'Asking Claude a question did not return plan limits.'
        return None


class Limits:
    """The latest readings for both tools, kept in memory and in a small file so they survive a restart."""

    def __init__(self, path, executable, clock=time.time, read_codex=read_codex_limits, read_claude=read_claude_limits, start=None, reader_sources=None):
        self.path = path
        self.executable = executable
        self.clock = clock
        self.readers = {'claude': read_claude, 'codex': read_codex}
        self.reader_sources = reader_sources or {}
        self.delays = {'claude': (CLAUDE_REFRESH_SECONDS, CLAUDE_RETRY_SECONDS), 'codex': (CODEX_REFRESH_SECONDS, CODEX_RETRY_SECONDS)}
        self.start = start or (lambda job: threading.Thread(target=job, name='limits', daemon=True).start())
        self.lock = threading.Lock()
        self.data = None
        self.next = {'claude': 0, 'codex': 0}
        self.busy = set()
        self.problems = {}

    def _load(self):
        if self.data is None:
            try:
                saved = json.loads(self.path.read_text())
                self.data = saved if isinstance(saved, dict) else {}
            except (OSError, ValueError):
                self.data = {}
        return self.data

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data))
        except OSError:
            pass

    def _store(self, tool, windows, source=None):
        with self.lock:
            self._load()[tool] = {**windows, 'seen_at': int(self.clock()), **({'source': source} if source else {})}
            self._save()

    def record_claude(self, event):
        """A reading that arrived with one of Relay's own Claude tasks."""
        windows = claude_reading(event)
        if windows:
            self._store('claude', windows, source='claude-code-stream')

    def refresh(self, tool):
        binary = self.executable(tool)
        reader = self.readers[tool]
        windows = reader(binary) if binary else None
        if tool == 'claude':
            if windows:
                problem = ''
            elif not binary:
                problem = 'Relay could not find the Claude command-line tool. Install Claude Code or set RELAY_CLAUDE.'
            else:
                problem = getattr(reader, 'problem', '') or 'Claude did not report its usage.'
            self._note_problem(problem, getattr(reader, 'sample', '') if binary and not windows else '')
        if getattr(reader, 'delays', None):
            self.delays[tool] = reader.delays
        refresh_after, retry_after = self.delays[tool]
        with self.lock:
            self.busy.discard(tool)
            self.next[tool] = self.clock() + (refresh_after if windows else retry_after)
        if windows:
            self._store(tool, windows, source=getattr(reader, 'source', None) or self.reader_sources.get(tool))

    def _note_problem(self, problem, sample=''):
        """Keep the reason Claude's usage is missing, and the raw report, so the screen and the log can show why."""
        with self.lock:
            self.problems['claude'] = problem
        debug = self.path.with_name('limits-claude-debug.txt')
        try:
            if problem and sample:
                debug.parent.mkdir(parents=True, exist_ok=True)
                debug.write_text('%s\n%s\n' % (problem, sample))
            elif not problem:
                debug.unlink(missing_ok=True)
        except OSError:
            pass

    def _maybe_refresh(self, tool):
        with self.lock:
            due = self.next[tool]
            if tool == 'claude':
                # A reading that arrived with a task is as good as one asked for.
                seen = (self._load().get('claude') or {}).get('seen_at')
                if isinstance(seen, (int, float)):
                    due = max(due, seen + self.delays['claude'][0])
            if tool in self.busy or self.clock() < due:
                return
            self.busy.add(tool)
        self.start(functools.partial(self.refresh, tool))

    def snapshot(self):
        """What the screens show. Asking never waits for a tool: readings are refreshed in the background."""
        for tool in ('claude', 'codex'):
            self._maybe_refresh(tool)
        now = int(self.clock())
        with self.lock:
            data = json.loads(json.dumps(self._load()))
        result = {'now': now}
        for tool in ('claude', 'codex'):
            reading = data.get(tool)
            if not isinstance(reading, dict):
                result[tool] = None
                continue
            item = {'seen_at': reading.get('seen_at')}
            if reading.get('source'):
                item['source'] = reading['source']
            if tool == 'claude':
                seen = reading.get('seen_at')
                fresh = CLAUDE_PROBE_FRESH_SECONDS if reading.get('source') == 'claude-code-probe' else CLAUDE_FRESH_SECONDS
                item['stale'] = not isinstance(seen, (int, float)) or not 0 <= now - seen <= fresh
            for name in ('session', 'week'):
                window = reading.get(name)
                if not isinstance(window, dict):
                    continue
                # An expired reading cannot tell us whether another app has already used the new window.
                if isinstance(window.get('resets_at'), int) and window['resets_at'] <= now:
                    continue
                item[name] = window
            result[tool] = item
        with self.lock:
            problem = self.problems.get('claude')
        claude = result['claude']
        if problem and (claude is None or claude.get('stale') or not (claude.get('session') or claude.get('week'))):
            result['claude'] = {**(claude or {}), 'problem': problem}
        return result
