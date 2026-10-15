"""Výpočet trati v samostatném procesu (GUI jen čte průběh).

Výpočet dřív běžel ve vláknech serveru Streamlitu. Náročný Python kód pak bral serveru procesor (GIL), prohlížeč
nedostával včas odpovědi, spojení spadlo a po návratu na záložku zůstala bílá obrazovka. V samostatném procesu
server vždy odpovídá a ani pád výpočtu (paměť, nativní knihovna) neshodí aplikaci.

Běží nejvýš jeden výpočet na celý program (modulový stav) – po obnovení stránky nebo novém připojení prohlížeče
se na rozběhnutý výpočet dá znovu napojit.
"""
from __future__ import annotations

import atexit
import multiprocessing
import os
import pickle
import queue
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field

from . import diagnostika
from .paralelne import _bez_importu_hlavniho_modulu

ZASTAVENO = "Výpočet byl zastaven."


def _proces(projekt, fronta, soubor: str) -> None:
    """Tělo pracovního procesu: spočítá trať, výsledek uloží do souboru (může mít stovky MB)."""
    if hasattr(os, "setsid"):
        try:
            os.setsid()                                 # vlastní skupina procesů – zastavení ukončí i pracovní procesy
        except OSError:
            pass
    from .pipeline import run_project

    def cb(frac, msg):
        try:
            fronta.put(("p", float(frac), str(msg)))
        except Exception:                               # noqa: BLE001 – průběh je jen kosmetický
            pass

    try:
        res = run_project(projekt, cb)
        with open(soubor, "wb") as f:
            pickle.dump(res, f, protocol=pickle.HIGHEST_PROTOCOL)
        fronta.put(("ok",))
    except BaseException as e:                          # noqa: BLE001
        fronta.put(("err", f"{type(e).__name__}: {e}", traceback.format_exc()))


@dataclass
class Uloha:
    proc: multiprocessing.process.BaseProcess
    fronta: object
    soubor: str
    t0: float = field(default_factory=time.time)
    t1: float | None = None
    frac: float = 0.0
    msg: str = "Spouštím výpočet …"
    log: list[str] = field(default_factory=list)
    hotovo: bool = False
    vysledek: object = None
    chyba: str | None = None
    tb: str = ""
    prevzato: bool = False

    def obnov(self) -> None:
        """Přečte nové zprávy z procesu (neblokuje)."""
        if self.hotovo:
            return
        while True:
            try:
                z = self.fronta.get_nowait()
            except queue.Empty:
                break
            except Exception:                           # noqa: BLE001 – rozbitá fronta = proces skončil
                break
            if z[0] == "p":
                self.frac = min(max(z[1], 0.0), 1.0)
                if z[2] != self.msg or not self.log:
                    self.log.append(z[2])
                    del self.log[:-200]
                self.msg = z[2]
            elif z[0] == "ok":
                self._dokonci(None)
                return
            elif z[0] == "err":
                self.tb = z[2]
                self._dokonci(z[1])
                return
        if not self.proc.is_alive():
            time.sleep(0.2)                             # poslední zprávy mohou být ještě v rouře
            try:
                z = self.fronta.get_nowait()
                if z[0] == "ok":
                    self._dokonci(None)
                    return
                if z[0] == "err":
                    self.tb = z[2]
                    self._dokonci(z[1])
                    return
            except Exception:                           # noqa: BLE001
                pass
            self._dokonci(f"Výpočet neočekávaně skončil (kód {self.proc.exitcode}) – nejspíš došla paměť. "
                          "Zkuste hrubší rozlišení rastru nebo menší oblast.")

    def _dokonci(self, chyba: str | None) -> None:
        self.t1 = time.time()
        if chyba is None:
            try:
                with open(self.soubor, "rb") as f:
                    self.vysledek = pickle.load(f)
            except Exception as e:                      # noqa: BLE001
                chyba, self.tb = f"Výsledek nelze načíst: {e}", traceback.format_exc()
        self.chyba = chyba
        if chyba and chyba != ZASTAVENO:
            diagnostika.zapis(f"výpočet trati selhal: {chyba}\n{self.tb}")
        try:
            os.remove(self.soubor)
        except OSError:
            pass
        self.hotovo = True

    def zastav(self) -> None:
        if self.proc.is_alive():
            _zabij_strom(self.proc)
            self.proc.join(5)
        self.tb = ""
        self._dokonci(ZASTAVENO)


def _zabij_strom(proc) -> None:
    """Ukončí proces výpočtu i jeho pracovní procesy (jinak by dál zatěžovaly procesor)."""
    try:
        if os.name == "nt":
            import subprocess

            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            import signal

            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:                                   # noqa: BLE001
        pass
    if proc.is_alive():
        proc.terminate()


_zamek = threading.Lock()
_uloha: Uloha | None = None


def aktualni() -> Uloha | None:
    """Běžící (nebo dokončený a ještě nepřevzatý) výpočet."""
    with _zamek:
        if _uloha is not None:
            _uloha.obnov()
        return _uloha


def spust(projekt) -> Uloha:
    """Spustí výpočet v novém procesu; běží-li už jiný, vrátí ten."""
    global _uloha
    with _zamek:
        if _uloha is not None:
            _uloha.obnov()
            if not _uloha.hotovo:
                return _uloha
        ctx = multiprocessing.get_context("spawn")
        fronta = ctx.Queue()
        fd, soubor = tempfile.mkstemp(prefix="planovac_vysledek_", suffix=".pkl")
        os.close(fd)
        # ne-daemon: výpočet si sám spouští procesy pro Dijkstru (daemon proces děti mít nesmí)
        proc = ctx.Process(target=_proces, args=(projekt, fronta, soubor), name="planovac-vypocet", daemon=False)
        with _bez_importu_hlavniho_modulu():
            proc.start()
        _uloha = Uloha(proc, fronta, soubor)
        return _uloha


def uvolni(u: Uloha) -> None:
    """Výsledek převzat – úloha se zapomene."""
    global _uloha
    with _zamek:
        u.prevzato = True
        if _uloha is u:
            _uloha = None


@atexit.register
def _ukonci_pri_vypnuti() -> None:
    # bez tohoto by multiprocessing při ukončení programu čekal na dokončení výpočtu
    u = _uloha
    if u is not None and u.proc.is_alive():
        _zabij_strom(u.proc)
