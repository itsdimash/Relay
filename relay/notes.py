"""Quick notes and to-dos for the notch panel, saved as one small JSON file in the app's data folder."""
import json
import uuid

from .reports import now

MAX_NOTES = 200
MAX_TEXT = 500
KINDS = ('note', 'todo')


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


def add_note(app, text, kind):
    if kind not in KINDS:
        raise ValueError('Choose a note or a to-do.')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Write something first.')
    text = ' '.join(text.split())
    if len(text) > MAX_TEXT:
        raise ValueError(f'Keep it under {MAX_TEXT} characters.')
    with app.LOCK:
        notes = app.read_notes()
        if len(notes) >= MAX_NOTES:
            raise ValueError('The list is full. Delete a few items first.')
        notes.insert(0, {'id': uuid.uuid4().hex, 'kind': kind, 'text': text, 'done': False, 'created': now()})
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
