"""Souběh nové trati se stávající železnicí a s hlavními silnicemi.

* Osa do ±``zeleznice_tolerance_m`` od stávající koleje → využije se stávající těleso a pozemky:
  stavba je o ``zeleznice_sleva_pct`` levnější a nepočítají se penalizace (zástavba, domy,
  chráněná území) ani demolice.
* Osa do ``silnice_vzdalenost_m`` od okraje dálnice / silnice pro motorová vozidla / silnice
  I. třídy → společný koridor, stavba o ``silnice_sleva_pct`` levnější.

Rastr nákladové mapy (typicky 50 m) přesnost ±4 m nezachytí, proto se vrcholy koridoru ležící
blízko koleje „přichytí“ přímo na kolej (``prichytit_ke_koleji``) a sleva se počítá přesně na
vzorcích výsledné osy po 10 m (``faktor_osy``).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import MultiLineString, Point
from shapely.ops import nearest_points

from .config import POLOVICNI_SIRKA_SILNICE, Soubeh
from .geo import Grid
from .osm import OsmData

ZELEZNICE, SILNICE = "stávající trať", "silnice"


@dataclass
class UsekSoubehu:
    druh: str
    s0: float
    s1: float

    @property
    def delka(self) -> float:
        return self.s1 - self.s0


def _tridy(cfg: Soubeh) -> set[str]:
    return {t.strip() for t in cfg.silnice_tridy.split(",") if t.strip()}


def koleje(osm: OsmData) -> MultiLineString | None:
    lines = [ls for ls in osm.zeleznice if ls.length > 0]
    return MultiLineString(lines) if lines else None


def silnice_pasy(osm: OsmData, cfg: Soubeh, navic_m: float = 0.0):
    """Pásy podél silnic, ve kterých osa dostane slevu (polygony)."""
    tridy = _tridy(cfg)
    out = []
    for trida, _, ls in osm.silnice:
        if trida in tridy:
            out.append(ls.buffer(POLOVICNI_SIRKA_SILNICE.get(trida, 4.0) + cfg.silnice_vzdalenost_m + navic_m))
    return out


def faktor_rastr(grid: Grid, osm: OsmData, cfg: Soubeh):
    """(faktor ceny buňky, maska buněk se stávající kolejí) pro nákladovou mapu."""
    from .costsurface import _rasterize

    f = np.ones(grid.shape)
    if not cfg.povolit:
        return f, np.zeros(grid.shape, dtype=bool)
    pasy = silnice_pasy(osm, cfg)
    if pasy:
        m = _rasterize(pasy, grid).astype(bool)
        f[m] = 1 - cfg.silnice_sleva_pct / 100.0
    kol = [ls for ls in osm.zeleznice if ls.length > 0]
    rail = _rasterize(kol, grid).astype(bool) if kol else np.zeros(grid.shape, dtype=bool)
    f[rail] = np.minimum(f[rail], 1 - cfg.zeleznice_sleva_pct / 100.0)
    return f, rail


def faktor_osy(xy: np.ndarray, osm: OsmData, cfg: Soubeh):
    """Faktor ceny v každém vzorku osy + masky souběhu (železnice, silnice)."""
    n = len(xy)
    f = np.ones(n)
    zel = np.zeros(n, dtype=bool)
    sil = np.zeros(n, dtype=bool)
    if not cfg.povolit or n == 0:
        return f, zel, sil
    pts = shapely.points(xy)
    k = koleje(osm)
    if k is not None:
        zel = shapely.distance(pts, k) <= cfg.zeleznice_tolerance_m
    pasy = silnice_pasy(osm, cfg)
    if pasy:
        sil = shapely.intersects(pts, shapely.union_all(pasy)) & ~zel
    f[sil] = 1 - cfg.silnice_sleva_pct / 100.0
    f[zel] = 1 - cfg.zeleznice_sleva_pct / 100.0
    return f, zel, sil


def prichytit_ke_koleji(xy: np.ndarray, osm: OsmData, max_vzdalenost: float) -> np.ndarray:
    """Posune vnitřní vrcholy lomené čáry ležící blízko koleje přesně na kolej."""
    k = koleje(osm)
    if k is None or len(xy) < 3:
        return xy
    out = xy.copy()
    d = shapely.distance(shapely.points(xy[1:-1]), k)
    for i in np.flatnonzero(d <= max_vzdalenost) + 1:
        p = nearest_points(k, Point(xy[i]))[0]
        out[i] = (p.x, p.y)
    return out


def useky(s: np.ndarray, zel: np.ndarray, sil: np.ndarray, min_delka: float = 50.0) -> list[UsekSoubehu]:
    out = []
    for druh, mask in ((ZELEZNICE, zel), (SILNICE, sil)):
        if not mask.any():
            continue
        idx = np.flatnonzero(np.diff(np.concatenate([[0], mask.astype(int), [0]])))
        for a, b in zip(idx[::2], idx[1::2]):
            s0, s1 = float(s[a]), float(s[b - 1])
            if s1 - s0 >= min_delka:
                out.append(UsekSoubehu(druh, s0, s1))
    return sorted(out, key=lambda u: u.s0)
