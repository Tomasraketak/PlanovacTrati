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
