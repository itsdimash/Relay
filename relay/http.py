"""Localhost HTTP routing, request protections, and allowlisted static assets."""
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from .contracts import TERMINAL
from . import notch


class Handler(BaseHTTPRequestHandler):
    """HTTP adapter; app is bound by Application, never stored in module globals."""
    # Browsers open idle connections ahead of time; do not let one keep a thread (and shutdown) waiting forever.
    timeout = 30

    def log_message(self, *_):
        pass

    def respond(self, data, status=200, content_type='application/json', download=None):
        body = json.dumps(data, ensure_ascii=False).encode() if content_type == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        if download:
            self.send_header('Content-Disposition', f'attachment; filename="{download}"')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get('Host', '') in [f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}']

    def do_GET(self):
        if not self.valid_host():
            return self.respond({'error': 'Invalid host'}, 403)
        path = urlparse(self.path).path
        if path == '/api/state':
            return self.respond({'runs': sorted(self.app.states(), key=lambda x: x['created'], reverse=True), 'token': self.app.TOKEN, 'dev': self.app.dev_metadata()})
        if path == '/api/dev':
            metadata = self.app.dev_metadata()
            return self.respond(metadata if metadata else {'error': 'Development mode is disabled'}, 200 if metadata else 404)
        if path == '/api/export':
            try:
                run_id = parse_qs(urlparse(self.path).query).get('run', [''])[0]
                folder = self.app.history_path(run_id)
                with self.app.LOCK:
                    run = self.app.RUNS.get(run_id)
                    info = run.info if isinstance(run, self.app.Run) else run
                    if not info:
                        return self.respond({'error': 'Chat not found.'}, 404)
                    if info['status'] not in TERMINAL or isinstance(run, self.app.Run) and not run.finished.is_set():
                        return self.respond({'error': 'Wait for the task to finish before exporting.'}, 409)
                    build = info if info.get('mode', 'build') == 'build' else next((t for t in reversed(info.get('turns', [])) if t.get('mode') == 'build'), {})
                    if not build.get('export_complete'):
                        return self.respond({'error': 'No complete export was saved for this task. Inspect its working copy.'}, 409)
                    patch = folder / 'changes.patch'
                    if folder.is_symlink() or patch.is_symlink() or not patch.resolve().is_relative_to(folder.resolve()):
                        raise ValueError('Invalid export path.')
                    return self.respond(patch.read_bytes(), content_type='application/octet-stream', download=f'relay-{run_id}.patch')
            except (ValueError, OSError):
                return self.respond({'error': 'Export not found.'}, 404)
        if path == '/api/image':
            try:
                query = parse_qs(urlparse(self.path).query)
                with self.app.LOCK:
                    run = self.app.RUNS.get(query.get('run',[''])[0])
                    info = run.info if isinstance(run,self.app.Run) else run
                    if not info:raise ValueError('Chat not found.')
                    image_id = query.get('image',[''])[0]
                    image_path = self.app.saved_image_path(info,image_id)
                    metadata = next(image for image in info['attachments'] if image['id']==image_id)
                    return self.respond(image_path.read_bytes(),content_type=metadata['mime'])
            except (ValueError,OSError):return self.respond({'error':'Image not found.'},404)
        if path == '/api/models':
            return self.respond(self.app.model_catalog())
        if path == '/api/notch':
            with self.app.LOCK:
                infos = [run.info if isinstance(run, self.app.Run) else run for run in self.app.RUNS.values()]
                data = notch.snapshot(infos)
            data['token'] = self.app.TOKEN
            return self.respond(data)
        if path == '/api/update':
            return self.respond(self.app.updater.public())
        if path == '/api/teams':
            try:
                return self.respond(self.app.team_presets())
            except (ValueError, OSError) as error:
                return self.respond({'error': str(error)}, 400)
        if path == '/api/projects':
            try:
                return self.respond(self.app.project_choices())
            except (ValueError, OSError) as error:
                return self.respond({'error': str(error)}, 400)
        if path == '/api/connections':
            return self.respond(self.app.tool_status())
        files = {'/review.js': ('review.js', 'text/javascript; charset=utf-8'), '/review.css': ('review.css', 'text/css; charset=utf-8'), '/markdown.js': ('markdown.js', 'text/javascript; charset=utf-8'), '/report.css': ('report.css', 'text/css; charset=utf-8'), '/sidebar.css': ('sidebar.css', 'text/css; charset=utf-8'), '/relay.svg': ('relay.svg', 'image/svg+xml'), '/favicon.ico': ('favicon.ico', 'image/x-icon'), '/favicon.png': ('favicon.png', 'image/png'), '/apple-touch-icon.png': ('apple-touch-icon.png', 'image/png'), '/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        modules = ('recovery', 'clarification', 'api', 'attachments', 'constants', 'conversation', 'dom', 'findings', 'history', 'notifications', 'projects', 'state', 'tasks', 'teams', 'updates', 'notch-room')
        files.update({f'/js/{name}.js': (f'js/{name}.js', 'text/javascript; charset=utf-8') for name in modules})
        files['/recovery.css'] = ('recovery.css', 'text/css; charset=utf-8')
        files['/clarification.css'] = ('clarification.css', 'text/css; charset=utf-8')
        files['/notifications.css'] = ('notifications.css', 'text/css; charset=utf-8')
        files['/workspace.css'] = ('workspace.css', 'text/css; charset=utf-8')
        files['/motion.css'] = ('motion.css', 'text/css; charset=utf-8')
        files['/brand.css'] = ('brand.css', 'text/css; charset=utf-8')
        files['/notch'] = ('notch.html', 'text/html; charset=utf-8')
        files['/notch.css'] = ('notch.css', 'text/css; charset=utf-8')
        files['/notch.js'] = ('notch.js', 'text/javascript; charset=utf-8')
        files['/fonts/geologica.woff2'] = ('fonts/geologica.woff2', 'font/woff2')
        files['/fonts/jetbrains-mono.woff2'] = ('fonts/jetbrains-mono.woff2', 'font/woff2')
        if path in files:
            name, mime = files[path]
            return self.respond((self.app.ROOT / 'static' / name).read_bytes(), content_type=mime)
        return self.respond({'error': 'Not found'}, 404)

    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-Relay-Token') != self.app.TOKEN:
            return self.respond({'error': 'Reload the dashboard to reconnect.'}, 403)
        origin = self.headers.get('Origin')
        if origin and origin not in [f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}']:
            return self.respond({'error': 'Invalid origin'}, 403)
        try:
            path = urlparse(self.path).path
            length = int(self.headers.get('Content-Length', 0))
            limit = 24 * 1024 * 1024 if path in ('/api/run','/api/followup') else 128000
            if not 0 < length <= limit:
                raise ValueError('Request exceeds the allowed size.')
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('Request body must be a JSON object.')
            path = urlparse(self.path).path
            if path == '/api/recover':
                return self.respond(self.app.recover_run(payload.get('id'), payload.get('checkpoint_id')), 201)
            if path == '/api/teams/save':
                return self.respond(self.app.save_team_preset(payload.get('team'), payload.get('id')), 201)
            if path == '/api/history/delete':
                return self.respond(self.app.delete_history(payload.get('id')))
            if path == '/api/history/restore':
                return self.respond(self.app.restore_history(payload.get('id')))
            if path == '/api/projects/save':
                return self.respond(self.app.save_project(payload.get('name'), payload.get('path')), 201)
            if path == '/api/projects/remove':
                self.app.remove_project(payload.get('id'))
                return self.respond({'ok': True})
            if path == '/api/folders':
                return self.respond(self.app.folder_choices(payload.get('path')))
            if path == '/api/update/install':
                if self.app.ACTIVE and not self.app.ACTIVE.finished.is_set():
                    raise ValueError('Finish or stop the running task before updating.')
                self.app.updater.install(self.app.quit_for_update)
                return self.respond({'ok': True, 'restarting': True})
            if path in ('/api/run', '/api/followup'):
                task = str(payload.get('task', '')).strip()
                demo = payload.get('demo') is True
                if not demo and not task:
                    raise ValueError('Describe the task first.')
                project = Path(str(payload.get('project', ''))).expanduser()
                if path == '/api/followup':
                    previous = self.app.report_source(payload.get('source_id'))
                    project = Path(previous.get('workspace') or previous['project'])
                if not demo and ((path != '/api/followup' and not str(payload.get('project', '')).strip()) or not project.is_dir()):
                    raise ValueError('Choose an existing project folder.')
                rounds, minutes = payload.get('rounds', 3), payload.get('minutes', 20)
                if type(rounds) is not int or type(minutes) is not int or not 0 <= rounds <= 5 or not 0 <= minutes <= 120:
                    raise ValueError('Choose 1–5 review rounds and 1–120 minutes, or Without limit (0).')
                with self.app.LOCK:
                    if self.app.ACTIVE and not self.app.ACTIVE.finished.is_set():
                        return self.respond({'error': 'A task is already running. Stop it before starting another.'}, 409)
                    source = self.app.report_source(payload.get('source_id')) if payload.get('source_id') is not None or path == '/api/followup' else None
                    if source and demo:
                        raise ValueError('Report actions require a real task.')
                    conversation = source if path == '/api/followup' else None
                    context = self.app.report_context(source, None if conversation else payload.get('finding_indexes')) if source else ''
                    if source and not conversation and payload.get('finding_indexes') is None:
                        raise ValueError('Select findings to carry into the new task.')
                    mode = 'observe' if conversation else payload.get('mode', 'build')
                    if conversation:
                        project = Path(source.get('workspace') or source['project'])
                        team = source.get('team')
                    else:
                        team = payload.get('team')
                        if source:
                            expected = Path(source.get('original_project', source['project'])).expanduser().resolve()
                            if project.resolve() != expected:
                                raise ValueError('Use the report’s original project for the selected findings.')
                    images = self.app.decode_images(payload.get('images', []))
                    if source:
                        images = self.app.inherited_images(source) + images
                    if demo and images:
                        raise ValueError('Examples do not use uploaded images.')
                    if len(task) > 10000:
                        raise ValueError('Keep the task under 10,000 characters.')
                    if self.app.SHUTTING_DOWN.is_set():
                        raise ValueError('Relay is shutting down. Restart it before starting a task.')
                    run = self.app.Run(task or 'Example: improve email validation', project, rounds, minutes, demo, team, mode, context=context, conversation=conversation, source={'id': source['id'], 'finding_indexes': payload.get('finding_indexes')} if source and not conversation else None, attachments=images)
                    self.app.RUNS[run.id] = run
                    self.app.ACTIVE = run
                    threading.Thread(target=run.execute, daemon=True).start()
                return self.respond({'id': run.id}, 201)
            with self.app.LOCK:
                run = self.app.RUNS.get(payload.get('id'))
            if not isinstance(run, self.app.Run) or run.info['status'] in TERMINAL:
                raise ValueError('This task is no longer running.')
            if path == '/api/answer-clarification':
                if run is not self.app.ACTIVE or run.finished.is_set():
                    raise ValueError('This task is no longer waiting for answers.')
                run.answer_clarification(payload.get('clarification_id'), payload.get('answers'))
            elif path == '/api/approve-plan':
                run.approve_plan(payload.get('plan_id'))
            elif path == '/api/stop':
                if run.info['status'] == 'awaiting_approval':
                    run.info['plan_rejected'] = True
                    run.info['summary'] = 'Plan rejected. No Builder was started.\n\n' + run.info['plan']['summary']
                run.stop_event.set()
                run.resume_event.set()
                threading.Thread(target=run.stop_process, daemon=True).start()
                run.emit('Relay', 'control', 'Stop requested.')
            elif path == '/api/pause':
                run.resume_event.clear()
                run.paused = True
                run.emit('Relay', 'control', 'Pause requested. The current step will finish; the next handoff will wait. The time limit continues.')
            elif path == '/api/resume':
                run.paused = False
                run.resume_event.set()
                run.emit('Relay', 'control', 'Handoffs resumed.')
            else:
                return self.respond({'error': 'Not found'}, 404)
            run.info['paused'] = run.paused
            run.save()
            return self.respond({'ok': True})
        except (ValueError, TypeError, OSError) as error:
            return self.respond({'error': str(error)}, 400)
