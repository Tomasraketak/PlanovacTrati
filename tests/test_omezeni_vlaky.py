from pathlib import Path

import numpy as np

from planovac.config import VLAKY, NavrhoveParametry, Project, Vlak
from planovac.horizontal import fit_alignment
from planovac.omezeni import polomer_pro_rychlost, useky_z_osy
from planovac.pipeline import run_project
from planovac.traction import compute, porovnani_vlaku

ROOT = Path(__file__).resolve().parent.parent


def _trat(L=60000.0):
    s = np.arange(0, L + 10, 10.0)
    return s, np.zeros(len(s)), np.zeros(len(s))


def test_predvolby_vlaku():
    s, z, k = _trat()
    nav = NavrhoveParametry(rychlost_kmh=300)
    por = {c.vlak: c for c in porovnani_vlaku(s, z, k, [0, 30000, s[-1]], ["A", "B", "C"], [True] * 3, nav,
                                              Vlak())}
    assert set(por) == set(VLAKY)
    rp = por["RegioPanter (ČD 640, 3 vozy)"]
    assert rp.jizda.v_kmh.max() <= 160 + 1e-6
    assert por["ICE 3 (8 vozů)"].celkem_s < rp.celkem_s
    # pobyt 90 s ve stanici B je v jízdním řádu
    j = rp.jizda
    assert abs((j.jizdni_rad[1][2] - j.jizdni_rad[1][1]) - 90.0) < 1e-6


def test_naklapeci_vlak_rychleji_v_oblouku():
    s, z, k = _trat(30000.0)
    k[(s > 12000) & (s < 18000)] = 1 / 1200.0
    nav = NavrhoveParametry(rychlost_kmh=230)
    pen = compute(s, z, k, [0, s[-1]], ["A", "B"], [True, True], nav, Vlak.z_predvolby("Pendolino (ČD 680, naklápěcí)"))
    rj = compute(s, z, k, [0, s[-1]], ["A", "B"], [True, True], nav, Vlak.z_predvolby("Railjet (Taurus + 7 vozů)"))
    m = (s > 14000) & (s < 16000)
    assert pen.vlim_kmh[m].max() > rj.vlim_kmh[m].max() + 10


def test_stary_yaml_pobyt_v_minutach():
    p = Project.from_dict({"body": [], "vlak": {"pobyt_stanice_min": 2.0}})
    assert p.vlak.pobyt_stanice_s == 120.0
    assert Project().vlak.pobyt_stanice_s == 90.0


def test_zona_povoli_mensi_oblouky_jen_uvnitr():
    a, b = (0.0, 0.0), (40000.0, 0.0)
    # koridor s ostrým uhnutím (obchvat) uprostřed
    path = np.array([a, (18000, 0), (19000, 900), (21000, 900), (22000, 0), b])
    nav = NavrhoveParametry(rychlost_kmh=200)
    Rmin = nav.min_polomer()
    zakl = fit_alignment([a, b], [True, True], [path], Rmin, nav.doporuceny_polomer())
    assert all(p.R >= Rmin - 1 for p in zakl.prvky if p.typ == "oblouk")
    Rz = polomer_pro_rychlost(120, nav)
    z = fit_alignment([a, b], [True, True], [path], Rmin, nav.doporuceny_polomer(),
                      zony=[(17000, 23000, Rz)], ref_xy=zakl.xy)
    useky = useky_z_osy(z, nav)
    assert useky, "v zóně mají vzniknout menší oblouky"
    for u in useky:
        assert 16000 <= u.s0 and u.s1 <= 24500
        assert u.min_polomer_m >= Rz - 1
        assert u.rychlost_kmh >= 120
    # osa v zóně lépe sleduje obchvat
    assert np.max(z.xy[:, 1]) > np.max(zakl.xy[:, 1])


def test_demo_s_omezenimi():
    p = Project.load(ROOT / "projekty" / "demo.yaml")
    p.vypocet.rozliseni_m = 100
    p.omezeni.min_uspora_mil = 0.0      # přijmout jakoukoli úsporu
    p.omezeni.min_uspora_demolic = 1
    r = run_project(p)
    assert len(r.omezeni) <= p.omezeni.max_pocet
    assert all(u.delka <= p.omezeni.max_delka_m + 1 for u in r.omezeni)
    J = lambda cena, dem: cena + p.vahy.penalizace_demolice_mil * p.vahy.budovy * dem  # noqa: E731
    assert J(r.rozpocet.celkem_mil, len(r.analyza.demolice_idx)) <= J(r.zaklad_cena_mil, r.zaklad_demolice) + 1e-6
    assert len(r.porovnani_vlaku) == len(VLAKY)
