#!/bin/zsh
set -euo pipefail

PROJECT_ROOT=${0:A:h:h}
python3 -m venv "$PROJECT_ROOT/.venv-packaging"
"$PROJECT_ROOT/.venv-packaging/bin/python" -m pip install --upgrade pip pyinstaller pillow
