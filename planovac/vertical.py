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
                 budovy_na_m: float | np.ndarray = 0.0, demolice_mil: float | None = None,
                 zast: bool | np.ndarray = False, st: float | np.ndarray = 0.0) -> np.ndarray:
    """Cena [Kč/m] jednotlivých variant pro výšky ``h``; tvar (4, *h.shape), nepřípustné = inf.

    ``zast`` – osa vede zástavbou (povrchové varianty mají příplatek, tunel je dovolen už od menší hloubky),
    ``st`` – 0 mimo stanici, jinak váha stanice (1 = stanice, 0,25 = zastávka): stanice smí být nejvýš
    ``max_hloubka_stanice_m`` pod terénem a každý metr hloubky se připlácí.
    """
    h = np.asarray(h, dtype=np.float64)
    voda = np.broadcast_to(np.asarray(voda, dtype=bool), h.shape)
    bud = np.broadcast_to(np.asarray(budovy_na_m, dtype=np.float64), h.shape)
    st = np.broadcast_to(np.asarray(st, dtype=np.float64), h.shape)
    zast = np.broadcast_to(np.asarray(zast, dtype=bool), h.shape) & (st <= 0)
    b, n = navrh.sirka_plane_m, navrh.sklon_svahu
    ah = np.abs(h)
    area = ah * (b + n * ah)
    zem = np.where(h >= 0, area * ceny.nasyp_kc_m3, area * ceny.vykop_kc_m3)
    zem = zem + (b + 2 * n * ah + 6.0) * ceny.pozemky_kc_m2
    # cena demolice pro optimalizaci = výkup + společenská penalizace (viz Vahy.penalizace_demolice_mil)
    demol = bud * (ceny.demolice_mil_budova if demolice_mil is None else demolice_mil) * 1e6
    zem = zem + demol
    # příplatek za vedení po povrchu zástavbou (vykoupení, rozdělení území) – mimo stanice
    pripl = np.where(zast, ceny.zastavba_prirazka_mil_km * 1000.0, 0.0)
    zem = zem + pripl
    zem_ok = (h <= navrh.vyska_nasypu_max_m) & (h >= -navrh.hloubka_zarezu_max_m) & ~voda
    estak = ceny.estakada_mil_km * 1000.0 * (1 + ceny.estakada_prirazka_pct_m / 100.0 * np.maximum(h - 20.0, 0))
    estak = estak + 0.3 * demol + 12.0 * ceny.pozemky_kc_m2 + 0.5 * pripl
    est_ok = (h >= navrh.vyska_estakady_min_m) & ~voda
    tunel = np.full(h.shape, ceny.tunel_mil_km * 1000.0)
    tun_ok = (h <= -navrh.hloubka_tunelu_min_m) | (zast & (h <= -navrh.hloubka_tunelu_pod_mestem_m))
    most = ceny.most_mil_km * 1000.0 * (1 + ceny.estakada_prirazka_pct_m / 100.0 * np.maximum(h - 20.0, 0)) + 0.3 * demol
    most_ok = voda & (h >= 4.0)
    out = np.stack([
        np.where(zem_ok, zem, np.inf),
        np.where(est_ok, estak, np.inf),
        np.where(tun_ok, tunel, np.inf),
        np.where(most_ok, most, np.inf),
    ])
    if (st > 0).any():
        hloub = np.maximum(-h, 0.0)
        extra = ceny.podzemni_stanice_mil_m * 1e6 * st * hloub / 400.0     # Kč za metr osy
        out = out + extra
        out = np.where((st > 0) & (h < -navrh.max_hloubka_stanice_m - 1e-9), np.inf, out)
    # záchrana: kdyby nic nebylo přípustné (např. voda a h mezi −15 a 4 m) – velmi drahé
    none = ~np.isfinite(out).any(axis=0) & ~((st > 0) & (h < -navrh.max_hloubka_stanice_m - 1e-9))
    if none.any():
        out[0] = np.where(none, 1e7 + 1e5 * ah, out[0])
    return out


def best_cost(h, navrh, ceny, voda=False, budovy_na_m=0.0, demolice_mil=None, zast=False, st=0.0) -> np.ndarray:
    return option_costs(h, navrh, ceny, voda, budovy_na_m, demolice_mil, zast, st).min(axis=0)


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
    demolice_mil: float | None = None,
    faktor: np.ndarray | None = None,
    zastavba: np.ndarray | None = None,
    stanice_info: list[tuple[float, float]] | None = None,
) -> np.ndarray:
    """``zastavba`` – maska vzorků osy vedených zástavbou; ``stanice_info`` – (délka nástupiště, váha) ke
    každé stanici v ``stanice_s`` (váha 1 = stanice, 0,25 = zastávka; výchozí stanice 1)."""
    """Vrátí výšku nivelety [m n. m.] ve vzorcích ``s``."""
    L = float(s[-1])
    M = max(3, int(np.ceil(L / ds)) + 1)
    sc = np.linspace(0, L, M)
    ds = sc[1] - sc[0]
    zc = np.interp(sc, s, z_teren)
    vc = _resample_flags(s, voda, sc, ds / 2 + 5)
    # budovy: součet na hrubý krok -> na metr
    bc = np.interp(sc, s, ndimage.uniform_filter1d(budovy_na_m.astype(float), max(1, int(ds / max(s[1] - s[0], 1)))))
    # sleva za souběh se stávající tratí / silnicí (násobí cenu metru)
    fc = np.ones(M) if faktor is None else np.interp(sc, s, faktor)
    zc_zast = np.zeros(M, dtype=bool) if zastavba is None else _resample_flags(s, zastavba, sc, ds / 2 + 5)
    # stanice: váha a délka nástupiště v každém hrubém kroku
    info = stanice_info or [(navrh.delka_nastupiste_m, 1.0)] * len(stanice_s)
    stc = np.zeros(M)
    st_len = np.full(M, navrh.delka_nastupiste_m)
    for st_s, (Lp_i, w_i) in zip(stanice_s, info):
        m = np.abs(sc - st_s) <= Lp_i / 2 + ds / 2
        stc[m] = np.maximum(stc[m], w_i)
        st_len[m] = Lp_i

    g = navrh.max_sklon_promile / 1000.0
    g_st = navrh.max_sklon_stanice_promile / 1000.0
    K = 4
    dz = g * ds / K
    gmax = np.full(M, g)
    for st_s, (Lp_i, _) in zip(stanice_s, info):
        m = np.abs(sc - st_s) <= Lp_i / 2 + ds
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
    D[0] = best_cost(levels - zc[0], navrh, ceny, vc[0], bc[0], demolice_mil, zc_zast[0], stc[0]) * fc[0] * ds / 2
    for i in range(1, M):
        k = int(min(kmax[i], kmax[i - 1]))
        prev = D[i - 1]
        best = ndimage.minimum_filter1d(prev, size=2 * k + 1, mode="nearest") if k > 0 else prev
        D[i] = best + best_cost(levels - zc[i], navrh, ceny, vc[i], bc[i], demolice_mil, zc_zast[i], stc[i]) * fc[i] * ds
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
    for st_s, (Lp_i, _) in zip(stanice_s, info):
        m = np.abs(sc - st_s) <= Lp_i / 2
        if m.any():
            zs[m] = zs[m].mean()
    # stanice nesmí být hlouběji než max_hloubka_stanice_m (vyhlazení mohlo profil zhoupnout)
    zs = np.where(stc > 0, np.maximum(zs, zc - navrh.max_hloubka_stanice_m), zs)
    # vynucení max. sklonu (dopředný průchod)
    lim = np.minimum(gmax[1:], gmax[:-1]) * ds
    for i in range(1, M):
        zs[i] = np.clip(zs[i], zs[i - 1] - lim[i - 1], zs[i - 1] + lim[i - 1])
    return np.interp(s, sc, zs)
