import numpy as np

from planovac.config import NavrhoveParametry
from planovac.geo import douglas_peucker, resample_polyline
from planovac.horizontal import fit_alignment


def zigzag(a, b, n=40, amp=800.0, seed=0):
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 1, n)
    p = np.outer(1 - t, a) + np.outer(t, b)
    d = np.array(b) - np.array(a)
    nrm = np.array([-d[1], d[0]]) / np.hypot(*d)
    off = amp * np.sin(t * 6 * np.pi) + rng.normal(0, 100, n)
    off[0] = off[-1] = 0
    return p + np.outer(off, nrm)


def test_min_radius_formula():
    n = NavrhoveParametry(rychlost_kmh=200)
    assert 1850 <= n.min_polomer() <= 1950
    assert n.doporuceny_polomer() >= n.min_polomer()


def test_douglas_peucker_keeps_endpoints():
    xy = zigzag((0, 0), (10000, 0))
    idx = douglas_peucker(xy, 200)
    assert idx[0] == 0 and idx[-1] == len(xy) - 1


def test_alignment_respects_radius_and_stations():
    a, b, c = (0.0, 0.0), (30000.0, 5000.0), (60000.0, -3000.0)
    paths = [zigzag(a, b), zigzag(b, c, seed=1)]
    Rmin = 1900.0
    al = fit_alignment([a, b, c], [True, True, True], paths, Rmin, 2600.0, Lp=400.0, tol=150.0)
    radii = [p.R for p in al.prvky if p.typ == "oblouk"]
    assert radii, "očekávány oblouky"
    assert min(radii) >= Rmin - 1e-6
    # osa prochází stanicemi
    for p in (a, b, c):
        d = np.min(np.hypot(al.xy[:, 0] - p[0], al.xy[:, 1] - p[1]))
        assert d < 6.0
    # ve stanici b je přímá alespoň na délku nástupiště
    sb = al.body_s[1]
    k = np.abs(al.s - sb) <= 190
    assert np.allclose(al.krivost[k], 0.0)
    # spojitost osy – žádné skoky
    steps = np.hypot(*np.diff(al.xy, axis=0).T)
    assert steps.max() < 15.0


def test_resample():
    xy = np.array([[0, 0], [100, 0], [100, 100]], float)
    r = resample_polyline(xy, 10)
    assert np.allclose(r[0], [0, 0]) and np.allclose(r[-1], [100, 100])
