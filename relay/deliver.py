"""The Deliver shelf of the notch panel: files waiting to be dragged somewhere else.

Only the paths are saved (one small JSON file in the app's data folder). The files themselves are never copied,
moved or read; the panel just remembers where they are, so the shelf costs no disk space and nothing is duplicated.
"""
import datetime as dt
import json
import os
import shutil
import threading
import uuid
import zipfile
from pathlib import Path

from .reports import now

MAX_ITEMS = 100
MAX_PATH = 4096
DEFAULT_SETTINGS = {'remove_after_drop': False, 'auto_catch': False, 'expire_hours': 0}
FLAG_KEYS = ('remove_after_drop', 'auto_catch')
EXPIRY_CHOICES = (0, 1, 6, 24, 168)  # hours a file may stay on the shelf; 0 means as long as you like
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
        forget_files(app, [item for item in items if item['id'] in ids])
        return [describe(item) for item in remaining]


def clear_items(app):
    with app.LOCK:
        items = app.read_deliver_items()  # an unreadable file is reported, never overwritten
        app.write_deliver_items([])
        forget_files(app, items)
        return []


def zips_folder(app):
    return app.DATA / 'deliver-zips'


def forget_files(app, items):
    """A zip that Relay made is deleted once it leaves the shelf. Nothing else is ever deleted: a shelf item is only a path."""
    root = os.path.normpath(zips_folder(app))
    for item in items:
        folder = os.path.dirname(item['path'])
        if os.path.dirname(folder) != root:
            continue
        for remove, target in ((os.remove, item['path']), (os.rmdir, folder)):
            try:
                remove(target)
            except OSError:
                pass  # already moved away by a drop, or not empty: leave it


def unique_name(name, used):
    candidate, number = name, 1
    stem, dot, extension = name.rpartition('.') if '.' in name.strip('.') else (name, '', '')
    while candidate in used:
        number += 1
        candidate = f'{stem} ({number}){dot}{extension}'
    used.add(candidate)
    return candidate


def add_to_zip(archive, source, name):
    if not source.is_dir():
        archive.write(source, name)
        return
    archive.write(source, name)  # the folder itself, so an empty one survives
    for current, folders, files in os.walk(source):
        folders.sort()
        for entry in folders + sorted(files):
            path = os.path.join(current, entry)
            if not os.path.exists(path) or not (os.path.isdir(path) or os.path.isfile(path)):
                continue  # a broken link or a socket has nothing to pack
            archive.write(path, os.path.join(name, os.path.relpath(path, source)))


def make_zip(app, item_ids):
    """Pack the chosen shelf items (files and folders) into one zip and put it on the shelf, ready to be dragged out.

    The originals stay where they are and on the shelf. The zip lives in the data folder and is deleted
    when it is taken off the shelf.
    """
    if not isinstance(item_ids, list) or not item_ids or not all(isinstance(item_id, str) for item_id in item_ids):
        raise ValueError('Choose what to zip.')
    with app.LOCK:
        chosen = [item for item in app.read_deliver_items() if item['id'] in item_ids]
    sources = [Path(item['path']) for item in chosen if os.path.lexists(item['path'])]
    if not sources:
        raise ValueError('Those files are no longer there.')
    folder = zips_folder(app) / uuid.uuid4().hex[:8]
    name = f'{sources[0].name}.zip' if len(sources) == 1 else f'Files {dt.datetime.now():%Y-%m-%d %H.%M.%S}.zip'
    target = folder / name
    try:
        folder.mkdir(parents=True)
        used = set()
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
            for source in sources:
                add_to_zip(archive, source, unique_name(source.name, used))
        items = add_paths(app, [str(target)])
    except OSError as error:
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError(f'The zip could not be made: {error.strerror or error.__class__.__name__}.')
    except ValueError:
        shutil.rmtree(folder, ignore_errors=True)  # the shelf is full, or its list cannot be read
        raise
    return {'items': items, 'zip': os.path.normpath(target)}


def expire_items(app, current=None):
    """Take files that have been on the shelf longer than the chosen time off it. The files themselves are never touched."""
    hours = read_settings(app)['expire_hours']
    if not hours:
        return []
    limit = (current or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(hours=hours)

    def too_old(item):
        try:
            added = dt.datetime.fromisoformat(item['added'])
        except (KeyError, TypeError, ValueError):
            return False
        return (added if added.tzinfo else added.replace(tzinfo=dt.timezone.utc)) < limit

    with app.LOCK:
        try:
            items = app.read_deliver_items()
        except ValueError:
            return []
        old = [item for item in items if too_old(item)]
        if not old:
            return []
        gone = {item['id'] for item in old}
        app.write_deliver_items([item for item in items if item['id'] not in gone])
        forget_files(app, old)
        return sorted(gone)


def read_settings(app):
    """How the shelf behaves. A damaged settings file just means the defaults: nothing precious is kept in it."""
    path = app.DATA / 'deliver-settings.json'
    settings = dict(DEFAULT_SETTINGS)
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        return settings
    if isinstance(saved, dict):
        for key in FLAG_KEYS:
            if isinstance(saved.get(key), bool):
                settings[key] = saved[key]
        if type(saved.get('expire_hours')) is int and saved['expire_hours'] in EXPIRY_CHOICES:
            settings['expire_hours'] = saved['expire_hours']
    return settings


def set_settings(app, remove_after_drop=None, auto_catch=None, expire_hours=None):
    """Change one or more choices; a choice left out stays as it was."""
    changes = {'remove_after_drop': remove_after_drop, 'auto_catch': auto_catch, 'expire_hours': expire_hours}
    changes = {key: value for key, value in changes.items() if value is not None}
    if not changes:
        raise ValueError('Choose on or off.')
    if any(type(value) is not bool for key, value in changes.items() if key in FLAG_KEYS):
        raise ValueError('Choose on or off.')
    if 'expire_hours' in changes and (type(changes['expire_hours']) is not int or changes['expire_hours'] not in EXPIRY_CHOICES):
        raise ValueError('Choose how long files may stay: never, 1, 6, 24 or 168 hours.')
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
    """Every few seconds, for as long as the engine runs: catch new downloads and let old shelf items go."""
    def watch():
        while not app.SHUTTING_DOWN.wait(interval):
            try:
                app.catcher.step()
                app.expire_deliver()
            except Exception:
                app.catcher.problem = 'unreadable'  # one bad look must never end the watching
    thread = threading.Thread(target=watch, name='downloads-watcher', daemon=True)
    thread.start()
    return thread
