"""Stahování a zpracování dat OpenStreetMap přes Overpass API.

Vrstvy:
* zástavba (landuse residential/industrial/commercial/retail),
* obce (place=city/town/village/hamlet),
* vodní plochy a řeky,
* silnice I./II. třídy, dálnice a železnice (křížení),
* chráněná území,
* budovy (středy, pro počty demolic).

Každá odpověď se ukládá do ``data/cache/osm`` (klíč = hash dotazu), takže
opakovaný výpočet nepotřebuje internet. Overpass bývá přetížený, proto se
zkouší několik serverů s opakováním a při selhání se vrstva vynechá s varováním.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import requests
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union

from .dem import USER_AGENT
from .geo import to_lonlat, to_xy
from . import zdroje
from .paths import cache_dir

log = logging.getLogger(__name__)

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

Progress = Callable[[str], None]

# Zdroj dat: "auto" = Overpass a při selhání Overture Maps, "overpass" = jen Overpass, "overture" = jen Overture.
ZDROJE_REZIM = "auto"


def nastav_zdroj(rezim: str) -> None:
    global ZDROJE_REZIM
    ZDROJE_REZIM = rezim if rezim in ("auto", "overpass", "overture") else "auto"


class OverpassError(RuntimeError):
    pass


@dataclass
class OsmData:
    """Vektorová data v metrických souřadnicích (UTM 33N)."""

    zastavba: list[Polygon] = field(default_factory=list)
    obce: list[tuple[str, str, Point]] = field(default_factory=list)   # (název, typ, bod)
    voda_plochy: list[Polygon] = field(default_factory=list)
    reky: list[tuple[str, LineString]] = field(default_factory=list)
    silnice: list[tuple[str, str, LineString]] = field(default_factory=list)  # (třída, název, linie)
    zeleznice: list[LineString] = field(default_factory=list)
    chranena: list[tuple[str, int, Polygon]] = field(default_factory=list)   # (název, stupeň 1–3, polygon)
    budovy: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))
    budovy_kompletni: bool = False          # True = budovy staženy pro celou oblast
    zdroje: dict[str, str] = field(default_factory=dict)   # vrstva → odkud data pocházejí
    varovani: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- HTTP

_NEDOSTUPNY_DO = 0.0          # po úplném selhání všech serverů se Overpass na chvíli přeskakuje (jistič)
JISTIC_S = 600.0


def overpass(query: str, fmt: str = "json", progress: Progress | None = None, label: str = ""):
    """Provede dotaz (s cache). ``fmt`` = 'json' nebo 'csv'."""
    global _NEDOSTUPNY_DO
    key = hashlib.sha1(query.encode("utf-8")).hexdigest()[:20]
    cfile = cache_dir("osm") / f"{key}.{fmt}"
    if cfile.exists():
        txt = cfile.read_text(encoding="utf-8")
        return json.loads(txt) if fmt == "json" else txt

    if ZDROJE_REZIM == "auto" and time.time() < _NEDOSTUPNY_DO:
        raise OverpassError(f"Overpass API nedostupné ({label}): přeskočeno po předchozím selhání")
    last_err = ""
    for rnd in range(2):
        for ep in OVERPASS_ENDPOINTS:
            if progress:
                host = ep.split("/")[2]
                progress(f"OSM: stahuji {label} ({host}{', pokus ' + str(rnd + 1) if rnd else ''}) …")
            try:
                r = requests.post(ep, data={"data": query}, timeout=(15, 150), headers={"User-Agent": USER_AGENT})
            except requests.RequestException as e:
                last_err = str(e)
                continue
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                continue
            txt = r.text
            if fmt == "json":
                try:
                    data = json.loads(txt)
                except json.JSONDecodeError:
                    last_err = "neplatná odpověď"
                    continue
                remark = str(data.get("remark", ""))
                if "error" in remark.lower() or "timed out" in remark.lower():
                    last_err = remark[:200]
                    continue
                cfile.write_text(txt, encoding="utf-8")
                return data
            if txt.lstrip().startswith("<"):
                last_err = "chybová odpověď serveru"
                continue
            cfile.write_text(txt, encoding="utf-8")
            return txt
        time.sleep(5 + 10 * rnd)
    if ZDROJE_REZIM == "auto":
        _NEDOSTUPNY_DO = time.time() + JISTIC_S
    raise OverpassError(f"Overpass API nedostupné ({label}): {last_err}")


def _bbox_str(bbox) -> str:
    west, south, east, north = bbox
    return f"({south:.5f},{west:.5f},{north:.5f},{east:.5f})"


# ---------------------------------------------------------------- geometrie

def _line_xy(geom: list[dict]) -> np.ndarray:
    lon = np.array([g["lon"] for g in geom])
    lat = np.array([g["lat"] for g in geom])
    x, y = to_xy(lon, lat)
    return np.column_stack([x, y])


def _way_polygon(el) -> Polygon | None:
    g = el.get("geometry")
    if not g or len(g) < 4:
        return None
    xy = _line_xy(g)
    try:
        p = Polygon(xy)
        if not p.is_valid:
            p = p.buffer(0)
        return p if not p.is_empty else None
    except Exception:
        return None


def _relation_polygons(el) -> list[Polygon]:
    outer, inner = [], []
    for m in el.get("members", []):
        if m.get("type") != "way" or not m.get("geometry"):
            continue
        g = [p for p in m["geometry"] if p]
        if len(g) < 2:
            continue
        ls = LineString(_line_xy(g))
        (inner if m.get("role") == "inner" else outer).append(ls)
    if not outer:
        return []
    polys = list(polygonize(linemerge(outer)))
    if not polys:
        return []
    shape = unary_union(polys)
    if inner:
        holes = list(polygonize(linemerge(inner)))
        if holes:
            shape = shape.difference(unary_union(holes))
    if shape.is_empty:
        return []
    return list(getattr(shape, "geoms", [shape]))


def _polygons(data) -> list[tuple[dict, Polygon]]:
    out = []
    for el in data.get("elements", []):
        if el["type"] == "way":
            p = _way_polygon(el)
            if p is not None:
                out.append((el.get("tags", {}), p))
        elif el["type"] == "relation":
            for p in _relation_polygons(el):
                out.append((el.get("tags", {}), p))
    return out


def _lines(data) -> list[tuple[dict, LineString]]:
    out = []
    for el in data.get("elements", []):
        if el["type"] == "way" and el.get("geometry") and len(el["geometry"]) >= 2:
            out.append((el.get("tags", {}), LineString(_line_xy(el["geometry"]))))
    return out


def _protect_level(tags: dict) -> int:
    """1 = nejpřísnější (NP, NPR), 2 = rezervace / Natura, 3 = CHKO a ostatní."""
    pc = str(tags.get("protect_class", ""))
    btype = tags.get("boundary", "")
    if btype == "national_park" or pc in ("1", "1a", "1b", "2"):
        return 1
    if tags.get("leisure") == "nature_reserve" or pc in ("4", "97"):
        return 2
    return 3


def _csv_points(txt: str) -> np.ndarray:
    try:
        arr = np.loadtxt(io.StringIO(txt), delimiter="\t", ndmin=2)
    except ValueError:
        rows = []
        for line in txt.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] and parts[1]:
                try:
                    rows.append((float(parts[0]), float(parts[1])))
                except ValueError:
                    pass
        arr = np.array(rows).reshape(-1, 2)
    if arr.size == 0:
        return np.zeros((0, 2))
    x, y = to_xy(arr[:, 1], arr[:, 0])
    return np.column_stack([x, y])



# ------------------------------------------------------------- záložní zdroj (Overture Maps)

def _xy_geom(g):
    import shapely
    return shapely.transform(g, lambda c: np.column_stack(to_xy(c[:, 0], c[:, 1])))


def _nazev(r: dict) -> str:
    n = r.get("names") or {}
    return (n.get("primary") if isinstance(n, dict) else "") or ""


def _polys(g):
    return [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon" and not p.is_empty]


def _ov_zastavba(osm: OsmData, bbox, progress):
    cil = {"residential", "industrial", "commercial", "retail", "garages", "farmyard", "developed"}
    for r, g in zdroje.geometrie("base", "land_use", bbox, ["class", "subtype"], progress):
        if (r.get("class") in cil) or (r.get("subtype") == "developed" and r.get("class") in (None, "")):
            osm.zastavba += [p for p in map(_xy_geom, _polys(g))]


def _ov_obce(osm: OsmData, bbox, progress):
    for r, g in zdroje.geometrie("divisions", "division", bbox, ["class", "subtype", "names"], progress):
        if g.geom_type == "Point" and r.get("class") in ("city", "town", "village", "hamlet"):
            x, y = to_xy(g.x, g.y)
            osm.obce.append((_nazev(r), r["class"], Point(x, y)))


def _ov_voda(osm: OsmData, bbox, progress):
    for r, g in zdroje.geometrie("base", "water", bbox, ["class", "subtype", "names"], progress):
        if g.geom_type in ("LineString", "MultiLineString"):
            for ls in getattr(g, "geoms", [g]):
                osm.reky.append((_nazev(r), _xy_geom(ls)))
        else:
            osm.voda_plochy += [p for p in map(_xy_geom, _polys(g)) if p.area > 2000]


def _ov_doprava(osm: OsmData, bbox, progress):
    for r, g in zdroje.geometrie("transportation", "segment", bbox, ["class", "subtype", "names"], progress):
        for ls in getattr(g, "geoms", [g]):
            if ls.geom_type != "LineString":
                continue
            if r.get("subtype") == "rail":
                if r.get("class") in ("standard_gauge", "rail", None, ""):
                    osm.zeleznice.append(_xy_geom(ls))
            elif r.get("subtype") == "road" and r.get("class") in ("motorway", "trunk", "primary", "secondary"):
                osm.silnice.append((r["class"], _nazev(r), _xy_geom(ls)))


def _ov_budovy(bbox, progress) -> np.ndarray:
    ll = zdroje.budovy_stredy(bbox, progress)
    if len(ll) == 0:
        return np.zeros((0, 2))
    x, y = to_xy(ll[:, 0], ll[:, 1])
    return np.column_stack([x, y])


def zalozni_povolen() -> bool:
    return ZDROJE_REZIM in ("auto", "overture")


def overpass_povolen() -> bool:
    return ZDROJE_REZIM in ("auto", "overpass")


# -------------------------------------------------------------------- dotazy

def _q(body: str, timeout: int = 180) -> str:
    return f"[out:json][timeout:{timeout}];\n({body});\nout geom qt;"


def fetch_area(bbox, budovy: bool = True, chranena: bool = True, progress: Progress | None = None) -> OsmData:
    """Stáhne všechny vrstvy pro obdélník ``bbox`` = (west, south, east, north).

    Obdélník se zaokrouhlí ven na 0,1°, aby drobné změny bodů trasy využily data z cache.
    """
    import math

    bbox = (math.floor(bbox[0] * 10) / 10, math.floor(bbox[1] * 10) / 10,
            math.ceil(bbox[2] * 10) / 10, math.ceil(bbox[3] * 10) / 10)
    b = _bbox_str(bbox)
    osm = OsmData()

    def safe(label, fn, zalozni=None):
        """Overpass; při selhání (nebo v režimu „jen Overture“) záložní zdroj Overture Maps."""
        chyba = None
        if overpass_povolen():
            try:
                fn()
                osm.zdroje[label] = "OSM (Overpass)"
                return
            except OverpassError as e:
                chyba = e
        if zalozni is not None and zalozni_povolen():
            try:
                zalozni(osm, bbox, progress)
                osm.zdroje[label] = "Overture Maps"
                if chyba:
                    osm.varovani.append(f"Vrstva '{label}': Overpass nedostupný, použit záložní zdroj Overture Maps.")
                return
            except Exception as e2:        # noqa: BLE001 – chybu zdroje vždy převést na varování
                chyba = chyba or e2
                log.warning("Overture %s: %s", label, e2)
        if chyba is not None:
            osm.varovani.append(f"{chyba}. Vrstva '{label}' nebyla použita – zkuste výpočet později zopakovat.")
            log.warning("%s", chyba)

    def zastavba():
        data = overpass(_q(
            f'way["landuse"~"^(residential|industrial|commercial|retail|garages|farmyard)$"]{b};'
            f'relation["landuse"~"^(residential|industrial|commercial|retail)$"]{b};'
        ), progress=progress, label="zástavba")
        osm.zastavba = [p for _, p in _polygons(data)]

    def obce():
        data = overpass(
            f'[out:json][timeout:120];node["place"~"^(city|town|village|hamlet)$"]{b};out qt;',
            progress=progress, label="obce")
        for el in data.get("elements", []):
            name = el.get("tags", {}).get("name", "")
            x, y = to_xy(el["lon"], el["lat"])
            osm.obce.append((name, el["tags"].get("place", ""), Point(x, y)))

    def voda():
        data = overpass(_q(
            f'way["natural"="water"]{b};relation["natural"="water"]{b};'
            f'way["landuse"="reservoir"]{b};way["waterway"~"^(river|canal)$"]{b};'
        ), progress=progress, label="vodstvo")
        polys = []
        for el in data.get("elements", []):
            tags = el.get("tags", {})
            if el["type"] == "way" and tags.get("waterway"):
                if el.get("geometry") and len(el["geometry"]) >= 2:
                    osm.reky.append((tags.get("name", ""), LineString(_line_xy(el["geometry"]))))
            elif el["type"] == "way":
                p = _way_polygon(el)
                if p is not None and p.area > 2000:
                    polys.append(p)
            else:
                polys += [p for p in _relation_polygons(el) if p.area > 2000]
        osm.voda_plochy = polys

    def doprava():
        data = overpass(_q(
            f'way["highway"~"^(motorway|trunk|primary|secondary)$"]{b};way["railway"="rail"]["service"!~"."]{b};'
        ), progress=progress, label="silnice a železnice")
        for tags, ls in _lines(data):
            if tags.get("railway") == "rail":
                osm.zeleznice.append(ls)
            else:
                osm.silnice.append((tags.get("highway", ""), tags.get("ref", tags.get("name", "")), ls))

    def chranena_uzemi():
        data = overpass(_q(
            f'relation["boundary"~"^(protected_area|national_park)$"]{b};way["boundary"="protected_area"]{b};'
            f'relation["leisure"="nature_reserve"]{b};way["leisure"="nature_reserve"]{b};'
        ), progress=progress, label="chráněná území")
        for tags, p in _polygons(data):
            osm.chranena.append((tags.get("name", "chráněné území"), _protect_level(tags), p))

    safe("zástavba", zastavba, _ov_zastavba)
    safe("obce", obce, _ov_obce)
    safe("vodstvo", voda, _ov_voda)
    safe("doprava", doprava, _ov_doprava)
    if chranena:
        safe("chráněná území", chranena_uzemi)
    if budovy:
        try:
            osm.budovy = fetch_buildings_bbox(bbox, progress)
            osm.budovy_kompletni = True
        except OverpassError as e:
            osm.varovani.append(f"{e}. Budovy v oblasti nebyly staženy (použije se jen zástavba).")
    return osm


def _budovy_dlazdice(q: str, tb, progress, label: str) -> np.ndarray:
    chyba = None
    if overpass_povolen():
        try:
            return _csv_points(overpass(q, fmt="csv", progress=progress, label=label))
        except OverpassError as e:
            chyba = e
    if zalozni_povolen():
        try:
            return _ov_budovy(tb, progress)
        except Exception as e2:            # noqa: BLE001
            chyba = chyba or e2
    raise OverpassError(str(chyba))


def fetch_buildings_bbox(bbox, progress: Progress | None = None, tile_deg: float = 0.3) -> np.ndarray:
    """Středy budov v obdélníku, stahováno po dlaždicích (kvůli limitům Overpass)."""
    west, south, east, north = bbox
    lons = np.arange(np.floor(west / tile_deg) * tile_deg, east, tile_deg)
    lats = np.arange(np.floor(south / tile_deg) * tile_deg, north, tile_deg)
    parts = []
    n = len(lons) * len(lats)
    i = 0
    for la in lats:
        for lo in lons:
            i += 1
            tb = (round(lo, 4), round(la, 4), round(lo + tile_deg, 4), round(la + tile_deg, 4))
            q = f'[out:csv(::lat,::lon;false)][timeout:180];way["building"]{_bbox_str(tb)};out center qt;'
            parts.append(_budovy_dlazdice(q, tb, progress, f"budovy {i}/{n}"))
    pts = np.vstack(parts) if parts else np.zeros((0, 2))
    return pts


def _fetch_poly(poly_lonlat, progress, label="budovy v koridoru") -> np.ndarray:
    coords = " ".join(f"{lat:.5f} {lon:.5f}" for lon, lat in poly_lonlat)
    q = f'[out:csv(::lat,::lon;false)][timeout:180];way["building"](poly:"{coords}");out center qt;'
    lo = [p[0] for p in poly_lonlat]
    la = [p[1] for p in poly_lonlat]
    return _budovy_dlazdice(q, (min(lo), min(la), max(lo), max(la)), progress, label)


def fetch_buildings_corridor(poly_lonlat: list[tuple[float, float]], progress: Progress | None = None) -> np.ndarray:
    """Středy budov uvnitř polygonu koridoru (lon, lat).

    Stažené budovy a pokrytá území se ukládají do ``data/cache/osm/budovy_store.npz``; při dalším
    výpočtu se ze serveru stahuje jen část polygonu, která ještě pokrytá není.
    """
    import shapely
    from shapely.geometry import Polygon

    lon = np.array([p[0] for p in poly_lonlat])
    lat = np.array([p[1] for p in poly_lonlat])
    x, y = to_xy(lon, lat)
    poly = Polygon(np.column_stack([x, y])).buffer(0)
    store = cache_dir("osm") / "budovy_store.npz"
    body = np.zeros((0, 2))
    pokryto = None
    if store.exists():
        try:
            d = np.load(store, allow_pickle=False)
            body = d["body"]
            pokryto = shapely.from_wkb(bytes(d["pokryto"]))
        except Exception:
            body, pokryto = np.zeros((0, 2)), None
    chybi = poly if pokryto is None else poly.difference(pokryto.buffer(-1))
    casti = [g for g in getattr(chybi, "geoms", [chybi]) if not g.is_empty and g.area > 2e4]
    selhalo: list[str] = []
    for i, g in enumerate(casti):
        g = g.simplify(30).buffer(20)
        ex = np.array(g.exterior.coords)
        glon, glat = to_lonlat(ex[:, 0], ex[:, 1])
        try:
            nove = _fetch_poly(list(zip(glon, glat)), progress, f"budovy v koridoru {i + 1}/{len(casti)}")
        except OverpassError as e:       # část se nepodařila → nepovažovat za pokrytou, pokračovat dál
            selhalo.append(str(e))
            continue
        body = np.unique(np.vstack([body, nove]).round(1), axis=0) if len(nove) else body
        pokryto = g if pokryto is None else pokryto.union(g)
        np.savez_compressed(store, body=body, pokryto=np.frombuffer(shapely.to_wkb(pokryto), dtype=np.uint8))
    if selhalo and progress:
        progress(f"Část budov se nepodařilo stáhnout ({len(selhalo)}×), výpočet pokračuje s tím, co je k dispozici.")
    if selhalo and len(casti) == len(selhalo) and len(body) == 0:
        raise OverpassError(selhalo[0])
    if len(body) == 0:
        return body
    uvnitr = shapely.contains_xy(poly, body[:, 0], body[:, 1])
    return body[uvnitr]


# ------------------------------------------------------------------ Nominatim

def geocode(text: str, limit: int = 6) -> list[dict]:
    """Vyhledá místo podle názvu (Nominatim). Vrací [{'nazev', 'lat', 'lon'}]."""
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": text, "format": "json", "limit": limit, "countrycodes": "cz,sk,at,de,pl", "accept-language": "cs"},
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    r.raise_for_status()
    return [{"nazev": d["display_name"], "lat": float(d["lat"]), "lon": float(d["lon"])} for d in r.json()]


def nejblizsi_obec(lat: float, lon: float) -> str:
    """Název nejbližší obce (Nominatim reverse, cache na disku). Při chybě vrací ""."""
    key = cache_dir("osm") / "reverse.json"
    try:
        cache = json.loads(key.read_text(encoding="utf-8")) if key.exists() else {}
    except Exception:
        cache = {}
    k = f"{lat:.3f},{lon:.3f}"
    if k in cache:
        return cache[k]
    try:
        r = requests.get("https://nominatim.openstreetmap.org/reverse",
                         params={"lat": lat, "lon": lon, "format": "json", "zoom": 12, "accept-language": "cs"},
                         headers={"User-Agent": USER_AGENT}, timeout=8)
        r.raise_for_status()
        a = r.json().get("address", {})
        nazev = (a.get("village") or a.get("town") or a.get("city") or a.get("hamlet")
                 or a.get("municipality") or a.get("suburb") or "")
    except Exception:
        return ""
    cache[k] = nazev
    try:
        key.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return nazev
