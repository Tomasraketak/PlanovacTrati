"""Výškové řešení (niveleta) metodou dynamického programování.

Stav = (poloha podél osy, výška nivelety na diskrétní hladině). Přechod mezi
sousedními polohami smí změnit výšku maximálně o ``max_sklon · krok``. Cena
polohy je cena 1 m trati při výšce nivelety ``h`` nad (+) / pod (−) terénem:
nejlevnější z přípustných variant násyp / zářez / estakáda / tunel (/ most nad
vodou). DP najde globálně nejlevnější niveletu splňující sklon; poté se vyhladí
(zakružovací oblouky) a znovu se vynutí limit sklonu.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from .config import Ceny, NavrhoveParametry

VARIANTY = ("násyp/zářez", "estakáda", "tunel", "most")


def option_costs(h: np.ndarray, navrh: NavrhoveParametry, ceny: Ceny, voda: bool | np.ndarray = False,
                 budovy_na_m: float | np.ndarray = 0.0) -> np.ndarray:
    """Cena [Kč/m] jednotlivých variant pro výšky ``h``; tvar (4, *h.shape), nepřípustné = inf."""
    h = np.asarray(h, dtype=np.float64)
    voda = np.broadcast_to(np.asarray(voda, dtype=bool), h.shape)
    bud = np.broadcast_to(np.asarray(budovy_na_m, dtype=np.float64), h.shape)
    b, n = navrh.sirka_plane_m, navrh.sklon_svahu
    ah = np.abs(h)
    area = ah * (b + n * ah)
    zem = np.where(h >= 0, area * ceny.nasyp_kc_m3, area * ceny.vykop_kc_m3)
    zem = zem + (b + 2 * n * ah + 6.0) * ceny.pozemky_kc_m2
    demol = bud * ceny.demolice_mil_budova * 1e6
    zem = zem + demol
    zem_ok = (h <= navrh.vyska_nasypu_max_m) & (h >= -navrh.hloubka_zarezu_max_m) & ~voda
    estak = ceny.estakada_mil_km * 1000.0 * (1 + ceny.estakada_prirazka_pct_m / 100.0 * np.maximum(h - 20.0, 0))
    estak = estak + 0.3 * demol + 12.0 * ceny.pozemky_kc_m2
    est_ok = (h >= navrh.vyska_estakady_min_m) & ~voda
    tunel = np.full(h.shape, ceny.tunel_mil_km * 1000.0)
    tun_ok = h <= -navrh.hloubka_tunelu_min_m
    most = ceny.most_mil_km * 1000.0 * (1 + ceny.estakada_prirazka_pct_m / 100.0 * np.maximum(h - 20.0, 0)) + 0.3 * demol
    most_ok = voda & (h >= 4.0)
    out = np.stack([
        np.where(zem_ok, zem, np.inf),
        np.where(est_ok, estak, np.inf),
        np.where(tun_ok, tunel, np.inf),
        np.where(most_ok, most, np.inf),
    ])
    # záchrana: kdyby nic nebylo přípustné (např. voda a h mezi −15 a 4 m) – velmi drahé
    none = ~np.isfinite(out).any(axis=0)
    if none.any():
        out[0] = np.where(none, 1e7 + 1e5 * ah, out[0])
    return out


def best_cost(h, navrh, ceny, voda=False, budovy_na_m=0.0) -> np.ndarray:
    return option_costs(h, navrh, ceny, voda, budovy_na_m).min(axis=0)


def _resample_flags(s_dense, flag, s_coarse, half):
    """Příznak na hrubém kroku = True, pokud je True kdekoli v okolí ±half."""
    idx = np.flatnonzero(flag)
    if idx.size == 0:
        return np.zeros(len(s_coarse), dtype=bool)
    fs = s_dense[idx]
    lo = np.searchsorted(fs, s_coarse - half)
    hi = np.searchsorted(fs, s_coarse + half, side="right")
    return hi > lo


def design_profile(
    s: np.ndarray,
    z_teren: np.ndarray,
    voda: np.ndarray,
    budovy_na_m: np.ndarray,
    stanice_s: list[float],
    navrh: NavrhoveParametry,
    ceny: Ceny,
    ds: float = 25.0,
) -> np.ndarray:
    """Vrátí výšku nivelety [m n. m.] ve vzorcích ``s``."""
    L = float(s[-1])
    M = max(3, int(np.ceil(L / ds)) + 1)
    sc = np.linspace(0, L, M)
    ds = sc[1] - sc[0]
    zc = np.interp(sc, s, z_teren)
    vc = _resample_flags(s, voda, sc, ds / 2 + 5)
    # budovy: součet na hrubý krok -> na metr
    bc = np.interp(sc, s, ndimage.uniform_filter1d(budovy_na_m.astype(float), max(1, int(ds / max(s[1] - s[0], 1)))))

    g = navrh.max_sklon_promile / 1000.0
    g_st = navrh.max_sklon_stanice_promile / 1000.0
    K = 4
    dz = g * ds / K
    gmax = np.full(M, g)
    for st in stanice_s:
        m = np.abs(sc - st) <= navrh.delka_nastupiste_m / 2 + ds
        gmax[m] = g_st
    kmax = np.floor(gmax * ds / dz + 1e-9).astype(int)

    zmin = float(zc.min()) - max(40.0, navrh.hloubka_tunelu_min_m + 25)
    zmax = float(zc.max()) + 40.0
    # hrubší hladiny pro velké rozsahy (paměť)
    while (zmax - zmin) / dz > 6000:
        dz *= 2
        kmax = np.floor(gmax * ds / dz + 1e-9).astype(int)
    levels = np.arange(zmin, zmax + dz, dz)
    N = len(levels)

    D = np.empty((M, N), dtype=np.float32)
    D[0] = best_cost(levels - zc[0], navrh, ceny, vc[0], bc[0]) * ds / 2
    for i in range(1, M):
        k = int(min(kmax[i], kmax[i - 1]))
        prev = D[i - 1]
        best = ndimage.minimum_filter1d(prev, size=2 * k + 1, mode="nearest") if k > 0 else prev
        D[i] = best + best_cost(levels - zc[i], navrh, ceny, vc[i], bc[i]) * ds
    # zpětný průchod
    lev = np.empty(M, dtype=int)
    lev[-1] = int(np.argmin(D[-1]))
    for i in range(M - 1, 0, -1):
        k = int(min(kmax[i], kmax[i - 1]))
        lo, hi = max(0, lev[i] - k), min(N, lev[i] + k + 1)
        lev[i - 1] = lo + int(np.argmin(D[i - 1, lo:hi]))
    zr = levels[lev]

    # vyhlazení – zakružovací oblouky Rv: okno ~ Rv·Δg
    Rv = navrh.min_polomer_vertikal()
    W = float(np.clip(Rv * 2 * g, 200.0, 1500.0))
    w = max(1, int(round(W / ds)))
    if w > 1:
        zs = ndimage.uniform_filter1d(zr, w, mode="nearest")
        zs = ndimage.uniform_filter1d(zs, w, mode="nearest")
    else:
        zs = zr.copy()
    # ve stanicích vodorovně
    for st in stanice_s:
        m = np.abs(sc - st) <= navrh.delka_nastupiste_m / 2
        if m.any():
            zs[m] = zs[m].mean()
    # vynucení max. sklonu (dopředný průchod)
    lim = np.minimum(gmax[1:], gmax[:-1]) * ds
    for i in range(1, M):
        zs[i] = np.clip(zs[i], zs[i - 1] - lim[i - 1], zs[i - 1] + lim[i - 1])
    return np.interp(s, sc, zs)
