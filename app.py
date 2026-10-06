"""Plánovač tratí – webové GUI (Streamlit).

Spuštění:  streamlit run app.py   (nebo run.bat / run.sh)
"""
from __future__ import annotations

import copy
import io
import time
import zipfile
from pathlib import Path

import folium
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

from planovac import __version__
from planovac.config import TYP_PRUJEZD, TYP_STANICE, TYPY_BODU, Bod, Project
from planovac.geo import to_xy
from planovac.paths import OUTPUT_DIR, PROJECTS_DIR, ROOT

st.set_page_config(page_title="Plánovač tratí", page_icon="🚄", layout="wide",
                   menu_items={"About": f"Plánovač tratí {__version__} – návrh osy VRT nad výškovým modelem a OSM."})

CSS = """
<style>
.block-container {padding-top: 1.6rem; padding-bottom: 2rem;}
.hero {background: linear-gradient(120deg,#1e3c72 0%,#2a5298 60%,#3a7bd5 100%); color: white;
       padding: 18px 26px; border-radius: 14px; margin-bottom: 14px;}
.hero h1 {color: white; margin: 0; font-size: 1.9rem;}
.hero p {margin: 4px 0 0; opacity: .88;}
div[data-testid="stMetric"] {background: var(--secondary-background-color); border-radius: 12px; padding: 10px 14px;}
div[data-testid="stMetricValue"] {font-size: 1.55rem;}
.small-note {font-size: .85rem; opacity: .75;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# =============================================================================== stav

def _default_project() -> Project:
    p = PROJECTS_DIR / "cb_jh_jihlava.yaml"
    return Project.load(p) if p.exists() else Project(body=[Bod("Start", 48.97, 14.49), Bod("Cíl", 49.41, 15.60)])


def _init_state():
    ss = st.session_state
    if "projekt" not in ss:
        ss.projekt = _default_project()
    ss.setdefault("vysledek", None)
    ss.setdefault("body_ver", 0)
    ss.setdefault("widget_ver", 0)
    ss.setdefault("hledani", [])
    ss.setdefault("posledni_klik", None)


def _set_project(p: Project):
    st.session_state.projekt = p
    st.session_state.vysledek = None
    st.session_state.body_ver += 1
    st.session_state.widget_ver += 1


_init_state()
P: Project = st.session_state.projekt
WV = st.session_state.widget_ver


def w(obj, attr, label, kind="number", **kw):
    """Widget svázaný s atributem dataclassu (hodnota se rovnou zapíše zpět)."""
    key = f"w{WV}_{type(obj).__name__}_{attr}"
    val = getattr(obj, attr)
    if kind == "slider":
        new = st.slider(label, value=type(kw.get("min_value", val))(val), key=key, **kw)
    elif kind == "check":
        new = st.checkbox(label, value=bool(val), key=key, **kw)
    elif kind == "text":
        new = st.text_input(label, value=str(val), key=key, **kw)
    elif kind == "select":
        opts = kw.pop("options")
        new = st.selectbox(label, opts, index=opts.index(val) if val in opts else 0, key=key, **kw)
    else:
        new = st.number_input(label, value=float(val), key=key, **kw)
    setattr(obj, attr, new)
    return new


# ============================================================================ sidebar

with st.sidebar:
    st.markdown("## 🚄 Plánovač tratí")
    st.caption(f"verze {__version__}")

    with st.expander("📁 Projekt", expanded=True):
        soubory = sorted(PROJECTS_DIR.glob("*.yaml"))
        if soubory:
            vyber = st.selectbox("Uložené projekty", soubory, format_func=lambda p: p.stem)
            if st.button("Načíst projekt", width="stretch"):
                _set_project(Project.load(vyber))
                st.rerun()
        up = st.file_uploader("…nebo nahrát YAML", type=["yaml", "yml"])
        if up is not None and st.button("Načíst nahraný soubor", width="stretch"):
            _set_project(Project.from_yaml(up.getvalue().decode("utf-8")))
            st.rerun()
        P.nazev = st.text_input("Název projektu", P.nazev, key=f"w{WV}_nazev")
        nazev_souboru = st.text_input("Uložit jako (projekty/…yaml)", value=Path(P.nazev).stem.lower()
                                      .replace(" ", "_").replace("–", "-")[:40], key=f"w{WV}_soubor")
        c1, c2 = st.columns(2)
        if c1.button("💾 Uložit", width="stretch"):
            PROJECTS_DIR.mkdir(exist_ok=True)
            P.save(PROJECTS_DIR / f"{nazev_souboru}.yaml")
            st.toast(f"Uloženo do projekty/{nazev_souboru}.yaml", icon="💾")
        c2.download_button("⬇️ YAML", P.to_yaml().encode("utf-8"), file_name=f"{nazev_souboru}.yaml",
                           mime="text/yaml", width="stretch")

    spustit = st.button("🚀 Navrhnout trať", type="primary", width="stretch")

    with st.expander("⚙️ Návrhové parametry", expanded=True):
        n = P.navrh
        w(n, "rychlost_kmh", "Návrhová rychlost [km/h]", "slider", min_value=80.0, max_value=360.0, step=10.0, format="%.0f")
        w(n, "max_sklon_promile", "Max. podélný sklon [‰]", "slider", min_value=5.0, max_value=40.0, step=0.5, format="%.1f",
          help="VRT pro osobní dopravu běžně 25–35 ‰, smíšený provoz 12,5–18 ‰.")
        w(n, "max_prodlouzeni_pct", "Max. prodloužení proti vzdušné čáře [%]", "slider", min_value=1.0,
          max_value=60.0, step=1.0, format="%.0f", help="Platí pro každý úsek mezi sousedními body trasy.")
        st.caption(f"➡️ min. poloměr oblouku **{n.min_polomer():,.0f} m**, doporučený "
                   f"**{n.doporuceny_polomer():,.0f} m**".replace(",", " "))
        with st.popover("Pokročilé", width="stretch"):
            w(n, "max_sklon_stanice_promile", "Max. sklon ve stanici [‰]", min_value=0.0, max_value=10.0, step=0.5)
            w(n, "delka_nastupiste_m", "Délka nástupiště (přímá, vodorovná) [m]", min_value=0.0, max_value=1000.0, step=50.0)
            w(n, "prevyseni_mm", "Převýšení D [mm]", min_value=0.0, max_value=180.0, step=5.0)
            w(n, "nedostatek_prevyseni_mm", "Nedostatek převýšení I [mm]", min_value=0.0, max_value=180.0, step=5.0)
            w(n, "vyska_nasypu_max_m", "Max. výška násypu [m]", min_value=3.0, max_value=40.0, step=1.0)
            w(n, "hloubka_zarezu_max_m", "Max. hloubka zářezu [m]", min_value=3.0, max_value=40.0, step=1.0)
            w(n, "vyska_estakady_min_m", "Estakáda od výšky [m]", min_value=3.0, max_value=30.0, step=1.0)
            w(n, "hloubka_tunelu_min_m", "Ražený tunel od hloubky [m]", min_value=5.0, max_value=40.0, step=1.0)
            w(n, "min_delka_tunelu_m", "Min. délka raženého tunelu [m]", min_value=0.0, max_value=2000.0, step=50.0)
            w(n, "polomer_stanice_m", "Okruh kolem stanice bez penalizace zástavby [m]", min_value=0.0,
              max_value=6000.0, step=250.0)

    with st.expander("⚖️ Priority optimalizace"):
        st.caption("1 = výchozí důležitost, 0 = ignorovat, 5 = velmi důležité")
        v = P.vahy
        w(v, "obce", "🏘️ Vyhýbat se obcím bez zastávky", "slider", min_value=0.0, max_value=5.0, step=0.25, format="%.2f")
        w(v, "budovy", "🏠 Nebourat domy (samoty, chaty)", "slider", min_value=0.0, max_value=5.0, step=0.25, format="%.2f")
        w(v, "teren", "⛰️ Šetřit tunely, estakády a zemní práce", "slider", min_value=0.0, max_value=5.0, step=0.25, format="%.2f")
        w(v, "voda", "🌊 Vyhýbat se vodním plochám", "slider", min_value=0.0, max_value=5.0, step=0.25, format="%.2f")
        w(v, "chranena_uzemi", "🌲 Šetřit chráněná území", "slider", min_value=0.0, max_value=5.0, step=0.25, format="%.2f")
        w(v, "delka", "📏 Co nejkratší trasa", "slider", min_value=0.1, max_value=5.0, step=0.1, format="%.1f")

    with st.expander("💰 Jednotkové ceny"):
        c = P.ceny
        st.caption("mil. Kč, není-li uvedeno jinak (cenová úroveň ~2025)")
        w(c, "trat_zaklad_mil_km", "Svršek + spodek [mil./km]", min_value=0.0, step=10.0)
        w(c, "technologie_mil_km", "Trakce + zabezpečení [mil./km]", min_value=0.0, step=10.0)
        w(c, "tunel_mil_km", "Ražený tunel [mil./km]", min_value=0.0, step=50.0)
        w(c, "portal_mil", "Portály tunelu [mil./tunel]", min_value=0.0, step=10.0)
        w(c, "hloubeny_tunel_mil_km", "Hloubený tunel [mil./km]", min_value=0.0, step=50.0)
        w(c, "estakada_mil_km", "Estakáda [mil./km]", min_value=0.0, step=25.0)
        w(c, "most_mil_km", "Most přes vodu [mil./km]", min_value=0.0, step=25.0)
        w(c, "nasyp_kc_m3", "Násyp [Kč/m³]", min_value=0.0, step=25.0)
        w(c, "vykop_kc_m3", "Výkop [Kč/m³]", min_value=0.0, step=25.0)
        w(c, "krizeni_silnice_mil", "Křížení silnice [mil./ks]", min_value=0.0, step=5.0)
        w(c, "krizeni_zeleznice_mil", "Křížení železnice [mil./ks]", min_value=0.0, step=5.0)
        w(c, "stanice_mil", "Mezilehlá stanice [mil.]", min_value=0.0, step=50.0)
        w(c, "koncova_stanice_mil", "Koncová stanice / uzel [mil.]", min_value=0.0, step=100.0)
        w(c, "demolice_mil_budova", "Výkup + demolice budovy [mil./ks]", min_value=0.0, step=0.5)
        w(c, "pozemky_kc_m2", "Pozemky [Kč/m²]", min_value=0.0, step=25.0)
        w(c, "projekt_pct", "Projekce a inženýring [%]", min_value=0.0, max_value=50.0, step=1.0)
        w(c, "rezerva_pct", "Rezerva [%]", min_value=0.0, max_value=100.0, step=5.0)

    with st.expander("🚆 Vlak a jízdní doby"):
        t = P.vlak
        w(t, "nazev", "Vozidlo", "text")
        w(t, "hmotnost_t", "Hmotnost [t]", min_value=50.0, step=10.0)
        w(t, "vykon_kw", "Výkon [kW]", min_value=500.0, step=100.0)
        w(t, "max_tazna_sila_kn", "Max. tažná síla [kN]", min_value=50.0, step=10.0)
        w(t, "max_rychlost_kmh", "Max. rychlost vozidla [km/h]", min_value=60.0, step=10.0)
        w(t, "max_zrychleni_ms2", "Max. zrychlení [m/s²]", min_value=0.1, max_value=2.0, step=0.05)
        w(t, "brzdne_zpomaleni_ms2", "Provozní brzdění [m/s²]", min_value=0.1, max_value=2.0, step=0.05)
        w(t, "pobyt_stanice_min", "Pobyt ve stanici [min]", min_value=0.0, max_value=15.0, step=0.5)
        w(t, "rezerva_pct", "Přirážka k jízdní době [%]", min_value=0.0, max_value=30.0, step=1.0)

    with st.expander("🖥️ Výpočet a data"):
        vy = P.vypocet
        w(vy, "rozliseni_m", "Rozlišení rastru [m]", "select", options=[100.0, 75.0, 50.0, 35.0, 25.0],
          help="100 m = rychlý náhled, 50 m = doporučeno, 25 m = detail (pomalé)")
        w(vy, "demo", "Demo režim (syntetický terén, bez internetu)", "check")
        w(vy, "stahovat_budovy", "Stahovat budovy v celé oblasti (velmi pomalé)", "check",
          help="Vypnuto: budovy se stáhnou v pásu 1,2 km kolem první varianty trasy a návrh se zopakuje – "
               "rychlejší a obvykle stejně dobré.")
        w(vy, "chranena_uzemi", "Stahovat chráněná území", "check")
        w(vy, "okraj_km", "Okraj oblasti [km]", min_value=0.0, max_value=30.0, step=1.0)
        w(vy, "tolerance_zjednoduseni_m", "Tolerance zjednodušení osy [m]", min_value=20.0, max_value=1000.0, step=10.0)
        w(vy, "vlastni_dem", "Vlastní DEM (cesta ke GeoTIFF, nepovinné)", "text")

    st.markdown('<p class="small-note">Data: Copernicus DEM GLO-30, © OpenStreetMap. '
                'Výsledky jsou orientační studie.</p>', unsafe_allow_html=True)


# ============================================================================= hlavička

st.markdown(f"""<div class="hero"><h1>🚄 {P.nazev}</h1>
<p>Automatický návrh osy trati nad výškovým modelem a mapou – {P.navrh.rychlost_kmh:.0f} km/h ·
max. sklon {P.navrh.max_sklon_promile:.0f} ‰ · prodloužení max. {P.navrh.max_prodlouzeni_pct:.0f} %</p></div>""",
            unsafe_allow_html=True)


# =============================================================================== výpočet

if spustit:
    chyby = P.validate()
    if chyby:
        for ch in chyby:
            st.error(ch)
    else:
        from planovac.pipeline import run_project

        bar = st.progress(0.0, text="Začínám …")
        with st.status("Navrhuji trať …", expanded=True) as status:
            last = {"msg": ""}

            def cb(frac, msg):
                bar.progress(min(max(frac, 0.0), 1.0), text=msg)
                if msg != last["msg"]:
                    status.write(msg)
                    last["msg"] = msg

            try:
                t0 = time.time()
                res = run_project(copy.deepcopy(P), cb)
                st.session_state.vysledek = res
                status.update(label=f"Hotovo za {time.time() - t0:.0f} s ✅", state="complete", expanded=False)
            except Exception as e:  # zobrazit uživateli
                status.update(label="Výpočet selhal ❌", state="error")
                st.exception(e)
        bar.empty()

R = st.session_state.vysledek

tabs = st.tabs(["🗺️ Trasa a zastávky", "🚄 Výsledek", "📈 Profil a rychlost", "🏗️ Stavby",
                "💰 Rozpočet", "⏱️ Jízdní doby", "⬇️ Export", "❓ Nápověda"])


# ========================================================================= tab: zadání

with tabs[0]:
    left, right = st.columns([3, 2], gap="medium")
    with left:
        st.markdown("**Klikněte do mapy** na místo nové stanice nebo průjezdního bodu.")
        if P.body:
            center = [float(np.mean([b.lat for b in P.body])), float(np.mean([b.lon for b in P.body]))]
        else:
            center = [49.8, 15.5]
        m = folium.Map(location=center, zoom_start=8, tiles=None, control_scale=True)
        folium.TileLayer("OpenStreetMap", name="Mapa OSM").add_to(m)
        folium.TileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", name="Topografická",
                         attr="© OpenTopoMap, © OpenStreetMap", max_zoom=17, show=False).add_to(m)
        if len(P.body) >= 2:
            folium.PolyLine([[b.lat, b.lon] for b in P.body], color="#555", weight=2, dash_array="8 8").add_to(m)
        if R is not None and R.project.body == P.body:
            from planovac.geo import xy_array_to_latlon

            folium.PolyLine(xy_array_to_latlon(R.osa.xy[::5]), color="#c0392b", weight=4,
                            tooltip="navržená trať").add_to(m)
        for i, b in enumerate(P.body, 1):
            color = "#1e3c72" if b.je_stanice else "#f39c12"
            folium.Marker([b.lat, b.lon], tooltip=f"{i}. {b.nazev} ({b.typ})", icon=folium.DivIcon(
                html=f'<div style="background:{color};color:#fff;border:2px solid #fff;border-radius:50%;width:26px;'
                     f'height:26px;line-height:22px;text-align:center;font:700 13px system-ui;box-shadow:0 1px 4px '
                     f'rgba(0,0,0,.5);transform:translate(-13px,-13px)">{i}</div>')).add_to(m)
        if st.session_state.posledni_klik:
            folium.CircleMarker(st.session_state.posledni_klik, radius=8, color="#e74c3c", fill=True).add_to(m)
        folium.LayerControl(collapsed=True).add_to(m)
        if len(P.body) >= 2:
            m.fit_bounds([[min(b.lat for b in P.body), min(b.lon for b in P.body)],
                          [max(b.lat for b in P.body), max(b.lon for b in P.body)]], padding=(30, 30))
        out = st_folium(m, height=560, use_container_width=True, returned_objects=["last_clicked"],
                        key=f"mapa_vstup_{st.session_state.body_ver}")
        if out and out.get("last_clicked"):
            lc = out["last_clicked"]
            klik = [round(lc["lat"], 5), round(lc["lng"], 5)]
            if klik != st.session_state.posledni_klik:
                st.session_state.posledni_klik = klik
                st.rerun()

    with right:
        if st.session_state.posledni_klik:
            lat, lon = st.session_state.posledni_klik
            with st.container(border=True):
                st.markdown(f"📍 **Vybrané místo:** {lat:.5f}, {lon:.5f}")
                c1, c2 = st.columns(2)
                nazev = c1.text_input("Název", value=f"Bod {len(P.body) + 1}", key="novy_nazev")
                typ = c2.selectbox("Typ", TYPY_BODU, key="novy_typ")
                moznosti = ["na konec"] + [f"před {i + 1}. {b.nazev}" for i, b in enumerate(P.body)]
                kam = st.selectbox("Vložit", moznosti, index=max(len(moznosti) - 1, 0) if len(P.body) >= 2 else 0,
                                   key="novy_kam")
                if st.button("➕ Přidat bod", type="primary", width="stretch"):
                    pos = len(P.body) if kam == "na konec" else moznosti.index(kam) - 1
                    P.body.insert(pos, Bod(nazev, lat, lon, typ))
                    st.session_state.posledni_klik = None
                    st.session_state.body_ver += 1
                    st.rerun()

        with st.container(border=True):
            st.markdown("🔎 **Hledat místo podle názvu**")
            c1, c2 = st.columns([3, 1])
            dotaz = c1.text_input("Hledat", placeholder="např. Jihlava, hlavní nádraží", label_visibility="collapsed")
            if c2.button("Hledat", width="stretch") and dotaz:
                try:
                    from planovac.osm import geocode

                    st.session_state.hledani = geocode(dotaz)
                    if not st.session_state.hledani:
                        st.warning("Nic nenalezeno.")
                except Exception as e:
                    st.error(f"Vyhledávání selhalo: {e}")
            if st.session_state.hledani:
                vysl = st.selectbox("Výsledky", st.session_state.hledani, format_func=lambda d: d["nazev"][:90])
                if st.button("📍 Označit v mapě", width="stretch"):
                    st.session_state.posledni_klik = [round(vysl["lat"], 5), round(vysl["lon"], 5)]
                    st.session_state.hledani = []
                    st.session_state.body_ver += 1
                    st.rerun()

        st.markdown("**Body trasy** (v pořadí jízdy; lze přímo editovat, mazat i přidávat řádky)")
        df = pd.DataFrame([{"Název": b.nazev, "Typ": b.typ, "Šířka (lat)": b.lat, "Délka (lon)": b.lon}
                           for b in P.body])
        if df.empty:
            df = pd.DataFrame(columns=["Název", "Typ", "Šířka (lat)", "Délka (lon)"])
        ed = st.data_editor(
            df, num_rows="dynamic", hide_index=False, width="stretch", key=f"body_editor_{st.session_state.body_ver}",
            column_config={
                "Typ": st.column_config.SelectboxColumn(options=list(TYPY_BODU), default=TYP_STANICE, required=True),
                "Šířka (lat)": st.column_config.NumberColumn(format="%.5f", min_value=-90, max_value=90),
                "Délka (lon)": st.column_config.NumberColumn(format="%.5f", min_value=-180, max_value=180),
            })
        nove = []
        for _, row in ed.iterrows():
            if pd.isna(row["Šířka (lat)"]) or pd.isna(row["Délka (lon)"]):
                continue
            nove.append(Bod(str(row["Název"] or "Bod"), float(row["Šířka (lat)"]), float(row["Délka (lon)"]),
                            row["Typ"] if row["Typ"] in TYPY_BODU else TYP_STANICE))
        if nove != P.body:
            P.body = nove

        c1, c2, c3 = st.columns(3)
        if c1.button("⇅ Obrátit směr", width="stretch", disabled=len(P.body) < 2):
            P.body.reverse()
            st.session_state.body_ver += 1
            st.rerun()
        if c2.button("↕ Poslední výš", width="stretch", disabled=len(P.body) < 3,
                     help="Přesune poslední bod o jedno místo dopředu"):
            P.body.insert(len(P.body) - 2, P.body.pop())
            st.session_state.body_ver += 1
            st.rerun()
        if c3.button("🗑️ Smazat vše", width="stretch", disabled=not P.body):
            P.body = []
            st.session_state.body_ver += 1
            st.rerun()

        if len(P.body) >= 2:
            xy = [to_xy(b.lon, b.lat) for b in P.body]
            d = [float(np.hypot(b[0] - a[0], b[1] - a[1])) / 1000 for a, b in zip(xy[:-1], xy[1:])]
            st.info(f"Vzdušnou čarou přes všechny body: **{sum(d):.1f} km** "
                    f"(max. délka trati ≈ {sum(d) * (1 + P.navrh.max_prodlouzeni_pct / 100):.1f} km). "
                    f"Stanic: {sum(b.je_stanice for b in P.body)}, průjezdních bodů: "
                    f"{sum(not b.je_stanice for b in P.body)}.")
        for ch in P.validate():
            st.warning(ch)


# ======================================================================== výsledky

def metric(col, label, value, delta=None):
    """Metrika s popiskem pod hodnotou (bez šipky a barvy)."""
    try:
        col.metric(label, value, delta, delta_color="off", delta_arrow="off")
    except TypeError:  # starší Streamlit bez delta_arrow
        col.metric(label, value, delta)


def _no_result():
    st.info("Zatím není nic spočítáno. Nastavte body trasy a parametry a stiskněte **🚀 Navrhnout trať** vlevo.")


if R is not None:
    from planovac import report
    from planovac.traction import fmt_cas

    S = report.souhrn(R)

with tabs[1]:
    if R is None:
        _no_result()
    else:
        if R.project.to_dict() != P.to_dict():
            st.caption("ℹ️ Parametry se od posledního výpočtu změnily – zobrazený výsledek odpovídá původnímu zadání.")
        c = st.columns(4)
        metric(c[0], "Délka trati", f"{S['delka_km']:.1f} km", f"+{S['prodlouzeni_pct']:.1f} % proti vzdušné")
        metric(c[1], "Odhad ceny", f"{S['cena_mld']:.1f} mld. Kč", f"{S['cena_mil_km']:.0f} mil. Kč/km")
        metric(c[2], "Jízdní doba", fmt_cas(S["jizdni_doba_s"]), f"bez zastavení {fmt_cas(S['express_s'])}")
        metric(c[3], "Průměrná rychlost", f"{S['prumerna_kmh']:.0f} km/h", f"max. sklon {S['max_sklon']:.1f} ‰")
        c = st.columns(4)
        metric(c[0], "Tunely", f"{S['tunely_ks'] + S['hloubene_ks']} ks", f"{S['tunely_km'] + S['hloubene_km']:.2f} km")
        metric(c[1], "Estakády a mosty", f"{S['estakady_ks'] + S['mosty_ks']} ks",
                    f"{S['estakady_km'] + S['mosty_km']:.2f} km")
        metric(c[2], "Demolice budov", f"{S['demolice']}", f"{S['hluk_budovy']} budov do 100 m")
        metric(c[3], "Zemní práce", f"{S['nasyp_mil_m3'] + S['vykop_mil_m3']:.1f} mil. m³",
                    f"násypy {S['nasyp_mil_m3']:.1f} / výkopy {S['vykop_mil_m3']:.1f}")
        for wmsg in R.varovani:
            st.warning(wmsg)
        with st.spinner("Kreslím mapu …"):
            html_mapa = report.build_map(R, fit=False).get_root().render()
            if hasattr(st, "iframe"):
                st.iframe(html_mapa, height=680)
            else:  # starší Streamlit
                components.html(html_mapa, height=680)
        st.caption(f"Výpočet trval {R.trvani_s:.0f} s · rastr {R.grid.ncols} × {R.grid.nrows} buněk po {R.grid.res:.0f} m "
                   "· v mapě lze přepínat podklady i vrstvy (vpravo nahoře), včetně nákladové mapy.")

with tabs[2]:
    if R is None:
        _no_result()
    else:
        st.subheader("Podélný profil")
        st.plotly_chart(report.fig_profil(R), width="stretch", key="pl_profil")
        st.subheader("Sklony nivelety")
        st.plotly_chart(report.fig_sklon(R), width="stretch", key="pl_sklon")
        st.subheader("Rychlostní profil")
        st.plotly_chart(report.fig_rychlost(R), width="stretch", key="pl_rychlost1")

with tabs[3]:
    if R is None:
        _no_result()
    else:
        c1, c2 = st.columns([3, 2])
        with c1:
            st.subheader("Souhrn objektů")
            st.dataframe(report.tab_objekty_souhrn(R), hide_index=True, width="stretch")
            st.subheader("Rozdělení délky trati")
            st.dataframe(report.tab_useky_typy(R), hide_index=True, width="stretch")
        with c2:
            st.plotly_chart(report.fig_objekty(R), width="stretch", key="pl_objekty")
        st.subheader("Seznam tunelů, estakád a mostů")
        df_o = report.tab_objekty(R)
        if len(df_o):
            st.dataframe(df_o, hide_index=True, width="stretch")
        else:
            st.success("Trasa nepotřebuje žádné tunely, estakády ani mosty. 🎉")
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Křížení")
            st.dataframe(report.tab_krizeni(R), hide_index=True, width="stretch", height=300)
            st.subheader("Směrové oblouky")
            st.dataframe(report.tab_oblouky(R), hide_index=True, width="stretch", height=300)
        with c2:
            st.subheader("Obce v blízkosti trati (bez zastávky)")
            st.dataframe(report.tab_obce(R), hide_index=True, width="stretch", height=300)
            st.subheader("Chráněná území")
            df_ch = report.tab_chranena(R)
            if len(df_ch):
                st.dataframe(df_ch, hide_index=True, width="stretch")
            else:
                st.write("Trať neprotíná chráněná území.")
            st.subheader("Prodloužení úseků")
            st.dataframe(report.tab_prodlouzeni(R), hide_index=True, width="stretch")

with tabs[4]:
    if R is None:
        _no_result()
    else:
        c = st.columns(3)
        metric(c[0], "Celkem vč. rezerv", f"{R.rozpocet.celkem_mil / 1000:.2f} mld. Kč")
        metric(c[1], "Přímé náklady", f"{R.rozpocet.primé_naklady_mil / 1000:.2f} mld. Kč")
        metric(c[2], "Na kilometr", f"{R.rozpocet.na_km_mil:.0f} mil. Kč/km")
        st.plotly_chart(report.fig_rozpocet(R), width="stretch", key="pl_rozpocet")
        st.dataframe(report.tab_rozpocet(R), hide_index=True, width="stretch")
        st.caption("Ceny jsou orientační (±40 %), vhodné pro porovnání variant. Jednotkové ceny lze upravit vlevo.")

with tabs[5]:
    if R is None:
        _no_result()
    else:
        c = st.columns(3)
        metric(c[0], "Se všemi zastávkami", fmt_cas(R.jizda.celkem_s))
        metric(c[1], "Bez zastavení", fmt_cas(R.jizda.express_s))
        metric(c[2], "Vlak", R.project.vlak.nazev)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Jízdní řád")
            st.dataframe(report.tab_jizdni_rad(R), hide_index=True, width="stretch")
        with c2:
            st.subheader("Úseky")
            st.dataframe(report.tab_useky_jizdy(R), hide_index=True, width="stretch")
        st.plotly_chart(report.fig_rychlost(R), width="stretch", key="pl_rychlost2")
        st.caption(f"Jízdní doby obsahují přirážku {R.project.vlak.rezerva_pct:.0f} % a pobyt ve stanici "
                   f"{R.project.vlak.pobyt_stanice_min:.1f} min.")

with tabs[6]:
    if R is None:
        _no_result()
    else:
        stem = R.project.nazev.lower().replace(" ", "_")[:40]
        html_rep = report.to_html_report(R)
        c = st.columns(3)
        c[0].download_button("📄 HTML report", html_rep.encode("utf-8"), f"{stem}_report.html", "text/html",
                             width="stretch")
        c[1].download_button("🗺️ GeoJSON", report.to_geojson(R).encode("utf-8"), f"{stem}.geojson",
                             "application/geo+json", width="stretch")
        c[2].download_button("🌍 KML (Google Earth)", report.to_kml(R).encode("utf-8"), f"{stem}.kml",
                             "application/vnd.google-earth.kml+xml", width="stretch")
        c = st.columns(3)
        c[0].download_button("📊 Profil CSV (Excel)", report.to_csv(R).encode("utf-8-sig"), f"{stem}_profil.csv",
                             "text/csv", width="stretch")
        c[1].download_button("⚙️ Projekt YAML", R.project.to_yaml().encode("utf-8"), f"{stem}.yaml", "text/yaml",
                             width="stretch")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("report.html", html_rep)
            z.writestr("trasa.geojson", report.to_geojson(R))
            z.writestr("trasa.kml", report.to_kml(R))
            z.writestr("profil.csv", report.to_csv(R).encode("utf-8-sig"))
            z.writestr("projekt.yaml", R.project.to_yaml())
            z.writestr("souhrn.txt", report.souhrn_text(R))
        c[2].download_button("📦 Vše v ZIP", buf.getvalue(), f"{stem}.zip", "application/zip", width="stretch",
                             type="primary")
        if st.button("💾 Uložit výstupy do složky vystupy/"):
            files = report.export_all(R, OUTPUT_DIR / stem)
            st.success(f"Uloženo do {files['report'].parent}")
        st.subheader("Souhrn")
        st.code(report.souhrn_text(R), language=None)

with tabs[7]:
    navod = ROOT / "docs" / "NAVOD.md"
    st.markdown(navod.read_text(encoding="utf-8") if navod.exists() else "Návod nenalezen (docs/NAVOD.md).")
