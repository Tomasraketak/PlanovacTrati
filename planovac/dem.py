"""Digitální model terénu (DEM).

Výchozí zdroj: Copernicus DEM GLO-30 (rozlišení ~30 m, volně dostupný, AWS Open Data).
Dlaždice 1°×1° se stáhnou do ``data/cache/dem`` a poté se slijí a převzorkují
do metrické mřížky UTM 33N v rozlišení zvoleném uživatelem.
Alternativně lze zadat vlastní GeoTIFF (např. DMR 5G od ČÚZK).
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Callable

import numpy as np
import requests
from scipy import ndimage

from .geo import CRS_METRIC, Grid
from .paths import cache_dir

log = logging.getLogger(__name__)

COPERNICUS_URL = "https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"
USER_AGENT = "PlanovacTrati/1.0 (+https://github.com/tomasraketak/planovactrati)"


def tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"


def tiles_for_bbox(west, south, east, north) -> list[tuple[int, int]]:
    return [
        (la, lo)
        for la in range(math.floor(south), math.floor(north) + 1)
        for lo in range(math.floor(west), math.floor(east) + 1)
    ]


def download_tile(lat: int, lon: int, progress: Callable[[str], None] | None = None) -> Path | None:
    """Stáhne dlaždici (pokud už není v cache). Vrací cestu nebo None (moře / chybí)."""
    name = tile_name(lat, lon)
    folder = cache_dir("dem")
    path = folder / f"{name}.tif"
    missing = folder / f"{name}.missing"
    if path.exists() and path.stat().st_size > 0:
        return path
    if missing.exists():
        return None
    url = COPERNICUS_URL.format(name=name)
    if progress:
        progress(f"Stahuji výškový model {name} …")
    tmp = path.with_suffix(".part")
    for attempt in range(4):
        try:
            with requests.get(url, stream=True, timeout=120, headers={"User-Agent": USER_AGENT}) as r:
                if r.status_code in (403, 404):
                    missing.write_text("tile not available")
                    return None
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            tmp.replace(path)
            return path
        except requests.RequestException as e:  # pragma: no cover - síť
            log.warning("Stažení %s selhalo (%s), pokus %d", name, e, attempt + 1)
            if attempt == 3:
                raise RuntimeError(f"Nepodařilo se stáhnout výškový model {name}: {e}") from e
    return None


def _reproject_into(src_path: Path, grid: Grid, dst: np.ndarray) -> None:
    import rasterio
    from rasterio.warp import Resampling, reproject

    tmp = np.full(grid.shape, np.nan, dtype=np.float32)
    with rasterio.open(src_path) as src:
        src_res_m = abs(src.res[0]) * (1.0 if src.crs and src.crs.is_projected else 111_000.0)
        # při zhrubnutí rastru průměrujeme, jinak bilineární interpolace
        resampling = Resampling.average if grid.res > 1.5 * src_res_m else Resampling.bilinear
        reproject(
            source=rasterio.band(src, 1),
            destination=tmp,
            dst_transform=grid.transform,
            dst_crs=CRS_METRIC,
            dst_nodata=np.nan,
            resampling=resampling,
            src_nodata=src.nodata,
        )
    ok = np.isfinite(tmp) & ~np.isfinite(dst)
    dst[ok] = tmp[ok]


def fill_nan(a: np.ndarray, fallback: float = 0.0) -> np.ndarray:
    """Vyplní NaN hodnotou nejbližšího platného pixelu."""
    bad = ~np.isfinite(a)
    if not bad.any():
        return a
    if bad.all():
        return np.full_like(a, fallback)
    idx = ndimage.distance_transform_edt(bad, return_distances=False, return_indices=True)
    return a[tuple(idx)]


def load_dem(grid: Grid, custom_path: str = "", progress: Callable[[str], None] | None = None) -> np.ndarray:
    """Vrátí výšky (m n. m.) na mřížce ``grid``."""
    dem = np.full(grid.shape, np.nan, dtype=np.float32)
    if custom_path:
        p = Path(custom_path)
        if not p.exists():
            raise FileNotFoundError(f"Vlastní DEM nenalezen: {p}")
        if progress:
            progress(f"Načítám vlastní výškový model {p.name} …")
        _reproject_into(p, grid, dem)
    else:
        west, south, east, north = grid.bbox_lonlat(0.01)
        for la, lo in tiles_for_bbox(west, south, east, north):
            path = download_tile(la, lo, progress)
            if path is not None:
                if progress:
                    progress(f"Převzorkovávám {path.stem} na {grid.res:.0f} m …")
                _reproject_into(path, grid, dem)
    if not np.isfinite(dem).any():
        raise RuntimeError("Výškový model pro zadanou oblast není k dispozici.")
    return fill_nan(dem)
