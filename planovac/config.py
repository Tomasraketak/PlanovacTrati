"""Konfigurace projektu: body trasy, návrhové parametry, váhy, ceny a vozidlo.

Všechny vstupy jsou v jednom objektu :class:`Project`, který lze uložit/načíst
jako YAML (soubor ve složce ``projekty/``) a editovat v GUI.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

TYP_STANICE = "stanice"          # vlak zastavuje, okolí obce není penalizováno
TYP_ZASTAVKA = "zastávka"        # malá zastávka (kratší nástupiště, levnější) – typicky jen zastávkové vlaky
TYP_PRUJEZD = "průjezdní bod"    # trasa musí projít bodem, vlak nezastavuje
TYPY_BODU = (TYP_STANICE, TYP_ZASTAVKA, TYP_PRUJEZD)


@dataclass
class Bod:
    """Bod trasy – stanice (zastávka) nebo průjezdní bod."""

    nazev: str
    lat: float
    lon: float
    typ: str = TYP_STANICE
    max_rychlost_kmh: float | None = None   # limit rychlosti úseku od tohoto bodu k dalšímu (None = globální)

    @property
    def je_stanice(self) -> bool:
        """Zastavovací bod = stanice nebo zastávka (průjezdní bod ne)."""
        return self.typ in (TYP_STANICE, TYP_ZASTAVKA)

    @property
    def je_zastavka(self) -> bool:
        return self.typ == TYP_ZASTAVKA


@dataclass
class NavrhoveParametry:
    """Technické parametry trati."""

    rychlost_kmh: float = 200.0            # návrhová rychlost
    max_sklon_promile: float = 25.0        # max. podélný sklon (‰)
    max_sklon_stanice_promile: float = 2.0  # max. sklon v obvodu zastávky (‰)
    delka_nastupiste_m: float = 400.0      # délka přímé a vodorovné části ve stanici
    max_prodlouzeni_pct: float = 20.0      # max. prodloužení úseku proti vzdušné čáře (%)
    prevyseni_mm: float = 150.0            # max. převýšení koleje D
    nedostatek_prevyseni_mm: float = 100.0  # max. nedostatek převýšení I
    min_polomer_m: float | None = None     # ruční přepis min. poloměru (None = vypočítat)
    vyska_nasypu_max_m: float = 15.0       # nad touto výškou už jen estakáda
    hloubka_zarezu_max_m: float = 20.0     # pod touto hloubkou už jen tunel
    vyska_estakady_min_m: float = 8.0      # od této výšky smí být estakáda (volí se levnější)
    hloubka_tunelu_min_m: float = 15.0     # min. hloubka nivelety pod terénem pro ražený tunel
    min_delka_tunelu_m: float = 300.0      # kratší tunely se mění na zářez / hloubený tunel
    min_delka_estakady_m: float = 60.0
    sirka_plane_m: float = 14.0            # šířka pláně dvoukolejné trati
    sklon_svahu: float = 1.5               # sklon svahů násypu/zářezu 1:n
    polomer_stanice_m: float = 2000.0      # okruh kolem stanice bez penalizace zástavby
    delka_nastupiste_zastavky_m: float = 200.0  # přímá a vodorovná část u malé zastávky
    polomer_zastavky_m: float = 800.0      # okruh kolem zastávky bez penalizace zástavby
    max_hloubka_stanice_m: float = 15.0    # stanice/zastávka smí být až tolik metrů pod terénem
    hloubka_tunelu_pod_mestem_m: float = 12.0  # min. hloubka nivelety pod ulicemi u tunelu pod zástavbou

    def min_polomer(self) -> float:
        """Minimální poloměr oblouku R = 11,8·V² / (D + I)."""
        if self.min_polomer_m:
            return float(self.min_polomer_m)
        r = 11.8 * self.rychlost_kmh ** 2 / (self.prevyseni_mm + self.nedostatek_prevyseni_mm)
        return math.ceil(r / 50.0) * 50.0

    def min_polomer_pro(self, v_kmh: float) -> float:
        """Minimální poloměr pro sníženou rychlost ``v_kmh`` (nikdy větší než pro návrhovou rychlost)."""
        if self.min_polomer_m:
            return float(self.min_polomer_m) * min(1.0, (v_kmh / self.rychlost_kmh) ** 2)
        r = 11.8 * min(v_kmh, self.rychlost_kmh) ** 2 / (self.prevyseni_mm + self.nedostatek_prevyseni_mm)
        return math.ceil(r / 50.0) * 50.0

    def doporuceny_polomer(self) -> float:
        """Doporučený (komfortní) poloměr – D = 100 mm, I = 60 mm."""
        r = 11.8 * self.rychlost_kmh ** 2 / 160.0
        return max(self.min_polomer(), math.ceil(r / 100.0) * 100.0)

    def min_polomer_vertikal(self) -> float:
        """Minimální poloměr zakružovacího oblouku Rv ≈ 0,35·V²."""
        return max(2000.0, 0.35 * self.rychlost_kmh ** 2)


@dataclass
class Vahy:
    """Relativní váhy optimalizace koridoru (1.0 = výchozí, 0 = ignorovat)."""

    obce: float = 1.0          # vyhýbání se zástavbě obcí bez zastávky
    budovy: float = 1.0        # vyhýbání se jednotlivým budovám (samoty, chaty)
    teren: float = 1.0         # členitý terén (=> tunely, estakády, velké zemní práce)
    voda: float = 1.0          # vodní plochy a řeky (=> mosty)
    chranena_uzemi: float = 1.0  # CHKO, NP, rezervace, Natura 2000
    delka: float = 1.0         # tlak na co nejkratší trasu
    hodnota_casu_mil_min: float = 500.0    # kolik mil. Kč „vyplatí“ 1 minuta jízdní doby (rozhodování
    #                                        obchvat × tunel, úseky se sníženou rychlostí) – nejde do rozpočtu
    tunel_pod_mestem: bool = True          # zvažovat tunel pod městem místo obchvatu
    penalizace_demolice_mil: float = 40.0  # společenská „cena“ zbourání domu – jen pro optimalizaci,
    #                                        do rozpočtu se nezapočítává (násobí se vahou „budovy“)

    def demolice_optimalizace_mil(self, ceny: "Ceny") -> float:
        """Cena jedné demolice [mil. Kč], se kterou počítá optimalizace (reálná + penalizace)."""
        return ceny.demolice_mil_budova + self.penalizace_demolice_mil * self.budovy


@dataclass
class PravidloOmezeni:
    """Jedno pravidlo: „na úseku do ``max_delka_m`` smí rychlost klesnout až na ``min_rychlost_kmh``,
    ušetří-li to aspoň ``min_uspora_mil`` mil. Kč nebo zachrání-li aspoň ``min_uspora_demolic`` domů“."""

    nazev: str = "Pravidlo"
    aktivni: bool = True
    max_delka_m: float = 3000.0        # nejdelší úsek se sníženou rychlostí
    min_rychlost_kmh: float = 120.0    # nejnižší dovolená rychlost v úseku
    max_pocet: int = 4                 # nejvýše tolik úseků tohoto pravidla na celé trase
    min_uspora_mil: float = 300.0      # úsek se použije, ušetří-li alespoň tolik mil. Kč …
    min_uspora_demolic: int = 5        # … nebo zachrání-li alespoň tolik domů


def vychozi_pravidla() -> list[PravidloOmezeni]:
    return [
        PravidloOmezeni("Mírné snížení (do 3 km, ≥ 120 km/h)", True, 3000.0, 120.0, 4, 300.0, 5),
        PravidloOmezeni("Silné snížení (do 2 km, až 80 km/h)", True, 2000.0, 80.0, 2, 500.0, 10),
    ]


@dataclass
class Omezeni:
    """Úseky se sníženou rychlostí, které smí optimalizace použít, když výrazně ušetří.

    Pravidel může být libovolně mnoho (každé má vlastní nejdelší úsek, nejnižší rychlost, počet a prahy úspory).
    """

    povolit: bool = True
    max_pocet: int = 6                 # nejvýše tolik úseků se sníženou rychlostí celkem (všechna pravidla)
    pravidla: list[PravidloOmezeni] = field(default_factory=vychozi_pravidla)

    def aktivni_pravidla(self) -> list[PravidloOmezeni]:
        return [r for r in self.pravidla if r.aktivni and r.max_pocet > 0 and r.max_delka_m > 0]

    @property
    def max_delka_m(self) -> float:
        """Nejdelší povolený úsek ze všech aktivních pravidel."""
        return max((r.max_delka_m for r in self.aktivni_pravidla()), default=0.0)

    def usek_povolen(self, delka_m: float, rychlost_kmh: float, tol: float = 1.0) -> bool:
        """Vyhovuje úsek (délka, rychlost) alespoň jednomu aktivnímu pravidlu?"""
        return any(delka_m <= r.max_delka_m + tol and rychlost_kmh >= r.min_rychlost_kmh - 5.0
                   for r in self.aktivni_pravidla())


@dataclass
class Ceny:
    """Jednotkové ceny (Kč, cenová úroveň cca 2025, orientační)."""

    trat_zaklad_mil_km: float = 150.0      # železniční svršek, pražcové podloží, odvodnění
    technologie_mil_km: float = 110.0      # trakce 25 kV, ETCS L2, GSM-R/FRMCS, napájení
    nasyp_kc_m3: float = 450.0
    vykop_kc_m3: float = 550.0
    estakada_mil_km: float = 650.0         # do výšky 20 m
    estakada_prirazka_pct_m: float = 2.0   # přirážka za každý metr výšky nad 20 m
    most_mil_km: float = 900.0             # mosty přes vodní toky a nádrže
    tunel_mil_km: float = 1300.0           # ražený dvoukolejný tunel
    portal_mil: float = 150.0              # za každý tunel (2 portály)
    hloubeny_tunel_mil_km: float = 900.0   # hloubený tunel / galerie
    krizeni_silnice_mil: float = 60.0      # nadjezd / podjezd
    krizeni_zeleznice_mil: float = 120.0
    stanice_mil: float = 1200.0            # mezilehlá stanice
    zastavka_mil: float = 250.0            # malá zastávka (jen zastávkové vlaky)
    podzemni_stanice_mil_m: float = 40.0   # příplatek za každý metr hloubky stanice pod terénem (zastávka ×0,25)
    zastavba_prirazka_mil_km: float = 1500.0  # příplatek za vedení po povrchu zástavbou (vykoupení, rozdělení
    #                                           území) – tunel pod městem se tak vyplatí i bez výškové potřeby
    rychlost_razeni_km_rok: float = 0.8    # orientační postup ražby (jen odhad doby výstavby v souhrnu)
    koncova_stanice_mil: float = 2500.0    # napojení na uzel / koncová stanice
    demolice_mil_budova: float = 8.0       # výkup + demolice jedné budovy
    pozemky_kc_m2: float = 300.0
    projekt_pct: float = 10.0              # projekce, inženýring, průzkumy
    rezerva_pct: float = 20.0              # rezerva na nepředvídané náklady


@dataclass
class Soubeh:
    """Slevy za souběh se stávající železnicí a s hlavními silnicemi."""

    povolit: bool = True
    zeleznice_tolerance_m: float = 4.0     # osa do ±4 m od stávající koleje
    zeleznice_sleva_pct: float = 50.0      # využití tělesa a pozemků; bez penalizací
    silnice_vzdalenost_m: float = 10.0     # osa do 10 m od okraje vozovky
    silnice_sleva_pct: float = 25.0
    silnice_tridy: str = "motorway,trunk,primary"  # dálnice, silnice pro motorová vozidla, I. třída
    pritahovat: bool = True                # zvýhodnit souběh už v nákladové mapě (rastr ±4 m nezaručí;
    #                                        může trasu i zhoršit) – sleva na výsledné ose platí vždy


# poloviční šířka vozovky [m] podle třídy OSM (dálnice: jeden směrový pás bývá v OSM samostatná linie)
POLOVICNI_SIRKA_SILNICE = {"motorway": 6.0, "trunk": 6.0, "primary": 4.0, "secondary": 3.5}


@dataclass
class Koeficienty:
    """Koeficienty nákladové mapy (relativní „cena za metr“, 1 = trať v otevřené krajině)."""

    pen_zastavba_uvnitr: float = 40.0   # uvnitř zástavby obce
    pen_zastavba_pas: float = 8.0       # pás 300 m kolem zástavby (klesá s odstupem)
    pen_budovy_u_stanic: float = 1.0       # podíl penalizace budov platný i v okruhu stanic (0 = u stanic se domy nepenalizují)
    pen_budovy: float = 10.0            # násobek hustoty budov (samoty, chaty)
    pen_teren_sklon: float = 1.5        # strmý terén vůči max. sklonu trati
    pen_teren_relief: float = 2.0       # lokální převýšení v okně 600 m
    pen_voda: float = 6.0               # vodní plocha
    pen_reka: float = 1.5               # vodní tok
    pen_chranena_np: float = 12.0       # NP, NPR
    pen_chranena_rez: float = 4.0       # rezervace, Natura 2000
    pen_chranena_chko: float = 0.8      # CHKO a ostatní
    pen_soubeh_koleje_zbytek: float = 0.3  # zbývající podíl penalizací podél sledovatelné koleje

    # tunel pod městem: kolik „jednotek“ stojí 1 m tunelu navíc oproti povrchové trati (nastaví se z cen)
    tunel_ekvivalent: float = 0.0       # 0 = automaticky z cen (tunel ÷ trať v úrovni terénu)
    demolice_nasobek: float = 3.0           # zpřesnění osy: váha demolice (× společenská cena domu) při odtlačování osy od budov
    demolice_polomer_m: float = 15.0        # budova do této vzdálenosti od osy se při zpřesnění osy počítá jako zasažená
    tunel_min_sirka_mesta_m: float = 800.0  # užší zástavba se neobtunelovává (rampy při sklonu nevyjdou)


@dataclass
class Linka:
    """Způsob zastavování vlaku. Prázdné ``zastavky`` = expres; ``vsechny`` = zastávkový."""

    nazev: str
    zastavky: list[str] = field(default_factory=list)
    vsechny: bool = False

    def zastavuje(self, nazev_stanice: str) -> bool:
        return self.vsechny or nazev_stanice in self.zastavky


def vychozi_linky() -> list[Linka]:
    return [Linka("Zastávkový (všechny stanice)", [], True),
            Linka("Expres (bez zastavení)", []),
            Linka("Rychlík (vybrané stanice)", [])]


# Předvolby vlaků – orientační veřejně dostupné parametry (hmotnost bez cestujících, trvalý výkon).
# Davisova rovnice: odpor R = A + B·v + C·v² [kN], v v km/h.
VLAKY: dict[str, dict] = {
    "RegioPanter (ČD 640, 3 vozy)": dict(
        hmotnost_t=156.0, vykon_kw=2040.0, max_tazna_sila_kn=180.0, max_rychlost_kmh=160.0,
        max_zrychleni_ms2=1.0, brzdne_zpomaleni_ms2=0.8, odpor_a_kn=1.6, odpor_b_kn=0.016, odpor_c_kn=0.00030,
        nedostatek_prevyseni_mm=0.0),
    "Railjet (Taurus + 7 vozů)": dict(
        hmotnost_t=440.0, vykon_kw=6400.0, max_tazna_sila_kn=300.0, max_rychlost_kmh=230.0,
        max_zrychleni_ms2=0.45, brzdne_zpomaleni_ms2=0.7, odpor_a_kn=4.5, odpor_b_kn=0.040, odpor_c_kn=0.00075,
        nedostatek_prevyseni_mm=0.0),
    "ComfortJet (Škoda 109E + 7 vozů)": dict(
        hmotnost_t=430.0, vykon_kw=6400.0, max_tazna_sila_kn=270.0, max_rychlost_kmh=200.0,
        max_zrychleni_ms2=0.45, brzdne_zpomaleni_ms2=0.7, odpor_a_kn=4.4, odpor_b_kn=0.038, odpor_c_kn=0.00072,
        nedostatek_prevyseni_mm=0.0),
    "Pendolino (ČD 680, naklápěcí)": dict(
        hmotnost_t=385.0, vykon_kw=4000.0, max_tazna_sila_kn=210.0, max_rychlost_kmh=230.0,
        max_zrychleni_ms2=0.5, brzdne_zpomaleni_ms2=0.7, odpor_a_kn=3.5, odpor_b_kn=0.030, odpor_c_kn=0.00060,
        nedostatek_prevyseni_mm=270.0),
    "ICE 3 (8 vozů)": dict(
        hmotnost_t=435.0, vykon_kw=8000.0, max_tazna_sila_kn=300.0, max_rychlost_kmh=320.0,
        max_zrychleni_ms2=0.6, brzdne_zpomaleni_ms2=0.7, odpor_a_kn=4.0, odpor_b_kn=0.035, odpor_c_kn=0.00050,
        nedostatek_prevyseni_mm=0.0),
    "TGV Euroduplex (2+8)": dict(
        hmotnost_t=424.0, vykon_kw=9280.0, max_tazna_sila_kn=220.0, max_rychlost_kmh=320.0,
        max_zrychleni_ms2=0.5, brzdne_zpomaleni_ms2=0.7, odpor_a_kn=3.5, odpor_b_kn=0.030, odpor_c_kn=0.00055,
        nedostatek_prevyseni_mm=0.0),
}
VLAK_VLASTNI = "vlastní"
VLAK_VYCHOZI = "ICE 3 (8 vozů)"


@dataclass
class Vlak:
    """Parametry vozidla pro simulaci jízdy (výchozí: ICE 3)."""

    nazev: str = VLAK_VYCHOZI          # název předvolby z VLAKY, nebo vlastní název
    hmotnost_t: float = 435.0
    vykon_kw: float = 8000.0
    max_tazna_sila_kn: float = 300.0
    max_zrychleni_ms2: float = 0.6
    brzdne_zpomaleni_ms2: float = 0.7
    max_rychlost_kmh: float = 320.0
    odpor_a_kn: float = 4.0        # Davisova rovnice R = A + B·v + C·v²  (v v km/h)
    odpor_b_kn: float = 0.035
    odpor_c_kn: float = 0.00050
    nedostatek_prevyseni_mm: float = 0.0  # 0 = podle návrhu trati; naklápěcí vlaky víc (rychleji v obloucích)
    pobyt_stanice_s: float = 90.0
    rezerva_pct: float = 7.0       # přirážka k jízdní době (provozní rezerva)

    @classmethod
    def z_predvolby(cls, nazev: str, **kw) -> "Vlak":
        return cls(nazev=nazev, **{**VLAKY[nazev], **kw})

    def nastav_predvolbu(self, nazev: str) -> None:
        self.nazev = nazev
        for k, v in VLAKY[nazev].items():
            setattr(self, k, v)


@dataclass
class Vypocet:
    """Nastavení výpočtu."""

    rozliseni_m: float = 20.0          # velikost buňky rastru (100 = rychle, 20 = detailně)
    max_bunek_mil: float = 80.0        # pojistka: větší rastr se automaticky zhrubí (32 GB RAM ≈ 80 mil. buněk)
    vlakna: int = 0                    # počet vláken/procesů (0 = všechna dostupná)
    demo: bool = False                 # syntetický terén bez stahování dat
    stahovat_budovy: bool = False      # budovy v celé oblasti (velmi pomalé); jinak jen v pásu kolem trasy
    chranena_uzemi: bool = True        # stahovat chráněná území
    zpresneni_osy: bool = True         # po vložení oblouků odtlačit osu od budov (lokální posun vrcholů)
    zdroj_dat: str = "auto"            # auto = Overpass → Overture Maps; overpass; overture
    vlastni_dem: str = ""              # cesta k vlastnímu GeoTIFF (např. DMR 5G), jinak Copernicus
    okraj_km: float = 5.0              # okraj oblasti kolem elipsy přípustných tras
    tolerance_zjednoduseni_m: float = 150.0  # tolerance Douglas–Peucker pro vrcholy oblouků


def _omezeni_z_dict(d: dict | None) -> Omezeni:
    """Načte ``Omezeni``; starší projekty (jedno pravidlo v hlavní úrovni) se převedou na seznam pravidel."""
    d = dict(d or {})
    names_r = {f.name for f in fields(PravidloOmezeni)}
    if "pravidla" in d and d["pravidla"] is not None:
        pr = [PravidloOmezeni(**{k: v for k, v in (r or {}).items() if k in names_r}) for r in d["pravidla"]]
    else:
        pr = vychozi_pravidla()
        for k in ("max_delka_m", "min_rychlost_kmh", "min_uspora_mil", "min_uspora_demolic"):
            if k in d:
                setattr(pr[0], k, d[k])
        if "max_pocet" in d:
            pr[0].max_pocet = int(d["max_pocet"])
    return Omezeni(povolit=bool(d.get("povolit", True)), max_pocet=int(d.get("max_pocet", 6)) if "pravidla" in d
                   else 6, pravidla=pr)


@dataclass
class Project:
    """Celý projekt trati."""

    nazev: str = "Nová trať"
    popis: str = ""
    body: list[Bod] = field(default_factory=list)
    navrh: NavrhoveParametry = field(default_factory=NavrhoveParametry)
    vahy: Vahy = field(default_factory=Vahy)
    ceny: Ceny = field(default_factory=Ceny)
    vlak: Vlak = field(default_factory=Vlak)
    omezeni: Omezeni = field(default_factory=Omezeni)
    soubeh: Soubeh = field(default_factory=Soubeh)
    linky: list[Linka] = field(default_factory=vychozi_linky)
    koef: Koeficienty = field(default_factory=Koeficienty)
    vypocet: Vypocet = field(default_factory=Vypocet)

    # ------------------------------------------------------------------ I/O
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Project":
        d = dict(d or {})

        def build(dc, data):
            data = data or {}
            names = {f.name for f in fields(dc)}
            return dc(**{k: v for k, v in data.items() if k in names})

        body = [build(Bod, b) for b in d.get("body", [])]
        vlak_d = dict(d.get("vlak") or {})
        if "pobyt_stanice_min" in vlak_d and "pobyt_stanice_s" not in vlak_d:  # starší projekty
            vlak_d["pobyt_stanice_s"] = float(vlak_d.pop("pobyt_stanice_min")) * 60
        return cls(
            nazev=d.get("nazev", "Nová trať"),
            popis=d.get("popis", ""),
            body=body,
            navrh=build(NavrhoveParametry, d.get("navrh")),
            vahy=build(Vahy, d.get("vahy")),
            ceny=build(Ceny, d.get("ceny")),
            vlak=build(Vlak, vlak_d),
            omezeni=_omezeni_z_dict(d.get("omezeni")),
            soubeh=build(Soubeh, d.get("soubeh")),
            koef=build(Koeficienty, d.get("koef")),
            linky=[build(Linka, x) for x in d["linky"]] if d.get("linky") else vychozi_linky(),
            vypocet=build(Vypocet, d.get("vypocet")),
        )

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False)

    @classmethod
    def from_yaml(cls, text: str) -> "Project":
        return cls.from_dict(yaml.safe_load(text))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_yaml(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        return cls.from_yaml(Path(path).read_text(encoding="utf-8"))

    # ------------------------------------------------------------ validace
    def validate(self) -> list[str]:
        """Vrátí seznam chyb (prázdný = v pořádku)."""
        err = []
        if len(self.body) < 2:
            err.append("Trasa potřebuje alespoň 2 body (start a cíl).")
        for i, b in enumerate(self.body):
            if not (-90 <= b.lat <= 90 and -180 <= b.lon <= 180):
                err.append(f"Bod {i + 1} ({b.nazev}) má neplatné souřadnice.")
            if b.typ not in TYPY_BODU:
                err.append(f"Bod {i + 1} ({b.nazev}) má neznámý typ '{b.typ}'.")
            if b.max_rychlost_kmh is not None and not (40 <= b.max_rychlost_kmh <= self.navrh.rychlost_kmh):
                err.append(f"Limit rychlosti úseku za bodem {i + 1} ({b.nazev}) musí být 40–{self.navrh.rychlost_kmh:.0f} km/h.")
        if self.body and self.body[0].typ != TYP_STANICE:
            err.append("První bod musí být stanice.")
        if self.body and self.body[-1].typ != TYP_STANICE:
            err.append("Poslední bod musí být stanice.")
        n = self.navrh
        if not 40 <= n.rychlost_kmh <= 400:
            err.append("Návrhová rychlost musí být 40–400 km/h.")
        if not 1 <= n.max_sklon_promile <= 60:
            err.append("Max. sklon musí být 1–60 ‰.")
        if not 0 < n.max_prodlouzeni_pct <= 200:
            err.append("Max. prodloužení musí být 0–200 %.")
        if self.vypocet.rozliseni_m < 10:
            err.append("Rozlišení musí být alespoň 10 m.")
        return err
