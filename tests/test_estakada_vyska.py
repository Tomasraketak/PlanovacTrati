"""Nastavitelná max. výška estakády / mostu a hranice cenové přirážky."""
import numpy as np

from planovac.config import Ceny, NavrhoveParametry
from planovac.vertical import option_costs


def test_max_vyska_estakady():
    h = np.array([10.0, 25.0, 40.0])
    n, c = NavrhoveParametry(), Ceny()
    assert np.isfinite(option_costs(h, n, c)[1]).all()                 # 0 = bez omezení
    n.vyska_estakady_max_m = 30.0
    est = option_costs(h, n, c)[1]
    assert np.isfinite(est[:2]).all() and np.isinf(est[2])
    most = option_costs(h, n, c, voda=True)[3]
    assert np.isinf(most[2])


def test_hranice_prirazky():
    h = np.array([30.0])
    n, c = NavrhoveParametry(), Ceny()
    a = option_costs(h, n, c)[1][0]
    c.estakada_vyska_zaklad_m = 40.0
    assert option_costs(h, n, c)[1][0] < a
