#!/usr/bin/env python3
"""Relay launcher. Backend composition and services live in the relay package."""
import os
from pathlib import Path
import sys

from relay.application import Application


def application_paths(*, frozen=None, bundle_root=None, environment=None, home=None):
    """Return resource and writable-data paths for source and packaged launches."""
    environment = os.environ if environment is None else environment
    frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    if frozen:
        root = Path(getattr(sys, '_MEIPASS') if bundle_root is None else bundle_root).resolve()
        user_home = Path.home() if home is None else Path(home)
        default_data = user_home / 'Library' / 'Application Support' / 'Relay'
    else:
        root = Path(__file__).resolve().parent
        default_data = root / 'data'
    data = Path(environment.get('RELAY_DATA_DIR', default_data)).expanduser().resolve()
    return root, data


ROOT, DATA = application_paths()
application = Application(ROOT, DATA)


def main():
    application.main()


if __name__ == '__main__':
    main()
