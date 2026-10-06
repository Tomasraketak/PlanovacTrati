#!/usr/bin/env bash
# Plánovač tratí – spuštění GUI (Linux / macOS)
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Nejprve spusťte ./install.sh"; exit 1; }
exec .venv/bin/python -m streamlit run app.py --browser.gatherUsageStats false "$@"
