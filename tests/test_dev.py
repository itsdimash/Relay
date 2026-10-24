"""Exercise the development supervisor using a disposable copy, never real agents."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('relay_dev', ROOT / 'dev.py')
dev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev)


class DevTests(unittest.TestCase):
    def test_source_watcher_ignores_private_and_generated_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'server.py').write_text('# source')
            (root / 'dev.py').write_text('# supervisor')
            for name in ['data', 'tests', '__pycache__', 'node_modules', '.venv']:
                (root / name).mkdir()
                (root / name / 'ignore.py').write_text('ignored')
            self.assertEqual(set(dev.source_snapshot(root)), {'server.py'})

    def test_live_reload_and_deferred_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['server.py', 'dev.py']:
                shutil.copy2(ROOT / name, root / name)
            shutil.copytree(ROOT / 'static', root / 'static')
            shutil.copytree(ROOT / 'relay', root / 'relay')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            log = (root / 'supervisor.log').open('w+')
            process = subprocess.Popen([sys.executable, str(root / 'dev.py'), '--port', str(port)],
                                       cwd=root, stdout=log, stderr=log, start_new_session=True)
            def request(path, body=None, token=None):
                req = urllib.request.Request(f'http://127.0.0.1:{port}'+path,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={'Content-Type':'application/json','X-Relay-Token':token or ''})
                with urllib.request.urlopen(req, timeout=1) as response:
                    return json.load(response)
            def wait_until(predicate, seconds=12):
                deadline = time.monotonic()+seconds
                while time.monotonic() < deadline:
                    try:
                        value = predicate()
                        if value: return value
                    except (OSError, ValueError):
                        pass
                    time.sleep(.1)
                log.flush();log.seek(0)
                self.fail('Development check timed out. '+log.read()[-2500:])
            try:
                state = wait_until(lambda: request('/api/state'))
                token = state['token']; revision = state['dev']['revision']
                with (root/'static/style.css').open('a') as f:f.write('\n/* dev test */\n')
                wait_until(lambda: request('/api/dev')['revision'] != revision)
                self.assertEqual(request('/api/state')['token'], token, 'Static edits must not restart Python')
                request('/api/run', {'demo':True}, token)
                wait_until(lambda: request('/api/dev')['busy'])
                with (root/'relay/workflow.py').open('a') as f:f.write('\n# development restart test\n')
                deadline = time.monotonic()+1.5
                while time.monotonic() < deadline:
                    self.assertEqual(request('/api/state')['token'], token, 'Active task must not be interrupted')
                    time.sleep(.15)
                newer = wait_until(lambda: (s if (s:=request('/api/state'))['token'] != token else None))
                self.assertEqual(newer['runs'][0]['status'], 'done')
                self.assertNotEqual(newer['dev']['revision'], revision)
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                    try: process.wait(timeout=12)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
                log.close()
