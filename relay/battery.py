"""Battery state for the notch, read from macOS with pmset. Never raises: a Mac without a battery, or a system without
pmset, simply has no reading."""
import re
import subprocess
import sys
import time

CACHE_SECONDS = 3  # the notch asks every second; pmset only needs to run now and then
_cache = {'at': None, 'value': None}


def parse(text):
    """The output of `pmset -g batt` -> {'percent', 'plugged', 'charging', 'charged'}, or None when there is no battery.

    Example:  Now drawing from 'AC Power'
               -InternalBattery-0 (id=4653155)	54%; charging; 1:12 remaining present: true"""
    text = text or ''
    first = text.splitlines()[0] if text.strip() else ''
    found = re.search(r'(\d{1,3})%;\s*([^;\n]+)', text)
    if not found:
        return None
    percent = min(100, int(found.group(1)))
    state = found.group(2).strip().lower()
    plugged = 'ac power' in first.lower()
    return {
        'percent': percent,
        'plugged': plugged,
        'charging': state in ('charging', 'finishing charge'),
        'charged': plugged and (state == 'charged' or percent >= 100),
    }


def snapshot(run=subprocess.run, clock=time.monotonic, platform=sys.platform):
    if platform != 'darwin':
        return None
    now = clock()
    if _cache['at'] is not None and now - _cache['at'] < CACHE_SECONDS:
        return _cache['value']
    value = None
    try:
        done = run(['/usr/bin/pmset', '-g', 'batt'], capture_output=True, text=True, timeout=2, stdin=subprocess.DEVNULL)
        if done.returncode == 0:
            value = parse(done.stdout)
    except (OSError, subprocess.SubprocessError):
        value = None
    _cache['at'] = now
    _cache['value'] = value
    return value
