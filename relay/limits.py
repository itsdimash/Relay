"""How much of each tool's usage limits is left (the 5-hour and weekly windows).

Claude Code reports them with every request it makes (a rate_limit_event in its stream), so Relay records the
last one it saw. Codex answers a direct question through its app-server, which Relay asks now and then.
Both only exist on subscription sign-ins, and a reading can be old, so each carries the time it was taken.
"""
import functools
import json
import os
import subprocess
import tempfile
import threading
import time

CODEX_REFRESH_SECONDS = 90
CODEX_RETRY_SECONDS = 600
CLAUDE_REFRESH_SECONDS = 900   # Claude only reports usage when asked a question, so a reading is taken at most this often
CLAUDE_RETRY_SECONDS = 1800
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


def read_claude_limits(binary, timeout=60, run=subprocess.run):
    """Ask Claude one tiny question and read the usage it reports along with the answer.

    Claude Code only reports its limits while answering. The question is the cheapest model, no tools and an empty
    folder, so it reads nothing of yours. Returns the windows, or None if Claude did not report them.
    """
    if os.environ.get('RELAY_NO_CLAUDE_PROBE'):
        return None
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
        if isinstance(event, dict) and event.get('type') == 'rate_limit_event':
            found = claude_reading(event) or found
    return found


class Limits:
    """The latest readings for both tools, kept in memory and in a small file so they survive a restart."""

    def __init__(self, path, executable, clock=time.time, read_codex=read_codex_limits, read_claude=read_claude_limits, start=None):
        self.path = path
        self.executable = executable
        self.clock = clock
        self.readers = {'claude': read_claude, 'codex': read_codex}
        self.delays = {'claude': (CLAUDE_REFRESH_SECONDS, CLAUDE_RETRY_SECONDS), 'codex': (CODEX_REFRESH_SECONDS, CODEX_RETRY_SECONDS)}
        self.start = start or (lambda job: threading.Thread(target=job, name='limits', daemon=True).start())
        self.lock = threading.Lock()
        self.data = None
        self.next = {'claude': 0, 'codex': 0}
        self.busy = set()

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

    def _store(self, tool, windows):
        with self.lock:
            self._load()[tool] = {**windows, 'seen_at': int(self.clock())}
            self._save()

    def record_claude(self, event):
        """A reading that arrived with one of Relay's own Claude tasks."""
        windows = claude_reading(event)
        if windows:
            self._store('claude', windows)

    def refresh(self, tool):
        binary = self.executable(tool)
        windows = self.readers[tool](binary) if binary else None
        refresh_after, retry_after = self.delays[tool]
        with self.lock:
            self.busy.discard(tool)
            self.next[tool] = self.clock() + (refresh_after if windows else retry_after)
        if windows:
            self._store(tool, windows)

    def _maybe_refresh(self, tool):
        with self.lock:
            due = self.next[tool]
            if tool == 'claude':
                # A reading that arrived with a task is as good as one asked for.
                seen = (self._load().get('claude') or {}).get('seen_at')
                if isinstance(seen, (int, float)):
                    due = max(due, seen + CLAUDE_REFRESH_SECONDS)
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
            for name in ('session', 'week'):
                window = reading.get(name)
                if not isinstance(window, dict):
                    continue
                # A window that has reset since the reading is full again.
                if isinstance(window.get('resets_at'), int) and window['resets_at'] <= now:
                    window = {'left': 100, 'resets_at': None}
                item[name] = window
            result[tool] = item
        return result
