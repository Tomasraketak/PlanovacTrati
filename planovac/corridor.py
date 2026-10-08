"""Hledání optimálního koridoru mezi dvěma body.

1. Dijkstra (skimage MCP_Geometric, 8-sousednost) na nákladovém rastru, oříznutém
   na elipsu s ohnisky v koncových bodech: každá trasa mimo elipsu by byla delší
   než povolené prodloužení, takže se vůbec neprohledává.
2. „Natahování provázku“ (string pulling): úseky schodovité rastrové cesty se
   nahradí přímkou, pokud tím celková cena nevzroste – vzniká lomená čára
   s libovolnými směry.
3. Pokud je trasa delší než limit, přidá se ke ceně každého metru Lagrangeův
   multiplikátor λ (tlak na kratší trasu) a hledá se bisekcí nejmenší λ,
   při kterém je limit splněn.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from skimage.graph import MCP_Geometric

from .geo import Grid, polyline_length


@dataclass
class SegmentPath:
    xy: np.ndarray        # lomená čára (N×2)
    delka: float
    vzdusna: float
    lam: float
    cena: float
    limit_splnen: bool


def _line_cost(cost: np.ndarray, grid: Grid, p, q, sub: Grid | None = None) -> float:
    g = sub or grid
    L = float(np.hypot(q[0] - p[0], q[1] - p[1]))
    n = max(2, int(L / (g.res * 0.5)) + 1)
    t = np.linspace(0, 1, n)
    xs = p[0] + (q[0] - p[0]) * t
    ys = p[1] + (q[1] - p[1]) * t
    r, c = g.frac_rowcol(xs, ys)
    ri = np.clip(np.rint(r).astype(int), 0, g.nrows - 1)
    ci = np.clip(np.rint(c).astype(int), 0, g.ncols - 1)
    v = cost[ri, ci]
    if not np.all(np.isfinite(v)):
        return np.inf
    return float(np.mean(v) * L)


def string_pull(xy: np.ndarray, cost: np.ndarray, grid: Grid, tol: float = 0.003) -> np.ndarray:
    """Zjednoduší rastrovou cestu na lomenou čáru bez zvýšení ceny (o víc než ``tol``)."""
    n = len(xy)
    if n <= 2:
        return xy
    seg = np.array([_line_cost(cost, grid, xy[k], xy[k + 1]) for k in range(n - 1)])
    cum = np.concatenate([[0.0], np.cumsum(seg)])

    def ok(i, j):
        lc = _line_cost(cost, grid, xy[i], xy[j])
        return lc <= (cum[j] - cum[i]) * (1 + tol) + 1e-6

    out = [0]
    i = 0
    while i < n - 1:
        good = i + 1
        step = 2
        bad = None
        while True:
            j = i + step
            if j >= n - 1:
                j = n - 1
                if ok(i, j):
                    good = j
                else:
                    bad = j
                break
            if ok(i, j):
                good = j
                step *= 2
            else:
                bad = j
                break
        if bad is not None:
            lo, hi = good, bad
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if ok(i, mid):
                    lo = mid
                else:
                    hi = mid
            good = lo
        out.append(good)
        i = good
    return xy[out]


def _subgrid(grid: Grid, a, b, max_ratio: float, margin: float):
    """Výřez rastru obsahující elipsu přípustných tras + okraj."""
    d = float(np.hypot(b[0] - a[0], b[1] - a[1]))
    semi_a = max_ratio * d / 2.0
    semi_b = np.sqrt(max(semi_a ** 2 - (d / 2) ** 2, 0.0))
    ext = max(semi_a, semi_b) + margin
    cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    xmin, ymin, xmax, ymax = grid.bounds
    x0 = max(xmin, cx - ext)
    x1 = min(xmax, cx + ext)
    y0 = max(ymin, cy - ext)
    y1 = min(ymax, cy + ext)
    c0 = int(np.floor((x0 - grid.x0) / grid.res))
    c1 = int(np.ceil((x1 - grid.x0) / grid.res))
    r0 = int(np.floor((grid.y0 - y1) / grid.res))
    r1 = int(np.ceil((grid.y0 - y0) / grid.res))
    r0, c0 = max(r0, 0), max(c0, 0)
    r1, c1 = min(r1, grid.nrows), min(c1, grid.ncols)
    sub = Grid(grid.x0 + c0 * grid.res, grid.y0 - r0 * grid.res, grid.res, r1 - r0, c1 - c0)
    return sub, (slice(r0, r1), slice(c0, c1)), d


@dataclass
class _Ulohy:
    """Vše, co je potřeba k řešení jednoho úseku (picklovatelné pro výpočet v procesech)."""

    c: np.ndarray            # nákladový výřez (float32, mimo elipsu inf)
    sub: Grid
    a: tuple[float, float]
    b: tuple[float, float]
    rc_a: tuple[int, int]
    rc_b: tuple[int, int]
    prichytit: object = None


def reseni_lambda(u: _Ulohy, lam: float):
    """Nejlevnější cesta pro cenu ``c + lam`` (lam = tlak na kratší trasu). Funkce na úrovni modulu,
    aby šla spustit v jiném procesu."""
    cl = (u.c + np.float32(lam)).astype(np.float64)
    mcp = MCP_Geometric(cl, fully_connected=True)
    mcp.find_costs([u.rc_a], [u.rc_b])
    path = np.array(mcp.traceback(u.rc_b))
    x, y = u.sub.xy(path[:, 0], path[:, 1])
    xy = np.column_stack([x, y])
    xy[0] = u.a
    xy[-1] = u.b
    xy = string_pull(xy, cl, u.sub)
    if u.prichytit is not None:
        xy = u.prichytit(xy)
    L = polyline_length(xy)
    cena = sum(_line_cost(u.c, u.sub, xy[k], xy[k + 1]) for k in range(len(xy) - 1))
    return xy, L, cena


def _serial_map(fn, ulohy, lams):
    return [fn(ulohy, lam) for lam in lams]


# vlny hodnot λ: první hrubá (geometrická řada), druhá zjemní interval mezi poslední nevyhovující a první
# vyhovující hodnotou. Stejné vlny se počítají sériově i paralelně → výsledek nezávisí na počtu vláken.
VLNA1 = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
POCET_VLNA2 = 6


def find_segment(
    cost: np.ndarray,
    grid: Grid,
    a: tuple[float, float],
    b: tuple[float, float],
    max_prodlouzeni_pct: float,
    progress=None,
    prichytit=None,
    map_fn=None,
) -> SegmentPath:
    """``prichytit`` – volitelná funkce xy -> xy (např. přichycení vrcholů ke stávající koleji);
    ``map_fn(fn, ulohy, lams)`` – paralelní mapování (výchozí sériové)."""
    map_fn = map_fn or _serial_map
    ratio = 1.0 + max_prodlouzeni_pct / 100.0
    sub, sl, d = _subgrid(grid, a, b, ratio, margin=3 * grid.res)
    c = np.array(cost[sl], dtype=np.float32)
    xs = (sub.x0 + (np.arange(sub.ncols) + 0.5) * sub.res).astype(np.float32)
    ys = (sub.y0 - (np.arange(sub.nrows) + 0.5) * sub.res).astype(np.float32)
    # elipsa: |XA| + |XB| <= ratio·d (s rezervou na rastrovou cestu)
    da = np.hypot(xs[None, :] - np.float32(a[0]), ys[:, None] - np.float32(a[1]))
    da += np.hypot(xs[None, :] - np.float32(b[0]), ys[:, None] - np.float32(b[1]))
    c[da > ratio * d + 2 * grid.res] = np.inf
    del da
    ra, ca = sub.rowcol(a[0], a[1])
    rb, cb = sub.rowcol(b[0], b[1])
    c[ra, ca] = max(float(np.nan_to_num(c[ra, ca], posinf=1.0)), 0.05)
    c[rb, cb] = max(float(np.nan_to_num(c[rb, cb], posinf=1.0)), 0.05)
    limit = ratio * d
    u = _Ulohy(c, sub, a, b, (int(ra), int(ca)), (int(rb), int(cb)), prichytit)

    xy, L, cena = map_fn(reseni_lambda, u, [0.0])[0]
    if L <= limit:
        return SegmentPath(xy, L, d, 0.0, cena, True)

    if progress:
        progress(f"Trasa o {100 * (L / d - 1):.0f} % delší než vzdušná čára – zkracuji …")
    res1 = map_fn(reseni_lambda, u, list(VLNA1))
    ok = [i for i, r in enumerate(res1) if r[1] <= limit]
    if not ok:
        xy_h, L_h, c_h = res1[-1]
        return SegmentPath(xy_h, L_h, d, VLNA1[-1], c_h, False)
    i = ok[0]
    best = (*res1[i], VLNA1[i])
    lo = VLNA1[i - 1] if i > 0 else 0.0
    hi = VLNA1[i]
    if hi - lo > 1e-3:
        lams = [lo + (hi - lo) * (k + 1) / (POCET_VLNA2 + 1) for k in range(POCET_VLNA2)]
        res2 = map_fn(reseni_lambda, u, lams)
        for lam, r in zip(lams, res2):
            if r[1] <= limit and lam < best[3]:
                best = (*r, lam)
    return SegmentPath(best[0], best[1], d, best[3], best[2], True)
