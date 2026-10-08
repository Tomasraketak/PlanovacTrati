"""v1.6: ruční limity rychlosti úseků a porovnání s autem."""
import numpy as np
import pytest

from planovac import auto, report, traction
from planovac.config import Bod, NavrhoveParametry, Project, Vlak
from planovac.horizontal import fit_alignment


def test_limit_useku_yaml_a_validace():
    p = Project(body=[Bod("A", 49.0, 14.5, max_rychlost_kmh=120), Bod("B", 49.1, 14.6), Bod("C", 49.2, 14.7)])
    p2 = Project.from_yaml(p.to_yaml())
    assert p2.body[0].max_rychlost_kmh == 120 and p2.body[1].max_rychlost_kmh is None
    assert not p2.validate()
    p2.body[0].max_rychlost_kmh = 300
    assert any("Limit rychlosti" in e for e in p2.validate())
    # starší YAML bez pole
    assert Project.from_dict({"body": [{"nazev": "A", "lat": 49, "lon": 14}]}).body[0].max_rychlost_kmh is None


def test_min_polomer_pro_rychlost():
    n = NavrhoveParametry()
    assert n.min_polomer_pro(200) == n.min_polomer()
    assert n.min_polomer_pro(120) < 0.5 * n.min_polomer()
    assert n.min_polomer_pro(300) == n.min_polomer()


def test_limit_snizi_rychlost_jen_v_useku():
    n = NavrhoveParametry()
    s = np.arange(0, 20000, 10.0)
    k = np.zeros(len(s))
    z = np.zeros(len(s))
    from planovac.config import VLAKY
    v = Vlak.z_predvolby(next(k for k in VLAKY if "ICE" in k))
    base = traction.compute(s, z, k, [0, 10000, 20000], ["A", "B", "C"], [True, True, True], n, v)
    lim = traction.compute(s, z, k, [0, 10000, 20000], ["A", "B", "C"], [True, True, True], n, v, None,
                           [(0.0, 10000.0, 120.0)])
    assert lim.celkem_s > base.celkem_s
    assert lim.v_kmh[(s > 2000) & (s < 8000)].max() <= 120.5
    assert lim.v_kmh[(s > 12000) & (s < 18000)].max() > 150
    assert traction.limity_useku([Bod("A", 0, 0, max_rychlost_kmh=120), Bod("B", 0, 0)], [0, 5000]) == [(0.0, 5000.0, 120.0)]


def test_mensi_oblouk_jen_v_pomalem_useku():
    pts = [np.array([0.0, 0.0]), np.array([4000.0, 0.0]), np.array([8000.0, 3000.0])]
    kor = [np.array([[0.0, 0.0], [4000.0, 0.0]]), np.array([[4000.0, 0.0], [5000.0, 0.0], [5500.0, 800.0], [8000.0, 3000.0]])]
    Rmin = NavrhoveParametry().min_polomer()
    a = fit_alignment(pts, [True, False, True], kor, Rmin, 2 * Rmin, Lp=[0, 0, 0], tol=50.0)
    b = fit_alignment(pts, [True, False, True], kor, Rmin, 2 * Rmin, Lp=[0, 0, 0], tol=50.0,
                      rmin_useky=[Rmin, 600.0])
    assert min(p.R for p in b.prvky if p.typ == "oblouk") <= min(p.R for p in a.prvky if p.typ == "oblouk")


class _Resp:
    def __init__(self, data, code=200):
        self._d, self.status_code = data, code

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANOVAC_DATA", str(tmp_path))
    monkeypatch.delenv("MAPY_API_KEY", raising=False)


STANICE = [("A", 49.0, 14.5), ("B", 49.1, 14.7), ("C", 49.2, 14.9)]


def test_auto_mapy_a_cache(monkeypatch):
    volani = []

    def fake_get(url, **kw):
        volani.append(url)
        assert kw["headers"]["X-Mapy-Api-Key"] == "klic"
        return _Resp({"properties": {"length": 30000, "duration": 1800}})

    monkeypatch.setattr(auto.requests, "get", fake_get)
    rows, varov = auto.jizda_autem(STANICE, "auto", klic="klic")
    assert len(rows) == 2 and rows[0].cas_s == 1800 and rows[0].delka_km == 30 and rows[0].zdroj == "Mapy.cz"
    auto.jizda_autem(STANICE, "auto", klic="klic")
    assert len(volani) == 2              # podruhé z cache


def test_auto_osrm_bez_klice_a_zaloha(monkeypatch):
    def fake_get(url, **kw):
        if "mapy.cz" in url:
            return _Resp({}, 401)
        return _Resp({"routes": [{"distance": 25000, "duration": 1500}]})

    monkeypatch.setattr(auto.requests, "get", fake_get)
    rows, varov = auto.jizda_autem(STANICE, "auto", klic="")
    assert rows[0].zdroj == "OSRM" and varov
    rows, varov = auto.jizda_autem(STANICE, "mapy", klic="spatny")
    assert rows and rows[0].zdroj == "OSRM" and any("Mapy.cz" in w for w in varov)


def test_auto_chyba_nevyhodi(monkeypatch):
    def boom(url, **kw):
        raise RuntimeError("síť")

    monkeypatch.setattr(auto.requests, "get", boom)
    rows, varov = auto.jizda_autem(STANICE, "osrm", klic="")
    assert rows == [] and len(varov) == 2


def test_tab_auto_rozdily():
    from types import SimpleNamespace as NS

    j = NS(radky=[NS(z="A", do="B", delka_km=30.0, jizdni_doba_s=900.0), NS(z="B", do="C", delka_km=30.0, jizdni_doba_s=900.0)],
           celkem_s=1800.0)
    rows = [auto.JizdaAutem("A", "B", 35, 2400, "OSRM"), auto.JizdaAutem("B", "C", 35, 2400, "OSRM")]
    t = report.tab_auto(NS(), rows, j)
    assert list(t["Z"]) == ["A", "B", "CELKEM"]
    assert t.iloc[0]["Rozdíl [min]"] == 25.0 and t.iloc[2]["Rozdíl [min]"] == 50.0
    assert report.cas_min("1:20:30") == pytest.approx(80.5)
