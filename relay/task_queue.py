"""Persistent task briefs. Admission is explicit and keeps the normal approval gate."""
import base64
import json
from pathlib import Path
import re
import threading
import uuid

MAX_TASKS = 20


def read_queue(app):
    path = app.DATA / 'queue.json'
    if not path.exists():
        return []
    try:
        items = json.loads(path.read_text())
        if not isinstance(items, list) or any(not isinstance(item, dict) or not re.fullmatch(r'[0-9a-f]{32}', str(item.get('id', ''))) for item in items):
            raise ValueError()
        return items
    except (ValueError, OSError):
        raise ValueError('The saved queue could not be read. Its contents have been preserved.')


def write_queue(app, items):
    app.DATA.mkdir(parents=True, exist_ok=True)
    temporary = app.DATA / 'queue.tmp'
    temporary.write_text(json.dumps(items, ensure_ascii=False))
    temporary.replace(app.DATA / 'queue.json')


def queue_snapshot(app):
    with app.LOCK:
        busy = bool(app.ACTIVE and not app.ACTIVE.finished.is_set())
        try:
            return {'items': read_queue(app), 'can_start': not busy and not app.SHUTTING_DOWN.is_set(), 'error': ''}
        except ValueError as error:
            return {'items': [], 'can_start': False, 'error': str(error)}


def parameters(app, payload):
    task = payload.get('task')
    if not isinstance(task, str) or not task.strip() or len(task.strip()) > 10000:
        raise ValueError('Describe a task using up to 10,000 characters.')
    project = payload.get('project')
    if not isinstance(project, str) or not project.strip() or not Path(project).expanduser().is_dir():
        raise ValueError('Choose an existing project folder.')
    mode = payload.get('mode', 'build')
    if mode not in app.TASK_MODES:
        raise ValueError('Choose a valid task mode.')
    rounds, minutes = payload.get('rounds', 0), payload.get('minutes', 0)
    if type(rounds) is not int or type(minutes) is not int or not 0 <= rounds <= 5 or not 0 <= minutes <= 120:
        raise ValueError('Choose valid review rounds and a time limit.')
    return dict(task=task.strip(), project=str(Path(project).expanduser().resolve()), mode=mode,
                rounds=rounds, minutes=minutes, auto=payload.get('auto') is True, team=app.validate_team(payload.get('team') or app.DEFAULT_TEAM))


def add_task(app, payload):
    with app.LOCK:
        if payload.get('demo'):
            raise ValueError('Examples cannot be queued as real tasks.')
        items = read_queue(app)
        if len(items) >= MAX_TASKS:
            raise ValueError('The queue holds up to 20 tasks. Start or remove one first.')
        settings = parameters(app, payload)
        images = app.decode_images(payload.get('images', []))
        context, source_record = '', None
        if payload.get('source_id') is not None:
            source = app.report_source(payload['source_id'])
            indexes = payload.get('finding_indexes')
            if indexes is None:
                raise ValueError('Select findings to carry into the queued task.')
            expected = Path(source.get('original_project', source['project'])).expanduser().resolve()
            if Path(settings['project']) != expected:
                raise ValueError('Use the report’s original project for these findings.')
            context = app.report_context(source, indexes)
            source_record = {'id': source['id'], 'finding_indexes': indexes}
            images = app.inherited_images(source) + images
        if len(images) > 4:
            raise ValueError('Attach up to four images, including inherited images.')
        ident = uuid.uuid4().hex
        entry = dict(settings, id=ident, created=app.now(), image_count=len(images))
        saved = dict(settings, context=context, source=source_record,
                     images=[{'name': image['name'], 'mime': image['mime'], 'data': base64.b64encode(image['raw']).decode()} for image in images])
        folder = app.DATA / 'queue'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (ident + '.json')).write_text(json.dumps(saved, ensure_ascii=False))
        write_queue(app, items + [entry])
        return queue_snapshot(app)


def remove_task(app, ident):
    with app.LOCK:
        items = read_queue(app)
        entry = next((item for item in items if item['id'] == ident), None)
        if entry is None:
            raise ValueError('This queued task no longer exists.')
        write_queue(app, [item for item in items if item['id'] != ident])
        # Keep a recoverable copy, matching Relay's local-history convention.
        original = app.DATA / 'queue' / (ident + '.json')
        if original.exists():
            trash = app.DATA / 'queue' / 'removed'
            trash.mkdir(exist_ok=True)
            original.replace(trash / original.name)
        return queue_snapshot(app)


def move_task(app, ident, direction):
    if type(direction) is not int or direction not in (-1, 1):
        raise ValueError('Choose a valid queue direction.')
    with app.LOCK:
        items = read_queue(app)
        index = next((i for i, item in enumerate(items) if item['id'] == ident), None)
        if index is None:
            raise ValueError('This queued task no longer exists.')
        target = index + direction
        if 0 <= target < len(items):
            items[index], items[target] = items[target], items[index]
            write_queue(app, items)
        return queue_snapshot(app)


def start_task(app, ident):
    with app.LOCK:
        if app.SHUTTING_DOWN.is_set():
            raise ValueError('Relay is shutting down. Restart it before starting a task.')
        if app.ACTIVE and not app.ACTIVE.finished.is_set():
            raise ValueError('Wait for the current task to finish before starting the next one.')
        items = read_queue(app)
        if not items or items[0]['id'] != ident:
            raise ValueError('Start the next task in the queue. Move a different task to the front first.')
        saved = json.loads((app.DATA / 'queue' / (ident + '.json')).read_text())
        settings = parameters(app, saved)  # Revalidate the folder and settings at admission.
        images = app.decode_images(saved.get('images', []))
        run = app.Run(settings['task'], Path(settings['project']), settings['rounds'], settings['minutes'],
                      team=settings['team'], mode=settings['mode'], auto=settings['auto'], context=saved.get('context', ''),
                      source=saved.get('source'), attachments=images)
        # The durable run exists before the brief is consumed. Nothing auto-resumes after restart.
        write_queue(app, items[1:])
        app.RUNS[run.id] = run
        app.ACTIVE = run
        threading.Thread(target=run.execute, daemon=True).start()
        return {'id': run.id, 'queue': queue_snapshot(app)}
