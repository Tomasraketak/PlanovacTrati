import numpy as np
from shapely.geometry import LineString

from planovac.config import Linka, NavrhoveParametry, Project, Soubeh, Vlak
from planovac.costs import cena_metru, sleva_soubeh
from planovac.osm import OsmData
from planovac.soubeh import faktor_osy, prichytit_ke_koleji, useky
from planovac.structures import NASYP
from planovac.traction import compute


def _osm():
    o = OsmData()
    o.zeleznice = [LineString([(0, 0), (10000, 0)])]
    o.silnice = [("motorway", "D3", LineString([(0, 1000), (10000, 1000)])),
                 ("secondary", "II/1", LineString([(0, 2000), (10000, 2000)]))]
    return o


def test_faktor_osy():
    cfg = Soubeh()
    xy = np.array([[100, 3.0], [100, 5.0], [100, 1000 + 6 + 8], [100, 1000 + 6 + 12], [100, 2005]])
    f, zel, sil = faktor_osy(xy, _osm(), cfg)
    assert list(zel) == [True, False, False, False, False]
    assert list(sil) == [False, False, True, False, False]      # silnice II. třídy se nepočítá
    assert np.allclose(f, [0.5, 1, 0.75, 1, 1])


def test_prichyceni_a_sleva():
    xy = np.array([[0, 30.0], [3000, 40.0], [6000, -20.0], [10000, 500.0]])
    out = prichytit_ke_koleji(xy, _osm(), 75.0)
    assert np.allclose(out[1:3, 1], 0.0) and out[0, 1] == 30.0
    s = np.arange(0, 1000.0 + 10, 10.0)
    h = np.full(len(s), 2.0)
    typy = np.full(len(s), NASYP)
    f = np.where(s < 500, 0.5, 1.0)
    nav = NavrhoveParametry()
    from planovac.config import Ceny

    c = Ceny()
    exp = float(np.sum(0.5 * cena_metru(h, typy, nav, c)[s < 500] * np.gradient(s)[s < 500]) / 1e6)
    assert abs(sleva_soubeh(s, h, typy, f, nav, c) - exp) < 1e-9
    u = useky(s, s < 500, np.zeros(len(s), bool))
    assert len(u) == 1 and u[0].druh == "stávající trať"


def test_linky_poradi_jizdnich_dob():
    s = np.arange(0, 90000.0 + 10, 10.0)
    z, k = np.zeros(len(s)), np.zeros(len(s))
    body_s, nazvy = [0, 30000, 60000, s[-1]], ["A", "B", "C", "D"]
    nav, v = NavrhoveParametry(rychlost_kmh=200), Vlak()
    zast = compute(s, z, k, body_s, nazvy, [True] * 4, nav, v, Linka("Z", [], True))
    rych = compute(s, z, k, body_s, nazvy, [True] * 4, nav, v, Linka("R", ["B"]))
    expr = compute(s, z, k, body_s, nazvy, [True] * 4, nav, v, Linka("E", []))
    assert expr.celkem_s < rych.celkem_s < zast.celkem_s
    assert rych.jizdni_rad[2][3] is False and rych.jizdni_rad[1][3] is True   # C projíždí, B zastavuje
    assert len(rych.radky) == 2


def test_yaml_linky_kompatibilita():
    p = Project.from_dict({"body": []})
    assert len(p.linky) == 3 and p.linky[0].vsechny
    q = Project.from_yaml(Project().to_yaml())
    assert q.soubeh.zeleznice_sleva_pct == 50 and q.soubeh.silnice_sleva_pct == 25
