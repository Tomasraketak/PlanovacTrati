"""Geografické pomůcky: projekce WGS84 <-> UTM 33N a pravidelná rastrová mřížka."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from pyproj import Transformer
from scipy import ndimage

# UTM zóna 33N pokrývá celé Česko (12°–18° v. d.) s malým zkreslením délek.
CRS_METRIC = "EPSG:32633"
CRS_WGS84 = "EPSG:4326"


@lru_cache(maxsize=1)
def _fwd() -> Transformer:
    return Transformer.from_crs(CRS_WGS84, CRS_METRIC, always_xy=True)


@lru_cache(maxsize=1)
def _inv() -> Transformer:
    return Transformer.from_crs(CRS_METRIC, CRS_WGS84, always_xy=True)


def to_xy(lon, lat):
    """WGS84 (lon, lat) -> metrické (x, y)."""
    return _fwd().transform(lon, lat)


def to_lonlat(x, y):
    """Metrické (x, y) -> WGS84 (lon, lat)."""
    return _inv().transform(x, y)


def xy_array_to_latlon(xy: np.ndarray) -> list[list[float]]:
    """Pole Nx2 (x, y) -> seznam [lat, lon] pro Leaflet."""
    lon, lat = to_lonlat(xy[:, 0], xy[:, 1])
    return [[float(a), float(b)] for a, b in zip(lat, lon)]


@dataclass
class Grid:
    """Pravidelná mřížka v metrickém CRS; počátek = levý horní roh."""

    x0: float
    y0: float
    res: float
    nrows: int
    ncols: int

    @classmethod
    def from_bounds(cls, xmin, ymin, xmax, ymax, res) -> "Grid":
        ncols = int(np.ceil((xmax - xmin) / res))
        nrows = int(np.ceil((ymax - ymin) / res))
        return cls(float(xmin), float(ymin + nrows * res), float(res), nrows, ncols)

    @property
    def shape(self) -> tuple[int, int]:
        return self.nrows, self.ncols

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0 - self.nrows * self.res, self.x0 + self.ncols * self.res, self.y0)

    @property
    def transform(self):
        from rasterio.transform import Affine

        return Affine(self.res, 0.0, self.x0, 0.0, -self.res, self.y0)

    def rowcol(self, x, y):
        """Souřadnice -> (řádek, sloupec) jako celá čísla (oříznuto do rastru)."""
        c = np.floor((np.asarray(x) - self.x0) / self.res).astype(int)
        r = np.floor((self.y0 - np.asarray(y)) / self.res).astype(int)
        return np.clip(r, 0, self.nrows - 1), np.clip(c, 0, self.ncols - 1)

    def frac_rowcol(self, x, y):
        """Spojité (řádek, sloupec) se středem buňky v celém čísle."""
        c = (np.asarray(x) - self.x0) / self.res - 0.5
        r = (self.y0 - np.asarray(y)) / self.res - 0.5
        return r, c

    def xy(self, r, c):
        """Střed buňky (řádek, sloupec) -> (x, y)."""
        x = self.x0 + (np.asarray(c) + 0.5) * self.res
        y = self.y0 - (np.asarray(r) + 0.5) * self.res
        return x, y

    def cell_centers(self):
        """Mřížky souřadnic X, Y (shape = rastr)."""
        xs = self.x0 + (np.arange(self.ncols) + 0.5) * self.res
        ys = self.y0 - (np.arange(self.nrows) + 0.5) * self.res
        return np.meshgrid(xs, ys)

    def sample(self, arr: np.ndarray, x, y, order: int = 1) -> np.ndarray:
        """Bilineární (order=1) vzorkování rastru v bodech."""
        r, c = self.frac_rowcol(x, y)
        return ndimage.map_coordinates(arr, [np.atleast_1d(r), np.atleast_1d(c)], order=order, mode="nearest")

    def bbox_lonlat(self, margin_deg: float = 0.0) -> tuple[float, float, float, float]:
        """Obalový obdélník rastru ve WGS84 (west, south, east, north)."""
        xmin, ymin, xmax, ymax = self.bounds
        xs = np.array([xmin, xmax, xmin, xmax, (xmin + xmax) / 2, (xmin + xmax) / 2])
        ys = np.array([ymin, ymin, ymax, ymax, ymin, ymax])
        lon, lat = to_lonlat(xs, ys)
        return (min(lon) - margin_deg, min(lat) - margin_deg, max(lon) + margin_deg, max(lat) + margin_deg)


def polyline_length(xy: np.ndarray) -> float:
    if len(xy) < 2:
        return 0.0
    return float(np.sum(np.hypot(*np.diff(xy, axis=0).T)))


def chainage(xy: np.ndarray) -> np.ndarray:
    """Kumulativní délka (staničení) podél lomené čáry."""
    if len(xy) < 2:
        return np.zeros(len(xy))
    return np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])


def resample_polyline(xy: np.ndarray, step: float) -> np.ndarray:
    """Převzorkuje lomenou čáru s konstantním krokem (poslední bod zachován)."""
    s = chainage(xy)
    n = max(2, int(np.ceil(s[-1] / step)) + 1)
    t = np.linspace(0.0, s[-1], n)
    return np.column_stack([np.interp(t, s, xy[:, 0]), np.interp(t, s, xy[:, 1])])


def douglas_peucker(xy: np.ndarray, tol: float, keep: set[int] | None = None) -> list[int]:
    """Douglas–Peuckerovo zjednodušení; vrací indexy zachovaných bodů.

    ``keep`` – indexy, které musí zůstat (např. stanice); čára se v nich rozdělí.
    """
    keep = set(keep or ())
    anchors = sorted({0, len(xy) - 1} | {k for k in keep if 0 <= k < len(xy)})
    out: set[int] = set(anchors)

    def rec(i0: int, i1: int) -> None:
        stack = [(i0, i1)]
        while stack:
            a, b = stack.pop()
            if b - a < 2:
                continue
            p, q = xy[a], xy[b]
            seg = q - p
            L = np.hypot(*seg)
            pts = xy[a + 1:b]
            if L < 1e-9:
                d = np.hypot(*(pts - p).T)
            else:
                d = np.abs(seg[0] * (pts[:, 1] - p[1]) - seg[1] * (pts[:, 0] - p[0])) / L
            k = int(np.argmax(d))
            if d[k] > tol:
                m = a + 1 + k
                out.add(m)
                stack.append((a, m))
                stack.append((m, b))

    for a, b in zip(anchors[:-1], anchors[1:]):
        rec(a, b)
    return sorted(out)
