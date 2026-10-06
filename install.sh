#!/usr/bin/env bash
# Plánovač tratí – instalace (Linux / macOS)
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
$PY -c 'import sys; assert sys.version_info >= (3, 10), "Je potřeba Python 3.10+"'
[ -x .venv/bin/python ] || $PY -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo "Hotovo. Spusťte ./run.sh"
