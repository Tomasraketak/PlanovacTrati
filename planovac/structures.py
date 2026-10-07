"""Klasifikace úseků trati (násyp, zářez, estakáda, most, tunel), křížení,
demolice a statistiky."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiLineString, Point

from .config import Ceny, NavrhoveParametry
from .osm import OsmData
from .vertical import option_costs

UROVEN, NASYP, ZAREZ, ESTAKADA, MOST, TUNEL, HLOUBENY = range(7)
NAZVY = ["v úrovni terénu", "násyp", "zářez", "estakáda", "most", "tunel", "hloubený tunel"]
BARVY = ["#95a5a6", "#e67e22", "#6d4c41", "#e74c3c", "#2e86de", "#2c3e50", "#8e44ad"]
OBJEKTY = (ESTAKADA, MOST, TUNEL, HLOUBENY)


@dataclass
class Usek:
    typ: int
    s0: float
    s1: float
    max_h: float = 0.0
    nazev: str = ""

    @property
    def delka(self) -> float:
        return self.s1 - self.s0

    @property
    def typ_nazev(self) -> str:
        return NAZVY[self.typ]


@dataclass
class Krizeni:
    druh: str         # silnice / železnice / vodní tok
    s: float
    nazev: str
    reseni: str


@dataclass
class Analyza:
    typy: np.ndarray                  # typ v každém vzorku osy
    useky: list[Usek]                 # souvislé úseky stejného typu
    objekty: list[Usek]               # jen umělé stavby (tunely, estakády, mosty)
    krizeni: list[Krizeni]
    demolice_idx: np.ndarray          # indexy budov k demolici
    hluk_pocet: int                   # budov do 100 m od osy (mimo tunely)
    objem_nasyp_m3: float
    objem_vykop_m3: float
    zabor_m2: float
    obce_blizko: list[tuple[str, float, float]] = field(default_factory=list)  # (název, vzdálenost, staničení)
    chranena_delky: list[tuple[str, int, float]] = field(default_factory=list)  # (název, stupeň, délka mimo tunel)
    delka_v_zastavbe: float = 0.0


def runs(labels: np.ndarray) -> list[tuple[int, int, int]]:
    """Souvislé běhy stejných hodnot: (hodnota, i0, i1) včetně i1."""
    if len(labels) == 0:
        return []
    change = np.flatnonzero(np.diff(labels)) + 1
    starts = np.concatenate([[0], change])
    ends = np.concatenate([change - 1, [len(labels) - 1]])
    return [(int(labels[a]), int(a), int(b)) for a, b in zip(starts, ends)]


# ------------------------------------------------------------------ voda a křížení

def _as_lines(geom):
    if geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, LineString)]


def _as_points(geom):
    if geom.is_empty:
        return []
    if isinstance(geom, Point):
        return [geom]
    out = []
    for g in getattr(geom, "geoms", []):
        if isinstance(g, Point):
            out.append(g)
        elif isinstance(g, LineString):
            out.append(Point(g.coords[0]))
    return out


def water_flags(line: LineString, s: np.ndarray, osm: OsmData) -> tuple[np.ndarray, list[tuple[float, str]]]:
    """Příznak „nad vodou“ v každém vzorku + seznam křížení vodních toků (s, název)."""
    flag = np.zeros(len(s), dtype=bool)
    reky = []
    for name, rl in osm.reky:
        if not line.bounds or not rl.intersects(line):
            continue
        for p in _as_points(line.intersection(rl)):
            sp = line.project(p)
            reky.append((sp, name or "vodní tok"))
            flag |= np.abs(s - sp) <= 15.0
    for poly in osm.voda_plochy:
        if not poly.intersects(line):
            continue
        for seg in _as_lines(line.intersection(poly)):
            a = line.project(Point(seg.coords[0]))
            b = line.project(Point(seg.coords[-1]))
            a, b = min(a, b), max(a, b)
            flag |= (s >= a - 10) & (s <= b + 10)
    reky.sort()
    return flag, reky


def building_density(xy: np.ndarray, s: np.ndarray, budovy: np.ndarray, radius: float = 30.0) -> np.ndarray:
    """Počet budov do ``radius`` od osy připadající na metr trati (pro optimalizaci nivelety)."""
    out = np.zeros(len(s))
    if len(budovy) == 0:
        return out
    tree = cKDTree(xy)
    d, idx = tree.query(budovy, distance_upper_bound=radius)
    ok = np.isfinite(d)
    np.add.at(out, idx[ok], 1.0)
    ds = np.gradient(s) if len(s) > 1 else np.ones(1)
    return out / np.maximum(ds, 1.0)


# ------------------------------------------------------------------ klasifikace

def classify(h: np.ndarray, s: np.ndarray, voda: np.ndarray, bud_na_m: np.ndarray,
             navrh: NavrhoveParametry, ceny: Ceny, demolice_mil: float | None = None) -> np.ndarray:
    costs = option_costs(h, navrh, ceny, voda, bud_na_m, demolice_mil)
    best = np.argmin(costs, axis=0)
    t = np.where(np.abs(h) < 1.5, UROVEN, np.where(h > 0, NASYP, ZAREZ))
    t = np.where(best == 1, ESTAKADA, t)
    t = np.where(best == 2, TUNEL, t)
    t = np.where(best == 3, MOST, t)

    def merge_gaps(t, kinds, target, max_gap, allowed_gap_types):
        r = runs(t)
        for k in range(1, len(r) - 1):
            val, a, b = r[k]
            if r[k - 1][0] in kinds and r[k + 1][0] in kinds and s[b] - s[a] < max_gap and val in allowed_gap_types:
                t[a:b + 1] = target
        return t

    # krátké mezery mezi tunely -> tunel; mezi estakádami -> estakáda
    t = merge_gaps(t, (TUNEL,), TUNEL, 250.0, (ZAREZ, UROVEN, NASYP))
    t = merge_gaps(t, (ESTAKADA, MOST), ESTAKADA, 120.0, (NASYP, UROVEN, ZAREZ))
    # krátké tunely -> hloubený tunel / zářez
    for val, a, b in runs(t):
        if val == TUNEL and s[b] - s[a] < navrh.min_delka_tunelu_m:
            deep = h[a:b + 1].min() < -navrh.hloubka_zarezu_max_m
            t[a:b + 1] = HLOUBENY if deep else ZAREZ
    # krátké estakády -> most
    for val, a, b in runs(t):
        if val == ESTAKADA and s[b] - s[a] < navrh.min_delka_estakady_m:
            t[a:b + 1] = MOST
    return t


def analyze(xy, s, h, voda, reky, bud_na_m, osm: OsmData, navrh: NavrhoveParametry, ceny: Ceny,
            stanice_xy: list[tuple[float, float]] | None = None,
            zastavba_mask: np.ndarray | None = None, demolice_mil: float | None = None) -> Analyza:
    t = classify(h, s, voda, bud_na_m, navrh, ceny, demolice_mil)
    line = LineString(xy)

    useky = []
    for val, a, b in runs(t):
        s0 = s[a - 1] if a > 0 else s[a]
        s0 = (s0 + s[a]) / 2 if a > 0 else s0
        s1 = (s[b] + s[b + 1]) / 2 if b < len(s) - 1 else s[b]
        mh = float(h[a:b + 1].max() if val in (NASYP, ESTAKADA, MOST) else h[a:b + 1].min())
        useky.append(Usek(val, float(s0), float(s1), mh))
    # pojmenovat mosty podle řek
    for u in useky:
        if u.typ in (MOST, ESTAKADA):
            names = sorted({n for sp, n in reky if u.s0 - 20 <= sp <= u.s1 + 20})
            if names:
                u.nazev = ", ".join(names)
    objekty = [u for u in useky if u.typ in OBJEKTY]

    # křížení
    def reseni(sp):
        i = min(int(np.searchsorted(s, sp)), len(s) - 1)
        tt = t[i]
        if tt in (TUNEL, HLOUBENY):
            return "v tunelu (bez objektu)"
        if tt in (ESTAKADA, MOST):
            return "pod estakádou/mostem"
        return "mimoúrovňové křížení (nový objekt)"

    krizeni = []
    for trida, nazev, rl in osm.silnice:
        if rl.intersects(line):
            for p in _as_points(line.intersection(rl)):
                sp = line.project(p)
                krizeni.append(Krizeni("silnice", sp, f"{nazev or ''} ({trida})".strip(), reseni(sp)))
    for rl in osm.zeleznice:
        if rl.intersects(line):
            for p in _as_points(line.intersection(rl)):
                sp = line.project(p)
                krizeni.append(Krizeni("železnice", sp, "železniční trať", reseni(sp)))
    for sp, n in reky:
        krizeni.append(Krizeni("vodní tok", sp, n, reseni(sp)))
    krizeni.sort(key=lambda k: k.s)
    # deduplikace (dvojité koleje / dvoupruhové silnice)
    dedup: list[Krizeni] = []
    for k in krizeni:
        if dedup and dedup[-1].druh == k.druh and abs(dedup[-1].s - k.s) < 60:
            continue
        dedup.append(k)

    # zemní práce a zábor
    b, n = navrh.sirka_plane_m, navrh.sklon_svahu
    ds = np.gradient(s)
    zem = np.isin(t, (UROVEN, NASYP, ZAREZ))
    area = np.abs(h) * (b + n * np.abs(h))
    v_nasyp = float(np.sum(np.where(zem & (h > 0), area, 0) * ds))
    v_vykop = float(np.sum(np.where(zem & (h < 0), area, 0) * ds))
    width = np.where(zem, b + 2 * n * np.abs(h) + 6, np.where(np.isin(t, (ESTAKADA, MOST)), 12.0,
                                                              np.where(t == HLOUBENY, b + 6, 0.0)))
    zabor = float(np.sum(width * ds))

    # demolice a hluk
    demol = np.zeros(0, dtype=int)
    hluk = 0
    if len(osm.budovy):
        tree = cKDTree(xy)
        d, idx = tree.query(osm.budovy, distance_upper_bound=150.0)
        ok = np.isfinite(d)
        bi = np.flatnonzero(ok)
        ii = idx[ok]
        dd = d[ok]
        half = np.where(zem[ii], b / 2 + n * np.abs(h[ii]) + 3, np.where(np.isin(t[ii], (ESTAKADA, MOST)), 8.0,
                                                                          np.where(t[ii] == HLOUBENY, b / 2 + 4, -1.0)))
        demol = bi[dd <= half]
        hluk = int(np.sum((dd <= 100.0) & (t[ii] != TUNEL) & (t[ii] != HLOUBENY)))

    # obce v blízkosti
    obce_blizko = []
    st = [Point(p) for p in (stanice_xy or [])]
    for name, kind, pt in osm.obce:
        d = line.distance(pt)
        if d < 1500 and kind in ("city", "town", "village") and not any(pt.distance(q) < 2500 for q in st):
            obce_blizko.append((name, float(d), float(line.project(pt))))
    obce_blizko.sort(key=lambda o: o[2])

    chran = []
    for name, lvl, poly in osm.chranena:
        if poly.intersects(line):
            inter = line.intersection(poly)
            L = 0.0
            for seg in _as_lines(inter):
                a = line.project(Point(seg.coords[0]))
                bb = line.project(Point(seg.coords[-1]))
                a, bb = min(a, bb), max(a, bb)
                m = (s >= a) & (s <= bb) & ~np.isin(t, (TUNEL,))
                L += float(np.sum(ds[m]))
            if L > 0:
                chran.append((name, lvl, L))

    v_zast = 0.0
    if zastavba_mask is not None:
        v_zast = float(np.sum(ds[zastavba_mask & ~np.isin(t, (TUNEL, HLOUBENY))]))

    return Analyza(typy=t, useky=useky, objekty=objekty, krizeni=dedup, demolice_idx=demol, hluk_pocet=hluk,
                   objem_nasyp_m3=v_nasyp, objem_vykop_m3=v_vykop, zabor_m2=zabor, obce_blizko=obce_blizko,
                   chranena_delky=chran, delka_v_zastavbe=v_zast)
