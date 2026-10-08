"""Záložní zdroj dat: Overture Maps (GeoParquet na S3), když je Overpass API nedostupné.

Overture publikuje budovy, silnice, železnice, vodu, využití území a sídla jako parquet soubory
prostorově seřazené po řádkových skupinách. Čte se přes HTTP Range (jen potřebné řádkové skupiny,
jen potřebné sloupce), takže se nestahuje celá země. Index statistik souborů se uloží do cache.
Využívá se jen ``pyarrow`` (je součástí Streamlitu) a ``requests`` – žádná další závislost.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import numpy as np
import requests

from .dem import USER_AGENT
from .paths import cache_dir

log = logging.getLogger(__name__)

BUCKET = "https://overturemaps-us-west-2.s3.amazonaws.com/"
POSLEDNI_ZNAME_VYDANI = "2026-09-23.1"

Progress = Callable[[str], None]


class ZdrojError(RuntimeError):
    pass


def _get(url: str, **kw):
    kw.setdefault("timeout", 60)
    kw.setdefault("headers", {"User-Agent": USER_AGENT})
    last = None
    for _ in range(3):
        try:
            r = requests.get(url, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
    raise ZdrojError(f"Overture Maps nedostupné: {last}")


def vydani() -> str:
    """Poslední vydání Overture (cache na disku; při chybě poslední známé)."""
    f = cache_dir("overture") / "vydani.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - d["cas"] < 7 * 86400:
            return d["vydani"]
    except Exception:
        pass
    try:
        x = _get(BUCKET, params={"list-type": 2, "prefix": "release/", "delimiter": "/"}).text
        v = sorted(re.findall(r"release/([0-9][^/]+)/", x))
        if v:
            f.write_text(json.dumps({"vydani": v[-1], "cas": time.time()}), encoding="utf-8")
            return v[-1]
    except ZdrojError:
        pass
    return POSLEDNI_ZNAME_VYDANI


class _RangeFile:
    """Soubor na HTTP čtený po částech (Range) – stačí pro ``pyarrow.parquet.ParquetFile``."""

    closed = False

    def __init__(self, url: str, size: int | None = None):
        self.url, self.pos = url, 0
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.size = size if size is not None else int(self.s.head(url, timeout=60).headers["Content-Length"])

    def seek(self, o, w=0):
        self.pos = {0: o, 1: self.pos + o, 2: self.size + o}[w]
        return self.pos

    def tell(self):
        return self.pos

    def readable(self):
        return True

    def seekable(self):
        return True

    def writable(self):
        return False

    def flush(self):
        pass

    def close(self):
        pass

    def read(self, n=-1):
        if n is None or n < 0 or self.pos + n > self.size:
            n = self.size - self.pos
        if n <= 0:
            return b""
        for pokus in range(5):
            try:
                r = self.s.get(self.url, headers={"Range": f"bytes={self.pos}-{self.pos + n - 1}"}, timeout=90)
                r.raise_for_status()
                break
            except requests.RequestException:
                if pokus == 4:
                    raise
                time.sleep(1.5 * (pokus + 1))
        self.pos += n
        return r.content

    def readinto(self, b):
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)


def _soubory(theme: str, typ: str, rel: str) -> list[str]:
    prefix = f"release/{rel}/theme={theme}/type={typ}/"
    klice, token = [], None
    while True:
        p = {"list-type": 2, "prefix": prefix}
        if token:
            p["continuation-token"] = token
        x = _get(BUCKET, params=p).text
        klice += re.findall(r"<Key>([^<]+)</Key>", x)
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", x)
        if not m:
            break
        token = m.group(1)
    return klice


def _stat_soubor(klic: str) -> list[list[float]]:
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(_RangeFile(BUCKET + klic))
    md = pf.metadata
    out = []
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        v = {}
        for c in range(rg.num_columns):
            col = rg.column(c)
            if col.path_in_schema in ("bbox.xmin", "bbox.xmax", "bbox.ymin", "bbox.ymax") and col.statistics:
                v[col.path_in_schema] = (col.statistics.min, col.statistics.max)
        if len(v) < 4:
            out.append([-180, 180, -90, 90, rg.num_rows])
        else:
            out.append([v["bbox.xmin"][0], v["bbox.xmax"][1], v["bbox.ymin"][0], v["bbox.ymax"][1], rg.num_rows])
    return out


_zamek = threading.Lock()


def _index(theme: str, typ: str, rel: str, progress: Progress | None) -> dict[str, list[list[float]]]:
    """Statistiky řádkových skupin všech souborů vrstvy (cache; nepodařené soubory se příště doplní)."""
    f = cache_dir("overture") / f"index_{rel}_{theme}_{typ}.json"
    with _zamek:
        idx: dict = {}
        chybi_klice: list[str] | None = None
        if f.exists():
            try:
                idx = json.loads(f.read_text(encoding="utf-8"))
                chybi_klice = idx.pop("_chybi", [])
                if not chybi_klice:
                    return idx
            except Exception:
                idx, chybi_klice = {}, None
        if progress:
            progress(f"Overture Maps: vytvářím index {theme}/{typ} (jednorázově) …")
        klice = chybi_klice if chybi_klice is not None else _soubory(theme, typ, rel)
        if not klice:
            raise ZdrojError(f"Overture Maps: vydání {rel} neobsahuje {theme}/{typ}")

        def bezpecne(k):
            try:
                return _stat_soubor(k)
            except Exception as e:           # soubor se nepodařilo přečíst → doplní se příště
                log.warning("Overture: %s: %s", k[-40:], str(e)[:120])
                return None

        with ThreadPoolExecutor(6) as ex:
            stat = list(ex.map(bezpecne, klice))
        for k, st in zip(klice, stat):
            if st is not None:
                idx[k] = st
        chybi = [k for k, st in zip(klice, stat) if st is None]
        if not idx:
            raise ZdrojError("Overture Maps: nepodařilo se načíst žádný soubor")
        f.write_text(json.dumps({**idx, "_chybi": chybi}), encoding="utf-8")
        if chybi and progress:
            progress(f"Overture Maps: {len(chybi)} souborů se nepodařilo načíst, doplní se při dalším spuštění.")
        return idx


def cti(theme: str, typ: str, bbox, sloupce: list[str], progress: Progress | None = None):
    """Vrátí ``pyarrow.Table`` s řádky, jejichž bbox leží (aspoň částečně) v ``bbox`` = (W, S, E, N).

    Cache výsledku je na disku (klíč = vydání, vrstva, obdélník, sloupce).
    """
    import hashlib

    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    rel = vydani()
    w, s, e, n = bbox
    key = hashlib.sha1(f"{rel}|{theme}|{typ}|{bbox}|{sloupce}".encode()).hexdigest()[:20]
    cf = cache_dir("overture") / f"{key}.parquet"
    if cf.exists():
        try:
            return pq.read_table(cf)
        except Exception:
            pass
    idx = _index(theme, typ, rel, progress)
    ukoly = [(k, g) for k, rgs in idx.items() for g, st in enumerate(rgs)
             if st[1] >= w and st[0] <= e and st[3] >= s and st[2] <= n]
    if progress:
        progress(f"Overture Maps: čtu {theme}/{typ} ({len(ukoly)} bloků) …")
    po_souborech: dict[str, list[int]] = {}
    for k, g in ukoly:
        po_souborech.setdefault(k, []).append(g)
    cols = list(dict.fromkeys(sloupce + ["bbox"]))

    def cti_soubor(item):
        k, gs = item
        pf = pq.ParquetFile(_RangeFile(BUCKET + k))
        return pf.read_row_groups(gs, columns=cols)

    tabs = []
    with ThreadPoolExecutor(6) as ex:
        for t in ex.map(cti_soubor, po_souborech.items()):
            m = pc.and_(pc.and_(pc.greater_equal(pc.struct_field(t["bbox"], "xmax"), w),
                                pc.less_equal(pc.struct_field(t["bbox"], "xmin"), e)),
                        pc.and_(pc.greater_equal(pc.struct_field(t["bbox"], "ymax"), s),
                                pc.less_equal(pc.struct_field(t["bbox"], "ymin"), n)))
            tabs.append(t.filter(m))
    tab = pa.concat_tables(tabs) if tabs else pa.table({c: [] for c in cols})
    try:
        pq.write_table(tab, cf)
    except Exception:
        pass
    return tab


# ----------------------------------------------------------------- vrstvy pro planovac

def budovy_stredy(bbox, progress: Progress | None = None) -> np.ndarray:
    """Středy budov (lon, lat) v obdélníku – ze středu bboxu budovy."""
    t = cti("buildings", "building", bbox, [], progress)
    if t.num_rows == 0:
        return np.zeros((0, 2))
    bb = t["bbox"].combine_chunks()
    x = (bb.field("xmin").to_numpy(zero_copy_only=False) + bb.field("xmax").to_numpy(zero_copy_only=False)) / 2
    y = (bb.field("ymin").to_numpy(zero_copy_only=False) + bb.field("ymax").to_numpy(zero_copy_only=False)) / 2
    w, s, e, n = bbox
    ok = (x >= w) & (x <= e) & (y >= s) & (y <= n)
    return np.column_stack([x[ok], y[ok]])


def geometrie(theme: str, typ: str, bbox, sloupce: list[str], progress: Progress | None = None):
    """Seznam (řádek jako dict, shapely geometrie v lon/lat)."""
    import shapely

    t = cti(theme, typ, bbox, sloupce + ["geometry"], progress)
    if t.num_rows == 0:
        return []
    geom = shapely.from_wkb(t["geometry"].to_pylist())
    radky = t.drop_columns(["geometry", "bbox"]).to_pylist()
    return list(zip(radky, geom))
