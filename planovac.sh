#!/usr/bin/env bash
# Plánovač tratí – příkazová řádka. Příklad: ./planovac.sh run projekty/cb_jh_jihlava.yaml
cd "$(dirname "$0")"
exec .venv/bin/python -m planovac "$@"
