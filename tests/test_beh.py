"""Výpočet v samostatném procesu (GUI jen čte průběh)."""
import time
from pathlib import Path

from planovac import beh
from planovac.config import Project

ROOT = Path(__file__).resolve().parent.parent


def _demo():
    p = Project.load(ROOT / "projekty" / "demo.yaml")
    p.vypocet.demo = True
    p.vypocet.rozliseni_m = 100
    return p


def _cekej(u, limit=300):
    t = time.time()
    while not u.hotovo and time.time() - t < limit:
        time.sleep(0.5)
        u.obnov()
    return u


def test_vypocet_v_procesu_vrati_vysledek_a_prubeh():
    u = _cekej(beh.spust(_demo()))
    assert u.hotovo and u.chyba is None, u.tb
    assert u.vysledek.osa.xy.shape[0] > 10
    assert u.log and u.frac > 0.5
    assert beh.aktualni() is u              # dokud si výsledek GUI nepřevezme, zůstává k dispozici
    beh.uvolni(u)
    assert beh.aktualni() is None


def test_zastaveni_ukonci_proces():
    u = beh.spust(_demo())
    time.sleep(3)
    u.zastav()
    assert u.hotovo and u.chyba == beh.ZASTAVENO
    assert not u.proc.is_alive()
    beh.uvolni(u)
