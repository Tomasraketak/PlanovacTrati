"""Velikost mapy výsledku (u 20 m dřív až 5,8 MB a bílá obrazovka)."""
from types import SimpleNamespace as NS

import numpy as np

from planovac import report
from planovac.geo import Grid


def test_naklad_overlay_je_maly():
    g = Grid.from_bounds(450000, 5400000, 550000, 5470000, 20.0)      # 5000 × 3500 buněk
    rng = np.random.default_rng(1)
    c = np.clip(np.cumsum(rng.normal(size=(g.nrows, g.ncols)).astype(np.float32), axis=1) % 100 + 1, 1, 100)
    uri, bounds = report._cost_overlay_png(NS(grid=g, cost=NS(cost=c)))
    assert uri.startswith("data:image/png;base64,") and len(uri) < 600_000
    assert len(bounds) == 2
