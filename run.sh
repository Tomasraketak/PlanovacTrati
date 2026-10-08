#!/usr/bin/env bash
# Spusteni bez aktualizace (vola start.sh)
PLANOVAC_BEZ_AKTUALIZACE=1 exec "$(dirname "$0")/start.sh" "$@"
