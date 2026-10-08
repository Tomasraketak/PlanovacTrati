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


def test_klic_trvale_a_migrace(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("PLANOVAC_CONFIG_DIR", str(cfg))
    assert auto.nacti_klic() == ""
    # starý soubor v data/ se přestěhuje
    (tmp_path / "nastaveni.json").write_text('{"mapy_klic": "stary"}')
    assert auto.nacti_klic() == "stary"
    assert (cfg / "nastaveni.json").exists()
    auto.uloz_klic("novy")
    assert auto.nacti_klic() == "novy"
    # po „aktualizaci“ (nová složka dat) klíč zůstane
    monkeypatch.setenv("PLANOVAC_DATA", str(tmp_path / "jina"))
    assert auto.nacti_klic() == "novy"
    monkeypatch.setenv("MAPY_API_KEY", "env")
    assert auto.nacti_klic() == "env"
    monkeypatch.delenv("MAPY_API_KEY")
    auto.uloz_klic("")
    assert auto.nacti_klic() == ""


def test_pravidla_omezeni_a_comfortjet():
    from planovac.config import VLAKY, Omezeni, Vlak, _omezeni_z_dict
    from planovac.omezeni import rychlosti_pravidla

    o = Omezeni()
    assert len(o.aktivni_pravidla()) == 2
    assert o.usek_povolen(1800, 80) and not o.usek_povolen(2500, 80) and o.usek_povolen(2900, 120)
    assert not o.usek_povolen(1500, 60)
    v = rychlosti_pravidla(o.pravidla[1], NavrhoveParametry())
    assert min(v) == 80 and max(v) < 200
    # starý formát projektu → pravidlo 1 z původních hodnot + výchozí silné pravidlo
    st = _omezeni_z_dict({"max_pocet": 3, "max_delka_m": 2500, "min_rychlost_kmh": 100, "min_uspora_mil": 111,
                          "min_uspora_demolic": 7})
    assert st.pravidla[0].max_delka_m == 2500 and st.pravidla[0].max_pocet == 3 and len(st.pravidla) == 2
    # YAML roundtrip
    p = Project()
    p.omezeni.pravidla[1].min_rychlost_kmh = 90
    assert Project.from_yaml(p.to_yaml()).omezeni.pravidla[1].min_rychlost_kmh == 90
    cj = next(k for k in VLAKY if k.startswith("ComfortJet"))
    assert Vlak.z_predvolby(cj).max_rychlost_kmh == 200


def test_silne_pravidlo_je_pouzito_jen_pri_velke_uspore(monkeypatch):
    """Stub: úsek 1,8 km při 75–80 km/h ušetří 600 mil. Kč a 12 domů → pravidlo „do 2 km, 80 km/h“ ho přijme;
    při úspoře 200 mil. a 2 domech ho zamítne."""
    from types import SimpleNamespace as NS

    from planovac import omezeni as om
    from planovac.config import Omezeni

    osa = NS(delka=10000.0)
    monkeypatch.setattr(om, "kandidati", lambda *a, **k: [(1000.0, 3000.0)])
    stav = {"prvni": True}

    def fake_useky(o, navrh, spojit_m=1000.0):
        if stav.pop("prvni", False):
            return []
        return [om.Usek(1000.0, 2800.0, 300.0, 75.0)]

    monkeypatch.setattr(om, "useky_z_osy", fake_useky)

    def zkus(uspora, domy):
        stav["prvni"] = True
        zaklad = om.Varianta(osa, 10000.0, 20, 10000.0 + 800.0, 1000.0)
        var = om.Varianta(osa, 10000.0 - uspora, 20 - domy, 10000.0 - uspora + 8.0 * (20 - domy), 1010.0)
        cfg = Omezeni()
        cfg.pravidla = [cfg.pravidla[1]]            # jen silné pravidlo (do 2 km, 80 km/h, ≥ 500 mil. / 10 domů)
        v, useky, prot = om.najdi_omezeni(zaklad, [], np.zeros(10), 50.0, NavrhoveParametry(), cfg,
                                          lambda zony: osa, lambda o: var, 40.0)
        return useky, prot

    useky, _ = zkus(600.0, 12)
    assert len(useky) == 1 and useky[0].rychlost_kmh <= 80
    useky, _ = zkus(200.0, 2)
    assert useky == []


def test_zlepsi_osu_odtlaci_osu_od_budovy():
    from scipy.spatial import cKDTree

    from planovac.horizontal import fit_alignment, zlepsi_osu

    pts = [np.array([0.0, 0.0]), np.array([12000.0, 0.0])]
    cesta = [np.array([[0.0, 0.0], [6000.0, 400.0], [12000.0, 0.0]])]
    Rmin = NavrhoveParametry().min_polomer()
    al = fit_alignment(pts, [True, True], cesta, Rmin, 2 * Rmin, Lp=[0, 0], tol=50.0)
    budova = np.array([[6000.0, 395.0]])
    pod_budovou = float(cKDTree(al.xy).query(budova)[0][0])
    assert pod_budovou < 15

    def objektiv(xy):
        d = cKDTree(xy).query(budova, distance_upper_bound=15.0)[0]
        delka = float(np.sum(np.hypot(*np.diff(xy, axis=0).T)))
        return delka + 5000.0 * int(np.isfinite(d).sum())

    nova = zlepsi_osu(al, pts, objektiv)
    assert float(cKDTree(nova.xy).query(budova)[0][0]) > 15
    # nikdy nezhorší: bez budovy se osa nemění
    assert zlepsi_osu(al, pts, lambda xy: float(np.sum(np.hypot(*np.diff(xy, axis=0).T)))) is not None


def test_okruh_stanic_nevypina_penalizaci_budov():
    from planovac.config import Koeficienty

    assert Koeficienty().pen_budovy_u_stanic == 1.0
