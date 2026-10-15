"""Menší oblouky u stanic a pojistka proti smyčkám osy."""
import numpy as np
from shapely.geometry import LineString

from planovac import horizontal


def _kor():
    # koncová stanice v (0,0); koridor jde 700 m na sever podél kolejí a pak ostře na východ
    S, B = (0.0, 0.0), (9000.0, 1500.0)
    return [S, B], [np.array([S, (0, 700), (250, 950), (900, 1100), B])]


def test_zona_u_stanice_sleduje_koridor():
    body, kor = _kor()
    zakl = horizontal.fit_alignment(body, [True, True], kor, 1900.0, 3000.0, Lp=400.0, tol=30.0)
    st = horizontal.fit_alignment(body, [True, True], kor, 1900.0, 3000.0, Lp=400.0, tol=30.0,
                                  stanice_zona=([body[0]], 1000.0, 150.0))
    R_st = min(p.R for p in st.prvky if p.typ == "oblouk")
    assert 150.0 - 1 <= R_st < 1900.0                    # u stanice smí být menší oblouk …
    # … a osa pak drží koridor (vzdálenost od koridoru u stanice je menší)
    k = LineString(kor[0])
    odch = lambda al: max(k.distance(LineString(al.xy[al.s < 1200]).interpolate(t, normalized=True))
                          for t in np.linspace(0, 1, 30))
    assert odch(st) < odch(zakl)


def test_osa_nikdy_nevytvori_smycku():
    # koridor, který se za stanicí vrací (vrchol s lomem > 115°), nesmí vytvořit smyčku
    S, B = (0.0, 0.0), (6000.0, 300.0)
    kor = [np.array([S, (0, 900), (-150, 500), (400, 700), B])]
    al = horizontal.fit_alignment([S, B], [True, True], kor, 1900.0, 3000.0, Lp=400.0, tol=10.0,
                                  stanice_zona=([S], 1000.0, 150.0))
    assert LineString(al.xy).is_simple


# body z reálného hlášení (export z mapy.com): stanice ČB, blízké průjezdní body u nádraží, zastávka Lišov, Třeboň
BODY_CB_TREBON = [(48.974580, 14.489102), (48.977028, 14.487749), (48.978065, 14.487891), (48.978740, 14.488774),
                  (48.979347, 14.490697), (48.980175, 14.494006), (48.981262, 14.499095), (48.983140, 14.503610),
                  (48.985170, 14.506906), (49.009020, 14.540262), (49.011368, 14.608528), (49.023323, 14.738499),
                  (49.020035, 14.758118), (49.015247, 14.760676)]


def test_blizke_pruchozi_body_bez_spiraly():
    from planovac.geo import to_xy

    xy = [tuple(to_xy(lo, la)) for la, lo in BODY_CB_TREBON]
    st = [i in (0, 10, len(xy) - 1) for i in range(len(xy))]
    kor = [np.array([xy[i], xy[i + 1]]) for i in range(len(xy) - 1)]
    for R in (1900.0, 700.0):
        for zona in (None, ([p for p, s in zip(xy, st) if s], 1000.0, 150.0)):
            al = horizontal.fit_alignment(xy, st, kor, R, 3000.0, Lp=[400.0 if s else 0.0 for s in st], tol=100.0,
                                          stanice_zona=zona)
            assert LineString(al.xy).is_simple
            vzd = sum(np.hypot(*np.diff(np.array(xy), axis=0).T))
            assert al.delka < 1.05 * vzd               # žádné okliky navíc


def test_nahodne_body_bez_smycky():
    rng = np.random.default_rng(5)
    for _ in range(300):
        n = int(rng.integers(3, 12))
        p, ang, pts = np.zeros(2), rng.uniform(0, 6.28), [np.zeros(2)]
        for _ in range(n - 1):
            ang += rng.normal(0, 0.8)
            p = p + rng.choice([rng.uniform(60, 400), rng.uniform(400, 8000)]) * np.array([np.cos(ang), np.sin(ang)])
            pts.append(p.copy())
        st = [True] + [bool(rng.random() < 0.2) for _ in range(n - 2)] + [True]
        kor = [np.array([a, b]) for a, b in zip(pts[:-1], pts[1:])]
        al = horizontal.fit_alignment(pts, st, kor, 1900.0, 3000.0, Lp=[400.0 if s else 0.0 for s in st], tol=50.0)
        # smyčka je přípustná jen tam, kde se kříží (nebo skoro obrací) už samotná spojnice zadaných bodů
        vraci_se = horizontal._deflections([horizontal._PI(q) for q in pts]).max() > 2.6
        if LineString(pts).is_simple and not vraci_se:
            assert LineString(al.xy).is_simple
