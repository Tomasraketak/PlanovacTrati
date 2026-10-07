"""Nákladový rastr pro hledání koridoru.

Hodnota buňky = relativní „cena“ jednoho metru trati vedené touto buňkou
(1.0 = trať v úrovni terénu v otevřené krajině). Přičítají se penalizace za
zástavbu, budovy, členitý terén, vodu a chráněná území. V okruhu kolem stanic
se zástavba nepenalizuje (trať do města vést má).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from rasterio.features import rasterize
from scipy import ndimage

from .config import NavrhoveParametry, Vahy
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


def _rasterize(geoms, grid: Grid, value=1, dtype="uint8") -> np.ndarray:
    shapes = [(g, value) for g in geoms if g is not None and not g.is_empty]
    if not shapes:
        return np.zeros(grid.shape, dtype=dtype)
    return rasterize(shapes, out_shape=grid.shape, transform=grid.transform, fill=0, dtype=dtype, all_touched=True)


def terrain_slope(dem: np.ndarray, res: float) -> np.ndarray:
    gy, gx = np.gradient(dem.astype(np.float64), res)
    return np.hypot(gx, gy)


def build_cost_surface(
    grid: Grid,
    dem: np.ndarray,
    osm: OsmData,
    stations_xy: list[tuple[float, float]],
    navrh: NavrhoveParametry,
    vahy: Vahy,
) -> CostSurface:
    res = grid.res
    X, Y = grid.cell_centers()

    # --- okolí stanic: plynulý přechod 0..1 (1 = uvnitř okruhu)
    vyjimka = np.zeros(grid.shape)
    R = navrh.polomer_stanice_m
    for sx, sy in stations_xy:
        d = np.hypot(X - sx, Y - sy)
        vyjimka = np.maximum(vyjimka, np.clip((1.5 * R - d) / (0.5 * R), 0, 1))
    pen_factor = 1.0 - vyjimka

    # --- zástavba: uvnitř vysoká penalizace, v pásmu 300 m klesající
    zast = _rasterize(osm.zastavba, grid).astype(bool)
    pen_obce = np.zeros(grid.shape)
    if zast.any():
        dist = ndimage.distance_transform_edt(~zast) * res
        pen_obce = np.where(zast, 40.0, 8.0 * np.clip(1 - dist / 300.0, 0, 1) ** 2)

    # --- jednotlivé budovy (hustota na buňku, vyhlazená)
    pen_bud = np.zeros(grid.shape)
    if len(osm.budovy):
        r, c = grid.rowcol(osm.budovy[:, 0], osm.budovy[:, 1])
        inside = (osm.budovy[:, 0] >= grid.bounds[0]) & (osm.budovy[:, 0] <= grid.bounds[2]) & \
                 (osm.budovy[:, 1] >= grid.bounds[1]) & (osm.budovy[:, 1] <= grid.bounds[3])
        cnt = np.zeros(grid.shape)
        np.add.at(cnt, (r[inside], c[inside]), 1.0)
        # počet budov na 1 ha zhruba, rozmazáno na šířku tělesa trati
        sigma = max(0.5, 30.0 / res)
        dens = ndimage.gaussian_filter(cnt, sigma) * (2500.0 / (res * res))
        pen_bud = 10.0 * np.clip(dens, 0, 10)

    # --- terén: sklon terénu vůči max. sklonu trati + lokální převýšení
    sl = terrain_slope(dem, res)
    g = navrh.max_sklon_promile / 1000.0
    pen_sl = 1.5 * np.clip((sl - g) / (4 * g), 0, 2) ** 1.5
    win = max(3, int(round(600.0 / res)) | 1)
    relief = ndimage.maximum_filter(dem, size=win) - ndimage.minimum_filter(dem, size=win)
    pen_rel = 2.0 * np.clip((relief - 25.0) / 60.0, 0, 2)
    pen_teren = pen_sl + pen_rel

    # --- voda
    voda = _rasterize(osm.voda_plochy, grid).astype(bool)
    pen_voda = np.where(voda, 6.0, 0.0)
    if osm.reky:
        reky = _rasterize([ls.buffer(res / 2) for _, ls in osm.reky], grid).astype(bool)
        pen_voda = pen_voda + np.where(reky, 1.5, 0.0)

    # --- chráněná území (nejpřísnější stupeň vyhrává)
    chran = np.zeros(grid.shape, dtype=np.uint8)
    for level in (3, 2, 1):
        m = _rasterize([p for _, lv, p in osm.chranena if lv == level], grid).astype(bool)
        chran[m] = level
    pen_chran = np.select([chran == 1, chran == 2, chran == 3], [12.0, 4.0, 0.8], 0.0)

    cost = (
        vahy.delka * 1.0
        + vahy.obce * pen_obce * pen_factor
        + vahy.budovy * pen_bud * pen_factor
        + vahy.teren * pen_teren
        + vahy.voda * pen_voda
        + vahy.chranena_uzemi * pen_chran
    )
    cost = np.maximum(cost, 0.05)
    return CostSurface(cost=cost.astype(np.float64), zastavba=zast, chranena=chran, voda=voda,
                       sklon=sl, stanice_vyjimka=vyjimka)
