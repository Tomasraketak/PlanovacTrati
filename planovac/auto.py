"""Jízdní doby autem mezi stanicemi (pro porovnání s vlakem).

Zdroje:
* **Mapy.cz** routing API (``api.mapy.cz/v1/routing/route``) – vyžaduje API klíč (zdarma na developer.mapy.com),
  klíč z GUI (``data/nastaveni.json``) nebo z proměnné prostředí ``MAPY_API_KEY``;
* **OSRM** (veřejné demo, bez klíče a bez dopravní situace) – záložní zdroj.
Odpovědi se ukládají do ``data/cache/auto``; chyby se vracejí jako varování, nikdy nevyhodí výjimku.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import requests

from .dem import USER_AGENT
from .paths import cache_dir, data_dir

MAPY_URL = "https://api.mapy.cz/v1/routing/route"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{a};{b}"


@dataclass
class JizdaAutem:
    z: str
    do: str
    delka_km: float
    cas_s: float
    zdroj: str


def nastaveni_soubor() -> Path:
    """Trvalé nastavení uživatele mimo složku programu (přežije aktualizaci i novou instalaci)."""
    d = os.environ.get("PLANOVAC_CONFIG_DIR")
    return (Path(d) if d else Path.home() / ".planovac") / "nastaveni.json"


def _stary_soubor() -> Path:
    return data_dir() / "nastaveni.json"


def _cti(f: Path) -> dict:
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def nacti_klic() -> str:
    """API klíč Mapy.cz: proměnná prostředí → trvalé nastavení → (migrace) starý soubor v data/."""
    k = os.environ.get("MAPY_API_KEY", "").strip()
    if k:
        return k
    k = str(_cti(nastaveni_soubor()).get("mapy_klic", "")).strip()
    if k:
        return k
    k = str(_cti(_stary_soubor()).get("mapy_klic", "")).strip()
    if k:
        uloz_klic(k)                      # přestěhovat do trvalého úložiště
    return k


def uloz_klic(klic: str) -> None:
    f = nastaveni_soubor()
    d = _cti(f)
    if klic.strip():
        d["mapy_klic"] = klic.strip()
    else:
        d.pop("mapy_klic", None)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d), encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    old = _stary_soubor()
    if old.exists():                      # starý soubor už nesmí klíč vracet po smazání
        o = _cti(old)
        if o.pop("mapy_klic", None) is not None:
            try:
                old.write_text(json.dumps(o), encoding="utf-8")
            except OSError:
                pass


def _mapy(a, b, klic) -> tuple[float, float]:
    r = requests.get(MAPY_URL, params={"start": f"{a[0]:.6f},{a[1]:.6f}", "end": f"{b[0]:.6f},{b[1]:.6f}",
                                       "routeType": "car_fast", "format": "geojson", "lang": "cs"},
                     headers={"X-Mapy-Api-Key": klic, "User-Agent": USER_AGENT}, timeout=25)
    if r.status_code in (401, 403):
        raise PermissionError("Mapy.cz: neplatný API klíč")
    r.raise_for_status()
    d = r.json()
    # geojson: {"properties": {"length": m, "duration": s}} (starší varianty: length/duration přímo)
    p = d.get("properties", d)
    return float(p["length"]) / 1000.0, float(p["duration"])


def _osrm(a, b) -> tuple[float, float]:
    r = requests.get(OSRM_URL.format(a=f"{a[0]:.6f},{a[1]:.6f}", b=f"{b[0]:.6f},{b[1]:.6f}"),
                     params={"overview": "false"}, headers={"User-Agent": USER_AGENT}, timeout=25)
    r.raise_for_status()
    rt = r.json()["routes"][0]
    return rt["distance"] / 1000.0, float(rt["duration"])


def _jeden(a, b, zdroj: str, klic: str) -> tuple[float, float, str]:
    key = hashlib.sha1(f"{a}|{b}|{zdroj}".encode()).hexdigest()[:20]
    cf = cache_dir("auto") / f"{key}.json"
    if cf.exists():
        try:
            d = json.loads(cf.read_text(encoding="utf-8"))
            return d["km"], d["s"], d["zdroj"]
        except Exception:
            pass
    km = s = None
    pouzity = zdroj
    if zdroj == "mapy":
        km, s = _mapy(a, b, klic)
    else:
        km, s = _osrm(a, b)
    cf.write_text(json.dumps({"km": km, "s": s, "zdroj": pouzity}), encoding="utf-8")
    return km, s, pouzity


def jizda_autem(stanice: list[tuple[str, float, float]], zdroj: str = "auto",
                klic: str | None = None) -> tuple[list[JizdaAutem], list[str]]:
    """Jízda autem mezi sousedními stanicemi ``[(název, lat, lon), …]``.

    ``zdroj``: "auto" (Mapy.cz, je-li klíč, jinak OSRM; při chybě Mapy.cz záloha OSRM), "mapy", "osrm".
    Vrací (řádky, varování).
    """
    klic = nacti_klic() if klic is None else klic
    varovani: list[str] = []
    if zdroj == "mapy" and not klic:
        varovani.append("Chybí API klíč Mapy.cz – použit OSRM.")
        zdroj = "osrm"
    if zdroj == "auto":
        zdroj = "mapy" if klic else "osrm"
        if not klic:
            varovani.append("API klíč Mapy.cz není zadán – použit OSRM (bez dopravní situace).")
    out: list[JizdaAutem] = []
    for (n0, la0, lo0), (n1, la1, lo1) in zip(stanice[:-1], stanice[1:]):
        a, b = (lo0, la0), (lo1, la1)
        try:
            km, s, z = _jeden(a, b, zdroj, klic)
        except Exception as e:                    # noqa: BLE001
            if zdroj == "mapy":
                try:
                    km, s, z = _jeden(a, b, "osrm", "")
                    varovani.append(f"Mapy.cz selhalo ({str(e)[:80]}) – použit OSRM pro {n0} → {n1}.")
                except Exception as e2:           # noqa: BLE001
                    varovani.append(f"Jízdu autem {n0} → {n1} se nepodařilo zjistit: {str(e2)[:100]}")
                    continue
            else:
                varovani.append(f"Jízdu autem {n0} → {n1} se nepodařilo zjistit: {str(e)[:100]}")
                continue
        out.append(JizdaAutem(n0, n1, km, s, "Mapy.cz" if z == "mapy" else "OSRM"))
    return out, varovani
