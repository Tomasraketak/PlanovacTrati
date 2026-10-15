"""Plošné vrstvy OSM se stahují po pevných dlaždicích – jednou stažené území se už nestahuje znovu."""
from planovac import osm


def test_dlazdice_pevna_mrizka():
    assert osm.dlazdice((15.52, 49.21, 15.78, 49.38)) == [(15.5, 49.0, 16.0, 49.5)]
    t = osm.dlazdice((15.32, 49.22, 15.70, 49.56))
    assert (15.0, 49.0, 15.5, 49.5) in t and (15.5, 49.5, 16.0, 50.0) in t and len(t) == 4


def test_posunuta_oblast_stahuje_jen_nove_dlazdice(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANOVAC_DATA", str(tmp_path))
    dotazy = []

    def fake_overpass(query, fmt="json", progress=None, label=""):
        dotazy.append(query)
        # jedna řeka přes hranici dlaždic (vrátí ji obě dlaždice) + jedna mimo požadovanou oblast
        return {"elements": [
            {"type": "way", "id": 1, "tags": {"waterway": "river", "name": "Jihlava"},
             "bounds": {"minlat": 49.3, "minlon": 15.4, "maxlat": 49.31, "maxlon": 15.6},
             "geometry": [{"lat": 49.3, "lon": 15.4}, {"lat": 49.31, "lon": 15.6}]},
            {"type": "way", "id": 2, "tags": {"waterway": "river", "name": "daleko"},
             "bounds": {"minlat": 49.9, "minlon": 15.9, "maxlat": 49.95, "maxlon": 15.95},
             "geometry": [{"lat": 49.9, "lon": 15.9}, {"lat": 49.95, "lon": 15.95}]},
        ]}

    monkeypatch.setattr(osm, "overpass", fake_overpass)
    d = osm.overpass_dlazdice(lambda b: f"dotaz{b}", (15.32, 49.22, 15.70, 49.36))
    assert [e["id"] for e in d["elements"]] == [1]          # bez duplicit a bez prvků mimo oblast
    assert len(dotazy) == 2
    # dotazy jsou pro pevné dlaždice: posunutá oblast ve stejných dlaždicích dá stejné dotazy (→ cache)
    dotazy2 = []
    monkeypatch.setattr(osm, "overpass", lambda q, **k: dotazy2.append(q) or {"elements": []})
    osm.overpass_dlazdice(lambda b: f"dotaz{b}", (15.40, 49.25, 15.60, 49.30))
    assert set(dotazy2) <= set(dotazy)
