import numpy as np

from planovac.config import Ceny, NavrhoveParametry
from planovac.structures import TUNEL, ESTAKADA, classify
from planovac.vertical import design_profile


def test_profile_respects_grade_and_station_flat():
    s = np.arange(0, 40000, 10.0)
    z = 450 + 60 * np.sin(s / 3000) + 25 * np.sin(s / 700)
    nav = NavrhoveParametry(max_sklon_promile=20)
    zr = design_profile(s, z, np.zeros(len(s), bool), np.zeros(len(s)), [0.0, 20000.0, s[-1]], nav, Ceny())
    g = np.abs(np.diff(zr) / np.diff(s))
    assert g.max() <= 0.020 + 1e-6
    m = np.abs(s - 20000) <= 190
    assert np.ptp(zr[m]) < 0.5


def test_mountain_needs_tunnel_and_valley_needs_viaduct():
    s = np.arange(0, 20000, 10.0)
    z = np.full(len(s), 400.0)
    z += 250 * np.exp(-((s - 6000) / 1200) ** 2)   # hora
    z -= 60 * np.exp(-((s - 14000) / 400) ** 2)    # hluboké údolí
    nav = NavrhoveParametry(max_sklon_promile=15)
    c = Ceny()
    zr = design_profile(s, z, np.zeros(len(s), bool), np.zeros(len(s)), [0.0, s[-1]], nav, c)
    t = classify(zr - z, s, np.zeros(len(s), bool), np.zeros(len(s)), nav, c)
    assert (t[np.abs(s - 6000) < 300] == TUNEL).any()
    assert (t[np.abs(s - 14000) < 100] == ESTAKADA).any()
