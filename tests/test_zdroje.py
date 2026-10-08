"""Záložní zdroj dat: při výpadku Overpassu se použije Overture Maps."""
import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon

from planovac import osm, zdroje


@pytest.fixture(autouse=True)
def _rezim():
    yield
    osm.nastav_zdroj("auto")


def _selze(*a, **k):
    raise osm.OverpassError("test: nedostupné")


def _falesne_geometrie(theme, typ, bbox, sloupce, progress=None):
    if typ == "land_use":
        return [({"class": "residential", "subtype": "developed"}, Polygon([(14.7, 49.0), (14.71, 49.0), (14.71, 49.01), (14.7, 49.01)]))]
    if typ == "division":
        return [({"class": "town", "subtype": "locality", "names": {"primary": "Třeboň"}}, Point(14.77, 49.0))]
    if typ == "water":
        return [({"names": None}, LineString([(14.7, 49.0), (14.8, 49.0)]))]
    if typ == "segment":
        return [({"subtype": "rail", "class": "standard_gauge", "names": None}, LineString([(14.7, 49.0), (14.8, 49.0)])),
                ({"subtype": "road", "class": "primary", "names": {"primary": "I/34"}}, LineString([(14.7, 49.0), (14.8, 49.01)])),
                ({"subtype": "road", "class": "residential", "names": None}, LineString([(14.7, 49.0), (14.8, 49.01)]))]
    return []


def _budovy(bbox, progress=None):
    p = np.array([[14.75, 49.0], [14.76, 49.0]])
    w, s, e, n = bbox
    return p[(p[:, 0] >= w) & (p[:, 0] < e) & (p[:, 1] >= s) & (p[:, 1] < n)]


def test_fallback_vsechny_vrstvy(monkeypatch):
    monkeypatch.setattr(osm, "overpass", _selze)
    monkeypatch.setattr(zdroje, "geometrie", _falesne_geometrie)
    monkeypatch.setattr(zdroje, "budovy_stredy", _budovy)
    o = osm.fetch_area((14.6, 48.9, 14.9, 49.1), budovy=True, chranena=False)
    assert len(o.zastavba) == 1 and len(o.reky) == 1 and len(o.zeleznice) == 1
    assert [s[0] for s in o.silnice] == ["primary"] and o.obce[0][0] == "Třeboň"
    assert len(o.budovy) == 2 and o.zdroje["doprava"] == "Overture Maps"
    assert any("Overture" in v for v in o.varovani)


def test_rezim_jen_overpass_nepouzije_zalozni(monkeypatch):
    osm.nastav_zdroj("overpass")
    monkeypatch.setattr(osm, "overpass", _selze)
    monkeypatch.setattr(zdroje, "geometrie", lambda *a, **k: pytest.fail("záložní zdroj nesmí být volán"))
    o = osm.fetch_area((14.6, 48.9, 14.9, 49.1), budovy=False, chranena=False)
    assert not o.zastavba and o.varovani


def test_chybny_zdroj_je_varovani(monkeypatch):
    monkeypatch.setattr(osm, "overpass", _selze)

    def spatny(*a, **k):
        raise zdroje.ZdrojError("S3 nedostupné")
    monkeypatch.setattr(zdroje, "geometrie", spatny)
    o = osm.fetch_area((14.6, 48.9, 14.9, 49.1), budovy=False, chranena=False)
    assert o.varovani
