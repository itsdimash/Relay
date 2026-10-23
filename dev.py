#!/usr/bin/env python3
"""Dependency-free development supervisor for Relay's existing Python server."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
EXCLUDED = {'data', 'tests', '__pycache__', '.git', '.venv', 'venv', 'node_modules'}


def source_snapshot(root=ROOT):
    files = {}
    for parent, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED and not d.startswith('.')]
        for name in names:
            path = Path(parent) / name
            if path.suffix == '.py' and path != root / 'dev.py':
                try:
                    stat = path.stat()
                    files[str(path.relative_to(root))] = (stat.st_mtime_ns, stat.st_size)
                except FileNotFoundError:
                    pass
    return files


def server_busy(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/dev', timeout=1) as response:
            status = json.load(response)
            return bool(status['busy'])
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        # Don't interrupt a potentially active server whose status is unavailable.
        return True


def stop_child(process):
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.SIGINT)
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
    except ProcessLookupError:
        pass


def main():
    parser = argparse.ArgumentParser(description='Run Relay with Python auto-restart and browser auto-refresh.')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open', action='store_true', help='Open the dashboard at initial startup')
    args = parser.parse_args()
    env = os.environ.copy()
    env['RELAY_DEV'] = '1'
    command = [sys.executable, str(ROOT / 'server.py'), '--port', str(args.port)]
    def start(open_browser=False):
        print('[dev] Starting Relay…', flush=True)
        return subprocess.Popen(command + (['--open'] if open_browser else []), cwd=ROOT, env=env, start_new_session=True)
    previous = source_snapshot()
    pending = False
    waiting_notice = False
    changed_at = 0.0
    process = start(args.open)
    print('[dev] Python changes restart the server; static changes refresh the browser.', flush=True)
    print('[dev] Restarts wait for running tasks to finish. Press Control+C to stop.', flush=True)
    try:
        while True:
            time.sleep(.4)
            current = source_snapshot()
            if current != previous:
                previous = current
                pending = True
                changed_at = time.monotonic()
            if not pending or time.monotonic() - changed_at < .6:
                continue
            if process.poll() is None and server_busy(args.port):
                if not waiting_notice:
                    print('[dev] Change detected. Waiting for the current task to finish or be stopped…', flush=True)
                    waiting_notice = True
                continue
            print('[dev] Python change detected. Restarting…', flush=True)
            stop_child(process)
            process = start()
            pending = False
            waiting_notice = False
    except KeyboardInterrupt:
        print('\n[dev] Stopping Relay…', flush=True)
    finally:
        stop_child(process)


if __name__ == '__main__':
    main()
