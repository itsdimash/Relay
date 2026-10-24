"""Make tools such as node, npm, python and git findable when Relay starts from Finder.

An app opened from Finder or the Dock inherits a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin).
Agents started by Relay inherit it too, so Homebrew, nvm or npm-installed tools would be missing.
"""
import os
from pathlib import Path
import subprocess
import threading

STANDARD_DIRECTORIES = (
    '/opt/homebrew/bin',
    '/opt/homebrew/sbin',
    '/usr/local/bin',
    '/usr/local/sbin',
    '~/.local/bin',
    '~/.claude/local',
    '~/.npm-global/bin',
    '~/.bun/bin',
    '~/.cargo/bin',
)


def login_shell_path(shell=None, timeout=4, run=subprocess.run):
    """Return PATH as the user's login shell sees it, or '' if it cannot be read quickly."""
    shell = shell or os.environ.get('SHELL') or '/bin/zsh'
    if not Path(shell).is_file():
        return ''
    try:
        result = run([shell, '-ilc', 'printf %s "$PATH"'], capture_output=True, text=True,
                     timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ''
    if result.returncode:
        return ''
    # Interactive shells can print banners; the PATH is the last line.
    lines = result.stdout.strip().splitlines()
    return lines[-1].strip() if lines else ''


def augment_path(current, home=None, shell_path='', exists=os.path.isdir):
    """Merge the current PATH, the login shell's PATH and common tool folders, without duplicates."""
    home = str(Path.home() if home is None else home)
    wanted = [entry for entry in current.split(os.pathsep) if entry]
    wanted += [entry for entry in shell_path.split(os.pathsep) if entry]
    wanted += [entry.replace('~', home, 1) for entry in STANDARD_DIRECTORIES]
    merged, seen = [], set()
    for entry in wanted:
        if entry in seen:
            continue
        seen.add(entry)
        if entry in current.split(os.pathsep) or exists(entry):
            merged.append(entry)
    return os.pathsep.join(merged)


def prepare_environment(environment=None, read_login_path=login_shell_path):
    """Extend PATH in place for packaged launches. Returns the new PATH."""
    environment = os.environ if environment is None else environment
    environment['PATH'] = augment_path(environment.get('PATH', ''), shell_path=read_login_path())
    return environment['PATH']


def quick_prepare_environment(cache_file, environment=None, read_login_path=login_shell_path, start=None):
    """Like prepare_environment, but without making the launch wait for the user's shell.

    Reading PATH from an interactive login shell can take seconds (nvm, conda and other shell setup) and the
    engine would not answer until it finished. The answer from the last launch is kept in cache_file and used
    at once; a background thread asks the shell again and updates PATH when it differs. Only the very first
    launch, which has no cache yet, waits for the shell.
    """
    environment = os.environ if environment is None else environment
    cache_file = Path(cache_file)
    try:
        cached = cache_file.read_text().strip().splitlines()[-1].strip()
    except (OSError, IndexError):
        cached = ''

    def remember(path):
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(path + '\n')
        except OSError:
            pass

    if not cached:
        shell_path = read_login_path()
        if shell_path:
            remember(shell_path)
        environment['PATH'] = augment_path(environment.get('PATH', ''), shell_path=shell_path)
        return environment['PATH']

    environment['PATH'] = augment_path(environment.get('PATH', ''), shell_path=cached)

    def refresh():
        shell_path = read_login_path()
        if shell_path and shell_path != cached:
            remember(shell_path)
            environment['PATH'] = augment_path(environment.get('PATH', ''), shell_path=shell_path)

    if start is None:
        threading.Thread(target=refresh, name='login-path', daemon=True).start()
    else:
        start(refresh)
    return environment['PATH']
