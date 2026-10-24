"""Saved conversation loading, snapshots, and recoverable Trash."""
import json
from .contracts import TERMINAL


def report_source(app, source_id):
    if not isinstance(source_id, str):
        raise ValueError('Choose a saved report.')
    source = app.RUNS.get(source_id)
    if isinstance(source, app.Run):
        if not source.finished.is_set():
            raise ValueError('Wait for this task to finish saving.')
        source = source.info
    if not source or (source.get('status') not in ('done', 'needs_attention') and not (source.get('status') in TERMINAL and source.get('turns'))) or (not source.get('summary') and not source.get('turns')) or source.get('demo'):
        raise ValueError('Choose a completed real report with a saved result.')
    return json.loads(json.dumps(source))


def load_runs(app):
    app.DATA.mkdir(parents=True, exist_ok=True)
    for path in (app.DATA / 'runs').glob('*/state.json'):
        try:
            info = json.loads(path.read_text())
            if info['status'] not in TERMINAL:
                info['interrupted_stage'] = info['status']
                info['status'] = 'interrupted'
                info['summary'] = 'Coordinator restarted. Changes are preserved. Continue from the saved checkpoint when available.'
                if info.get('recovery_attempts') and info['recovery_attempts'][-1].get('status') == 'running':
                    info['recovery_attempts'][-1].update(status='interrupted', finished_at=app.now())
                path.write_text(json.dumps(info, indent=2))
            app.RUNS[info['id']] = info
        except (OSError, ValueError, KeyError):
            pass


def history_path(app, run_id, trash=False):
    if not isinstance(run_id, str) or len(run_id) != 12 or any(c not in '0123456789abcdef' for c in run_id):
        raise ValueError('Invalid chat id.')
    return app.DATA / ('trash' if trash else 'runs') / run_id


def delete_history(app, run_id):
    source = app.history_path(run_id)
    destination = app.history_path(run_id, trash=True)
    with app.LOCK:
        run = app.RUNS.get(run_id)
        if run is None:
            raise ValueError('Chat was not found.')
        info = run.info if isinstance(run, app.Run) else run
        if info['status'] not in TERMINAL:
            raise ValueError('Stop the running task before deleting its history.')
        if isinstance(run, app.Run) and not run.finished.is_set():
            raise ValueError('This task is still finishing. Try again in a moment.')
        if source.is_symlink() or not source.is_dir() or destination.exists():
            raise ValueError('Chat history cannot be moved safely.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        del app.RUNS[run_id]
    return {'id': run_id, 'message': 'Chat moved to local Trash. Working-copy files are preserved.'}


def restore_history(app, run_id):
    source = app.history_path(run_id, trash=True)
    destination = app.history_path(run_id)
    with app.LOCK:
        if run_id in app.RUNS or destination.exists() or source.is_symlink() or not source.is_dir():
            raise ValueError('This chat cannot be restored.')
        info = json.loads((source / 'state.json').read_text())
        if info.get('id') != run_id or info.get('status') not in TERMINAL:
            raise ValueError('Invalid saved chat record.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        app.RUNS[run_id] = info
    return {'id': run_id}


def states(app):
    with app.LOCK:
        snapshots = []
        for run in app.RUNS.values():
            info = json.loads(json.dumps(run.info if isinstance(run, app.Run) else run))
            info['worker_finished'] = run.finished.is_set() if isinstance(run, app.Run) else True
            info['recovery'] = app.recovery_option(info)
            snapshots.append(info)
        return snapshots
