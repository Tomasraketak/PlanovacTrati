"""Úpravy seznamu bodů trasy (stanice a průjezdní body) – používá GUI při klikání do mapy."""
from __future__ import annotations

import numpy as np

from .config import TYP_PRUJEZD, TYP_STANICE, Bod
from .geo import to_xy


def _xy(b: Bod) -> np.ndarray:
    x, y = to_xy(b.lon, b.lat)
    return np.array([x, y])


def nejlepsi_pozice(body: list[Bod], lat: float, lon: float, konce_faktor: float = 1.5) -> int:
    """Index, na který vložit nový bod, aby co nejméně prodloužil trasu.

    Vnitřní pozice (mezi dvěma body) mají přednost; před první / za poslední bod se vloží jen tehdy,
    když je to ``konce_faktor``× výhodnější (konce trasy se tak omylem nemění).
    """
    n = len(body)
    if n == 0:
        return 0
    p = np.array(to_xy(lon, lat))
    pts = [_xy(b) for b in body]
    if n == 1:
        return 1
    nejlepsi_i, nejlepsi_c = 1, np.inf
    for i in range(1, n):
        a, b = pts[i - 1], pts[i]
        c = np.hypot(*(p - a)) + np.hypot(*(b - p)) - np.hypot(*(b - a))
        if c < nejlepsi_c:
            nejlepsi_i, nejlepsi_c = i, c
    pred = np.hypot(*(p - pts[0]))          # přírůstek délky při vložení před začátek
    za = np.hypot(*(p - pts[-1]))           # … za konec
    if pred * konce_faktor < nejlepsi_c and pred <= za:
        return 0
    if za * konce_faktor < nejlepsi_c:
        return n
    return nejlepsi_i


def vychozi_nazev(body: list[Bod], typ: str, obec: str = "") -> str:
    if typ == TYP_STANICE:
        return obec or f"Stanice {sum(b.je_stanice for b in body) + 1}"
    n = sum(not b.je_stanice for b in body) + 1
    return f"Průjezdní bod {n}" + (f" (u {obec})" if obec else "")


def pridej(body: list[Bod], lat: float, lon: float, typ: str, nazev: str | None = None,
           obec: str = "") -> tuple[list[Bod], int]:
    """Vrátí nový seznam s přidaným bodem a jeho index."""
    i = nejlepsi_pozice(body, lat, lon)
    novy = Bod(nazev or vychozi_nazev(body, typ, obec), round(lat, 5), round(lon, 5), typ)
    out = list(body)
    out.insert(i, novy)
    return out, i


def posun(body: list[Bod], i: int, smer: int) -> tuple[list[Bod], int]:
    j = i + smer
    if not (0 <= i < len(body) and 0 <= j < len(body)):
        return list(body), i
    out = list(body)
    out[i], out[j] = out[j], out[i]
    return out, j


def smaz(body: list[Bod], i: int) -> list[Bod]:
    return [b for k, b in enumerate(body) if k != i]


def prepni_typ(body: list[Bod], i: int) -> list[Bod]:
    out = list(body)
    b = out[i]
    out[i] = Bod(b.nazev, b.lat, b.lon, TYP_PRUJEZD if b.je_stanice else TYP_STANICE)
    return out


def nejblizsi_bod(body: list[Bod], lat: float, lon: float, max_m: float = 3000.0) -> int | None:
    """Index bodu nejblíž kliknutí (pro výběr klikem na značku), nebo None."""
    if not body:
        return None
    p = np.array(to_xy(lon, lat))
    d = [np.hypot(*(p - _xy(b))) for b in body]
    i = int(np.argmin(d))
    return i if d[i] <= max_m else None
