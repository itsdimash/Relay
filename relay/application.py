"""Composition root: one explicit owner for state and bound service dependencies."""
from pathlib import Path
import secrets
import threading

from . import attachments, git_ops, history, lifecycle, limits, notes, providers, recovery, registry, reports
from . import contracts
from .http import Handler
from .updater import Updater, RESTART_STATUS
from .workflow import Run


class Application:
    """Services share this context; separate instances never share mutable task state.

    Pure helpers remain static functions. Stateful services take this instance as
    their first argument. Run/Handler subclasses bind it without singleton imports.
    Constructing an application performs no filesystem, network, or provider I/O.
    """

    def __init__(self, root, data=None):
        self.ROOT = Path(root).resolve()
        self.DATA = Path(data) if data is not None else self.ROOT / 'data'
        self.TOKEN = secrets.token_urlsafe(32)
        self.LOCK = threading.RLock()
        self.RUNS = {}
        self.ACTIVE = None
        self.SHUTTING_DOWN = threading.Event()
        self.updater = Updater()
        # How much of each tool's usage limits is left; reads nothing until the first screen asks.
        self.limits = limits.Limits(self.DATA / 'limits.json', providers.executable)

        class TaskRun(Run):
            app = self

        class RequestHandler(Handler):
            app = self

        self.Run = TaskRun
        self.Handler = RequestHandler

    @staticmethod
    def quit_for_update():
        """Exit shortly after the HTTP response is sent; the native app sees RESTART_STATUS and quits too."""
        import os
        threading.Timer(0.8, lambda: os._exit(RESTART_STATUS)).start()

    DEFAULT_TEAM = contracts.DEFAULT_TEAM
    IMAGE_TYPES = contracts.IMAGE_TYPES
    MAX_IMAGE_BYTES = contracts.MAX_IMAGE_BYTES
    PROVIDERS = contracts.PROVIDERS
    ROLES = contracts.ROLES
    SCHEMA = contracts.SCHEMA
    Stopped = contracts.Stopped
    TASK_MODES = contracts.TASK_MODES
    TERMINAL = contracts.TERMINAL

    # Report validation, summaries, follow-up context, and timestamps.
    now = staticmethod(reports.now)
    source_findings = staticmethod(reports.source_findings)
    report_context = staticmethod(reports.report_context)
    reported_checks = staticmethod(reports.reported_checks)
    report_metadata = staticmethod(reports.report_metadata)
    validate_questions = staticmethod(reports.validate_questions)
    validate_review = staticmethod(reports.validate_review)

    # Git inspection and complete patch export; never stage into the real index.
    git = staticmethod(git_ops.git)
    capture_file_reviews = staticmethod(git_ops.capture_file_reviews)
    complete_patch = staticmethod(git_ops.complete_patch)
    git_common_directory = staticmethod(git_ops.git_common_directory)

    # Provider discovery, capability-limited commands, and response adapters.
    executable = staticmethod(providers.executable)
    model_catalog = staticmethod(providers.model_catalog)
    validate_team = staticmethod(providers.validate_team)
    provider_command = staticmethod(providers.provider_command)
    tool_status = staticmethod(providers.tool_status)

    # Saved projects, team presets, and folder browsing.
    team_presets = registry.team_presets
    save_team_preset = registry.save_team_preset
    read_projects = registry.read_projects
    project_choices = registry.project_choices
    save_project = registry.save_project
    write_projects = registry.write_projects
    remove_project = registry.remove_project
    folder_choices = staticmethod(registry.folder_choices)

    # Quick notes and to-dos shown in the notch panel.
    read_notes = notes.read_notes
    write_notes = notes.write_notes
    add_note = notes.add_note
    set_note_done = notes.set_done
    remove_note = notes.remove_note

    # Image validation and task-scoped attachment access.
    decode_images = staticmethod(attachments.decode_images)
    saved_image_path = attachments.saved_image_path
    inherited_images = attachments.inherited_images

    # Saved conversation loading, snapshots, and recoverable Trash.
    report_source = history.report_source
    load_runs = history.load_runs
    history_path = history.history_path
    delete_history = history.delete_history
    restore_history = history.restore_history
    states = history.states

    # Checkpoint admission and preserved-workspace validation.
    require_recovery_approval = staticmethod(recovery.require_recovery_approval)
    recovery_option = staticmethod(recovery.recovery_option)
    validate_recovery_workspace = recovery.validate_recovery_workspace
    recover_run = recovery.recover_run

    # Server startup, development metadata, instance locking, and shutdown.
    dev_metadata = lifecycle.dev_metadata
    acquire_instance_lock = lifecycle.acquire_instance_lock
    main = lifecycle.main
