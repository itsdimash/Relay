"""System notifications for tasks that run while the person is away."""
import json
import os
import subprocess
import sys
import threading


def applescript(title, message, sound='Glass'):
    quoted = [json.dumps(str(value), ensure_ascii=False) for value in (message, title, sound)]
    return 'display notification {} with title {} sound name {}'.format(*quoted)


def send(title, message, sound='Glass'):
    """Show a macOS notification. Best effort: it must never affect a task, so every failure is swallowed."""
    if sys.platform != 'darwin' or os.environ.get('RELAY_NO_NOTIFY'):
        return False
    def show():
        try:
            subprocess.run(['osascript', '-e', applescript(title, message, sound)], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
    threading.Thread(target=show, daemon=True).start()
    return True
