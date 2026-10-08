import numpy as np

from planovac.config import (TYP_ZASTAVKA, Bod, Ceny, Koeficienty, Linka, NavrhoveParametry, Project, Vlak)
from planovac.corridor import find_segment
from planovac.costsurface import siroka_mesta, tunel_ekvivalent
from planovac.geo import Grid
from planovac.paralelne import map_procesy, procesy
from planovac.traction import compute
from planovac.vertical import design_profile, option_costs


def test_zastavka_zastavuje_jen_zastavkovy_vlak():
    s = np.arange(0, 60000.0 + 10, 10.0)
    z, k = np.zeros(len(s)), np.zeros(len(s))
    body_s, nazvy = [0, 20000, 40000, s[-1]], ["A", "Zast", "B", "C"]
    nav, v = NavrhoveParametry(rychlost_kmh=200), Vlak()
    vse = compute(s, z, k, body_s, nazvy, [True] * 4, nav, v, Linka("Z", [], True))
    rych = compute(s, z, k, body_s, nazvy, [True] * 4, nav, v, Linka("R", ["B"]))
    assert [x[3] for x in vse.jizdni_rad] == [True, True, True, True]
    assert [x[3] for x in rych.jizdni_rad] == [True, False, True, True]
    assert vse.celkem_s > rych.celkem_s
    assert Bod("x", 1, 2, TYP_ZASTAVKA).je_stanice and Bod("x", 1, 2, TYP_ZASTAVKA).je_zastavka


def test_stanice_max_15m_pod_terenem():
    s = np.arange(0, 20000.0, 10.0)
    z = 400 + 80 * np.exp(-((s - 10000) / 800) ** 2)      # kopec přesně nad stanicí
    nav = NavrhoveParametry(max_sklon_promile=12.5, max_hloubka_stanice_m=15.0)
    zr = design_profile(s, z, np.zeros(len(s), bool), np.zeros(len(s)), [0.0, 10000.0, s[-1]], nav, Ceny(),
                        stanice_info=[(400.0, 1.0)] * 3)
    m = np.abs(s - 10000) <= 200
    assert (z[m] - zr[m]).max() <= 15.0 + 0.5
    # nástupiště vodorovně
    assert np.ptp(zr[m]) < 0.9      # sklon ve stanici ≤ 2 ‰ na 400 m


def test_podzemni_stanice_je_draha_a_tunel_pod_mestem_je_povolen():
    nav, c = NavrhoveParametry(), Ceny()
    h = np.array([-10.0])
    bez = option_costs(h, nav, c)
    st = option_costs(h, nav, c, st=1.0)
    assert np.isfinite(st[0]) and st[0] > bez[0]                       # příplatek za hloubku
    assert not np.isfinite(option_costs(np.array([-16.0]), nav, c, st=1.0)).any()   # hlouběji než 15 m nelze
    h12 = np.array([-13.0])
    assert not np.isfinite(option_costs(h12, nav, c)[2])               # ražený tunel jen od 15 m
    assert np.isfinite(option_costs(h12, nav, c, zast=True)[2])        # pod zástavbou už od 12 m
    assert option_costs(np.array([0.0]), nav, c, zast=True)[0] > option_costs(np.array([0.0]), nav, c)[0] + 1e6


def test_siroka_mesta_a_ekvivalent():
    zast = np.zeros((200, 200), bool)
    zast[20:180, 20:180] = True          # město 8 km při 50 m
    zast[100:104, 0:20] = True           # úzká „vesnice podél silnice“
    m = siroka_mesta(zast, 50.0, 800.0)
    assert m[100, 100] and not m[101, 5]
    assert 4.0 < tunel_ekvivalent(Ceny(), Koeficienty()) < 8.0
    k = Koeficienty(tunel_ekvivalent=3.0)
    assert tunel_ekvivalent(Ceny(), k) == 3.0


def test_paralelni_koridor_stejny_jako_seriovy():
    g = Grid.from_bounds(0, 0, 20000, 10000, 50)
    cost = np.ones(g.shape, dtype=np.float32)
    X, Y = g.cell_centers()
    cost[np.hypot(X - 10000, Y - 5000) < 2500] = 60.0
    a, b = (1000.0, 5000.0), (19000.0, 5000.0)
    ser = find_segment(cost, g, a, b, 8.0)
    with procesy(2) as pool:
        par = find_segment(cost, g, a, b, 8.0, map_fn=map_procesy(pool))
    assert ser.limit_splnen and par.limit_splnen
    assert ser.delka <= 1.08 * 18000 + 1
    assert np.allclose(ser.xy, par.xy) and abs(ser.lam - par.lam) < 1e-9


def test_koeficienty_yaml_a_nove_vychozi():
    p = Project()
    p.koef.pen_budovy = 7.5
    p.vahy.hodnota_casu_mil_min = 123
    q = Project.from_yaml(p.to_yaml())
    assert q.koef.pen_budovy == 7.5 and q.vahy.hodnota_casu_mil_min == 123
    assert Project().vahy.hodnota_casu_mil_min == 500 and Project().vypocet.rozliseni_m == 20.0
    assert Project().vypocet.max_bunek_mil >= 60
