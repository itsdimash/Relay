"""In-app updates for the packaged macOS app.

Relay checks the project's latest GitHub release, and when the person agrees it downloads the
new Relay.app, verifies its checksum, swaps it in after the app quits, and opens it again.
Source runs (no RELAY_APP_VERSION) never update themselves.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request

REPOSITORY = 'itsdimash/Relay'
LATEST_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
ASSET = 'Relay-macOS-arm64.zip'
RESTART_STATUS = 75  # the native shell treats this exit code as "quit for an update"
CHECK_TTL = 6 * 60 * 60
MAX_DOWNLOAD = 400 * 1024 * 1024

_VERSION = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)')


def parse_version(text):
    match = _VERSION.match(str(text or '').strip())
    return tuple(int(part) for part in match.groups()) if match else None


def pick_asset(release, name):
    for asset in release.get('assets') or []:
        if asset.get('name') == name and str(asset.get('browser_download_url', '')).startswith('https://'):
            return asset['browser_download_url']
    return ''


def _fetch_json(url, opener=urllib.request.urlopen, timeout=8):
    request = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'Relay-updater'})
    with opener(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def describe(current, release):
    """Pure comparison of the running version with a release payload."""
    latest = parse_version(release.get('tag_name'))
    installed = parse_version(current)
    url = pick_asset(release, ASSET)
    available = bool(latest and installed and latest > installed and url)
    return {
        'enabled': bool(installed),
        'current': current or '',
        'latest': '.'.join(map(str, latest)) if latest else '',
        'available': available,
        'notes_url': release.get('html_url', '') if available else '',
    }


class Updater:
    def __init__(self, environment=None, fetch=_fetch_json, clock=time.time):
        self.environment = os.environ if environment is None else environment
        self.fetch = fetch
        self.clock = clock
        self._cached = None
        self._checked = 0.0

    @property
    def current(self):
        return self.environment.get('RELAY_APP_VERSION', '')

    @property
    def app_path(self):
        value = self.environment.get('RELAY_APP_PATH', '')
        return Path(value) if value else None

    def check(self, force=False):
        if not parse_version(self.current):
            return {'enabled': False, 'current': '', 'latest': '', 'available': False, 'notes_url': ''}
        if self._cached is not None and not force and self.clock() - self._checked < CHECK_TTL:
            return self._cached
        try:
            release = self.fetch(LATEST_URL)
        except Exception:
            # Offline or rate limited: stay quiet, try again on the next check.
            return self._cached or {'enabled': True, 'current': self.current, 'latest': '', 'available': False, 'notes_url': ''}
        self._cached = describe(self.current, release)
        self._cached['_release'] = release
        self._checked = self.clock()
        return self._cached

    def public(self, force=False):
        return {key: value for key, value in self.check(force).items() if not key.startswith('_')}

    def install_problem(self):
        """Why this copy cannot replace itself, or '' when it can."""
        path = self.app_path
        if not path or not path.name.endswith('.app'):
            return 'Updates are only available in the Relay app.'
        if '/AppTranslocation/' in str(path) or str(path).startswith('/Volumes/'):
            return 'Move Relay to your Applications folder first, then update.'
        if not path.is_dir():
            return 'Relay could not find itself on disk.'
        if not os.access(path.parent, os.W_OK):
            return 'Relay cannot write to its folder. Move it to Applications, or download the new version manually.'
        return ''

    def download(self, url, destination, opener=urllib.request.urlopen):
        request = urllib.request.Request(url, headers={'User-Agent': 'Relay-updater'})
        digest, size = hashlib.sha256(), 0
        with opener(request, timeout=30) as response, open(destination, 'wb') as out:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise ValueError('The update download is unexpectedly large.')
                digest.update(chunk)
                out.write(chunk)
        return digest.hexdigest()

    def expected_checksum(self, release, opener=urllib.request.urlopen):
        url = pick_asset(release, ASSET + '.sha256')
        if not url:
            return ''
        request = urllib.request.Request(url, headers={'User-Agent': 'Relay-updater'})
        with opener(request, timeout=15) as response:
            text = response.read(4096).decode('utf-8', 'replace')
        match = re.match(r'\s*([0-9a-fA-F]{64})', text)
        return match.group(1).lower() if match else ''

    def stage(self, workspace):
        """Download, verify and unpack the latest release into workspace; return the new Relay.app path."""
        info = self.check(force=True)
        release = info.get('_release') or {}
        if not info.get('available'):
            raise ValueError('Relay is already up to date.')
        archive = Path(workspace) / ASSET
        actual = self.download(pick_asset(release, ASSET), archive)
        expected = self.expected_checksum(release)
        if not expected:
            raise ValueError('The release has no checksum, so Relay will not install it.')
        if actual != expected:
            raise ValueError('The download did not match its checksum. Nothing was changed.')
        unpacked = Path(workspace) / 'unpacked'
        unpacked.mkdir()
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive), str(unpacked)], check=True, timeout=300)
        new_app = unpacked / 'Relay.app'
        if not (new_app / 'Contents' / 'MacOS').is_dir():
            raise ValueError('The update did not contain Relay.app.')
        return new_app

    @staticmethod
    def swap_script(app_pid, old_app, new_app, workspace):
        """Shell script that waits for Relay to quit, swaps the bundles and reopens the app."""
        quote = lambda value: "'" + str(value).replace("'", "'\\''") + "'"
        return '\n'.join([
            '#!/bin/sh',
            f'PID={int(app_pid)}',
            f'OLD={quote(old_app)}',
            f'NEW={quote(new_app)}',
            f'WORK={quote(workspace)}',
            'BACKUP="$OLD.previous"',
            'i=0',
            'while kill -0 "$PID" 2>/dev/null && [ "$i" -lt 100 ]; do sleep 0.3; i=$((i+1)); done',
            'rm -rf "$BACKUP"',
            'if mv "$OLD" "$BACKUP"; then',
            '  if mv "$NEW" "$OLD"; then',
            '    /usr/bin/xattr -cr "$OLD" 2>/dev/null',
            '    rm -rf "$BACKUP"',
            '  else',
            '    mv "$BACKUP" "$OLD"',
            '  fi',
            'fi',
            '/usr/bin/open "$OLD"',
            'rm -rf "$WORK"',
            '',
        ])

    def install(self, quit_app):
        """Prepare the swap, start the helper, then ask the app to quit. Raises ValueError with a person-readable reason."""
        problem = self.install_problem()
        if problem:
            raise ValueError(problem)
        try:
            app_pid = int(self.environment.get('RELAY_APP_PID', ''))
        except ValueError:
            raise ValueError('Relay could not tell which app to replace.')
        workspace = tempfile.mkdtemp(prefix='relay-update-')
        try:
            new_app = self.stage(workspace)
            script = Path(workspace) / 'swap.sh'
            script.write_text(self.swap_script(app_pid, self.app_path, new_app, workspace))
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            subprocess.Popen(['/bin/sh', str(script)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise
        quit_app()
