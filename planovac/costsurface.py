"""Nákladový rastr pro hledání koridoru.

Hodnota buňky = relativní „cena“ jednoho metru trati vedené touto buňkou
(1.0 = trať v úrovni terénu v otevřené krajině). Přičítají se penalizace za
zástavbu, budovy, členitý terén, vodu a chráněná území. V okruhu kolem stanic
se zástavba nepenalizuje (trať do města vést má).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
from rasterio.features import rasterize
from scipy import ndimage

from .config import Ceny, Koeficienty, NavrhoveParametry, Vahy
from .geo import Grid
from .osm import OsmData


@dataclass
class CostSurface:
    cost: np.ndarray            # nákladový rastr (>= 1)
    zastavba: np.ndarray        # bool – zastavěné území
    chranena: np.ndarray        # 0 = ne, 1–3 stupeň ochrany
    voda: np.ndarray            # bool – vodní plocha
    sklon: np.ndarray           # sklon terénu (bezrozměrný)
    stanice_vyjimka: np.ndarray  # 0..1 – 1 = v okolí stanice (bez penalizace zástavby)
    soubeh: np.ndarray | None = None  # faktor ceny za souběh (1 = bez slevy)


def _rasterize(geoms, grid: Grid, value=1, dtype="uint8") -> np.ndarray:
    shapes = [(g, value) for g in geoms if g is not None and not g.is_empty]
    if not shapes:
        return np.zeros(grid.shape, dtype=dtype)
    return rasterize(shapes, out_shape=grid.shape, transform=grid.transform, fill=0, dtype=dtype, all_touched=True)


def terrain_slope(dem: np.ndarray, res: float) -> np.ndarray:
    gy, gx = np.gradient(dem.astype(np.float32), np.float32(res))
    return np.hypot(gx, gy)


def siroka_mesta(zast: np.ndarray, res: float, min_sirka_m: float) -> np.ndarray:
    """Maska zástavby, kterou se vyplatí podtunelovat: části, do kterých se vejde kruh o průměru
    ``min_sirka_m`` (morfologické otevření přes vzdálenostní transformaci). Užší zástavbu (vesnice
    podél silnice) tunel nevyřeší – rampy by při sklonu nevyšly."""
    if not zast.any():
        return np.zeros_like(zast)
    r = min_sirka_m / 2.0
    jadro = ndimage.distance_transform_edt(zast) * res >= r
    if not jadro.any():
        return np.zeros_like(zast)
    return (ndimage.distance_transform_edt(~jadro) * res <= r) & zast


def tunel_ekvivalent(ceny, koef) -> float:
    """Příplatek „za metr“ v jednotkách nákladového rastru za vedení tunelem oproti trati v úrovni terénu."""
    if koef.tunel_ekvivalent > 0:
        return koef.tunel_ekvivalent
    zaklad = max(ceny.trat_zaklad_mil_km + ceny.technologie_mil_km, 1.0)
    return (ceny.tunel_mil_km + 0.15 * ceny.portal_mil) / zaklad


def _vrstvy(grid, dem, osm, stations_xy, navrh, koef, polomery_stanic, vlakna: int):
    """Výpočetně náročné vrstvy nákladové mapy (společné pro obě varianty); nezávislé části ve vláknech."""
    res = grid.res
    f32 = np.float32

    def stanice():
        X, Y = grid.cell_centers()
        vyj = np.zeros(grid.shape, dtype=f32)
        for k, (sx, sy) in enumerate(stations_xy):
            R = polomery_stanic[k] if polomery_stanic else navrh.polomer_stanice_m
            d = np.hypot(X - sx, Y - sy)
            np.maximum(vyj, np.clip((1.5 * R - d) / (0.5 * R), 0, 1).astype(f32), out=vyj)
        return vyj

    def zastavba():
        zast = _rasterize(osm.zastavba, grid).astype(bool)
        pen = np.zeros(grid.shape, dtype=f32)
        if zast.any():
            dist = (ndimage.distance_transform_edt(~zast) * res).astype(f32)
            pen = np.where(zast, f32(koef.pen_zastavba_uvnitr),
                           f32(koef.pen_zastavba_pas) * np.clip(1 - dist / 300.0, 0, 1) ** 2).astype(f32)
        return zast, pen

    def budovy():
        pen = np.zeros(grid.shape, dtype=f32)
        if len(osm.budovy):
            r, c = grid.rowcol(osm.budovy[:, 0], osm.budovy[:, 1])
            inside = (osm.budovy[:, 0] >= grid.bounds[0]) & (osm.budovy[:, 0] <= grid.bounds[2]) & \
                     (osm.budovy[:, 1] >= grid.bounds[1]) & (osm.budovy[:, 1] <= grid.bounds[3])
            cnt = np.zeros(grid.shape, dtype=f32)
            np.add.at(cnt, (r[inside], c[inside]), 1.0)
            sigma = max(0.5, 30.0 / res)           # rozmazáno na šířku tělesa trati
            dens = ndimage.gaussian_filter(cnt, sigma) * f32(2500.0 / (res * res))   # budov na ~1 ha
            pen = (koef.pen_budovy * np.clip(dens, 0, 10)).astype(f32)
        return pen

    def teren():
        sl = terrain_slope(dem, res)
        g = navrh.max_sklon_promile / 1000.0
        pen_sl = koef.pen_teren_sklon * np.clip((sl - g) / (4 * g), 0, 2) ** 1.5
        win = max(3, int(round(600.0 / res)) | 1)
        relief = ndimage.maximum_filter(dem, size=win) - ndimage.minimum_filter(dem, size=win)
        pen_rel = koef.pen_teren_relief * np.clip((relief - 25.0) / 60.0, 0, 2)
        return (pen_sl + pen_rel).astype(f32), sl.astype(f32)

    def voda_a_chranena():
        voda = _rasterize(osm.voda_plochy, grid).astype(bool)
        pen_voda = np.where(voda, f32(koef.pen_voda), f32(0))
        if osm.reky:
            reky = _rasterize([ls.buffer(res / 2) for _, ls in osm.reky], grid).astype(bool)
            pen_voda = pen_voda + np.where(reky, f32(koef.pen_reka), f32(0))
        chran = np.zeros(grid.shape, dtype=np.uint8)
        for level in (3, 2, 1):
            m = _rasterize([p for _, lv, p in osm.chranena if lv == level], grid).astype(bool)
            chran[m] = level
        pen_chran = np.select([chran == 1, chran == 2, chran == 3],
                              [koef.pen_chranena_np, koef.pen_chranena_rez, koef.pen_chranena_chko], 0.0).astype(f32)
        return voda, pen_voda, chran, pen_chran

    ulohy = [stanice, zastavba, budovy, teren, voda_a_chranena]
    if vlakna > 1:
        with ThreadPoolExecutor(max_workers=min(vlakna, len(ulohy))) as ex:
            fut = [ex.submit(u) for u in ulohy]
            vysl = [f.result() for f in fut]
    else:
        vysl = [u() for u in ulohy]
    vyj, (zast, pen_obce), pen_bud, (pen_teren, sl), (voda, pen_voda, chran, pen_chran) = vysl
    return dict(vyjimka=vyj, zast=zast, pen_obce=pen_obce, pen_bud=pen_bud, pen_teren=pen_teren, sklon=sl,
                voda=voda, pen_voda=pen_voda, chran=chran, pen_chran=pen_chran)


def build_cost_surfaces(
    grid: Grid,
    dem: np.ndarray,
    osm: OsmData,
    stations_xy: list[tuple[float, float]],
    navrh: NavrhoveParametry,
    vahy: Vahy,
    soubeh=None,
    koef: Koeficienty | None = None,
    ceny: Ceny | None = None,
    polomery_stanic: list[float] | None = None,
    s_tunelem: bool = False,
    vlakna: int = 1,
) -> tuple[CostSurface, CostSurface | None]:
    """Nákladová mapa základní varianty (město se objíždí) a – je-li ``s_tunelem`` – varianty „tunel pod městem“.
    Náročné vrstvy se počítají jen jednou."""
    koef = koef or Koeficienty()
    ceny = ceny or Ceny()
    f32 = np.float32
    L = _vrstvy(grid, dem, osm, stations_xy, navrh, koef, polomery_stanic, vlakna)
    zast = L["zast"]
    pen_factor0 = 1.0 - L["vyjimka"]
    rail = soubeh_f = None
    if soubeh is not None and soubeh.povolit and soubeh.pritahovat:
        from .soubeh import faktor_rastr

        soubeh_f, rail = faktor_rastr(grid, osm, soubeh, navrh.min_polomer())
        soubeh_f = soubeh_f.astype(f32)

    def slozit(tunel_mesto: bool) -> CostSurface:
        pen_obce, pen_bud, pen_factor = L["pen_obce"], L["pen_bud"], pen_factor0
        if tunel_mesto and zast.any():
            tm = siroka_mesta(zast, grid.res, koef.tunel_min_sirka_mesta_m)
            ekv = f32(tunel_ekvivalent(ceny, koef))
            pen_obce = np.where(tm, np.minimum(pen_obce, ekv), pen_obce)
            pen_bud = np.where(tm, f32(0), pen_bud)
            pen_factor = np.where(tm, f32(1), pen_factor)
        # okruh stanic zmírňuje jen penalizaci zástavby (trať smí do města), ne bourání domů
        bud_factor = 1.0 - L["vyjimka"] * (1.0 - koef.pen_budovy_u_stanic)
        if tunel_mesto and zast.any():
            bud_factor = np.where(tm, f32(1), bud_factor)
        cost = (vahy.delka * 1.0 + vahy.obce * pen_obce * pen_factor + vahy.budovy * pen_bud * bud_factor
                + vahy.teren * L["pen_teren"] + vahy.voda * L["pen_voda"]
                + vahy.chranena_uzemi * L["pen_chran"]).astype(f32)
        sf = np.ones(grid.shape, dtype=f32)
        if soubeh_f is not None:
            sf = soubeh_f
            zakl = (vahy.delka * 1.0 + vahy.teren * L["pen_teren"]).astype(f32)
            pen = cost - zakl
            cost = zakl * sf + np.where(rail, f32(koef.pen_soubeh_koleje_zbytek), f32(1)) * pen
        cost = np.maximum(cost, f32(0.05))
        return CostSurface(cost=cost, zastavba=zast, chranena=L["chran"], voda=L["voda"], sklon=L["sklon"],
                           stanice_vyjimka=L["vyjimka"], soubeh=sf)

    a = slozit(False)
    b = slozit(True) if s_tunelem else None
    return a, b


def build_cost_surface(grid, dem, osm, stations_xy, navrh, vahy, soubeh=None, koef=None, ceny=None,
                       polomery_stanic=None, tunel_mesto: bool = False, vlakna: int = 1) -> CostSurface:
    """Jedna varianta nákladové mapy (``tunel_mesto`` – varianta s tunelem pod městem)."""
    a, b = build_cost_surfaces(grid, dem, osm, stations_xy, navrh, vahy, soubeh, koef, ceny, polomery_stanic,
                               s_tunelem=tunel_mesto, vlakna=vlakna)
    return b if tunel_mesto else a
