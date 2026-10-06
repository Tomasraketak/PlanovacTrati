"""Orchestrace celého návrhu trati: data -> koridor -> osa -> niveleta -> analýza."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from shapely.geometry import LineString

from . import corridor, costs, dem, horizontal, osm as osm_mod, structures, synthetic, traction, vertical
from .config import Project
from .costsurface import CostSurface, build_cost_surface
from .geo import Grid, to_lonlat, to_xy

log = logging.getLogger(__name__)
Progress = Callable[[float, str], None]


@dataclass
class Result:
    project: Project
    grid: Grid
    dem: np.ndarray
    cost: CostSurface
    osm: osm_mod.OsmData
    body_xy: list[tuple[float, float]]
    koridory: list[corridor.SegmentPath]
    osa: horizontal.Alignment
    z_teren: np.ndarray
    z_kolej: np.ndarray
    analyza: structures.Analyza
    rozpocet: costs.Rozpocet
    jizda: traction.JizdniDoby
    vzdusna_m: float
    vzdusna_useky_m: list[float]
    varovani: list[str] = field(default_factory=list)
    trvani_s: float = 0.0

    # ----------------------------------------------------------- souhrny
    @property
    def delka_m(self) -> float:
        return self.osa.delka

    @property
    def vzdusna_primo_m(self) -> float:
        """Vzdušná vzdálenost start – cíl (bez mezilehlých bodů)."""
        a, b = self.body_xy[0], self.body_xy[-1]
        return float(np.hypot(b[0] - a[0], b[1] - a[1]))

    @property
    def prodlouzeni_pct(self) -> float:
        return 100.0 * (self.delka_m / self.vzdusna_m - 1.0)

    def prodlouzeni_useku(self) -> list[tuple[str, str, float, float, float]]:
        """(z, do, délka osy, vzdušná, prodloužení %) pro úseky mezi body."""
        out = []
        b = self.project.body
        for k in range(len(b) - 1):
            L = self.osa.body_s[k + 1] - self.osa.body_s[k]
            d = self.vzdusna_useky_m[k]
            out.append((b[k].nazev, b[k + 1].nazev, L, d, 100.0 * (L / d - 1) if d > 0 else 0.0))
        return out

    def sklon_promile(self) -> np.ndarray:
        return np.gradient(self.z_kolej, self.osa.s) * 1000.0


def _area_bounds(pts: list[tuple[float, float]], ratio: float, margin: float):
    xs, ys = [], []
    for a, b in zip(pts[:-1], pts[1:]):
        d = np.hypot(b[0] - a[0], b[1] - a[1])
        sa = ratio * d / 2
        sb = np.sqrt(max(sa ** 2 - (d / 2) ** 2, 0))
        cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        ang = np.arctan2(b[1] - a[1], b[0] - a[0])
        t = np.linspace(0, 2 * np.pi, 72)
        ex = cx + sa * np.cos(t) * np.cos(ang) - sb * np.sin(t) * np.sin(ang)
        ey = cy + sa * np.cos(t) * np.sin(ang) + sb * np.sin(t) * np.cos(ang)
        xs += list(ex)
        ys += list(ey)
    return min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin


def run_project(project: Project, progress: Progress | None = None) -> Result:
    t0 = time.time()
    errors = project.validate()
    if errors:
        raise ValueError("\n".join(errors))

    def prog(frac: float, msg: str):
        log.info("[%3.0f %%] %s", frac * 100, msg)
        if progress:
            progress(frac, msg)

    nav, vyp = project.navrh, project.vypocet
    body = project.body
    lon = np.array([b.lon for b in body])
    lat = np.array([b.lat for b in body])
    bx, by = to_xy(lon, lat)
    body_xy = [(float(x), float(y)) for x, y in zip(bx, by)]
    je_stanice = [b.je_stanice for b in body]
    stanice_xy = [p for p, js in zip(body_xy, je_stanice) if js]
    varovani: list[str] = []

    # ------------------------------------------------------------ oblast
    ratio = 1 + nav.max_prodlouzeni_pct / 100.0
    xmin, ymin, xmax, ymax = _area_bounds(body_xy, ratio, vyp.okraj_km * 1000)
    res = float(vyp.rozliseni_m)
    while (xmax - xmin) * (ymax - ymin) / res ** 2 > 16e6:
        res *= 1.5
    if res != vyp.rozliseni_m:
        varovani.append(f"Oblast je velká – rozlišení automaticky zhrubeno na {res:.0f} m.")
    grid = Grid.from_bounds(xmin, ymin, xmax, ymax, res)
    prog(0.02, f"Oblast {grid.ncols * res / 1000:.0f} × {grid.nrows * res / 1000:.0f} km, rastr {grid.ncols} × {grid.nrows}")

    # -------------------------------------------------------------- data
    if vyp.demo:
        prog(0.05, "Generuji syntetický terén (demo) …")
        z = synthetic.synthetic_dem(grid)
        osm = synthetic.synthetic_osm(grid, stanice_xy)
    else:
        z = dem.load_dem(grid, vyp.vlastni_dem, lambda m: prog(0.08, m))
        prog(0.15, "Stahuji data OpenStreetMap …")
        osm = osm_mod.fetch_area(grid.bbox_lonlat(0.005), budovy=vyp.stahovat_budovy,
                                 chranena=vyp.chranena_uzemi, progress=lambda m: prog(0.2, m))
        varovani += osm.varovani

    # ------------------------------------------------------ nákladová mapa
    prog(0.3, "Počítám nákladovou mapu (zástavba, terén, voda, chráněná území) …")
    cs = build_cost_surface(grid, z, osm, stanice_xy, nav, project.vahy)

    # ---------------------------------------------------------- koridory
    koridory = []
    n_seg = len(body_xy) - 1
    for k in range(n_seg):
        prog(0.35 + 0.25 * k / n_seg, f"Hledám koridor {body[k].nazev} → {body[k + 1].nazev} …")
        sp = corridor.find_segment(cs.cost, grid, body_xy[k], body_xy[k + 1], nav.max_prodlouzeni_pct,
                                   progress=lambda m: prog(0.35 + 0.25 * k / n_seg, m))
        if not sp.limit_splnen:
            varovani.append(f"Úsek {body[k].nazev} → {body[k + 1].nazev}: limit prodloužení nelze splnit.")
        koridory.append(sp)

    # -------------------------------------------------------- směrové řešení
    prog(0.62, "Navrhuji směrové řešení (přímé a oblouky) …")
    Rmin, Rpref = nav.min_polomer(), nav.doporuceny_polomer()
    tol = max(vyp.tolerance_zjednoduseni_m, 2 * res)
    osa = horizontal.fit_alignment(body_xy, je_stanice, [k.xy for k in koridory], Rmin, Rpref,
                                   Lp=nav.delka_nastupiste_m, tol=tol, ds=10.0)
    varovani += osa.varovani
    line = LineString(osa.xy)

    # budovy v koridoru, pokud nejsou pro celou oblast
    if not osm.budovy_kompletni and not vyp.demo:
        prog(0.66, "Stahuji budovy v koridoru trati …")
        buf = line.buffer(200).simplify(40)
        ex = np.array(buf.exterior.coords)
        lo, la = to_lonlat(ex[:, 0], ex[:, 1])
        try:
            osm.budovy = osm_mod.fetch_buildings_corridor(list(zip(lo, la)), lambda m: prog(0.66, m))
        except osm_mod.OverpassError as e:
            varovani.append(f"{e}. Počet demolic nelze určit.")

    # ---------------------------------------------------------- niveleta
    prog(0.7, "Optimalizuji niveletu (výškové řešení) …")
    s = osa.s
    z_ter = grid.sample(z, osa.xy[:, 0], osa.xy[:, 1]).astype(float)
    voda, reky = structures.water_flags(line, s, osm)
    bud = structures.building_density(osa.xy, s, osm.budovy)
    st_s = [bs for bs, js in zip(osa.body_s, je_stanice) if js]
    z_rail = vertical.design_profile(s, z_ter, voda, bud, st_s, nav, project.ceny)
    h = z_rail - z_ter

    # ---------------------------------------------------------- analýza
    prog(0.85, "Klasifikuji stavby, demolice a křížení …")
    rr, cc = grid.rowcol(osa.xy[:, 0], osa.xy[:, 1])
    zast_mask = cs.zastavba[rr, cc] & (cs.stanice_vyjimka[rr, cc] < 0.5)
    an = structures.analyze(osa.xy, s, h, voda, reky, bud, osm, nav, project.ceny,
                            stanice_xy=stanice_xy, zastavba_mask=zast_mask)

    prog(0.9, "Počítám rozpočet …")
    n_st = sum(je_stanice)
    rozp = costs.estimate(osa.delka, s, h, an, max(n_st - 2, 0), 2, project.ceny)

    prog(0.94, "Simuluji jízdu vlaku …")
    jizda = traction.compute(s, z_rail, osa.krivost, osa.body_s, [b.nazev for b in body], je_stanice, nav,
                             project.vlak)

    vz_useky = [float(np.hypot(b[0] - a[0], b[1] - a[1])) for a, b in zip(body_xy[:-1], body_xy[1:])]
    vz = max(sum(vz_useky), 1.0)
    for k in range(n_seg):
        L = osa.body_s[k + 1] - osa.body_s[k]
        d = vz_useky[k]
        if d > 0 and L / d - 1 > nav.max_prodlouzeni_pct / 100 + 0.02:
            varovani.append(f"Úsek {body[k].nazev} → {body[k + 1].nazev} je po vložení oblouků "
                            f"o {100 * (L / d - 1):.1f} % delší než vzdušná čára.")
    prog(1.0, "Hotovo.")
    return Result(project=project, grid=grid, dem=z, cost=cs, osm=osm, body_xy=body_xy, koridory=koridory, osa=osa,
                  z_teren=z_ter, z_kolej=z_rail, analyza=an, rozpocet=rozp, jizda=jizda, vzdusna_m=vz,
                  vzdusna_useky_m=vz_useky, varovani=varovani, trvani_s=time.time() - t0)
