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
        data_dir().mkdir(parents=True, exist_ok=True)
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
    """HTML s JavaScriptem, který hlásí chyby stránky, výpadky spojení a prázdnou obrazovku.

    Vkládá se přes iframe, ale vlastní hlídač se zapíše přímo do stránky aplikace: kdyby běžel v iframu, při pádu
    frontendu (bílá obrazovka) by zanikl spolu s ním a nic by nezapsal.
    """
    kod = f"""
(function () {{
  if (window.__planovacLog) return; window.__planovacLog = true;
  var URL = 'http://127.0.0.1:{port}/log';
  function send(t) {{
    t = String(t).slice(0, 4000);
    try {{ if (navigator.sendBeacon && navigator.sendBeacon(URL, t)) return; }} catch (e) {{}}
    try {{ fetch(URL, {{method: 'POST', mode: 'no-cors', body: t, keepalive: true}}); }} catch (e) {{}}
  }}
  window.__planovacSend = send;
  window.addEventListener('error', function (e) {{ send('error: ' + e.message + ' @' + e.filename + ':' + e.lineno + '\\n' + ((e.error && e.error.stack) || '')); }});
  window.addEventListener('unhandledrejection', function (e) {{ send('unhandledrejection: ' + (e.reason && (e.reason.stack || e.reason.message) || e.reason)); }});
  var ce = console.error; console.error = function () {{ try {{ send('console.error: ' + Array.prototype.slice.call(arguments).join(' ')); }} catch (x) {{}} return ce.apply(console, arguments); }};
  var cw = console.warn; console.warn = function () {{ try {{ var t = Array.prototype.slice.call(arguments).join(' '); if (/websocket|connection|disconnect|reconnect/i.test(t)) send('console.warn: ' + t); }} catch (x) {{}} return cw.apply(console, arguments); }};
  document.addEventListener('visibilitychange', function () {{ send('záložka ' + (document.hidden ? 'skryta' : 'zobrazena')); }});
  var prazdno = 0, posl = '';
  setInterval(function () {{
    var r = document.getElementById('root');
    var prazdne = !r || r.innerText.trim().length === 0;
    prazdno = prazdne ? prazdno + 1 : 0;
    if (prazdno === 3) send('PRÁZDNÁ STRÁNKA (3 s) ' + location.href + ' ' + navigator.userAgent + ' mem=' + (performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1e6) + ' MB' : '?'));
    var s = document.querySelector('[data-testid="stStatusWidget"]');
    var st = s ? s.innerText.trim() : '';
    if (st !== posl) {{ if (/connect|připoj/i.test(st + posl)) send('stav spojení: ' + (st || 'OK')); posl = st; }}
  }}, 1000);
}})();
"""
    return f"""<script>
(function () {{
  var W; try {{ W = window.parent; W.document; }} catch (e) {{ return; }}
  if (W.__planovacLog) return;
  var s = W.document.createElement('script');
  s.textContent = {json.dumps(kod)};
  W.document.head.appendChild(s);
}})();
</script>"""


class _HlidacKontextu(logging.Filter):
    """Zapíše do logu, odkud přišlo varování „missing ScriptRunContext“ (proces, vlákno, zásobník)."""

    def __init__(self):
        super().__init__()
        self._posledni = 0.0

    def filter(self, record):                         # noqa: A003
        try:
            if "ScriptRunContext" in record.getMessage() and time.time() - self._posledni > 30:
                import os

                self._posledni = time.time()
                zasobnik = "".join(traceback.format_stack(limit=25)[:-1])
                zapis(f"{record.getMessage()} (pid {os.getpid()}, vlákno {threading.current_thread().name})\n"
                      f"{zasobnik}", "varování")
        except Exception:                              # noqa: BLE001
            pass
        return True


def hlidej_varovani() -> None:
    lg = logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context")
    if not any(isinstance(f, _HlidacKontextu) for f in lg.filters):
        lg.addFilter(_HlidacKontextu())


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
