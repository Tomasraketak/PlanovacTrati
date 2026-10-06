"""Výstupy: interaktivní mapa, grafy, tabulky, HTML report a exporty (GeoJSON, KML, CSV)."""
from __future__ import annotations

import base64
import html
import io
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .geo import to_lonlat, xy_array_to_latlon
from .pipeline import Result
from .structures import BARVY, NAZVY, OBJEKTY, ESTAKADA, MOST, TUNEL, HLOUBENY, runs
from .traction import fmt_cas


# =========================================================================== souhrn

def souhrn(r: Result) -> dict:
    an = r.analyza
    obj = an.objekty

    def cnt(t):
        return sum(1 for u in obj if u.typ == t)

    def length(t):
        return sum(u.delka for u in obj if u.typ == t)

    sk = np.abs(r.sklon_promile())
    oblouky = [p for p in r.osa.prvky if p.typ == "oblouk"]
    return {
        "delka_km": r.delka_m / 1000,
        "vzdusna_km": r.vzdusna_m / 1000,
        "vzdusna_primo_km": r.vzdusna_primo_m / 1000,
        "prodlouzeni_pct": r.prodlouzeni_pct,
        "cena_mld": r.rozpocet.celkem_mil / 1000,
        "cena_mil_km": r.rozpocet.na_km_mil,
        "tunely_ks": cnt(TUNEL),
        "tunely_km": length(TUNEL) / 1000,
        "hloubene_ks": cnt(HLOUBENY),
        "hloubene_km": length(HLOUBENY) / 1000,
        "estakady_ks": cnt(ESTAKADA),
        "estakady_km": length(ESTAKADA) / 1000,
        "mosty_ks": cnt(MOST),
        "mosty_km": length(MOST) / 1000,
        "podil_objektu_pct": 100 * sum(u.delka for u in obj) / max(r.delka_m, 1),
        "demolice": len(an.demolice_idx),
        "hluk_budovy": an.hluk_pocet,
        "nasyp_mil_m3": an.objem_nasyp_m3 / 1e6,
        "vykop_mil_m3": an.objem_vykop_m3 / 1e6,
        "max_sklon": float(sk.max()) if len(sk) else 0.0,
        "min_polomer": min((p.R for p in oblouky), default=float("inf")),
        "pocet_oblouku": len(oblouky),
        "jizdni_doba_s": r.jizda.celkem_s,
        "express_s": r.jizda.express_s,
        "prumerna_kmh": r.delka_m / 1000 / max(r.jizda.celkem_s / 3600, 1e-9),
        "krizeni_silnic": sum(1 for k in an.krizeni if k.druh == "silnice"),
        "krizeni_zeleznic": sum(1 for k in an.krizeni if k.druh == "železnice"),
        "krizeni_vod": sum(1 for k in an.krizeni if k.druh == "vodní tok"),
        "v_zastavbe_km": an.delka_v_zastavbe / 1000,
        "min_vyska": float(np.min(r.z_kolej)),
        "max_vyska": float(np.max(r.z_kolej)),
        "trvani_s": r.trvani_s,
    }


def souhrn_text(r: Result) -> str:
    s = souhrn(r)
    lines = [
        f"Trať: {r.project.nazev}",
        f"Délka: {s['delka_km']:.1f} km (vzdušnou čarou přes zadané body {s['vzdusna_km']:.1f} km, "
        f"+{s['prodlouzeni_pct']:.1f} %)",
        f"Odhad ceny: {s['cena_mld']:.1f} mld. Kč ({s['cena_mil_km']:.0f} mil. Kč/km)",
        f"Tunely: {s['tunely_ks']} ks / {s['tunely_km']:.2f} km, hloubené {s['hloubene_ks']} ks / {s['hloubene_km']:.2f} km",
        f"Estakády: {s['estakady_ks']} ks / {s['estakady_km']:.2f} km, mosty {s['mosty_ks']} ks / {s['mosty_km']:.2f} km",
        f"Demolice budov: {s['demolice']}, budov v pásmu 100 m: {s['hluk_budovy']}",
        f"Max. sklon: {s['max_sklon']:.1f} ‰, nejmenší poloměr oblouku: {s['min_polomer']:.0f} m",
        f"Jízdní doba (všechny zastávky): {fmt_cas(s['jizdni_doba_s'])}, bez zastavení: {fmt_cas(s['express_s'])}",
    ]
    if r.varovani:
        lines.append("Varování:")
        lines += [f"  • {w}" for w in r.varovani]
    return "\n".join(lines)


# =========================================================================== tabulky

def tab_objekty(r: Result) -> pd.DataFrame:
    rows = []
    for i, u in enumerate(r.analyza.objekty, 1):
        rows.append({"#": i, "Typ": u.typ_nazev, "Od km": round(u.s0 / 1000, 3), "Do km": round(u.s1 / 1000, 3),
                     "Délka [m]": round(u.delka), "Max. výška/hloubka [m]": round(u.max_h, 1), "Poznámka": u.nazev})
    return pd.DataFrame(rows)


def tab_objekty_souhrn(r: Result) -> pd.DataFrame:
    rows = []
    for t in OBJEKTY:
        lst = [u for u in r.analyza.objekty if u.typ == t]
        if not lst:
            rows.append({"Typ": NAZVY[t], "Počet": 0, "Celkem [m]": 0, "Nejdelší [m]": 0, "Průměr [m]": 0})
            continue
        d = [u.delka for u in lst]
        rows.append({"Typ": NAZVY[t], "Počet": len(lst), "Celkem [m]": round(sum(d)), "Nejdelší [m]": round(max(d)),
                     "Průměr [m]": round(float(np.mean(d)))})
    return pd.DataFrame(rows)


def tab_useky_typy(r: Result) -> pd.DataFrame:
    s = r.osa.s
    ds = np.gradient(s)
    rows = []
    for t in range(len(NAZVY)):
        L = float(np.sum(ds[r.analyza.typy == t]))
        rows.append({"Typ": NAZVY[t], "Délka [km]": round(L / 1000, 2), "Podíl [%]": round(100 * L / r.delka_m, 1)})
    return pd.DataFrame(rows)


def tab_rozpocet(r: Result) -> pd.DataFrame:
    rows = []
    for p in r.rozpocet.polozky:
        jc = f"{p.jednotkova_cena:,.0f} Kč" if p.jednotka in ("m³", "m²") else f"{p.jednotkova_cena:,.0f} mil. Kč"
        mn = f"{p.mnozstvi:,.0f}" if p.jednotka in ("m³", "m²", "ks") else f"{p.mnozstvi:,.2f}"
        rows.append({"Položka": p.nazev, "Množství": mn, "Jednotka": p.jednotka, "Jedn. cena": jc,
                     "Cena [mil. Kč]": round(p.cena_mil, 1)})
    R = r.rozpocet
    rows.append({"Položka": "Přímé náklady celkem", "Množství": "", "Jednotka": "", "Jedn. cena": "",
                 "Cena [mil. Kč]": round(R.primé_naklady_mil, 1)})
    rows.append({"Položka": f"Projekce a inženýring ({r.project.ceny.projekt_pct:.0f} %)", "Množství": "",
                 "Jednotka": "", "Jedn. cena": "", "Cena [mil. Kč]": round(R.projekt_mil, 1)})
    rows.append({"Položka": f"Rezerva ({r.project.ceny.rezerva_pct:.0f} %)", "Množství": "", "Jednotka": "",
                 "Jedn. cena": "", "Cena [mil. Kč]": round(R.rezerva_mil, 1)})
    rows.append({"Položka": "CELKEM", "Množství": "", "Jednotka": "", "Jedn. cena": "",
                 "Cena [mil. Kč]": round(R.celkem_mil, 1)})
    return pd.DataFrame(rows)


def tab_jizdni_rad(r: Result) -> pd.DataFrame:
    rows = []
    for i, (st, prij, odj) in enumerate(r.jizda.jizdni_rad):
        rows.append({"Stanice": st, "Příjezd": fmt_cas(prij), "Odjezd": fmt_cas(odj)})
    return pd.DataFrame(rows)


def tab_useky_jizdy(r: Result) -> pd.DataFrame:
    return pd.DataFrame([{"Z": x.z, "Do": x.do, "Délka [km]": round(x.delka_km, 1),
                          "Jízdní doba": fmt_cas(x.jizdni_doba_s), "Průměrná rychlost [km/h]": round(x.prumerna_kmh)}
                         for x in r.jizda.radky])


def tab_prodlouzeni(r: Result) -> pd.DataFrame:
    return pd.DataFrame([{"Z": a, "Do": b, "Délka trati [km]": round(L / 1000, 2), "Vzdušně [km]": round(d / 1000, 2),
                          "Prodloužení [%]": round(p, 1), "Limit [%]": r.project.navrh.max_prodlouzeni_pct}
                         for a, b, L, d, p in r.prodlouzeni_useku()])


def tab_oblouky(r: Result) -> pd.DataFrame:
    rows = []
    vmax = r.project.navrh.rychlost_kmh
    DI = r.project.navrh.prevyseni_mm + r.project.navrh.nedostatek_prevyseni_mm
    for p in r.osa.prvky:
        if p.typ == "oblouk":
            v = min(vmax, np.sqrt(p.R * DI / 11.8))
            rows.append({"Od km": round(p.s0 / 1000, 3), "Do km": round(p.s1 / 1000, 3), "Délka [m]": round(p.delka),
                         "Poloměr [m]": round(p.R), "Směr": "vlevo" if p.smer == "L" else "vpravo",
                         "Max. rychlost [km/h]": int(v)})
    return pd.DataFrame(rows)


def tab_krizeni(r: Result) -> pd.DataFrame:
    return pd.DataFrame([{"km": round(k.s / 1000, 3), "Druh": k.druh, "Název": k.nazev, "Řešení": k.reseni}
                         for k in r.analyza.krizeni])


def tab_obce(r: Result) -> pd.DataFrame:
    return pd.DataFrame([{"Obec": n, "km": round(sp / 1000, 1), "Vzdálenost od osy [m]": round(d)}
                         for n, d, sp in r.analyza.obce_blizko])


def tab_chranena(r: Result) -> pd.DataFrame:
    stupne = {1: "nejpřísnější (NP, NPR)", 2: "rezervace / Natura 2000", 3: "CHKO a ostatní"}
    return pd.DataFrame([{"Území": n, "Stupeň ochrany": stupne.get(lv, lv), "Délka mimo tunel [m]": round(L)}
                         for n, lv, L in r.analyza.chranena_delky])


# =========================================================================== mapa

def _cost_overlay_png(r: Result):
    """Nákladová mapa převedená do WGS84 jako PNG (data URI) + hranice."""
    import rasterio
    from rasterio.warp import Resampling, calculate_default_transform, reproject
    from PIL import Image

    g = r.grid
    src = np.log10(np.clip(r.cost.cost, 1, 100)).astype(np.float32) / 2.0  # 0..1
    w, s_, e, n = g.bounds[0], g.bounds[1], g.bounds[2], g.bounds[3]
    tr, wd, ht = calculate_default_transform("EPSG:32633", "EPSG:4326", g.ncols, g.nrows, w, s_, e, n)
    dst = np.full((ht, wd), np.nan, dtype=np.float32)
    reproject(src, dst, src_transform=g.transform, src_crs="EPSG:32633", dst_transform=tr, dst_crs="EPSG:4326",
              resampling=Resampling.bilinear, dst_nodata=np.nan)
    v = np.nan_to_num(dst, nan=0.0)
    # barevná škála: průhledná -> žlutá -> červená -> fialová
    rgba = np.zeros((ht, wd, 4), dtype=np.uint8)
    rgba[..., 0] = np.clip(255 * np.minimum(1, v * 2.2), 0, 255)
    rgba[..., 1] = np.clip(220 * (1 - v) ** 1.2, 0, 255)
    rgba[..., 2] = np.clip(255 * np.maximum(0, v - 0.6) * 2.5, 0, 255)
    rgba[..., 3] = np.clip(230 * np.minimum(1, v * 1.6), 0, 230)
    rgba[~np.isfinite(dst)] = 0
    img = Image.fromarray(rgba, "RGBA")
    if max(img.size) > 1600:
        img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    west, north = tr.c, tr.f
    east = west + tr.a * wd
    south = north + tr.e * ht
    del rasterio
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), [[south, west], [north, east]]


LEGEND_HTML = """
<div style="position: fixed; bottom: 24px; left: 12px; z-index: 9999; background: rgba(255,255,255,0.94);
 padding: 10px 12px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,.25); font: 13px/1.5 system-ui, sans-serif;">
<div style="font-weight:600; margin-bottom:4px;">Legenda</div>
{rows}
<div><span style="display:inline-block;width:22px;border-top:2px dashed #555;margin-right:6px;vertical-align:middle"></span>vzdušná čára</div>
<div><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#e74c3c;margin:0 8px 0 6px"></span>demolice budovy</div>
</div>
"""


def build_map(r: Result, cost_layer: bool = True, fit: bool = True):
    import folium
    from folium import plugins

    latlon = xy_array_to_latlon(r.osa.xy)
    lat = [p[0] for p in latlon]
    lon = [p[1] for p in latlon]
    # počáteční zoom z rozsahu trasy (fitBounds v neviditelné záložce nefunguje)
    span = max(max(lon) - min(lon), (max(lat) - min(lat)) * 1.5, 1e-3)
    zoom = int(np.clip(np.floor(np.log2(360.0 / span * 2.6)), 5, 15))
    m = folium.Map(location=[(min(lat) + max(lat)) / 2, (min(lon) + max(lon)) / 2], zoom_start=zoom, tiles=None,
                   control_scale=True)
    folium.TileLayer("OpenStreetMap", name="Mapa OSM").add_to(m)
    folium.TileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", name="Topografická (OpenTopoMap)",
                     attr="© OpenTopoMap (CC-BY-SA), © OpenStreetMap", max_zoom=17, show=False).add_to(m)
    folium.TileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                     name="Satelit (Esri)", attr="Tiles © Esri", show=False).add_to(m)

    if cost_layer:
        try:
            uri, bounds = _cost_overlay_png(r)
            folium.raster_layers.ImageOverlay(uri, bounds=bounds, name="Nákladová mapa (penalizace)", opacity=0.6,
                                              show=False).add_to(m)
        except Exception:  # pragma: no cover - jen vizualizace
            pass

    # vzdušná čára a surový koridor
    fg_air = folium.FeatureGroup("Vzdušná čára", show=True)
    pts = [[b.lat, b.lon] for b in r.project.body]
    folium.PolyLine(pts, color="#555", weight=2, dash_array="8 8", opacity=0.8).add_to(fg_air)
    fg_air.add_to(m)
    fg_kor = folium.FeatureGroup("Koridor před vložením oblouků", show=False)
    for k in r.koridory:
        folium.PolyLine(xy_array_to_latlon(k.xy), color="#8e44ad", weight=2, dash_array="4 6").add_to(fg_kor)
    fg_kor.add_to(m)

    # osa po úsecích
    s = r.osa.s
    h = r.z_kolej - r.z_teren
    folium.PolyLine(latlon, color="white", weight=9, opacity=0.9).add_to(m)
    groups = {t: folium.FeatureGroup(f"Trať – {NAZVY[t]}", show=True) for t in range(len(NAZVY))}
    for t, a, b in runs(r.analyza.typy):
        a0, b1 = max(a - 1, 0), min(b + 1, len(latlon) - 1)
        seg = latlon[a0:b1 + 1]
        L = s[b1] - s[a0]
        hh = h[a:b + 1]
        info = (f"<b>{NAZVY[t]}</b><br>km {s[a0] / 1000:.2f} – {s[b1] / 1000:.2f}<br>délka {L:,.0f} m".replace(",", " ")
                + (f"<br>max. výška nad terénem {hh.max():.1f} m" if hh.max() > 1 else "")
                + (f"<br>max. hloubka pod terénem {-hh.min():.1f} m" if hh.min() < -1 else ""))
        dash = "10 6" if t in (TUNEL, HLOUBENY) else None
        folium.PolyLine(seg, color=BARVY[t], weight=6 if t in OBJEKTY else 5, opacity=0.95, dash_array=dash,
                        tooltip=folium.Tooltip(info)).add_to(groups[t])
    for t, g in groups.items():
        if (r.analyza.typy == t).any():
            g.add_to(m)

    # kilometrovník
    fg_km = folium.FeatureGroup("Kilometrovník", show=True)
    step = 10_000 if r.delka_m > 40_000 else 5_000
    for km in np.arange(step, r.delka_m, step):
        i = int(np.searchsorted(s, km))
        folium.Marker(latlon[i], icon=folium.DivIcon(
            html=f'<div style="font:600 11px system-ui;color:#333;background:#fff;border:1px solid #999;'
                 f'border-radius:4px;padding:0 3px;white-space:nowrap;transform:translate(-50%,-50%);'
                 f'display:inline-block">{km / 1000:.0f}</div>')).add_to(fg_km)
    fg_km.add_to(m)

    # stanice a body
    jr = {st: (pr, od) for st, pr, od in r.jizda.jizdni_rad}
    for b, bs in zip(r.project.body, r.osa.body_s):
        i = int(np.searchsorted(s, bs))
        i = min(i, len(s) - 1)
        if b.je_stanice:
            pr, od = jr.get(b.nazev, (np.nan, np.nan))
            popup = (f"<b>🚉 {html.escape(b.nazev)}</b><br>km {bs / 1000:.2f}<br>niveleta {r.z_kolej[i]:.0f} m n. m."
                     f"<br>příjezd {fmt_cas(pr)} | odjezd {fmt_cas(od)}")
            folium.Marker([b.lat, b.lon], tooltip=b.nazev, popup=folium.Popup(popup, max_width=260),
                          icon=folium.Icon(color="darkblue", icon="train", prefix="fa")).add_to(m)
        else:
            folium.CircleMarker([b.lat, b.lon], radius=7, color="#2c3e50", fill=True, fill_color="#f1c40f",
                                fill_opacity=1, tooltip=f"Průjezdní bod: {b.nazev} (km {bs / 1000:.2f})").add_to(m)

    # demolice
    if len(r.analyza.demolice_idx):
        fg_d = folium.FeatureGroup(f"Demolice ({len(r.analyza.demolice_idx)})", show=True)
        pts = r.osm.budovy[r.analyza.demolice_idx]
        lo, la = to_lonlat(pts[:, 0], pts[:, 1])
        for a, b in zip(la, lo):
            folium.CircleMarker([float(a), float(b)], radius=4, color="#c0392b", fill=True, fill_color="#e74c3c",
                                fill_opacity=0.9, weight=1, tooltip="budova k demolici").add_to(fg_d)
        fg_d.add_to(m)

    rows = "".join(
        f'<div><span style="display:inline-block;width:22px;height:5px;background:{BARVY[t]};margin-right:6px;'
        f'vertical-align:middle;border-radius:2px"></span>{NAZVY[t]}</div>'
        for t in range(len(NAZVY)) if (r.analyza.typy == t).any())
    m.get_root().html.add_child(folium.Element(LEGEND_HTML.format(rows=rows)))
    plugins.Fullscreen(position="topleft", title="Celá obrazovka", title_cancel="Zavřít").add_to(m)
    plugins.MeasureControl(position="topleft", primary_length_unit="kilometers", secondary_length_unit="meters",
                           primary_area_unit="hectares").add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    if fit:
        m.fit_bounds([[min(lat), min(lon)], [max(lat), max(lon)]], padding=(20, 20))
    m.get_root().script.add_child(folium.Element(
        f"window.addEventListener('resize', function() {{ {m.get_name()}.invalidateSize(); }});"))
    return m


# =========================================================================== grafy

def fig_profil(r: Result):
    import plotly.graph_objects as go

    km = r.osa.s / 1000
    fig = go.Figure()
    zmin = float(min(r.z_teren.min(), r.z_kolej.min())) - 20
    fig.add_trace(go.Scatter(x=km, y=r.z_teren, name="terén", fill="tozeroy", line=dict(color="#a1887f", width=1),
                             fillcolor="rgba(161,136,127,0.35)", hovertemplate="km %{x:.2f}<br>terén %{y:.1f} m<extra></extra>"))
    for t in range(len(NAZVY)):
        mask = r.analyza.typy == t
        if not mask.any():
            continue
        y = np.where(mask, r.z_kolej, np.nan)
        # spojit hranice úseků
        edge = np.flatnonzero(np.diff(mask.astype(int)) == -1)
        y[np.minimum(edge + 1, len(y) - 1)] = r.z_kolej[np.minimum(edge + 1, len(y) - 1)]
        fig.add_trace(go.Scatter(x=km, y=y, name=NAZVY[t], mode="lines", line=dict(color=BARVY[t], width=4),
                                 connectgaps=False, hovertemplate="km %{x:.2f}<br>niveleta %{y:.1f} m<extra>" + NAZVY[t] + "</extra>"))
    for b, bs in zip(r.project.body, r.osa.body_s):
        fig.add_vline(x=bs / 1000, line=dict(color="#34495e", dash="dot", width=1))
        fig.add_annotation(x=bs / 1000, y=1.02, yref="paper", text=("🚉 " if b.je_stanice else "◆ ") + b.nazev,
                           showarrow=False, font=dict(size=11))
    fig.update_layout(height=430, margin=dict(l=50, r=20, t=40, b=40), hovermode="x unified",
                      xaxis_title="staničení [km]", yaxis_title="nadmořská výška [m]",
                      legend=dict(orientation="h", y=-0.2), template="plotly_white")
    fig.update_yaxes(range=[zmin, float(max(r.z_teren.max(), r.z_kolej.max())) + 30])
    return fig


def fig_sklon(r: Result):
    import plotly.graph_objects as go

    km = r.osa.s / 1000
    g = r.sklon_promile()
    lim = r.project.navrh.max_sklon_promile
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=km, y=g, name="sklon", line=dict(color="#16a085"), fill="tozeroy",
                             fillcolor="rgba(22,160,133,.2)", hovertemplate="km %{x:.2f}: %{y:.1f} ‰<extra></extra>"))
    fig.add_hline(y=lim, line=dict(color="#c0392b", dash="dash"), annotation_text=f"limit {lim:.0f} ‰")
    fig.add_hline(y=-lim, line=dict(color="#c0392b", dash="dash"))
    fig.update_layout(height=230, margin=dict(l=50, r=20, t=20, b=40), xaxis_title="staničení [km]",
                      yaxis_title="sklon [‰]", template="plotly_white", showlegend=False)
    return fig


def fig_rychlost(r: Result):
    import plotly.graph_objects as go

    km = r.jizda.s / 1000
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=km, y=r.jizda.vlim_kmh, name="traťová rychlost", line=dict(color="#95a5a6", dash="dot")))
    fig.add_trace(go.Scatter(x=km, y=r.jizda.v_express_kmh, name="vlak bez zastavení", line=dict(color="#e67e22")))
    fig.add_trace(go.Scatter(x=km, y=r.jizda.v_kmh, name="vlak zastavující všude", line=dict(color="#2980b9", width=3)))
    for b, bs in zip(r.project.body, r.osa.body_s):
        if b.je_stanice:
            fig.add_vline(x=bs / 1000, line=dict(color="#34495e", dash="dot", width=1))
    fig.update_layout(height=330, margin=dict(l=50, r=20, t=20, b=40), xaxis_title="staničení [km]",
                      yaxis_title="rychlost [km/h]", hovermode="x unified", template="plotly_white",
                      legend=dict(orientation="h", y=-0.3))
    return fig


def fig_objekty(r: Result):
    import plotly.graph_objects as go

    df = tab_useky_typy(r)
    df = df[df["Délka [km]"] > 0]
    colors = [BARVY[NAZVY.index(t)] for t in df["Typ"]]
    fig = go.Figure(go.Pie(labels=df["Typ"], values=df["Délka [km]"], hole=0.55, marker=dict(colors=colors),
                           sort=False, textinfo="label+percent"))
    fig.update_layout(height=330, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
    return fig


def fig_rozpocet(r: Result):
    import plotly.graph_objects as go

    P = sorted([p for p in r.rozpocet.polozky if p.cena_mil > 0], key=lambda p: p.cena_mil)
    fig = go.Figure(go.Bar(x=[p.cena_mil / 1000 for p in P], y=[p.nazev for p in P], orientation="h",
                           marker_color="#2e86de", hovertemplate="%{y}: %{x:.2f} mld. Kč<extra></extra>"))
    fig.update_layout(height=60 + 28 * len(P), margin=dict(l=10, r=20, t=10, b=40), xaxis_title="mld. Kč",
                      template="plotly_white")
    return fig


# =========================================================================== exporty

def to_geojson(r: Result) -> str:
    feats = []
    latlon = xy_array_to_latlon(r.osa.xy)
    s = r.osa.s
    for t, a, b in runs(r.analyza.typy):
        a0, b1 = max(a - 1, 0), min(b + 1, len(latlon) - 1)
        feats.append({"type": "Feature", "properties": {"typ": NAZVY[t], "od_km": round(s[a0] / 1000, 3),
                                                        "do_km": round(s[b1] / 1000, 3),
                                                        "delka_m": round(float(s[b1] - s[a0]), 1), "barva": BARVY[t]},
                      "geometry": {"type": "LineString", "coordinates": [[p[1], p[0]] for p in latlon[a0:b1 + 1]]}})
    for b, bs in zip(r.project.body, r.osa.body_s):
        feats.append({"type": "Feature", "properties": {"nazev": b.nazev, "typ": b.typ, "km": round(bs / 1000, 3)},
                      "geometry": {"type": "Point", "coordinates": [b.lon, b.lat]}})
    if len(r.analyza.demolice_idx):
        pts = r.osm.budovy[r.analyza.demolice_idx]
        lo, la = to_lonlat(pts[:, 0], pts[:, 1])
        for a, b in zip(lo, la):
            feats.append({"type": "Feature", "properties": {"typ": "demolice"},
                          "geometry": {"type": "Point", "coordinates": [float(a), float(b)]}})
    return json.dumps({"type": "FeatureCollection", "name": r.project.nazev, "features": feats}, ensure_ascii=False)


def to_kml(r: Result) -> str:
    def kml_color(hexc):
        hexc = hexc.lstrip("#")
        return f"ff{hexc[4:6]}{hexc[2:4]}{hexc[0:2]}"

    latlon = xy_array_to_latlon(r.osa.xy)
    s = r.osa.s
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
           f"<name>{html.escape(r.project.nazev)}</name>"]
    for t in range(len(NAZVY)):
        out.append(f'<Style id="t{t}"><LineStyle><color>{kml_color(BARVY[t])}</color><width>5</width></LineStyle></Style>')
    for t, a, b in runs(r.analyza.typy):
        a0, b1 = max(a - 1, 0), min(b + 1, len(latlon) - 1)
        coords = " ".join(f"{p[1]:.6f},{p[0]:.6f},{r.z_kolej[i]:.1f}" for i, p in enumerate(latlon[a0:b1 + 1], a0))
        out.append(f"<Placemark><name>{NAZVY[t]} km {s[a0] / 1000:.2f}–{s[b1] / 1000:.2f}</name>"
                   f"<styleUrl>#t{t}</styleUrl><LineString><altitudeMode>absolute</altitudeMode>"
                   f"<coordinates>{coords}</coordinates></LineString></Placemark>")
    for b in r.project.body:
        out.append(f"<Placemark><name>{html.escape(b.nazev)}</name><Point><coordinates>{b.lon},{b.lat},0"
                   f"</coordinates></Point></Placemark>")
    out.append("</Document></kml>")
    return "\n".join(out)


def to_csv(r: Result) -> str:
    lon, lat = to_lonlat(r.osa.xy[:, 0], r.osa.xy[:, 1])
    v = np.interp(r.osa.s, r.jizda.s, r.jizda.v_kmh)
    df = pd.DataFrame({
        "km": np.round(r.osa.s / 1000, 4), "lat": np.round(lat, 6), "lon": np.round(lon, 6),
        "x_utm33": np.round(r.osa.xy[:, 0], 1), "y_utm33": np.round(r.osa.xy[:, 1], 1),
        "teren_m": np.round(r.z_teren, 2), "niveleta_m": np.round(r.z_kolej, 2),
        "vyska_nad_terenem_m": np.round(r.z_kolej - r.z_teren, 2),
        "sklon_promile": np.round(r.sklon_promile(), 2),
        "polomer_m": np.round(np.where(np.isfinite(r.osa.polomer()), r.osa.polomer(), 0), 0),
        "typ": [NAZVY[t] for t in r.analyza.typy],
        "tratova_rychlost_kmh": np.round(r.jizda.vlim_kmh, 0), "rychlost_vlaku_kmh": np.round(v, 1),
    })
    return df.to_csv(index=False, sep=";", decimal=",")


REPORT_CSS = """
body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;margin:0;background:#f4f6f8;color:#1d2b36}
header{background:linear-gradient(120deg,#1e3c72,#2a5298);color:#fff;padding:28px 40px}
header h1{margin:0 0 6px;font-size:28px} header p{margin:0;opacity:.85}
main{max-width:1250px;margin:0 auto;padding:24px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:22px}
.kpi{background:#fff;border-radius:12px;padding:14px 16px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.kpi .v{font-size:24px;font-weight:700;color:#1e3c72}.kpi .l{font-size:13px;color:#5d6d7e}
section{background:#fff;border-radius:12px;padding:18px 22px;margin-bottom:20px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
h2{margin-top:0;font-size:20px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:6px 10px;border-bottom:1px solid #e5e8eb;text-align:left}
th{background:#f0f3f6}
.warn{background:#fff8e1;border-left:4px solid #f39c12;padding:10px 14px;border-radius:6px}
iframe{border:0;width:100%;height:640px;border-radius:10px}
footer{color:#7f8c8d;font-size:12px;text-align:center;padding:20px}
"""


def to_html_report(r: Result) -> str:
    S = souhrn(r)
    m = build_map(r)
    map_html = m.get_root().render()
    kpi = [
        (f"{S['delka_km']:.1f} km", f"délka trati (+{S['prodlouzeni_pct']:.1f} % proti vzdušné čáře)"),
        (f"{S['cena_mld']:.1f} mld. Kč", f"odhad ceny ({S['cena_mil_km']:.0f} mil. Kč/km)"),
        (fmt_cas(S["jizdni_doba_s"]), "jízdní doba se všemi zastávkami"),
        (fmt_cas(S["express_s"]), "jízdní doba bez zastavení"),
        (f"{S['tunely_ks']} / {S['tunely_km']:.1f} km", "tunely"),
        (f"{S['estakady_ks'] + S['mosty_ks']} / {S['estakady_km'] + S['mosty_km']:.1f} km", "estakády a mosty"),
        (f"{S['demolice']}", "budov k demolici"),
        (f"{S['max_sklon']:.1f} ‰", "max. sklon"),
    ]
    kpi_html = "".join(f'<div class="kpi"><div class="v">{v}</div><div class="l">{lab}</div></div>' for v, lab in kpi)

    def tbl(df):
        return df.to_html(index=False, border=0, escape=True) if len(df) else "<p>—</p>"

    figs = "".join(f.to_html(full_html=False, include_plotlyjs="cdn" if i == 0 else False)
                   for i, f in enumerate([fig_profil(r), fig_sklon(r), fig_rychlost(r)]))
    warn = ""
    if r.varovani:
        warn = '<div class="warn"><b>Upozornění:</b><ul>' + "".join(f"<li>{html.escape(w)}</li>" for w in r.varovani) + "</ul></div>"
    srcdoc = html.escape(map_html, quote=True)
    return f"""<!doctype html><html lang="cs"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(r.project.nazev)} – návrh trati</title>
<style>{REPORT_CSS}</style></head><body>
<header><h1>🚄 {html.escape(r.project.nazev)}</h1>
<p>Návrhová rychlost {r.project.navrh.rychlost_kmh:.0f} km/h · max. sklon {r.project.navrh.max_sklon_promile:.0f} ‰ ·
min. poloměr {r.project.navrh.min_polomer():.0f} m · vygenerováno {datetime.now():%d. %m. %Y %H:%M} programem Plánovač tratí</p></header>
<main>
<div class="kpis">{kpi_html}</div>
{warn}
<section><h2>Mapa trasy</h2><iframe srcdoc="{srcdoc}"></iframe></section>
<section><h2>Podélný profil, sklony a rychlost</h2>{figs}</section>
<section><h2>Souhrn staveb</h2>{tbl(tab_objekty_souhrn(r))}<h3>Rozdělení délky trati</h3>{tbl(tab_useky_typy(r))}</section>
<section><h2>Seznam objektů</h2>{tbl(tab_objekty(r))}</section>
<section><h2>Rozpočet (orientační)</h2>{tbl(tab_rozpocet(r))}</section>
<section><h2>Jízdní řád</h2>{tbl(tab_jizdni_rad(r))}<h3>Úseky</h3>{tbl(tab_useky_jizdy(r))}</section>
<section><h2>Prodloužení proti vzdušné čáře</h2>{tbl(tab_prodlouzeni(r))}</section>
<section><h2>Směrové oblouky</h2>{tbl(tab_oblouky(r))}</section>
<section><h2>Křížení</h2>{tbl(tab_krizeni(r))}</section>
<section><h2>Obce v blízkosti trati (bez zastávky)</h2>{tbl(tab_obce(r))}</section>
<section><h2>Chráněná území</h2>{tbl(tab_chranena(r))}</section>
</main><footer>Data: Copernicus DEM GLO-30 © DLR/ESA, © přispěvatelé OpenStreetMap (ODbL). Výsledky jsou orientační studie,
nikoli projektová dokumentace.</footer></body></html>"""


def export_all(r: Result, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "report": out / "report.html",
        "mapa": out / "mapa.html",
        "geojson": out / "trasa.geojson",
        "kml": out / "trasa.kml",
        "csv": out / "profil.csv",
        "projekt": out / "projekt.yaml",
        "souhrn": out / "souhrn.txt",
    }
    files["report"].write_text(to_html_report(r), encoding="utf-8")
    build_map(r).save(str(files["mapa"]))
    files["geojson"].write_text(to_geojson(r), encoding="utf-8")
    files["kml"].write_text(to_kml(r), encoding="utf-8")
    files["csv"].write_text(to_csv(r), encoding="utf-8-sig")
    r.project.save(files["projekt"])
    files["souhrn"].write_text(souhrn_text(r), encoding="utf-8")
    return files
