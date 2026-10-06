"""Syntetický terén a „obce“ pro demo režim a testy (bez internetu)."""
from __future__ import annotations

import numpy as np
from shapely.geometry import LineString, Point, Polygon

from .geo import Grid
from .osm import OsmData


def synthetic_dem(grid: Grid, seed: int = 7) -> np.ndarray:
    """Pahorkatina 400–750 m s hřbetem, údolím řeky a náhodnými kopci."""
    X, Y = grid.cell_centers()
    rng = np.random.default_rng(seed)
    xmin, ymin, xmax, ymax = grid.bounds
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    span = max(xmax - xmin, ymax - ymin)
    z = 480.0 + 0.0008 * (Y - cy)  # mírný sklon k jihu
    # kopce
    for _ in range(40):
        hx = cx + rng.uniform(-0.5, 0.5) * span
        hy = cy + rng.uniform(-0.5, 0.5) * span
        h = rng.uniform(30, 160)
        s = rng.uniform(1500, 6000)
        z += h * np.exp(-((X - hx) ** 2 + (Y - hy) ** 2) / (2 * s * s))
    # hřbet napříč oblastí
    z += 120 * np.exp(-((X - cx - 0.1 * span) ** 2) / (2 * 3000.0 ** 2))
    # údolí řeky (meandr)
    rx = cx - 0.2 * span + 2500 * np.sin((Y - cy) / 4000.0)
    z -= 70 * np.exp(-((X - rx) ** 2) / (2 * 900.0 ** 2))
    # drobná členitost
    for k in range(1, 6):
        a, b, c = rng.uniform(0, 2 * np.pi, 3)
        L = 1200.0 * k
        z += (12.0 / k) * np.sin(X / L + a) * np.cos(Y / (1.3 * L) + b) + (6.0 / k) * np.sin((X + Y) / (0.7 * L) + c)
    return z.astype(np.float32)


def synthetic_osm(grid: Grid, stations_xy: list[tuple[float, float]], seed: int = 7) -> OsmData:
    rng = np.random.default_rng(seed + 1)
    xmin, ymin, xmax, ymax = grid.bounds
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    span = max(xmax - xmin, ymax - ymin)
    osm = OsmData()
    centers: list[tuple[str, float, float, float]] = []
    for i, (sx, sy) in enumerate(stations_xy):
        centers.append((f"Město {i + 1}", sx, sy, 2500.0))
    for i in range(45):
        x = rng.uniform(xmin + 1000, xmax - 1000)
        y = rng.uniform(ymin + 1000, ymax - 1000)
        if any(np.hypot(x - c[1], y - c[2]) < c[3] + 1200 for c in centers):
            continue
        centers.append((f"Obec {i + 1}", x, y, rng.uniform(300, 900)))
    pts = []
    for name, x, y, r in centers:
        ang = np.linspace(0, 2 * np.pi, 24, endpoint=False)
        rr = r * (1 + 0.25 * rng.uniform(-1, 1, ang.size))
        osm.zastavba.append(Polygon(np.column_stack([x + rr * np.cos(ang), y + rr * np.sin(ang)])))
        osm.obce.append((name, "town" if r > 1000 else "village", Point(x, y)))
        n = int(r * r / 6000)
        a = rng.uniform(0, 2 * np.pi, n)
        d = r * np.sqrt(rng.uniform(0, 1, n))
        pts.append(np.column_stack([x + d * np.cos(a), y + d * np.sin(a)]))
    # samoty
    pts.append(np.column_stack([rng.uniform(xmin, xmax, 400), rng.uniform(ymin, ymax, 400)]))
    osm.budovy = np.vstack(pts)
    osm.budovy_kompletni = True
    # řeka v údolí
    ys = np.linspace(ymin, ymax, 200)
    rx = cx - 0.2 * span + 2500 * np.sin((ys - cy) / 4000.0)
    osm.reky.append(("Řeka", LineString(np.column_stack([rx, ys]))))
    # rybník
    px, py = cx + 0.25 * span, cy - 0.2 * span
    osm.voda_plochy.append(Point(px, py).buffer(1200))
    # silnice mezi sousedními obcemi
    big = [c for c in centers if c[3] > 600]
    for a, b in zip(big[:-1], big[1:]):
        osm.silnice.append(("primary", "I/xx", LineString([(a[1], a[2]), (b[1], b[2])])))
    osm.zeleznice.append(LineString([(xmin, cy + 0.3 * span), (xmax, cy + 0.25 * span)]))
    # chráněné území
    osm.chranena.append(("CHKO Demo", 3, Point(cx - 0.1 * span, cy + 0.2 * span).buffer(5000)))
    osm.chranena.append(("NPR Demo", 1, Point(cx + 0.15 * span, cy + 0.05 * span).buffer(1500)))
    return osm
