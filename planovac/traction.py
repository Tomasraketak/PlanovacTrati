"""Trakční simulace jízdy vlaku a výpočet jízdních dob.

Model: hmotný bod. Tažná síla F(v) = min(F_max, P / v), jízdní odpor podle
Davisovy rovnice R(v) = A + B·v + C·v² (v v km/h), odpor ze sklonu m·g·i.
Rychlost je omezena návrhovou rychlostí, rychlostí v oblouku
v = √(R·(D + I) / 11,8) a zastavením ve stanicích. Dopředný průchod počítá
rozjezd, zpětný průchod brzdění s konstantním zpomalením.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import VLAKY, NavrhoveParametry, Vlak

G = 9.81
ROT = 1.06  # přirážka na rotující hmoty


@dataclass
class RadekJR:
    z: str
    do: str
    delka_km: float
    jizdni_doba_s: float
    prumerna_kmh: float


@dataclass
class JizdniDoby:
    s: np.ndarray
    v_kmh: np.ndarray           # rychlost – zastavuje ve všech stanicích
    v_express_kmh: np.ndarray   # rychlost – bez mezilehlých zastavení
    vlim_kmh: np.ndarray        # rychlostní profil trati
    radky: list[RadekJR]        # úseky mezi stanicemi (vč. rezervy)
    celkem_s: float             # celková doba vč. pobytů ve stanicích
    express_s: float            # celková doba bez mezilehlých zastavení
    jizdni_rad: list[tuple[str, float, float]]  # (stanice, příjezd s, odjezd s)
    vlak: str = ""


def speed_limit(krivost: np.ndarray, navrh: NavrhoveParametry, vlak: Vlak, ds: float = 10.0,
                delka_vlaku_m: float = 200.0) -> np.ndarray:
    """Nejvyšší dovolená rychlost [km/h] v každém bodě osy."""
    from scipy.ndimage import minimum_filter1d

    v = np.full(len(krivost), min(navrh.rychlost_kmh, vlak.max_rychlost_kmh), dtype=float)
    k = np.abs(krivost)
    with np.errstate(divide="ignore"):
        R = np.where(k > 1e-9, 1.0 / k, np.inf)
    # naklápěcí vlaky smí mít větší nedostatek převýšení -> projedou oblouk rychleji
    I = vlak.nedostatek_prevyseni_mm or navrh.nedostatek_prevyseni_mm
    vc = np.sqrt(R * (navrh.prevyseni_mm + I) / 11.8)
    v = np.minimum(v, vc)
    # omezení musí platit po celé délce vlaku -> rozšíření minim o délku vlaku
    size = max(1, int(round(delka_vlaku_m / ds))) | 1
    return minimum_filter1d(v, size=size, mode="nearest")


def simulate(s: np.ndarray, z: np.ndarray, vlim_kmh: np.ndarray, stops: list[float], vlak: Vlak) -> tuple[np.ndarray, np.ndarray]:
    """Vrací (rychlost m/s, čas v každém bodě s)."""
    n = len(s)
    vlim = vlim_kmh / 3.6
    vlim = vlim.copy()
    stop_idx = [int(np.argmin(np.abs(s - st))) for st in stops]
    for i in stop_idx:
        vlim[i] = 0.0
    ds = np.diff(s)
    grade = np.diff(z) / np.maximum(ds, 1e-6)
    m = vlak.hmotnost_t
    P = vlak.vykon_kw
    F0 = vlak.max_tazna_sila_kn

    # dopředný průchod (rozjezd)
    vf = np.zeros(n)
    vf[0] = min(vlim[0], 0.0)
    for i in range(n - 1):
        v = vf[i]
        vk = v * 3.6
        F = F0 if v < 0.5 else min(F0, P / v)
        R = vlak.odpor_a_kn + vlak.odpor_b_kn * vk + vlak.odpor_c_kn * vk * vk
        a = (F - R - m * G * grade[i]) / (m * ROT)
        a = min(a, vlak.max_zrychleni_ms2)
        v2 = v * v + 2 * a * ds[i]
        vf[i + 1] = min(np.sqrt(max(v2, 0.25)), vlim[i + 1])
    # zpětný průchod (brzdění)
    vb = np.empty(n)
    vb[-1] = 0.0
    b = vlak.brzdne_zpomaleni_ms2
    for i in range(n - 2, -1, -1):
        vb[i] = min(vlim[i], np.sqrt(vb[i + 1] ** 2 + 2 * b * ds[i]))
    v = np.minimum(vf, vb)
    vmid = (v[:-1] + v[1:]) / 2
    dt = ds / np.maximum(vmid, 0.3)
    t = np.concatenate([[0.0], np.cumsum(dt)])
    return v, t


def compute(s, z, krivost, body_s, body_nazvy, je_stanice, navrh: NavrhoveParametry, vlak: Vlak) -> JizdniDoby:
    ds = float(np.median(np.diff(s))) if len(s) > 1 else 10.0
    vlim = speed_limit(krivost, navrh, vlak, ds)
    st_s = [bs for bs, js in zip(body_s, je_stanice) if js]
    st_n = [nm for nm, js in zip(body_nazvy, je_stanice) if js]
    v, t = simulate(s, z, vlim, st_s, vlak)
    ve, te = simulate(s, z, vlim, [st_s[0], st_s[-1]], vlak)
    rez = 1 + vlak.rezerva_pct / 100.0
    radky = []
    jr = []
    cas = 0.0
    pobyt = vlak.pobyt_stanice_s
    for k in range(len(st_s) - 1):
        i0 = int(np.argmin(np.abs(s - st_s[k])))
        i1 = int(np.argmin(np.abs(s - st_s[k + 1])))
        jd = (t[i1] - t[i0]) * rez
        L = (s[i1] - s[i0]) / 1000.0
        radky.append(RadekJR(st_n[k], st_n[k + 1], L, jd, L / max(jd / 3600, 1e-9)))
        if k == 0:
            jr.append((st_n[0], np.nan, 0.0))
        cas += jd
        if k + 1 < len(st_s) - 1:
            jr.append((st_n[k + 1], cas, cas + pobyt))
            cas += pobyt
        else:
            jr.append((st_n[k + 1], cas, np.nan))
    express = float(te[-1] * rez)
    return JizdniDoby(s=s, v_kmh=v * 3.6, v_express_kmh=ve * 3.6, vlim_kmh=vlim, radky=radky, celkem_s=cas,
                      express_s=express, jizdni_rad=jr, vlak=vlak.nazev)


@dataclass
class PorovnaniVlaku:
    vlak: str
    max_rychlost_kmh: float
    celkem_s: float          # se všemi zastávkami (vč. pobytů a rezervy)
    express_s: float         # bez mezilehlých zastavení
    prumerna_kmh: float
    jizda: JizdniDoby


def porovnani_vlaku(s, z, krivost, body_s, body_nazvy, je_stanice, navrh: NavrhoveParametry,
                    zaklad: Vlak) -> list[PorovnaniVlaku]:
    """Jízdní doby pro všechny předvolby vlaků (pobyt a rezerva z ``zaklad``)."""
    out = []
    for nazev in VLAKY:
        v = Vlak.z_predvolby(nazev, pobyt_stanice_s=zaklad.pobyt_stanice_s, rezerva_pct=zaklad.rezerva_pct)
        j = compute(s, z, krivost, body_s, body_nazvy, je_stanice, navrh, v)
        L = (s[-1] - s[0]) / 1000.0
        out.append(PorovnaniVlaku(nazev, v.max_rychlost_kmh, j.celkem_s, j.express_s,
                                  L / max(j.celkem_s / 3600, 1e-9), j))
    return out


def fmt_cas(sec: float) -> str:
    if sec is None or not np.isfinite(sec):
        return "–"
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
