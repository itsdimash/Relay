"""The Deliver shelf of the notch panel: files waiting to be dragged somewhere else.

Only the paths are saved (one small JSON file in the app's data folder). The files themselves are never copied,
moved or read; the panel just remembers where they are, so the shelf costs no disk space and nothing is duplicated.
"""
import json
import os
import threading
import uuid
from pathlib import Path

from .reports import now

MAX_ITEMS = 100
MAX_PATH = 4096
DEFAULT_SETTINGS = {'remove_after_drop': False, 'auto_catch': False}
SETTING_KEYS = tuple(DEFAULT_SETTINGS)
# Names a browser or downloader gives a file while it is still arriving. Hidden files (a dot first) are skipped too.
INCOMPLETE_SUFFIXES = ('.crdownload', '.download', '.part', '.partial', '.tmp', '.temp', '.opdownload', '.aria2')


def read_items(app):
    path = app.DATA / 'deliver.json'
    if not path.exists():
        return []
    try:
        items = json.loads(path.read_text())
    except (OSError, ValueError):
        raise ValueError('The Deliver list could not be read.')
    if not isinstance(items, list):
        raise ValueError('The Deliver list could not be read.')
    return [item for item in items if isinstance(item, dict) and isinstance(item.get('id'), str) and isinstance(item.get('path'), str)]


def write_items(app, items):
    app.DATA.mkdir(parents=True, exist_ok=True)
    temporary = app.DATA / 'deliver.tmp'
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2))
    temporary.replace(app.DATA / 'deliver.json')


def describe(item):
    """What the panel shows for one saved path. A file that was moved or deleted since is reported as missing."""
    path = Path(item['path'])
    info = {'id': item['id'], 'path': item['path'], 'name': path.name or item['path'], 'added': item.get('added'),
            'kind': 'file', 'size': None, 'missing': False}
    try:
        stat = path.stat()
    except (OSError, ValueError):
        info['missing'] = True
        return info
    if path.is_dir():
        info['kind'] = 'folder'
    else:
        info['size'] = stat.st_size
    return info


def listing(app):
    return [describe(item) for item in app.read_deliver_items()]


def add_paths(app, paths):
    """Put dropped files on the shelf, newest first. A file that is already there stays where it is."""
    if not isinstance(paths, list) or not paths or not all(isinstance(path, str) for path in paths):
        raise ValueError('Drop at least one file.')
    with app.LOCK:
        items = app.read_deliver_items()
        known = {item['path'] for item in items}
        fresh = []
        for raw in paths[:MAX_ITEMS]:
            if not raw or len(raw) > MAX_PATH or not os.path.isabs(raw):
                continue
            path = os.path.normpath(raw)
            try:
                exists = os.path.lexists(path)
            except ValueError:
                exists = False
            if not exists or path in known:
                continue
            known.add(path)
            fresh.append({'id': uuid.uuid4().hex, 'path': path, 'added': now()})
        if not fresh and not any(os.path.normpath(raw) in known for raw in paths if isinstance(raw, str) and raw):
            raise ValueError('Those files could not be found.')
        if len(fresh) + len(items) > MAX_ITEMS:
            raise ValueError(f'The shelf holds {MAX_ITEMS} items. Clear a few first.')
        if fresh:
            app.write_deliver_items(fresh + items)
        return [describe(item) for item in fresh + items]


def remove_item(app, item_ids):
    """Take one item (an id) or several (a list of ids) off the shelf. The files themselves are never touched."""
    ids = [item_ids] if isinstance(item_ids, str) else item_ids
    if not isinstance(ids, list) or not ids or not all(isinstance(item_id, str) for item_id in ids):
        raise ValueError('Choose what to take off the shelf.')
    with app.LOCK:
        items = app.read_deliver_items()
        remaining = [item for item in items if item['id'] not in ids]
        if len(remaining) == len(items):
            raise ValueError('That item is no longer on the shelf.')
        app.write_deliver_items(remaining)
        return [describe(item) for item in remaining]


def clear_items(app):
    with app.LOCK:
        app.read_deliver_items()  # an unreadable file is reported, never overwritten
        app.write_deliver_items([])
        return []


def read_settings(app):
    """How the shelf behaves. A damaged settings file just means the defaults: nothing precious is kept in it."""
    path = app.DATA / 'deliver-settings.json'
    settings = dict(DEFAULT_SETTINGS)
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        return settings
    if isinstance(saved, dict):
        for key in SETTING_KEYS:
            if isinstance(saved.get(key), bool):
                settings[key] = saved[key]
    return settings


def set_settings(app, remove_after_drop=None, auto_catch=None):
    """Change one or both choices; a choice left out stays as it was."""
    changes = {'remove_after_drop': remove_after_drop, 'auto_catch': auto_catch}
    changes = {key: value for key, value in changes.items() if value is not None}
    if not changes or any(type(value) is not bool for value in changes.values()):
        raise ValueError('Choose on or off.')
    with app.LOCK:
        settings = dict(read_settings(app), **changes)
        app.DATA.mkdir(parents=True, exist_ok=True)
        temporary = app.DATA / 'deliver-settings.tmp'
        temporary.write_text(json.dumps(settings, indent=2))
        temporary.replace(app.DATA / 'deliver-settings.json')
        return settings


class Catcher:
    """Watches the Downloads folder and puts each file that has finished arriving on the shelf.

    Only files that show up after catching was switched on are taken; what was already there is left alone, and so is
    anything the person has since taken off the shelf. A file counts as finished when its size and time did not change
    between two looks, so a download that is still growing, or one a browser has not yet renamed, is never picked up early.
    Folders inside Downloads are not looked into.
    """

    def __init__(self, app, folder=None):
        self.app = app
        self.folder = Path(folder) if folder else Path.home() / 'Downloads'
        self.known = None      # (name, time) of every file that is not news: set when catching is switched on
        self.pending = {}      # path -> (size, time) as of the previous look, for files that are new but may still be growing
        self.problem = None    # why the folder cannot be read, when it cannot: 'denied' or 'unreadable'

    def scan(self):
        files = []
        with os.scandir(self.folder) as entries:
            for entry in entries:
                name = entry.name
                if name.startswith('.') or name.lower().endswith(INCOMPLETE_SUFFIXES):
                    continue
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue  # gone since the folder was listed
                files.append((entry.path, name, stat.st_size, stat.st_mtime_ns))
        return files

    def step(self):
        """One look at the folder. Returns the paths that were put on the shelf by it."""
        if not read_settings(self.app)['auto_catch']:
            self.known, self.pending, self.problem = None, {}, None
            return []
        try:
            files = self.scan()
        except FileNotFoundError:
            files = []
        except PermissionError:
            self.problem = 'denied'
            return []
        except OSError:
            self.problem = 'unreadable'
            return []
        self.problem = None
        present = {(name, mtime) for _, name, _, mtime in files}
        if self.known is None:  # just switched on: everything here now is old news
            self.known, self.pending = present, {}
            return []
        self.known &= present
        fresh = {path: (size, mtime) for path, name, size, mtime in files if (name, mtime) not in self.known}
        steady = sorted((path for path, seen in fresh.items() if self.pending.get(path) == seen),
                        key=lambda path: fresh[path][1], reverse=True)
        self.pending = fresh
        if not steady:
            return []
        try:
            add_paths(self.app, steady)
        except ValueError:
            return []  # the shelf is full or unreadable right now; the same files are tried again at the next look
        for path in steady:
            self.known.add((Path(path).name, fresh[path][1]))
        self.pending = {path: seen for path, seen in fresh.items() if path not in steady}
        return steady


def watch_downloads(app, interval=2.0):
    """Look at the Downloads folder every few seconds for as long as the engine runs."""
    def watch():
        while not app.SHUTTING_DOWN.wait(interval):
            try:
                app.catcher.step()
            except Exception:
                app.catcher.problem = 'unreadable'  # one bad look must never end the watching
    thread = threading.Thread(target=watch, name='downloads-watcher', daemon=True)
    thread.start()
    return thread
