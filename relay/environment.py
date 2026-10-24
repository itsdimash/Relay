"""Make tools such as node, npm, python and git findable when Relay starts from Finder.

An app opened from Finder or the Dock inherits a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin).
Agents started by Relay inherit it too, so Homebrew, nvm or npm-installed tools would be missing.
"""
import os
from pathlib import Path
import subprocess

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
