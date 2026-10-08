#!/usr/bin/env bash
# Plánovač tratí – příkazová řádka. Příklad: ./planovac.sh run projekty/demo.yaml
cd "$(dirname "$0")"
exec .venv/bin/python -m planovac "$@"
