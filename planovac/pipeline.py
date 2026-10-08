"""Orchestrace celého návrhu trati: data -> koridor -> osa -> niveleta -> analýza."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from concurrent.futures import ThreadPoolExecutor

import numpy as np
from shapely.geometry import LineString
from shapely.ops import unary_union

from . import paralelne
from . import soubeh as soubeh_mod
from . import corridor, costs, dem, horizontal, omezeni, osm as osm_mod, structures, synthetic, traction, vertical
from .config import TYP_STANICE, Project
from .costsurface import CostSurface, build_cost_surfaces, siroka_mesta
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
    auto: list = field(default_factory=list)            # jízdy autem mezi stanicemi (auto.JizdaAutem)
    auto_varovani: list[str] = field(default_factory=list)
    zaklad_cena_mil: float = 0.0          # cena varianty bez úseků se sníženou rychlostí
    zaklad_demolice: int = 0
    porovnani_vlaku: list[traction.PorovnaniVlaku] = field(default_factory=list)
    soubeh: list[soubeh_mod.UsekSoubehu] = field(default_factory=list)
    matice: list[traction.BunkaMatice] = field(default_factory=list)   # vlak × linka
    varianty: list[dict] = field(default_factory=list)     # obchvat měst × tunel pod městem
    vystavba_tunelu_let: float = 0.0                       # orientační doba výstavby nejdelšího tunelu
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
    while (xmax - xmin) * (ymax - ymin) / res ** 2 > vyp.max_bunek_mil * 1e6:
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
        osm_mod.nastav_zdroj(vyp.zdroj_dat)
        prog(0.15, "Stahuji data OpenStreetMap …")
        osm = osm_mod.fetch_area(grid.bbox_lonlat(0.005), budovy=vyp.stahovat_budovy,
                                 chranena=vyp.chranena_uzemi, progress=lambda m: prog(0.2, m))
        varovani += osm.varovani

    Rmin, Rpref = nav.min_polomer(), nav.doporuceny_polomer()
    rmin_useky = [nav.min_polomer_pro(b.max_rychlost_kmh) if b.max_rychlost_kmh else Rmin for b in body[:-1]]
    tol = max(vyp.tolerance_zjednoduseni_m, 2 * res)
    n_seg = len(body_xy) - 1
    n_vl = paralelne.pocet_vlaken(vyp.vlakna)

    # parametry jednotlivých bodů: nástupiště, okruh bez penalizace zástavby, váha stanice v DP
    delky_nast = [nav.delka_nastupiste_zastavky_m if b.je_zastavka else (nav.delka_nastupiste_m if b.je_stanice else 0.0)
                  for b in body]
    polomery = [nav.polomer_zastavky_m if b.je_zastavka else nav.polomer_stanice_m for b in body if b.je_stanice]
    vahy_st = [0.25 if b.je_zastavka else 1.0 for b in body]
    nazvy = [b.nazev for b in body]
    demol_mil = project.vahy.demolice_optimalizace_mil(project.ceny)
    hod_casu = project.vahy.hodnota_casu_mil_min

    sledovatelne = soubeh_mod.koleje_sledovatelne(osm, Rmin) if project.soubeh.povolit else []
    prichytit = soubeh_mod.PrichytitKolej(sledovatelne, 1.5 * res) if sledovatelne else None

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

    def koridory_a_osa(cs, popis: str, map_fn, f0: float, f1: float):
        """Koridory všech úseků (souběžně) + směrové řešení."""
        var: list[str] = []

        def jeden(k):
            prog(f0, f"Hledám koridor {popis}{body[k].nazev} → {body[k + 1].nazev} …")
            return corridor.find_segment(cs.cost, grid, body_xy[k], body_xy[k + 1], nav.max_prodlouzeni_pct,
                                         progress=lambda m: prog(f0, m), prichytit=prichytit, map_fn=map_fn)

        if map_fn is not None and n_seg > 1:
            with ThreadPoolExecutor(max_workers=n_seg) as ex:
                kor = list(ex.map(jeden, range(n_seg)))
        else:
            kor = [jeden(k) for k in range(n_seg)]
        for k, sp in enumerate(kor):
            if not sp.limit_splnen:
                var.append(f"Úsek {body[k].nazev} → {body[k + 1].nazev}: limit prodloužení nelze splnit.")
        prog(f1, f"Navrhuji směrové řešení {popis}(přímé a oblouky) …")
        o = fit(kor)
        return kor, o, var + o.varovani

    def fit(kor, zony=None, ref_xy=None):
        return horizontal.fit_alignment(body_xy, je_stanice, [k.xy for k in kor], Rmin, Rpref, Lp=delky_nast,
                                        tol=tol, ds=10.0, zony=zony, ref_xy=ref_xy, rmin_useky=rmin_useky)

    def stavba_cs(s_tunelem: bool):
        """(základní, tunel pod městem | None) – náročné vrstvy se počítají jednou."""
        return build_cost_surfaces(grid, z, osm, stanice_xy, nav, project.vahy, project.soubeh, project.koef,
                                   project.ceny, polomery, s_tunelem, n_vl)

    with paralelne.procesy(n_vl) as pool:
        map_fn = paralelne.map_procesy(pool)
        prog(0.3, f"Počítám nákladovou mapu (zástavba, terén, voda, chráněná území) – {n_vl} vláken …")
        mesta = project.vahy.tunel_pod_mestem
        cs_a, cs_b = stavba_cs(mesta)
        if cs_b is not None and not siroka_mesta(cs_a.zastavba, grid.res, project.koef.tunel_min_sirka_mesta_m).any():
            cs_b = None            # v oblasti není dost velké město – varianta s tunelem by nic nezměnila
        kor_a, osa_a, var_a = koridory_a_osa(cs_a, "", map_fn, 0.35, 0.5)
        kor_b = osa_b = None
        if cs_b is not None:
            kor_b, osa_b, var_b = koridory_a_osa(cs_b, "(tunel pod městem) ", map_fn, 0.45, 0.5)

        # budovy nejsou pro celou oblast -> stáhnout v pásu kolem 1. variant a návrh zopakovat
        if not osm.budovy_kompletni and not vyp.demo:
            try:
                osy = [osa_a] + ([osa_b] if osa_b is not None else [])
                pas1 = unary_union([LineString(o.xy).buffer(1200).simplify(150) for o in osy])
                stahni_budovy(pas1, 0.52)
                prog(0.56, "Přepočítávám nákladovou mapu s budovami a hledám trasu znovu …")
                cs_a, cs_b = stavba_cs(cs_b is not None)
                kor_a, osa_a, var_a = koridory_a_osa(cs_a, "", map_fn, 0.57, 0.62)
                if cs_b is not None:
                    kor_b, osa_b, var_b = koridory_a_osa(cs_b, "(tunel pod městem) ", map_fn, 0.6, 0.64)
                osy = [osa_a] + ([osa_b] if osa_b is not None else [])
                pas2 = unary_union([LineString(o.xy).buffer(250).simplify(50) for o in osy]).difference(
                    pas1.buffer(-50))
                if not pas2.is_empty and pas2.area > 1e5:
                    try:
                        stahni_budovy(pas2, 0.66)
                    except osm_mod.OverpassError as e:
                        varovani.append(f"{e}. Budovy na krátkých úsecích mimo první prohledaný pás chybí – "
                                        "počet demolic tam může být podhodnocen.")
            except osm_mod.OverpassError as e:
                varovani.append(f"{e}. Budovy nebyly staženy – vyhýbání se domům a počet demolic jsou jen přibližné "
                                "(podle zástavby).")

        def vyhodnot(o: horizontal.Alignment) -> omezeni.Varianta:
            """Niveleta + stavby + rozpočet + jízdní doba pro danou osu."""
            line = LineString(o.xy)
            s = o.s
            z_ter = grid.sample(z, o.xy[:, 0], o.xy[:, 1]).astype(float)
            voda, reky = structures.water_flags(line, s, osm)
            bud = structures.building_density(o.xy, s, osm.budovy)
            f_soub, zel, sil = soubeh_mod.faktor_osy(o.xy, osm, project.soubeh)
            bud = np.where(zel, 0.0, bud)          # na stávající trati se nebourá
            rr, cc = grid.rowcol(o.xy[:, 0], o.xy[:, 1])
            zast_os = cs_a.zastavba[rr, cc] & ~zel
            # stanice a zastávky: poloha, délka nástupiště, váha (stanice 1, zastávka 0,25)
            idx = [i for i, b in enumerate(body) if b.je_stanice]
            st_s = [o.body_s[i] for i in idx]
            st_info = [(delky_nast[i], vahy_st[i]) for i in idx]
            st_vz = np.zeros(len(s))
            for sx, (Lp_i, w_i) in zip(st_s, st_info):
                m = np.abs(s - sx) <= Lp_i / 2 + 5.0
                st_vz[m] = np.maximum(st_vz[m], w_i)
            z_rail = vertical.design_profile(s, z_ter, voda, bud, st_s, nav, project.ceny, demolice_mil=demol_mil,
                                             faktor=f_soub, zastavba=zast_os, stanice_info=st_info)
            h = z_rail - z_ter
            zast_mask = zast_os & (cs_a.stanice_vyjimka[rr, cc] < 0.5)
            an = structures.analyze(o.xy, s, h, voda, reky, bud, osm, nav, project.ceny,
                                    stanice_xy=stanice_xy, zastavba_mask=zast_mask, demolice_mil=demol_mil,
                                    bez_demolic=zel, zast=zast_os, st=st_vz)
            sleva = costs.sleva_soubeh(s, h, an.typy, f_soub, nav, project.ceny)
            # příplatek za hloubku stanic/zastávek
            podz = 0.0
            for sx, (Lp_i, w_i) in zip(st_s, st_info):
                m = np.abs(s - sx) <= Lp_i / 2
                if m.any():
                    podz += project.ceny.podzemni_stanice_mil_m * w_i * max(0.0, float(-h[m].min()))
            n_zast = sum(1 for b in body[1:-1] if b.je_zastavka)
            n_mezi = sum(1 for b in body[1:-1] if b.typ == TYP_STANICE)
            rozp = costs.estimate(o.delka, s, h, an, n_mezi, 2, project.ceny, sleva_mil=sleva, n_zastavek=n_zast,
                                  podzemni_mil=podz)
            jizda = traction.compute(s, z_rail, o.krivost, o.body_s, nazvy, je_stanice, nav, project.vlak, None,
                                     traction.limity_useku(body, o.body_s))
            nd = len(an.demolice_idx)
            cena_m = vertical.best_cost(h, nav, project.ceny, voda, bud, demol_mil, zast_os, st_vz) * f_soub
            J = (rozp.celkem_mil + project.vahy.penalizace_demolice_mil * project.vahy.budovy * nd
                 + hod_casu * jizda.celkem_s / 60.0)
            return omezeni.Varianta(osa=o, cena_mil=rozp.celkem_mil, demolice=nd, J=J,
                                    jizdni_doba_s=jizda.celkem_s,
                                    data=dict(z_ter=z_ter, z_rail=z_rail, an=an, rozp=rozp, jizda=jizda,
                                              cena_m=cena_m, soubeh=soubeh_mod.useky(s, zel, sil), sleva=sleva))

        prog(0.7, "Optimalizuji niveletu (výškové řešení) …")
        var_a_ev = vyhodnot(osa_a)
        porovnani_var = [("Obchvat měst (základní)", var_a_ev)]
        vybrana, kor, cs = var_a_ev, kor_a, cs_a
        var_osa = var_a
        if osa_b is not None:
            prog(0.74, "Vyhodnocuji variantu s tunelem pod městem …")
            var_b_ev = vyhodnot(osa_b)
            porovnani_var.append(("Tunel pod městem", var_b_ev))
            if var_b_ev.J < var_a_ev.J - 1e-6:
                vybrana, kor, cs, var_osa = var_b_ev, kor_b, cs_b, var_b
        zaklad = vybrana
        varovani += var_osa
        osa = vybrana.osa
        var, useky_omez, protokol = zaklad, [], []
        if project.omezeni.povolit and project.omezeni.max_pocet > 0:
            prog(0.76, "Hledám místa, kde by snížená rychlost výrazně ušetřila …")

            def navrhni(zony, kor=kor, osa=osa):
                return fit(kor, zony, osa.xy)

            var, useky_omez, protokol = omezeni.najdi_omezeni(
                zaklad, [k.xy for k in kor], zaklad.data["cena_m"], res, nav, project.omezeni, navrhni, vyhodnot,
                project.vahy.penalizace_demolice_mil, progress=lambda m: prog(0.8, m),
                vlakna=n_vl, hodnota_casu_mil_min=hod_casu)
    osa = var.osa
    koridory = kor
    z_ter, z_rail, an, rozp, jizda = (var.data[k] for k in ("z_ter", "z_rail", "an", "rozp", "jizda"))
    useky_soubehu, sleva_soubehu = var.data["soubeh"], var.data["sleva"]

    prog(0.94, "Porovnávám jízdní doby vlaků …")
    lim = traction.limity_useku(body, osa.body_s)
    porovnani = traction.porovnani_vlaku(osa.s, z_rail, osa.krivost, osa.body_s, nazvy, je_stanice, nav,
                                         project.vlak, lim)
    matice = traction.matice_jizdnich_dob(osa.s, z_rail, osa.krivost, osa.body_s, nazvy, je_stanice, nav,
                                          project.vlak, project.linky, lim)

    vz_useky = [float(np.hypot(b[0] - a[0], b[1] - a[1])) for a, b in zip(body_xy[:-1], body_xy[1:])]
    vz = max(sum(vz_useky), 1.0)
    for k in range(n_seg):
        L = osa.body_s[k + 1] - osa.body_s[k]
        d = vz_useky[k]
        if d > 0 and L / d - 1 > nav.max_prodlouzeni_pct / 100 + 0.02:
            varovani.append(f"Úsek {body[k].nazev} → {body[k + 1].nazev} je po vložení oblouků "
                            f"o {100 * (L / d - 1):.1f} % delší než vzdušná čára.")
    # orientační doba výstavby nejdelšího tunelu (ražba ze dvou portálů)
    tun = [u.delka for u in an.objekty if u.typ in (structures.TUNEL,)]
    vystavba = (max(tun) / 1000 / (2 * project.ceny.rychlost_razeni_km_rok) + 1.0) if tun else 0.0
    varianty = [{"varianta": nm, "delka_km": v.osa.delka / 1000, "cena_mld": v.cena_mil / 1000,
                 "demolice": v.demolice, "jizdni_doba_s": v.jizdni_doba_s, "J_mld": v.J / 1000,
                 "vybrana": v is zaklad} for nm, v in porovnani_var]
    prog(1.0, "Hotovo.")
    return Result(project=project, grid=grid, dem=z, cost=cs, osm=osm, body_xy=body_xy, koridory=koridory, osa=osa,
                  z_teren=z_ter, z_kolej=z_rail, analyza=an, rozpocet=rozp, jizda=jizda, vzdusna_m=vz,
                  vzdusna_useky_m=vz_useky, varovani=varovani, trvani_s=time.time() - t0, omezeni=useky_omez,
                  omezeni_protokol=protokol, zaklad_cena_mil=zaklad.cena_mil, zaklad_demolice=zaklad.demolice,
                  porovnani_vlaku=porovnani, soubeh=useky_soubehu, sleva_soubeh_mil=sleva_soubehu,
                  matice=matice, varianty=varianty, vystavba_tunelu_let=vystavba)


def jizda_pro(r: Result, vlak_nazev: str, linka) -> traction.JizdniDoby:
    """Přepočítá jízdní doby výsledku pro jiný vlak a linku (bez nového návrhu trati)."""
    from .config import VLAKY, Vlak

    p = r.project
    v = (Vlak.z_predvolby(vlak_nazev, pobyt_stanice_s=p.vlak.pobyt_stanice_s, rezerva_pct=p.vlak.rezerva_pct)
         if vlak_nazev in VLAKY else p.vlak)
    if isinstance(linka, str):
        linka = next((li for li in p.linky if li.nazev == linka), None)
    return traction.compute(r.osa.s, r.z_kolej, r.osa.krivost, r.osa.body_s, [b.nazev for b in p.body],
                            [b.je_stanice for b in p.body], p.navrh, v, linka,
                            traction.limity_useku(p.body, r.osa.body_s))


def matice_pro(r: Result, linky) -> list[traction.BunkaMatice]:
    """Matice vlak × linka pro výsledek a (případně upravené) linky."""
    p = r.project
    return traction.matice_jizdnich_dob(r.osa.s, r.z_kolej, r.osa.krivost, r.osa.body_s, [b.nazev for b in p.body],
                                        [b.je_stanice for b in p.body], p.navrh, p.vlak, linky,
                                        traction.limity_useku(p.body, r.osa.body_s))
