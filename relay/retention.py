"""Optional limits on how much chat history Relay keeps. Off by default: nothing is deleted unless a limit is chosen."""
import json
import os

from .contracts import TERMINAL
from .history import last_event_time

CHAT_CHOICES = (25, 50, 100, 250)
SIZE_CHOICES_MB = (1024, 2048, 5120)
NO_LIMIT = {'max_chats': None, 'max_mb': None}


def policy_path(app):
    return app.DATA / 'retention.json'


def read_policy(app):
    """A damaged file just means no limits: it is never a reason to delete anything."""
    policy = dict(NO_LIMIT)
    try:
        saved = json.loads(policy_path(app).read_text())
    except (OSError, ValueError):
        return policy
    if isinstance(saved, dict):
        if type(saved.get('max_chats')) is int and saved['max_chats'] in CHAT_CHOICES:
            policy['max_chats'] = saved['max_chats']
        if type(saved.get('max_mb')) is int and saved['max_mb'] in SIZE_CHOICES_MB:
            policy['max_mb'] = saved['max_mb']
    return policy


def set_policy(app, changes):
    """Change one or both limits (null removes a limit), then delete the oldest finished chats beyond them.
    With preview: true nothing is saved or deleted; the answer lists the chats that would go."""
    if not isinstance(changes, dict) or not {'max_chats', 'max_mb'} & set(changes):
        raise ValueError('Choose how many chats or how much space to keep.')
    for key, choices in (('max_chats', CHAT_CHOICES), ('max_mb', SIZE_CHOICES_MB)):
        if key in changes and changes[key] is not None and (type(changes[key]) is not int or changes[key] not in choices):
            raise ValueError('Choose one of the listed limits.')
    with app.LOCK:
        policy = dict(read_policy(app), **{key: changes[key] for key in NO_LIMIT if key in changes})
        if changes.get('preview') is True:
            return {'policy': policy, 'would_delete': len(plan(app, policy))}
        app.DATA.mkdir(parents=True, exist_ok=True)
        temporary = app.DATA / 'retention.tmp'
        temporary.write_text(json.dumps(policy, indent=2))
        temporary.replace(policy_path(app))
    return {'policy': policy, 'deleted': enforce(app)}


def folder_bytes(path):
    total = 0
    for folder, _, names in os.walk(path):
        for name in names:
            try:
                status = os.lstat(os.path.join(folder, name))
            except OSError:
                continue
            total += status.st_size
    return total


def chat_bytes(app, run_id):
    return sum(folder_bytes(path) for path in (app.DATA / 'runs' / run_id, app.DATA / 'baselines' / (run_id + '.git')) if path.is_dir() and not path.is_symlink())


def usage(app):
    with app.LOCK:
        ids = list(app.RUNS)
    sizes = [chat_bytes(app, run_id) for run_id in ids]
    return {'chats': len(ids), 'bytes': sum(sizes), 'policy': read_policy(app)}


def finished_chats(app):
    """Finished chats, oldest first."""
    with app.LOCK:
        found = []
        for run_id, run in app.RUNS.items():
            if isinstance(run, app.Run):
                if run.finished.is_set() and run.info['status'] in TERMINAL:
                    found.append((last_event_time(run.info), run_id))
            elif run.get('status') in TERMINAL:
                found.append((run.get('finished_at') or run.get('created', ''), run_id))
    return [run_id for _, run_id in sorted(found)]


def plan(app, policy, keep=()):
    """Which finished chats the limits would delete, oldest first. The newest finished chat and any chat in keep stay."""
    if not policy['max_chats'] and not policy['max_mb']:
        return []
    queue = finished_chats(app)
    protected = [run_id for run_id in queue if run_id in keep]
    queue = [run_id for run_id in queue if run_id not in keep]
    doomed = []
    with app.LOCK:
        everything = list(app.RUNS)
    if policy['max_chats']:
        total = len(everything)
        while total > policy['max_chats'] and len(queue) + len(protected) > 1 and queue:
            doomed.append(queue.pop(0))
            total -= 1
    if policy['max_mb']:
        sizes = {run_id: chat_bytes(app, run_id) for run_id in everything}
        total = sum(size for run_id, size in sizes.items() if run_id not in doomed)
        limit = policy['max_mb'] * 1024 * 1024
        while total > limit and len(queue) + len(protected) > 1 and queue:
            run_id = queue.pop(0)
            doomed.append(run_id)
            total -= sizes.get(run_id, 0)
    return doomed


def enforce(app, keep=()):
    """Delete the chats the limits call for."""
    deleted = []
    for run_id in plan(app, read_policy(app), keep):
        try:
            app.delete_history(run_id)
        except ValueError:
            continue
        deleted.append(run_id)
    return deleted
