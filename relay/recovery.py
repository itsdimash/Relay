"""Checkpoint admission and preserved-workspace validation."""
from pathlib import Path
import subprocess
import threading
from .contracts import TASK_MODES


def require_recovery_approval(info):
    workflow, plan = info.get('workflow', {}), info.get('plan')
    if (not plan or info.get('approved_plan_id') != plan.get('id')
            or workflow.get('approved_plan') != plan or not info.get('plan_approved_at')):
        raise ValueError('A matching, explicitly approved plan is required before continuing edits or review.')


def recovery_option(info):
    workflow = info.get('workflow', {})
    limit_reached = info.get('status') == 'needs_attention' and workflow.get('step') == 'limit'
    if (info.get('status') not in ('failed', 'interrupted', 'stopped') and not limit_reached) or info.get('demo'):
        return None
    labels = dict(observe='Retry observation', chat='Retry reply', clarify='Continue questions', refine='Retry plan update',
                  approve='Return to plan approval', report='Finish saved report', build='Continue build',
                  review='Retry review', decide='Finish saved review', limit='Fix the remaining findings')
    if info.get('plan_rejected'):
        return dict(available=False, reason='This plan was rejected. Start a new task when you are ready.')
    if workflow.get('version') != 1 or workflow.get('step') not in labels or not workflow.get('id'):
        return dict(available=False, reason='This task has no supported recovery checkpoint. Its saved work is still available.')
    if workflow['step'] in ('build', 'review', 'decide', 'limit'):
        try: require_recovery_approval(info)
        except ValueError as error: return dict(available=False, reason=str(error))
    completed = []
    if workflow.get('observation'): completed.append('Observation saved')
    if info.get('approved_plan_id'): completed.append('Explicit plan approval saved')
    reports = info.get('builder_reports', [])
    if reports: completed.append(f'{len(reports)} Builder report(s) saved')
    if workflow['step'] == 'decide': completed.append('Review result saved')
    if workflow['step'] == 'limit': completed.append('Review limit reached; changes and open findings saved')
    return dict(available=True, checkpoint_id=workflow['id'], step=workflow['step'],
                label=labels[workflow['step']], completed=completed)


def validate_recovery_workspace(app, info):
    folder = app.history_path(info['id'])
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('The saved task folder is unavailable. Restore it before continuing.')
    workspace = Path(info.get('workspace', ''))
    if not info.get('workspace') or workspace.is_symlink() or not workspace.is_dir():
        raise ValueError('The preserved working copy is missing or is a link. Restore it before continuing.')
    if info['mode'] == 'build' and info['workflow'].get('repository'):
        # Older tasks built in a separate Git worktree.
        expected = app.DATA / 'workspaces' / info['id']
        if workspace.resolve() != expected.resolve() or app.git(workspace, 'rev-parse', '--show-toplevel').strip() != str(workspace.resolve()):
            raise ValueError('The saved working copy no longer matches this task.')
        workflow = info['workflow']
        if app.git(workspace, 'rev-parse', 'HEAD').strip() != workflow.get('base_commit') or app.git_common_directory(workspace) != workflow.get('repository'):
            raise ValueError('The working copy commit or repository changed. Keep your changes and start a new task.')
    elif info['mode'] == 'build':
        if workspace.resolve() != Path(info['project']).expanduser().resolve():
            raise ValueError('The edited folder no longer matches this task.')
        workflow = info['workflow']
        if workflow.get('baseline') and (not Path(workflow['baseline']).is_dir() or app.git(workspace, 'rev-parse', 'HEAD', shadow=workflow['baseline']).strip() != workflow.get('base_commit')):
            raise ValueError('The saved baseline of your folder is missing or changed. Keep your changes and start a new task.')
    elif workspace.resolve() != Path(info['project']).expanduser().resolve():
        raise ValueError('The inspected folder no longer matches this task.')


def recover_run(app, run_id, checkpoint_id, minutes=None, rounds=None):
    with app.LOCK:
        if app.SHUTTING_DOWN.is_set(): raise ValueError('Relay is shutting down.')
        if app.ACTIVE and not app.ACTIVE.finished.is_set():
            raise ValueError('Wait for the active task to finish before recovering another task.')
        source = app.RUNS.get(run_id)
        if isinstance(source, app.Run):
            if not source.finished.is_set(): raise ValueError('Wait for this task to finish saving.')
            if source.process and source.process.poll() is None: raise ValueError('The previous agent has not exited yet.')
            info = source.info
        else:
            info = app.run_info(run_id)
        if not info: raise ValueError('Task not found.')
        option = app.recovery_option(info)
        if not option or not option.get('available'): raise ValueError((option or {}).get('reason', 'This task cannot be recovered.'))
        if checkpoint_id != option['checkpoint_id']: raise ValueError('This recovery checkpoint is stale. Refresh the chat.')
        try:
            app.validate_recovery_workspace(info)
        except subprocess.TimeoutExpired:
            raise ValueError('Working-copy checks timed out. No recovery was started; try again when the folder is available.')
        app.validate_team(info['team'])
        if info.get('mode') not in TASK_MODES or type(info.get('max_rounds')) is not int or not 0 <= info['max_rounds'] <= 50:
            raise ValueError('Invalid saved workflow settings.')
        if info['workflow']['step'] in ('build', 'review', 'decide'):
            index = info['workflow'].get('round')
            if type(index) is not int or index < 1 or info['max_rounds'] and index > info['max_rounds']:
                raise ValueError('The saved step exceeds the configured review-round limit.')
        if type(info.get('minutes')) is not int or not 0 <= info['minutes'] <= 120:
            raise ValueError('Invalid saved time limit.')
        if info['workflow']['step'] == 'limit':
            index = info['workflow'].get('round')
            if type(rounds) is not int or not 0 <= rounds <= 5 or type(index) is not int or index < 1:
                raise ValueError('Choose 1–5 more review rounds, or Without limit (0).')
            info = dict(info, max_rounds=0 if rounds == 0 else index + rounds)
        if minutes is not None:
            if type(minutes) is not int or not 0 <= minutes <= 120:
                raise ValueError('Choose 1–120 minutes, or Without limit (0).')
            info = dict(info, minutes=minutes)
        run = app.Run.recover(info)
        run.save()
        app.RUNS[run.id] = run; app.ACTIVE = run
        threading.Thread(target=run.execute, kwargs={'recovering': True}, daemon=True).start()
        return {'id': run.id}
