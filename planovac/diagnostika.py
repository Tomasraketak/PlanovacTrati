"""Diagnostika GUI: log chyb (i z prohlížeče), pády nativního kódu a balíček pro odeslání.

Bílá obrazovka v prohlížeči je chyba frontendu – Python o ní nic neví. Proto aplikace vloží do stránky
malý skript, který chyby prohlížeče posílá na lokální logovací server (127.0.0.1) a ten je zapisuje do
``data/gui_chyby.log``.
"""
from __future__ import annotations

import faulthandler
import io
import json
import logging
import platform
import sys
import threading
import time
import traceback
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .paths import data_dir

log = logging.getLogger(__name__)
_zamek = threading.Lock()
_server: ThreadingHTTPServer | None = None
_crash_file = None
PORT_OD = 8599


def log_soubor() -> Path:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "gui_chyby.log"


def zapis(text: str, zdroj: str = "python") -> None:
    """Přidá záznam do logu (nikdy nevyhodí výjimku; log se při velikosti > 1 MB zkrátí)."""
    try:
        with _zamek:
            f = log_soubor()
            if f.exists() and f.stat().st_size > 1_000_000:
                f.write_text(f.read_text(encoding="utf-8", errors="replace")[-300_000:], encoding="utf-8")
            with open(f, "a", encoding="utf-8") as h:
                h.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ({zdroj}) {text.strip()}\n")
    except Exception:                                  # noqa: BLE001
        pass


def zapis_vyjimku(kde: str) -> None:
    zapis(f"{kde}\n{traceback.format_exc()}")


def zapni_faulthandler() -> None:
    """Pády nativního kódu (segfault) se zapíšou do ``data/gui_crash.log``."""
    global _crash_file
    if _crash_file is not None:
        return
    try:
        _crash_file = open(data_dir() / "gui_crash.log", "a", encoding="utf-8")   # držet otevřený
        faulthandler.enable(file=_crash_file, all_threads=True)
    except Exception:                                  # noqa: BLE001
        pass


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):                                 # noqa: N802
        try:
            n = min(int(self.headers.get("Content-Length", 0) or 0), 20000)
            zapis(self.rfile.read(n).decode("utf-8", errors="replace"), "prohlížeč")
        finally:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

    def do_OPTIONS(self):                              # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, *a):                         # noqa: D401 – ticho
        pass


def spust_server() -> int | None:
    """Spustí (jednou na proces) lokální logovací server; vrací port nebo None."""
    global _server
    if _server is not None:
        return _server.server_address[1]
    for port in range(PORT_OD, PORT_OD + 12):
        try:
            _server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        except OSError:
            continue
        threading.Thread(target=_server.serve_forever, daemon=True, name="planovac-log").start()
        return port
    return None


def skript(port: int) -> str:
    """HTML s JavaScriptem, který hlásí chyby stránky a prázdnou obrazovku (vloží se přes components.html)."""
    return f"""<script>
(function () {{
  var W; try {{ W = window.parent; W.document; }} catch (e) {{ return; }}
  if (W.__planovacLog) return; W.__planovacLog = true;
  function send(t) {{ try {{ fetch('http://127.0.0.1:{port}/log', {{method: 'POST', mode: 'no-cors', body: String(t).slice(0, 4000)}}); }} catch (e) {{}} }}
  W.addEventListener('error', function (e) {{ send('error: ' + e.message + ' @' + e.filename + ':' + e.lineno + '\\n' + ((e.error && e.error.stack) || '')); }});
  W.addEventListener('unhandledrejection', function (e) {{ send('unhandledrejection: ' + (e.reason && (e.reason.stack || e.reason.message) || e.reason)); }});
  var ce = W.console.error; W.console.error = function () {{ try {{ send('console.error: ' + Array.prototype.slice.call(arguments).join(' ')); }} catch (x) {{}} return ce.apply(W.console, arguments); }};
  var prazdno = 0;
  setInterval(function () {{
    var r = W.document.getElementById('root');
    var prazdne = !r || r.innerText.trim().length === 0;
    prazdno = prazdne ? prazdno + 1 : 0;
    if (prazdno === 3) send('PRÁZDNÁ STRÁNKA (3 s) ' + W.location.href + ' ' + W.navigator.userAgent + ' mem=' + (W.performance.memory ? Math.round(W.performance.memory.usedJSHeapSize / 1e6) + ' MB' : '?'));
  }}, 1000);
}})();
</script>"""


def info() -> dict:
    try:
        import streamlit
        sv = streamlit.__version__
    except Exception:                                  # noqa: BLE001
        sv = "?"
    return {"python": sys.version.split()[0], "os": platform.platform(), "streamlit": sv}


def posledni_chyby(n: int = 25) -> str:
    try:
        return "\n".join(log_soubor().read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except Exception:                                  # noqa: BLE001
        return ""


def zip_diagnostiky(extra: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("info.json", json.dumps({**info(), **(extra or {})}, ensure_ascii=False, indent=2))
        for nm in ("gui_chyby.log", "gui_crash.log"):
            f = data_dir() / nm
            if f.exists():
                z.write(f, nm)
    return buf.getvalue()
