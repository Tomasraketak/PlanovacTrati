"""Orchestrace celého návrhu trati: data -> koridor -> osa -> niveleta -> analýza."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from shapely.geometry import LineString

from . import soubeh as soubeh_mod
from . import corridor, costs, dem, horizontal, omezeni, osm as osm_mod, structures, synthetic, traction, vertical
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
    omezeni: list[omezeni.Usek] = field(default_factory=list)     # úseky se sníženou rychlostí
    omezeni_protokol: list[str] = field(default_factory=list)
    zaklad_cena_mil: float = 0.0          # cena varianty bez úseků se sníženou rychlostí
    zaklad_demolice: int = 0
    porovnani_vlaku: list[traction.PorovnaniVlaku] = field(default_factory=list)
    soubeh: list[soubeh_mod.UsekSoubehu] = field(default_factory=list)
    matice: list[traction.BunkaMatice] = field(default_factory=list)   # vlak × linka
    sleva_soubeh_mil: float = 0.0

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

    Rmin, Rpref = nav.min_polomer(), nav.doporuceny_polomer()
    tol = max(vyp.tolerance_zjednoduseni_m, 2 * res)
    n_seg = len(body_xy) - 1

    sledovatelne = osm_mod.OsmData(zeleznice=soubeh_mod.koleje_sledovatelne(osm, Rmin))

    def prichytit(xy):
        if not project.soubeh.povolit:
            return xy
        return soubeh_mod.prichytit_ke_koleji(xy, sledovatelne, 1.5 * res)

    def navrh_osy(cs, f0: float, f1: float):
        """Koridory všech úseků + směrové řešení."""
        kor = []
        var = []
        for k in range(n_seg):
            f = f0 + (f1 - f0) * k / n_seg
            prog(f, f"Hledám koridor {body[k].nazev} → {body[k + 1].nazev} …")
            sp = corridor.find_segment(cs.cost, grid, body_xy[k], body_xy[k + 1], nav.max_prodlouzeni_pct,
                                       progress=lambda m, f=f: prog(f, m), prichytit=prichytit)
            if not sp.limit_splnen:
                var.append(f"Úsek {body[k].nazev} → {body[k + 1].nazev}: limit prodloužení nelze splnit.")
            kor.append(sp)
        prog(f1, "Navrhuji směrové řešení (přímé a oblouky) …")
        o = horizontal.fit_alignment(body_xy, je_stanice, [k.xy for k in kor], Rmin, Rpref,
                                     Lp=nav.delka_nastupiste_m, tol=tol, ds=10.0)
        return kor, o, var + o.varovani

    def stahni_budovy(oblast, f):
        """Doplní budovy uvnitř (multi)polygonu ``oblast`` (metrické souřadnice)."""
        parts = list(getattr(oblast, "geoms", [oblast]))
        new = [osm.budovy] if len(osm.budovy) else []
        for i, poly in enumerate(parts):
            if poly.area < 1e4:
                continue
            ex = np.array(poly.exterior.coords)
            lo, la = to_lonlat(ex[:, 0], ex[:, 1])
            prog(f, f"Stahuji budovy v koridoru trati ({i + 1}/{len(parts)}) …")
            new.append(osm_mod.fetch_buildings_corridor(list(zip(lo, la)), lambda m: prog(f, m)))
        if new:
            osm.budovy = np.unique(np.vstack(new).round(1), axis=0)

    # ------------------------------------------------------ nákladová mapa
    prog(0.3, "Počítám nákladovou mapu (zástavba, terén, voda, chráněná území) …")
    cs = build_cost_surface(grid, z, osm, stanice_xy, nav, project.vahy, project.soubeh)
    koridory, osa, var_osa = navrh_osy(cs, 0.35, 0.5)

    # budovy nejsou pro celou oblast -> stáhnout v pásu kolem 1. varianty a návrh zopakovat
    if not osm.budovy_kompletni and not vyp.demo:
        try:
            pas1 = LineString(osa.xy).buffer(1200).simplify(150)
            stahni_budovy(pas1, 0.52)
            prog(0.56, "Přepočítávám nákladovou mapu s budovami a hledám trasu znovu …")
            cs = build_cost_surface(grid, z, osm, stanice_xy, nav, project.vahy, project.soubeh)
            koridory, osa, var_osa = navrh_osy(cs, 0.57, 0.64)
            # části nové osy mimo prohledaný pás doplnit
            pas2 = LineString(osa.xy).buffer(250).simplify(50).difference(pas1.buffer(-50))
            if not pas2.is_empty and pas2.area > 1e5:
                try:
                    stahni_budovy(pas2, 0.66)
                except osm_mod.OverpassError as e:
                    varovani.append(f"{e}. Budovy na krátkých úsecích mimo první prohledaný pás chybí – "
                                    "počet demolic tam může být podhodnocen.")
        except osm_mod.OverpassError as e:
            varovani.append(f"{e}. Budovy nebyly staženy – vyhýbání se domům a počet demolic jsou jen přibližné "
                            "(podle zástavby).")
    varovani += var_osa
    demol_mil = project.vahy.demolice_optimalizace_mil(project.ceny)
    nazvy = [b.nazev for b in body]
    n_st = sum(je_stanice)

    def vyhodnot(o: horizontal.Alignment) -> omezeni.Varianta:
        """Niveleta + stavby + rozpočet + jízdní doba pro danou osu."""
        line = LineString(o.xy)
        s = o.s
        z_ter = grid.sample(z, o.xy[:, 0], o.xy[:, 1]).astype(float)
        voda, reky = structures.water_flags(line, s, osm)
        bud = structures.building_density(o.xy, s, osm.budovy)
        f_soub, zel, sil = soubeh_mod.faktor_osy(o.xy, osm, project.soubeh)
        bud = np.where(zel, 0.0, bud)          # na stávající trati se nebourá
        st_s = [bs for bs, js in zip(o.body_s, je_stanice) if js]
        z_rail = vertical.design_profile(s, z_ter, voda, bud, st_s, nav, project.ceny, demolice_mil=demol_mil,
                                         faktor=f_soub)
        h = z_rail - z_ter
        rr, cc = grid.rowcol(o.xy[:, 0], o.xy[:, 1])
        zast_mask = cs.zastavba[rr, cc] & (cs.stanice_vyjimka[rr, cc] < 0.5) & ~zel
        an = structures.analyze(o.xy, s, h, voda, reky, bud, osm, nav, project.ceny,
                                stanice_xy=stanice_xy, zastavba_mask=zast_mask, demolice_mil=demol_mil,
                                bez_demolic=zel)
        sleva = costs.sleva_soubeh(s, h, an.typy, f_soub, nav, project.ceny)
        rozp = costs.estimate(o.delka, s, h, an, max(n_st - 2, 0), 2, project.ceny, sleva_mil=sleva)
        jizda = traction.compute(s, z_rail, o.krivost, o.body_s, nazvy, je_stanice, nav, project.vlak)
        nd = len(an.demolice_idx)
        cena_m = vertical.best_cost(h, nav, project.ceny, voda, bud, demol_mil) * f_soub
        return omezeni.Varianta(osa=o, cena_mil=rozp.celkem_mil, demolice=nd,
                                J=rozp.celkem_mil + project.vahy.penalizace_demolice_mil * project.vahy.budovy * nd,
                                jizdni_doba_s=jizda.celkem_s,
                                data=dict(z_ter=z_ter, z_rail=z_rail, an=an, rozp=rozp, jizda=jizda, cena_m=cena_m,
                                          soubeh=soubeh_mod.useky(s, zel, sil), sleva=sleva))

    prog(0.7, "Optimalizuji niveletu (výškové řešení) …")
    zaklad = vyhodnot(osa)
    var, useky_omez, protokol = zaklad, [], []
    if project.omezeni.povolit and project.omezeni.max_pocet > 0:
        prog(0.76, "Hledám místa, kde by snížená rychlost výrazně ušetřila …")

        def navrhni(zony):
            return horizontal.fit_alignment(body_xy, je_stanice, [k.xy for k in koridory], Rmin, Rpref,
                                            Lp=nav.delka_nastupiste_m, tol=tol, ds=10.0, zony=zony, ref_xy=osa.xy)

        var, useky_omez, protokol = omezeni.najdi_omezeni(
            zaklad, [k.xy for k in koridory], zaklad.data["cena_m"], res, nav, project.omezeni, navrhni, vyhodnot,
            project.vahy.penalizace_demolice_mil, progress=lambda m: prog(0.8, m))
    osa = var.osa
    z_ter, z_rail, an, rozp, jizda = (var.data[k] for k in ("z_ter", "z_rail", "an", "rozp", "jizda"))
    useky_soubehu, sleva_soubehu = var.data["soubeh"], var.data["sleva"]

    prog(0.94, "Porovnávám jízdní doby vlaků …")
    porovnani = traction.porovnani_vlaku(osa.s, z_rail, osa.krivost, osa.body_s, nazvy, je_stanice, nav,
                                         project.vlak)
    matice = traction.matice_jizdnich_dob(osa.s, z_rail, osa.krivost, osa.body_s, nazvy, je_stanice, nav,
                                          project.vlak, project.linky)

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
                  vzdusna_useky_m=vz_useky, varovani=varovani, trvani_s=time.time() - t0, omezeni=useky_omez,
                  omezeni_protokol=protokol, zaklad_cena_mil=zaklad.cena_mil, zaklad_demolice=zaklad.demolice,
                  porovnani_vlaku=porovnani, soubeh=useky_soubehu, sleva_soubeh_mil=sleva_soubehu,
                  matice=matice)


def jizda_pro(r: Result, vlak_nazev: str, linka) -> traction.JizdniDoby:
    """Přepočítá jízdní doby výsledku pro jiný vlak a linku (bez nového návrhu trati)."""
    from .config import VLAKY, Vlak

    p = r.project
    v = (Vlak.z_predvolby(vlak_nazev, pobyt_stanice_s=p.vlak.pobyt_stanice_s, rezerva_pct=p.vlak.rezerva_pct)
         if vlak_nazev in VLAKY else p.vlak)
    if isinstance(linka, str):
        linka = next((li for li in p.linky if li.nazev == linka), None)
    return traction.compute(r.osa.s, r.z_kolej, r.osa.krivost, r.osa.body_s, [b.nazev for b in p.body],
                            [b.je_stanice for b in p.body], p.navrh, v, linka)


def matice_pro(r: Result, linky) -> list[traction.BunkaMatice]:
    """Matice vlak × linka pro výsledek a (případně upravené) linky."""
    p = r.project
    return traction.matice_jizdnich_dob(r.osa.s, r.z_kolej, r.osa.krivost, r.osa.body_s, [b.nazev for b in p.body],
                                        [b.je_stanice for b in p.body], p.navrh, p.vlak, linky)
