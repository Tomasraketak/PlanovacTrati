"""Úseky se sníženou rychlostí.

Plná návrhová rychlost vyžaduje velké poloměry oblouků (200 km/h → R ≥ 1 900 m), takže osa občas
nemůže sledovat optimální koridor a „řízne“ přes obec, kopec nebo údolí. Povolíme-li na krátkém
úseku nižší rychlost, smí tam být oblouk menší (120 km/h → R ≈ 700 m, 80 km/h → R ≈ 300 m)
a osa se tomu místu vyhne. Povolených „pravidel“ může být několik (každé s vlastní nejdelší délkou
úseku, nejnižší rychlostí, počtem a prahy úspory) – např. mírné snížení do 3 km na ≥ 120 km/h
a silné snížení do 2 km až na 80 km/h, ale jen při velké úspoře.

Postup:
1. Kandidáti = okna podél osy, kde je stavba drahá (tunely, estakády, demolice) a osa se přitom
   odchyluje od optimálního koridoru.
2. Pro každého kandidáta a dvě rychlosti (minimální a střední) se osa přepočítá s menším
   poloměrem jen v okně a celá varianta se vyhodnotí (niveleta, stavby, rozpočet).
3. Kandidát se přijme, pokud ušetří alespoň ``min_uspora_mil`` mil. Kč nebo zachrání alespoň
   ``min_uspora_demolic`` domů (prahy pravidla, ve kterém byl zkoušen), a přitom nepřibude žádná
   demolice. Vybere se nejvýše ``max_pocet`` nepřekrývajících se úseků (celkem i po pravidlech)
   a ověří se jejich společný účinek.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import numpy as np
import shapely
from shapely.geometry import MultiLineString

from .config import NavrhoveParametry, Omezeni, PravidloOmezeni

DELKA_VLAKU_M = 200.0


@dataclass
class Varianta:
    """Vyhodnocená varianta osy (vrací funkce ``vyhodnot`` z pipeline)."""

    osa: object
    cena_mil: float           # rozpočet celkem
    demolice: int
    J: float                  # cena + penalizace demolic (kritérium optimalizace)
    jizdni_doba_s: float
    data: dict = field(default_factory=dict)


@dataclass
class Usek:
    s0: float
    s1: float
    min_polomer_m: float
    rychlost_kmh: float
    uspora_mil: float = 0.0
    demolic_mene: int = 0
    ztrata_casu_s: float = 0.0

    @property
    def delka(self) -> float:
        return self.s1 - self.s0


def polomer_pro_rychlost(v_kmh: float, navrh: NavrhoveParametry) -> float:
    r = 11.8 * v_kmh ** 2 / (navrh.prevyseni_mm + navrh.nedostatek_prevyseni_mm)
    return math.ceil(r / 50.0) * 50.0


def rychlost_pro_polomer(R: float, navrh: NavrhoveParametry) -> float:
    v = math.sqrt(R * (navrh.prevyseni_mm + navrh.nedostatek_prevyseni_mm) / 11.8)
    return min(navrh.rychlost_kmh, math.floor(v / 5.0) * 5.0)


def useky_z_osy(osa, navrh: NavrhoveParametry, spojit_m: float = 1000.0) -> list[Usek]:
    """Najde v ose úseky s oblouky menšími než min. poloměr pro návrhovou rychlost."""
    Rmin = navrh.min_polomer()
    arcs = [p for p in osa.prvky if p.typ == "oblouk" and p.R < Rmin - 1]
    out: list[Usek] = []
    for p in arcs:
        if out and p.s0 - out[-1].s1 < spojit_m:
            u = out[-1]
            u.s1 = max(u.s1, p.s1)
            u.min_polomer_m = min(u.min_polomer_m, p.R)
        else:
            out.append(Usek(p.s0, p.s1, p.R, 0.0))
    for u in out:
        # omezení platí po celou délku vlaku před a za obloukem
        u.s0 = max(0.0, u.s0 - DELKA_VLAKU_M / 2)
        u.s1 = min(osa.delka, u.s1 + DELKA_VLAKU_M / 2)
        u.rychlost_kmh = rychlost_pro_polomer(u.min_polomer_m, navrh)
    return out


def kandidati(zaklad: Varianta, koridory_xy: list[np.ndarray], cena_na_m: np.ndarray, rozliseni: float,
              L: float, pocet: int = 6) -> list[tuple[float, float]]:
    """Okna (s0, s1) ve staničení základní osy, kde by snížená rychlost mohla pomoci."""
    osa = zaklad.osa
    s, xy = osa.s, osa.xy
    kor = MultiLineString([k for k in koridory_xy if len(k) > 1])
    dev = shapely.distance(shapely.points(xy), kor)
    odchylka = dev > max(2 * rozliseni, 60.0)
    # rozšířit o ±500 m – vrcholy oblouku leží i kousek vedle místa odchylky
    ds = float(np.median(np.diff(s)))
    w = max(1, int(500 / ds))
    odchylka = np.convolve(odchylka.astype(float), np.ones(2 * w + 1), mode="same") > 0
    cena_na_m = np.where(np.isfinite(cena_na_m), cena_na_m, 0.0)
    nadmerna = np.maximum(cena_na_m - np.median(cena_na_m), 0.0) * odchylka * ds
    n = max(1, int(L / ds))
    okno = np.convolve(nadmerna, np.ones(n), mode="same")
    vybrane: list[tuple[float, float]] = []
    for i in np.argsort(okno)[::-1]:
        if okno[i] <= 0 or len(vybrane) >= pocet:
            break
        c = s[i]
        s0, s1 = max(0.0, c - L / 2), min(osa.delka, c + L / 2)
        if any(not (s1 <= a or s0 >= b) for a, b in vybrane):
            continue
        vybrane.append((s0, s1))
    return vybrane


def rychlosti_pravidla(pr: PravidloOmezeni, navrh: NavrhoveParametry) -> list[float]:
    """Rychlosti, které se pro pravidlo zkoušejí: nejnižší dovolená, střední a (u velkého rozpětí) další."""
    v_min = min(pr.min_rychlost_kmh, navrh.rychlost_kmh - 10)
    v_stred = math.floor(((v_min + navrh.rychlost_kmh) / 2) / 10) * 10
    v = {v_stred, v_min}
    if v_stred - v_min >= 60:
        v.add(math.floor(((v_min + v_stred) / 2) / 10) * 10)
    return sorted(v, reverse=True)


def najdi_omezeni(
    zaklad: Varianta,
    koridory_xy: list[np.ndarray],
    cena_na_m: np.ndarray,
    rozliseni: float,
    navrh: NavrhoveParametry,
    cfg: Omezeni,
    navrhni: Callable[[list[tuple[float, float, float]]], object],
    vyhodnot: Callable[[object], Varianta],
    penalizace_mil: float,
    progress: Callable[[str], None] | None = None,
    vlakna: int = 1,
    hodnota_casu_mil_min: float = 0.0,
) -> tuple[Varianta, list[Usek], list[str]]:
    """Vrátí (nejlepší varianta, použité úseky se sníženou rychlostí, protokol).

    Kritérium J (cena + penalizace demolic + hodnota času) je v ``Varianta.J``; ztráta jízdní doby tedy
    snižuje přínos úseku se sníženou rychlostí. Zkoušky kandidátů běží ve vláknech.
    """
    protokol: list[str] = []
    pravidla = cfg.aktivni_pravidla()
    if not cfg.povolit or cfg.max_pocet <= 0 or not pravidla:
        return zaklad, [], protokol
    puvodni = useky_z_osy(zaklad.osa, navrh)

    ulohy = []                     # (index pravidla, okno, s0, s1, rychlost)
    pocet_oken = {}
    for ri, pr in enumerate(pravidla):
        kand = kandidati(zaklad, koridory_xy, cena_na_m, rozliseni, pr.max_delka_m)
        pocet_oken[ri] = len(kand)
        for ci, (s0, s1) in enumerate(kand):
            for v in rychlosti_pravidla(pr, navrh):
                ulohy.append((ri, ci, s0, s1, v))

    def zkus(uloha):
        ri, ci, s0, s1, v = uloha
        pr = pravidla[ri]
        if progress:
            progress(f"Zkouším snížit rychlost na {v:.0f} km/h v km {s0 / 1000:.1f}–{s1 / 1000:.1f} "
                     f"({pr.nazev}, {ci + 1}/{pocet_oken[ri]}) …")
        Rz = polomer_pro_rychlost(v, navrh)
        osa = navrhni([(s0, s1, Rz)])
        useky = useky_z_osy(osa, navrh)
        nove = [u for u in useky if not any(abs(u.s0 - z.s0) < 50 and abs(u.s1 - z.s1) < 50 for z in puvodni)]
        if not nove:
            return None
        if max(u.delka for u in nove) > pr.max_delka_m + 1:
            return (f"km {s0 / 1000:.1f}: úsek by byl delší než {pr.max_delka_m / 1000:.1f} km – zamítnuto",
                    None)
        var = vyhodnot(osa)
        dcena = zaklad.cena_mil - var.cena_mil
        ddem = zaklad.demolice - var.demolice
        dJ = zaklad.J - var.J
        # nesmí přibýt demolice; musí výrazně ušetřit peníze nebo zachránit domy (a vyplatit se i s časem)
        ok = dJ > 0 and ddem >= 0 and (dcena >= pr.min_uspora_mil or ddem >= pr.min_uspora_demolic)
        radek = (f"[{pr.nazev}] km {s0 / 1000:.1f}–{s1 / 1000:.1f}, {v:.0f} km/h: úspora {dcena:,.0f} mil. Kč, "
                 f"demolic o {ddem} méně, čas {var.jizdni_doba_s - zaklad.jizdni_doba_s:+.0f} s "
                 f"→ {'přijato' if ok else 'nevyplatí se'}").replace(",", " ")
        if not ok:
            return radek, None
        info = Usek(min(u.s0 for u in nove), max(u.s1 for u in nove), min(u.min_polomer_m for u in nove), v,
                    uspora_mil=dcena, demolic_mene=ddem, ztrata_casu_s=var.jizdni_doba_s - zaklad.jizdni_doba_s)
        return radek, (ri, ci, s0, s1, Rz, dJ, info)

    if vlakna > 1 and len(ulohy) > 1:
        with ThreadPoolExecutor(max_workers=min(vlakna, len(ulohy))) as ex:
            vysledky = list(ex.map(zkus, ulohy))
    else:
        vysledky = [zkus(u) for u in ulohy]
    nejlepsi_na_okno: dict[tuple[int, int], tuple] = {}
    for r in vysledky:
        if r is None:
            continue
        radek, ok = r
        protokol.append(radek)
        if ok is None:
            continue
        ri, ci, s0, s1, Rz, dJ, info = ok
        # vyšší rychlost má přednost, pokud dá aspoň 80 % úspory nižší
        kl = (ri, ci)
        if kl not in nejlepsi_na_okno or dJ > nejlepsi_na_okno[kl][3] / 0.8:
            nejlepsi_na_okno[kl] = (s0, s1, Rz, dJ, info, ri)

    # výběr: nejvýhodnější první, bez překryvů, v mezích počtů (celkem i po pravidlech)
    prijate: list[tuple] = []
    po_pravidlech = {i: 0 for i in range(len(pravidla))}
    for kandidat in sorted(nejlepsi_na_okno.values(), key=lambda p: -p[3]):
        s0, s1, _, _, _, ri = kandidat
        if len(prijate) >= cfg.max_pocet or po_pravidlech[ri] >= pravidla[ri].max_pocet:
            continue
        if any(not (s1 <= p[0] or s0 >= p[1]) for p in prijate):
            continue
        prijate.append(kandidat)
        po_pravidlech[ri] += 1

    while prijate:
        if progress:
            progress(f"Ověřuji kombinaci {len(prijate)} úseků se sníženou rychlostí …")
        osa = navrhni([(p[0], p[1], p[2]) for p in prijate])
        useky = useky_z_osy(osa, navrh)
        var = vyhodnot(osa)
        if (var.J < zaklad.J and var.demolice <= zaklad.demolice and len(useky) <= cfg.max_pocet
                and all(cfg.usek_povolen(u.delka, u.rychlost_kmh) for u in useky)):
            # přiřadit k výsledným úsekům úspory jednotlivých kandidátů (podle polohy)
            for u in useky:
                c = (u.s0 + u.s1) / 2
                best = min(prijate, key=lambda p: abs((p[4].s0 + p[4].s1) / 2 - c))
                u.uspora_mil, u.demolic_mene, u.ztrata_casu_s = (best[4].uspora_mil, best[4].demolic_mene,
                                                                 best[4].ztrata_casu_s)
            protokol.append(f"Použito {len(useky)} úseků: celkem úspora {zaklad.cena_mil - var.cena_mil:,.0f} mil. Kč, "
                            f"demolic o {zaklad.demolice - var.demolice} méně, jízdní doba "
                            f"{var.jizdni_doba_s - zaklad.jizdni_doba_s:+.0f} s.".replace(",", " "))
            return var, useky, protokol
        prijate.pop()  # odebrat nejslabší a zkusit znovu
    protokol.append("Žádný úsek se sníženou rychlostí se nevyplatí.")
    return zaklad, [], protokol
