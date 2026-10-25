"""Compact live status for the notch panel: what is running, who is working, and what needs approval."""
import datetime as dt
import json

from .contracts import TERMINAL

STEP_SETS = {
    'build': [('observing', 'Inspect'), ('awaiting_clarification', 'Clarify'), ('awaiting_approval', 'Approve'),
              ('building', 'Build'), ('reviewing', 'Review'), ('fixing', 'Refine'), ('done', 'Result')],
    'plan': [('observing', 'Inspect'), ('awaiting_clarification', 'Clarify'), ('done', 'Plan')],
    'observe': [('observing', 'Observe'), ('done', 'Report')],
}

# Who is doing the work at each status. "you" means Relay is waiting for the person.
ACTORS = {
    'queued': 'relay', 'preparing': 'relay', 'observing': 'observer', 'awaiting_clarification': 'you',
    'awaiting_approval': 'you', 'building': 'builder', 'fixing': 'builder', 'reviewing': 'reviewer',
}

QUIET_KINDS = {'stage'}


def clip(text, limit):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def steps_for(info):
    steps = STEP_SETS.get(info.get('mode') or 'build', STEP_SETS['build'])
    status = info.get('status')
    keys = [key for key, _ in steps]
    current = keys.index(status) if status in keys else -1
    result = []
    for index, (key, label) in enumerate(steps):
        if status == 'done':
            state = 'done'
        elif current < 0:
            state = 'todo'
        else:
            state = 'done' if index < current else 'current' if index == current else 'todo'
        result.append({'key': key, 'label': label, 'state': state})
    return result


def last_message(info):
    for event in reversed(info.get('events') or []):
        if event.get('kind') in QUIET_KINDS or not event.get('message'):
            continue
        return {'agent': event.get('agent', ''), 'message': clip(event['message'], 160)}
    return None


def seconds_since(started, now):
    try:
        return max(0, int((now - dt.datetime.fromisoformat(started)).total_seconds()))
    except (TypeError, ValueError):
        return 0


def agent_activity(info, role):
    """Expose one saved update per role, never infer activity from a provider name."""
    for event in reversed(info.get('events') or []):
        if event.get('role') != role or not event.get('message') or event.get('kind') == 'stage':
            continue
        message = event['message']
        if event.get('kind') == 'message':
            try:
                report = json.loads(message)
                if isinstance(report, dict):
                    message = report.get('overview') or report.get('summary') or message
            except (ValueError, TypeError):
                pass
        return {'message': clip(message, 240), 'kind': event.get('kind', ''), 'time': event.get('time', '')}
    return None


def result_counts(info):
    reports = info.get('builder_reports') or []
    latest = max(enumerate(reports), key=lambda item: (item[1].get('round', 0), item[0]))[1] if reports else {}
    checks = latest.get('checks') or []
    return {
        'files': len(info.get('files') or []),
        'findings': len(info.get('findings') or []),
        'checks': {status: sum(check.get('status') == status for check in checks)
                   for status in ('passed', 'failed', 'not_run')},
        'checks_source': 'builder',
    }


def recent_events(info):
    saved = []
    for index, event in enumerate(info.get('events') or []):
        if event.get('kind') not in ('stage', 'message', 'note', 'control', 'review', 'error') or not event.get('message'):
            continue
        message = event['message']
        try:
            report = json.loads(message)
            if isinstance(report, dict):
                message = report.get('overview') or report.get('summary') or message
        except (ValueError, TypeError):
            pass
        text = clip(message, 240)
        role = event.get('role', '')
        if saved and saved[-1]['message'] == text and saved[-1]['role'] == role:
            continue
        saved.append({'id': str(index), 'time': event.get('time', ''), 'kind': event.get('kind', ''),
                      'role': role, 'agent': event.get('agent') or role.capitalize() or 'Relay', 'message': text})
    return saved[-12:][::-1]


def describe_run(info, now):
    status = info.get('status', '')
    running = status not in TERMINAL
    team = (info.get('team') or {}).get('roles') or {}
    result = {
        'id': info.get('id', ''),
        'title': clip(info.get('conversation_title') or info.get('task'), 120),
        'status': status,
        'running': running,
        'demo': bool(info.get('demo')),
        'mode': info.get('mode') or 'build',
        'round': info.get('round', 0),
        'max_rounds': info.get('max_rounds', 0),
        'actor': ACTORS.get(status),
        'paused': bool(info.get('paused')),
        'steps': steps_for(info),
        'last': last_message(info),
        'elapsed': seconds_since(info.get('created'), now) if running else 0,
        'team': {role: {'provider': (team.get(role) or {}).get('provider', ''), 'model': (team.get(role) or {}).get('model', '')}
                 for role in ('observer', 'builder', 'reviewer')},
        'activities': {role: agent_activity(info, role) for role in ('observer', 'builder', 'reviewer')},
        'result': result_counts(info),
        'recent_events': recent_events(info),
        'plan': None,
        'question': None,
    }
    if status == 'awaiting_approval' and info.get('plan') and not info.get('approved_plan_id'):
        plan = info['plan']
        result['plan'] = {'id': plan.get('id', ''), 'summary': clip(plan.get('summary'), 420),
                          'checks': [clip(check, 110) for check in (plan.get('acceptance_checks') or [])[:3]]}
    if status == 'awaiting_clarification':
        result['question'] = 'The Observer needs a few details. Open Relay to answer.'
    if not running:
        result['summary'] = clip(info.get('summary'), 260)
    return result


def snapshot(runs, now=None):
    """Pick the run to show: one still running, otherwise the newest. runs are plain state dictionaries."""
    now = now or dt.datetime.now(dt.timezone.utc)
    visible = list(runs)
    if not visible:
        return {'run': None}
    running = [info for info in visible if info.get('status') not in TERMINAL]
    chosen = max(running or visible, key=lambda info: info.get('created', ''))
    return {'run': describe_run(chosen, now)}
