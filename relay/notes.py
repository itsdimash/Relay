"""Quick notes and to-dos for the notch panel, saved as one small JSON file in the app's data folder."""
import json
import time
import uuid

from .reports import now

MAX_NOTES = 200
MAX_TEXT = 500
KINDS = ('note', 'todo')
MAX_AHEAD_MS = 366 * 24 * 3600 * 1000
GRACE_MS = 60 * 1000  # a reminder typed at the very second it is due is still accepted


def read_notes(app):
    path = app.DATA / 'notes.json'
    if not path.exists():
        return []
    try:
        notes = json.loads(path.read_text())
    except (OSError, ValueError):
        raise ValueError('Saved notes could not be read.')
    if not isinstance(notes, list):
        raise ValueError('Saved notes could not be read.')
    return [note for note in notes if isinstance(note, dict) and isinstance(note.get('id'), str) and isinstance(note.get('text'), str)]


def write_notes(app, notes):
    app.DATA.mkdir(parents=True, exist_ok=True)
    temporary = app.DATA / 'notes.tmp'
    temporary.write_text(json.dumps(notes, ensure_ascii=False, indent=2))
    temporary.replace(app.DATA / 'notes.json')


def add_note(app, text, kind, due=None):
    if kind not in KINDS:
        raise ValueError('Choose a note or a to-do.')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Write something first.')
    text = ' '.join(text.split())
    if len(text) > MAX_TEXT:
        raise ValueError(f'Keep it under {MAX_TEXT} characters.')
    if due is not None:
        stamp = time.time() * 1000
        if type(due) is not int or due < stamp - GRACE_MS:
            raise ValueError('That reminder time has already passed.')
        if due > stamp + MAX_AHEAD_MS:
            raise ValueError('Set a reminder within the next year.')
    with app.LOCK:
        notes = app.read_notes()
        if len(notes) >= MAX_NOTES:
            raise ValueError('The list is full. Delete a few items first.')
        note = {'id': uuid.uuid4().hex, 'kind': kind, 'text': text, 'done': False, 'created': now()}
        if due is not None:
            note['due'] = due
            note['reminded'] = False
        notes.insert(0, note)
        app.write_notes(notes)
        return notes


def set_done(app, note_id, done):
    if type(done) is not bool:
        raise ValueError('Done must be true or false.')
    with app.LOCK:
        notes = app.read_notes()
        note = next((item for item in notes if item['id'] == note_id), None)
        if note is None:
            raise ValueError('That item no longer exists.')
        if note.get('kind') != 'todo':
            raise ValueError('Only to-dos can be ticked off.')
        note['done'] = done
        app.write_notes(notes)
        return notes


def remove_note(app, note_id):
    with app.LOCK:
        notes = app.read_notes()
        remaining = [item for item in notes if item['id'] != note_id]
        if len(remaining) == len(notes):
            raise ValueError('That item no longer exists.')
        app.write_notes(remaining)
        return remaining


def due_reminders(app):
    """Notes whose reminder time has come and that the notch has not announced yet."""
    try:
        notes = app.read_notes()
    except (ValueError, OSError):
        return []
    stamp = time.time() * 1000
    return [
        {'id': note['id'], 'text': note['text'], 'due': note['due']}
        for note in notes
        if type(note.get('due')) is int and not note.get('reminded') and not note.get('done') and note['due'] <= stamp
    ]


def mark_reminded(app, ids):
    if not isinstance(ids, list) or len(ids) > 50 or not all(isinstance(item, str) for item in ids):
        raise ValueError('Send the ids of the reminders that were shown.')
    with app.LOCK:
        notes = app.read_notes()
        changed = False
        for note in notes:
            if note['id'] in ids and not note.get('reminded'):
                note['reminded'] = True
                changed = True
        if changed:
            app.write_notes(notes)
        return notes
