#!/usr/bin/env bash
# Plánovač tratí – aktualizace (Linux / macOS)
set -e
cd "$(dirname "$0")"
git pull
[ -x .venv/bin/python ] || exec ./install.sh
.venv/bin/python -m pip install --upgrade -r requirements.txt
echo "Hotovo. Spusťte ./run.sh"
