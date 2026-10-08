#!/usr/bin/env bash
# ===== Planovac trati - instalace / aktualizace / spusteni jednim prikazem (Linux / macOS) =====
#   curl -fsSL https://raw.githubusercontent.com/Tomasraketak/PlanovacTrati/HEAD/start.sh | bash
# Promenne prostredi: PLANOVAC_DIR, PLANOVAC_BEZ_AKTUALIZACE=1, PLANOVAC_BRANCH
set -u
REPO="https://github.com/Tomasraketak/PlanovacTrati"
zprava() { printf '\033[36m[Planovac] %s\033[0m\n' "$*"; }
chyba() { printf '\033[31m[Planovac] CHYBA: %s\033[0m\n' "$*" >&2; }

SRC="${BASH_SOURCE[0]:-}"
if [ -n "${PLANOVAC_DIR:-}" ]; then DIR="$PLANOVAC_DIR"
elif [ -n "$SRC" ] && [ -f "$(dirname "$SRC")/app.py" ]; then DIR="$(cd "$(dirname "$SRC")" && pwd)"
else DIR="$HOME/PlanovacTrati"; fi

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
[ -n "$PY" ] || { chyba "Je potreba Python 3.10+ (Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip; macOS: brew install python)."; exit 1; }

if [ -d "$DIR/.git" ]; then
  if [ -z "${PLANOVAC_BEZ_AKTUALIZACE:-}" ] && command -v git >/dev/null 2>&1; then
    zprava "Aktualizuji program (git pull) ..."
    ( cd "$DIR" && { [ -z "${PLANOVAC_BRANCH:-}" ] || { git fetch origin "$PLANOVAC_BRANCH" && git checkout "$PLANOVAC_BRANCH"; }; } && git pull --ff-only ) \
      || echo "[Planovac] Aktualizace se nepodarila (lokalni zmeny?) - spoustim stavajici verzi."
  fi
elif [ ! -f "$DIR/app.py" ]; then
  command -v git >/dev/null 2>&1 || { chyba "Je potreba git (nebo stahnete ZIP z $REPO)."; exit 1; }
  zprava "Stahuji program do $DIR ..."
  if [ -n "${PLANOVAC_BRANCH:-}" ]; then git clone --branch "$PLANOVAC_BRANCH" "$REPO" "$DIR"; else git clone "$REPO" "$DIR"; fi || exit 1
fi
cd "$DIR" || exit 1

if [ ! -x .venv/bin/python ]; then
  zprava "Vytvarim virtualni prostredi .venv ..."
  "$PY" -m venv .venv || { chyba "Nepodarilo se vytvorit .venv (Debian/Ubuntu: sudo apt install python3-venv)."; exit 1; }
fi
if command -v sha256sum >/dev/null 2>&1; then HASH="$(sha256sum requirements.txt | cut -d' ' -f1)"; else HASH="$(shasum -a 256 requirements.txt | cut -d' ' -f1)"; fi
if [ "$HASH" != "$(cat .venv/requirements.sha 2>/dev/null || true)" ]; then
  zprava "Instaluji / aktualizuji knihovny (pri prvnim spusteni nekolik minut) ..."
  .venv/bin/python -m pip install --upgrade pip --quiet
  .venv/bin/python -m pip install -r requirements.txt || { chyba "Instalace knihoven selhala."; exit 1; }
  echo "$HASH" > .venv/requirements.sha
fi

export PLANOVAC_LAUNCHER=1
while true; do
  zprava "Spoustim Planovac trati ... (ukonceni: Ctrl+C nebo tlacitko v aplikaci)"
  .venv/bin/python -m streamlit run app.py --browser.gatherUsageStats false
  kod=$?
  [ "$kod" -eq 75 ] || exit "$kod"
  zprava "Restartuji aplikaci ..."
done
