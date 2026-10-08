"""Orientační rozpočet stavby."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import Ceny
from .structures import ESTAKADA, HLOUBENY, MOST, NASYP, TUNEL, UROVEN, ZAREZ, Analyza


@dataclass
class Polozka:
    nazev: str
    mnozstvi: float
    jednotka: str
    jednotkova_cena: float   # mil. Kč za jednotku (pro m³ a m² v Kč)
    cena_mil: float          # mil. Kč


@dataclass
class Rozpocet:
    polozky: list[Polozka]
    primé_naklady_mil: float
    projekt_mil: float
    rezerva_mil: float
    celkem_mil: float
    na_km_mil: float


def cena_metru(h: np.ndarray, typy: np.ndarray, navrh, ceny: Ceny) -> np.ndarray:
    """Přímá stavební cena [Kč/m] v každém vzorku osy podle typu úseku (bez stanic a demolic)."""
    b, n = navrh.sirka_plane_m, navrh.sklon_svahu
    ah = np.abs(h)
    area = ah * (b + n * ah)
    zaklad = (ceny.trat_zaklad_mil_km + ceny.technologie_mil_km) * 1000.0
    prirazka = 1 + ceny.estakada_prirazka_pct_m / 100.0 * np.maximum(h - 20.0, 0)
    zem = np.isin(typy, (UROVEN, NASYP, ZAREZ))
    c = np.where(zem, np.where(h >= 0, area * ceny.nasyp_kc_m3, area * ceny.vykop_kc_m3)
                 + (b + 2 * n * ah + 6.0) * ceny.pozemky_kc_m2, 0.0)
    c = np.where(typy == ESTAKADA, ceny.estakada_mil_km * 1000.0 * prirazka, c)
    c = np.where(typy == MOST, ceny.most_mil_km * 1000.0 * prirazka, c)
    c = np.where(typy == TUNEL, ceny.tunel_mil_km * 1000.0, c)
    c = np.where(typy == HLOUBENY, ceny.hloubeny_tunel_mil_km * 1000.0, c)
    return zaklad + c


def sleva_soubeh(s: np.ndarray, h: np.ndarray, typy: np.ndarray, faktor: np.ndarray, navrh, ceny: Ceny) -> float:
    """Sleva [mil. Kč] za úseky v souběhu se stávající tratí / silnicí."""
    ds = np.gradient(s)
    return float(np.sum((1 - faktor) * cena_metru(h, typy, navrh, ceny) * ds) / 1e6)


def estimate(delka_m: float, s: np.ndarray, h: np.ndarray, an: Analyza, n_mezilehlych: int, n_koncovych: int,
             ceny: Ceny, sleva_mil: float = 0.0, n_zastavek: int = 0, podzemni_mil: float = 0.0) -> Rozpocet:
    km = delka_m / 1000.0
    P: list[Polozka] = []

    def add(nazev, mn, jedn, jc, cena):
        P.append(Polozka(nazev, float(mn), jedn, float(jc), float(cena)))

    add("Železniční svršek a spodek", km, "km", ceny.trat_zaklad_mil_km, km * ceny.trat_zaklad_mil_km)
    add("Trakce, zabezpečení (ETCS), napájení", km, "km", ceny.technologie_mil_km, km * ceny.technologie_mil_km)
    add("Násypy", an.objem_nasyp_m3, "m³", ceny.nasyp_kc_m3, an.objem_nasyp_m3 * ceny.nasyp_kc_m3 / 1e6)
    add("Výkopy a zářezy", an.objem_vykop_m3, "m³", ceny.vykop_kc_m3, an.objem_vykop_m3 * ceny.vykop_kc_m3 / 1e6)

    def objekt_cena(typ, zaklad_mil_km, vyska_prirazka=False):
        L = 0.0
        C = 0.0
        for u in an.objekty:
            if u.typ != typ:
                continue
            L += u.delka
            m = (s >= u.s0) & (s <= u.s1)
            hh = float(np.mean(h[m])) if m.any() else 0.0
            f = 1 + ceny.estakada_prirazka_pct_m / 100.0 * max(hh - 20.0, 0.0) if vyska_prirazka else 1.0
            C += u.delka / 1000.0 * zaklad_mil_km * f
        return L, C

    L, C = objekt_cena(ESTAKADA, ceny.estakada_mil_km, True)
    add("Estakády", L / 1000, "km", ceny.estakada_mil_km, C)
    L, C = objekt_cena(MOST, ceny.most_mil_km, True)
    add("Mosty", L / 1000, "km", ceny.most_mil_km, C)
    L, C = objekt_cena(TUNEL, ceny.tunel_mil_km)
    add("Tunely ražené", L / 1000, "km", ceny.tunel_mil_km, C)
    n_tun = sum(1 for u in an.objekty if u.typ == TUNEL)
    add("Tunelové portály", n_tun, "ks", ceny.portal_mil, n_tun * ceny.portal_mil)
    L, C = objekt_cena(HLOUBENY, ceny.hloubeny_tunel_mil_km)
    add("Tunely hloubené", L / 1000, "km", ceny.hloubeny_tunel_mil_km, C)
    n_sil = sum(1 for k in an.krizeni if k.druh == "silnice" and k.reseni.startswith("mimoúrovňové"))
    add("Křížení silnic (nadjezdy/podjezdy)", n_sil, "ks", ceny.krizeni_silnice_mil, n_sil * ceny.krizeni_silnice_mil)
    n_zel = sum(1 for k in an.krizeni if k.druh == "železnice" and k.reseni.startswith("mimoúrovňové"))
    add("Křížení železnic", n_zel, "ks", ceny.krizeni_zeleznice_mil, n_zel * ceny.krizeni_zeleznice_mil)
    add("Mezilehlé stanice", n_mezilehlych, "ks", ceny.stanice_mil, n_mezilehlych * ceny.stanice_mil)
    if n_zastavek:
        add("Malé zastávky", n_zastavek, "ks", ceny.zastavka_mil, n_zastavek * ceny.zastavka_mil)
    if podzemni_mil > 0:
        add("Podzemní stanice / zastávky (příplatek za hloubku)", 1, "", podzemni_mil, podzemni_mil)
    add("Koncové stanice / napojení uzlů", n_koncovych, "ks", ceny.koncova_stanice_mil,
        n_koncovych * ceny.koncova_stanice_mil)
    nd = len(an.demolice_idx)
    add("Výkup a demolice budov", nd, "ks", ceny.demolice_mil_budova, nd * ceny.demolice_mil_budova)
    add("Výkup pozemků (trvalý zábor)", an.zabor_m2, "m²", ceny.pozemky_kc_m2, an.zabor_m2 * ceny.pozemky_kc_m2 / 1e6)

    if sleva_mil > 0:
        add("Sleva za souběh se stávající tratí / silnicí", 1, "", -sleva_mil, -sleva_mil)
    prime = sum(p.cena_mil for p in P)
    projekt = prime * ceny.projekt_pct / 100.0
    rezerva = (prime + projekt) * ceny.rezerva_pct / 100.0
    celkem = prime + projekt + rezerva
    return Rozpocet(P, prime, projekt, rezerva, celkem, celkem / max(km, 1e-9))
