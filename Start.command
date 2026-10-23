#!/bin/zsh
cd -- "${0:A:h}"
PYTHON_BIN=$(command -v python3)
if [[ -z "$PYTHON_BIN" ]]; then
  print 'Python 3 is needed to start Relay.'
  read '?Press Enter to close.'
  exit 1
fi
"$PYTHON_BIN" server.py --open
