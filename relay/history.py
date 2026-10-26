"""Saved conversation loading, snapshots, and permanent deletion."""
import json
from pathlib import Path
import shutil
from .contracts import TERMINAL


def report_source(app, source_id):
    if not isinstance(source_id, str):
        raise ValueError('Choose a saved report.')
    source = app.RUNS.get(source_id)
    if isinstance(source, app.Run):
        if not source.finished.is_set():
            raise ValueError('Wait for this task to finish saving.')
    source = app.run_info(source_id)
    if not source or (source.get('status') not in ('done', 'needs_attention') and not (source.get('status') in TERMINAL and source.get('turns'))) or (not source.get('summary') and not source.get('turns')) or source.get('demo'):
        raise ValueError('Choose a completed real report with a saved result.')
    return json.loads(json.dumps(source))


# What the history list needs about a chat. Everything else is loaded from disk only when a chat is opened.
LIGHT_FIELDS = ('id', 'status', 'task', 'created', 'demo', 'mode', 'conversation_title')


def count_events(folder):
    """Lines already in a chat's activity log: where a new turn's events begin."""
    try:
        with (Path(folder) / 'events.jsonl').open('rb') as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def read_events(folder, start=0):
    events = []
    try:
        with (Path(folder) / 'events.jsonl').open(encoding='utf-8', errors='replace') as f:
            for number, line in enumerate(f):
                if number < start:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue  # a half-written last line after a crash
                if isinstance(event, dict):
                    events.append(event)
    except OSError:
        pass
    return events


def last_event_time(info):
    for event in reversed(info.get('events') or []):
        if event.get('time'):
            return event['time']
    return info.get('created', '')


def summarize(info):
    """The small record kept in memory (and in summary.json) for a chat that is not open."""
    summary = {key: info[key] for key in LIGHT_FIELDS if key in info}
    summary['finished_at'] = last_event_time(info)
    summary['light'] = True
    return summary


def write_state(folder, info):
    """Save a chat. Events live only in events.jsonl; summary.json is written first so a crash never
    leaves a finished-looking summary next to a newer unfinished state."""
    folder = Path(folder)
    state = json.dumps({key: value for key, value in info.items() if key != 'events'}, ensure_ascii=False, indent=2)
    # state_bytes lets the next start notice a state.json that changed without its summary.
    summary = json.dumps({**summarize(info), 'state_bytes': len(state.encode('utf-8'))}, ensure_ascii=False)
    for name, text in (('summary', summary), ('state', state)):
        temp = folder / (name + '.tmp')
        temp.write_text(text)
        temp.replace(folder / (name + '.json'))


def load_full(app, run_id):
    folder = app.history_path(run_id)
    info = json.loads((folder / 'state.json').read_text())
    if 'events' not in info:  # older saves embedded the events in state.json
        info['events'] = read_events(folder, info.get('events_start', 0))
    return info


def run_info(app, run_id):
    """The complete state of a chat: the live task's own dictionary, or the saved files for one not in use."""
    with app.LOCK:
        run = app.RUNS.get(run_id)
        if isinstance(run, app.Run):
            return run.info
    if run is None:
        return None
    if not run.get('light'):
        return run
    try:
        return load_full(app, run_id)
    except (OSError, ValueError, KeyError):
        return None


def load_runs(app):
    app.DATA.mkdir(parents=True, exist_ok=True)
    # Finish deletions a crash interrupted, and drop the Trash folder older versions kept.
    for leftover in ('deleting', 'trash', 'queue/removed'):
        shutil.rmtree(app.DATA / leftover, ignore_errors=True)
    for path in (app.DATA / 'runs').glob('*/state.json'):
        try:
            summary = None
            try:
                summary = json.loads((path.parent / 'summary.json').read_text())
            except (OSError, ValueError):
                pass
            if (isinstance(summary, dict) and summary.get('light') and summary.get('id') == path.parent.name
                    and summary.get('status') in TERMINAL and summary.get('state_bytes') == path.stat().st_size):
                summary.pop('state_bytes', None)
                app.RUNS[summary['id']] = summary
                continue
            info = load_full(app, path.parent.name)
            if 'events_start' not in info:
                # Saved by an older version, which embedded the current turn's events: they are the log's last lines.
                info['events_start'] = max(0, count_events(path.parent) - len(info.get('events') or []))
            if info['status'] not in TERMINAL:
                info['interrupted_stage'] = info['status']
                info['status'] = 'interrupted'
                info['summary'] = 'Coordinator restarted. Changes are preserved. Continue from the saved checkpoint when available.'
                if info.get('recovery_attempts') and info['recovery_attempts'][-1].get('status') == 'running':
                    info['recovery_attempts'][-1].update(status='interrupted', finished_at=app.now())
            write_state(path.parent, info)
            app.RUNS[info['id']] = summarize(info)
        except (OSError, ValueError, KeyError):
            pass


def history_path(app, run_id):
    if not isinstance(run_id, str) or len(run_id) != 12 or any(c not in '0123456789abcdef' for c in run_id):
        raise ValueError('Invalid chat id.')
    return app.DATA / 'runs' / run_id


def delete_history(app, run_id):
    """Delete a finished chat for good: its conversation, prompts, logs, attachments and baseline.
    Your project folder (and any older working copy) is never touched."""
    source = app.history_path(run_id)
    pending = app.DATA / 'deleting' / run_id
    with app.LOCK:
        run = app.RUNS.get(run_id)
        if run is None:
            raise ValueError('Chat was not found.')
        info = run.info if isinstance(run, app.Run) else run
        if info['status'] not in TERMINAL:
            raise ValueError('Stop the running task before deleting its history.')
        if isinstance(run, app.Run) and not run.finished.is_set():
            raise ValueError('This task is still finishing. Try again in a moment.')
        if source.is_symlink() or not source.is_dir():
            raise ValueError('Chat history cannot be deleted safely.')
        # The rename hides the chat atomically; a crash before the cleanup below is finished at the next start.
        shutil.rmtree(pending, ignore_errors=True)
        pending.parent.mkdir(parents=True, exist_ok=True)
        source.rename(pending)
        del app.RUNS[run_id]
    shutil.rmtree(pending, ignore_errors=True)
    baseline = app.DATA / 'baselines' / (run_id + '.git')
    if not baseline.is_symlink():
        shutil.rmtree(baseline, ignore_errors=True)
    return {'id': run_id, 'message': 'Chat deleted. Your project files were not touched.'}


def states(app, selected=None):
    """Chats for the dashboard. Chats that are running, or open in the dashboard, are complete;
    every other chat is only its small summary, so each poll stays cheap however long the history is."""
    with app.LOCK:
        snapshots, need_disk = [], []
        for run_id, run in app.RUNS.items():
            if isinstance(run, app.Run):
                finished = run.finished.is_set()
                if finished and run.info['status'] in TERMINAL and run_id != selected:
                    info = summarize(run.info)
                else:
                    info = json.loads(json.dumps(run.info))
                    info['recovery'] = app.recovery_option(info)
                info['worker_finished'] = finished
            elif run.get('light'):
                if run_id == selected:
                    need_disk.append(len(snapshots))
                    info = dict(run)
                else:
                    info = dict(run)
                info['worker_finished'] = True
            else:
                info = json.loads(json.dumps(run))
                info['worker_finished'] = True
                info['recovery'] = app.recovery_option(info)
            snapshots.append(info)
        for index in need_disk:
            try:
                info = load_full(app, snapshots[index]['id'])
            except (OSError, ValueError, KeyError):
                continue
            info['worker_finished'] = True
            info['recovery'] = app.recovery_option(info)
            snapshots[index] = info
        return snapshots
