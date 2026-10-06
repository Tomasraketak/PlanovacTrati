import numpy as np

from planovac.corridor import find_segment
from planovac.geo import Grid


def test_avoids_obstacle_and_respects_detour_limit():
    g = Grid.from_bounds(0, 0, 20000, 10000, 50)
    cost = np.ones(g.shape)
    X, Y = g.cell_centers()
    cost[np.hypot(X - 10000, Y - 5000) < 1500] = 50.0     # „město“ uprostřed
    a, b = (1000.0, 5000.0), (19000.0, 5000.0)
    sp = find_segment(cost, g, a, b, 20.0)
    assert sp.limit_splnen
    assert sp.delka <= 1.2 * 18000 + 1
    d = np.min(np.hypot(sp.xy[:, 0] - 10000, sp.xy[:, 1] - 5000))
    assert d > 1200          # obešla město
    # přísný limit -> rovně přes město
    sp2 = find_segment(cost, g, a, b, 1.0)
    assert sp2.delka <= 1.01 * 18000 + 1
