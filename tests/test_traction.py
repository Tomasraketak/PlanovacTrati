import numpy as np

from planovac.config import NavrhoveParametry, Vlak
from planovac.traction import compute, fmt_cas


def test_flat_straight_run_time_reasonable():
    s = np.arange(0, 50000.0 + 10, 10.0)
    z = np.zeros(len(s))
    k = np.zeros(len(s))
    nav = NavrhoveParametry(rychlost_kmh=200)
    v = Vlak(rezerva_pct=0)
    j = compute(s, z, k, [0.0, s[-1]], ["A", "B"], [True, True], nav, v)
    pure = 50.0 / 200.0 * 3600
    assert pure < j.celkem_s < pure + 240        # rozjezd a brzdění přidají max. pár minut
    assert j.v_kmh.max() <= 200.0 + 1e-6
    assert j.v_kmh[0] == 0 and j.v_kmh[-1] == 0


def test_curve_reduces_speed():
    s = np.arange(0, 30000.0, 10.0)
    k = np.zeros(len(s))
    k[(s > 14000) & (s < 16000)] = 1 / 1000.0
    nav = NavrhoveParametry(rychlost_kmh=250)
    j = compute(s, np.zeros(len(s)), k, [0.0, s[-1]], ["A", "B"], [True, True], nav, Vlak())
    assert j.v_kmh[(s > 14500) & (s < 15500)].max() <= np.sqrt(1000 * 250 / 11.8) + 1


def test_fmt():
    assert fmt_cas(3725) == "1:02:05"
    assert fmt_cas(125) == "2:05"
