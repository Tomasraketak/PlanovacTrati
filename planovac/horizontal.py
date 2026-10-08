"""Směrové (půdorysné) řešení: přímé + kružnicové oblouky s R >= R_min.

Postup:
1. Lomené čáry koridorů se zjednoduší (Douglas–Peucker) na vrcholy (PI).
2. Každá mezilehlá stanice / průjezdní bod se nahradí dvojicí vrcholů před
   a za bodem ve směru osy – bod tak leží na přímé (nástupiště je v přímé).
3. Do každého vrcholu se vloží kružnicový oblouk s co největším poloměrem
   (až do doporučeného), který se vejde mezi sousední oblouky. Pokud se
   nevejde ani minimální poloměr, odstraní se vrchol s nejmenší odchylkou od
   spojnice sousedů a postup se opakuje.
4. Výsledná osa se navzorkuje po 10 m (souřadnice, staničení, křivost).

Přechodnice se nemodelují (zjednodušení, vliv na délku i cenu je zanedbatelný).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .geo import douglas_peucker


@dataclass
class Prvek:
    typ: str          # "přímá" | "oblouk"
    s0: float
    s1: float
    R: float = 0.0
    smer: str = ""    # "L" / "P"

    @property
    def delka(self) -> float:
        return self.s1 - self.s0


@dataclass
class Alignment:
    xy: np.ndarray            # vzorky osy (N×2)
    s: np.ndarray             # staničení (m)
    krivost: np.ndarray       # 1/R se znaménkem (+ vlevo)
    prvky: list[Prvek]
    body_s: list[float]       # staničení zadaných bodů trasy
    varovani: list[str] = field(default_factory=list)

    @property
    def delka(self) -> float:
        return float(self.s[-1])

    def polomer(self) -> np.ndarray:
        with np.errstate(divide="ignore"):
            return np.where(np.abs(self.krivost) > 1e-9, 1.0 / np.abs(self.krivost), np.inf)


@dataclass
class _PI:
    xy: np.ndarray
    fixed: bool = False       # nelze odstranit (koncový bod, okraj nástupiště)
    req_after: float = 0.0    # požadovaná délka přímé za tímto vrcholem
    sym_after: bool = False   # přímá za vrcholem musí být symetrická kolem bodu (nástupiště)
    rmin: float = 0.0         # minimální poloměr v tomto vrcholu (menší v úseku se sníženou rychlostí)


def _unit(v):
    n = np.hypot(*v)
    return v / n if n > 1e-12 else np.array([1.0, 0.0])


def _build_pis(points_xy, je_stanice, seg_paths, Lp, tol, Rpref) -> list[_PI]:
    n = len(points_xy)
    # 1) surová posloupnost vrcholů: (xy, index zadaného bodu nebo None)
    raw: list[tuple[np.ndarray, int | None]] = [(np.asarray(points_xy[0], float), 0)]
    for i in range(n - 1):
        path = np.asarray(seg_paths[i], dtype=float)
        keep = douglas_peucker(path, tol)
        for k in keep[1:-1]:
            raw.append((path[k], None))
        raw.append((np.asarray(points_xy[i + 1], float), i + 1))

    Lps = list(Lp) if hasattr(Lp, "__len__") else [Lp] * n      # délka nástupiště po bodech
    half = [Lps[j] / 2 if je_stanice[j] else 0.0 for j in range(n)]
    # vzdálenost pomocných vrcholů od bodu: polovina nástupiště + tečna oblouku
    # (bod rozdělí lom osy na dva oblouky, každý s úhlem ~ Δ/2)
    idx_of = [k for k, (_, j) in enumerate(raw) if j is not None]
    dist_D = []
    for j in range(n):
        if j in (0, n - 1):
            dist_D.append(half[j])
            continue
        k = idx_of[j]
        u = _unit(raw[k][0] - raw[k - 1][0])
        v = _unit(raw[k + 1][0] - raw[k][0])
        delta = np.arccos(np.clip(np.dot(u, v), -1, 1))
        dist_D.append(half[j] + 1.2 * Rpref * np.tan(delta / 4) + 40.0)
    # 2) vrcholy uvnitř zóny mezilehlého bodu (nástupiště) zahodit
    keep_raw = []
    for xy, j in raw:
        if j is None and any(
            np.hypot(*(xy - np.asarray(points_xy[m], float))) < dist_D[m] + 30.0 for m in range(1, n - 1)
        ):
            continue
        keep_raw.append((xy, j))

    out: list[_PI] = []
    for idx, (xy, j) in enumerate(keep_raw):
        if j is None:
            out.append(_PI(xy))
        elif j == 0:
            out.append(_PI(xy, fixed=True, req_after=half[0]))
        elif j == n - 1:
            if out:
                out[-1].req_after = max(out[-1].req_after, half[j])
            out.append(_PI(xy, fixed=True))
        else:
            t = _unit(keep_raw[idx + 1][0] - keep_raw[idx - 1][0])
            D = dist_D[j]
            out.append(_PI(xy - D * t, fixed=True, req_after=2 * half[j], sym_after=True))
            out.append(_PI(xy + D * t, fixed=True))
    cleaned: list[_PI] = []
    for p in out:
        if cleaned and np.hypot(*(p.xy - cleaned[-1].xy)) < 1.0 and not p.fixed:
            continue
        cleaned.append(p)
    return cleaned


def _deflections(pis: list[_PI]) -> np.ndarray:
    n = len(pis)
    d = np.zeros(n)
    for k in range(1, n - 1):
        u = _unit(pis[k].xy - pis[k - 1].xy)
        v = _unit(pis[k + 1].xy - pis[k].xy)
        d[k] = np.arccos(np.clip(np.dot(u, v), -1.0, 1.0))
    return d


def _fit_radii(pis, Rmin, Rpref):
    n = len(pis)
    delta = _deflections(pis)
    t = np.tan(np.minimum(delta, np.pi * 0.999) / 2)
    seg_len = np.array([np.hypot(*(pis[j + 1].xy - pis[j].xy)) for j in range(n - 1)])
    avail = np.array([seg_len[j] - max(pis[j].req_after, 0.0) for j in range(n - 1)])
    T_max = np.full(n, np.inf)
    for j in range(n - 1):
        a, b = t[j], t[j + 1]
        tot = a + b
        if tot <= 1e-12:
            continue
        if pis[j].sym_after:
            # nástupiště uprostřed přímé – každý oblouk smí zabrat jen svou polovinu rezervy
            fa = fb = 0.5
        else:
            fa, fb = a / tot, b / tot
        T_max[j] = min(T_max[j], max(avail[j], 0) * fa)
        T_max[j + 1] = min(T_max[j + 1], max(avail[j], 0) * fb)
    R = np.full(n, Rpref)
    for k in range(1, n - 1):
        if t[k] > 1e-9:
            R[k] = min(Rpref, T_max[k] / t[k])
    return R, delta


def fit_alignment(points_xy, je_stanice, seg_paths, Rmin, Rpref, Lp=400.0, tol=150.0, ds=10.0,
                  zony: list[tuple[float, float, float]] | None = None, ref_xy: np.ndarray | None = None
                  ) -> Alignment:
    """Vloží přímé a oblouky do koridorů.

    ``zony`` – úseky se sníženou rychlostí [(s0, s1, Rmin_zóny)] ve staničení osy ``ref_xy``;
    vrcholy, které na ni padnou do zóny, smí mít oblouk až s poloměrem Rmin_zóny.
    """
    pis = _build_pis(points_xy, je_stanice, seg_paths, Lp, tol, Rpref)
    varovani: list[str] = []
    # odstranit téměř přímé vrcholy
    if len(pis) > 2:
        d0 = _deflections(pis)
        pis = [p for k, p in enumerate(pis) if p.fixed or k in (0, len(pis) - 1) or d0[k] > np.radians(0.05)]
    for p in pis:
        p.rmin = Rmin
    if zony and ref_xy is not None and len(ref_xy) > 1:
        from shapely.geometry import LineString, Point

        ref = LineString(ref_xy)
        for p in pis:
            if p.fixed:
                continue
            sp = ref.project(Point(p.xy))
            for s0, s1, rz in zony:
                if s0 <= sp <= s1:
                    p.rmin = min(p.rmin, rz)

    def rmin_arr():
        return np.array([p.rmin for p in pis])

    for _ in range(10 * len(pis) + 10):
        R, delta = _fit_radii(pis, Rmin, Rpref)
        rm = rmin_arr()
        bad = [k for k in range(1, len(pis) - 1) if delta[k] > 1e-6 and R[k] < rm[k] - 1e-6]
        if not bad:
            break
        k = min(bad, key=lambda q: R[q] / rm[q])
        cand = [q for q in (k - 1, k, k + 1) if 0 < q < len(pis) - 1 and not pis[q].fixed]
        if not cand:
            # všechny okolní vrcholy jsou pevné – ponecháme menší poloměr (rychlostní omezení)
            others = [q for q in bad if any(0 < z < len(pis) - 1 and not pis[z].fixed for z in (q - 1, q, q + 1))]
            if not others:
                break
            k = min(others, key=lambda q: R[q] / rm[q])
            cand = [q for q in (k - 1, k, k + 1) if 0 < q < len(pis) - 1 and not pis[q].fixed]

        def dev(q):
            a, b, p = pis[q - 1].xy, pis[q + 1].xy, pis[q].xy
            ab = b - a
            L = np.hypot(*ab)
            if L < 1e-9:
                return 0.0
            return abs(ab[0] * (p[1] - a[1]) - ab[1] * (p[0] - a[0])) / L

        q = min(cand, key=dev)
        pis.pop(q)
    R, delta = _fit_radii(pis, Rmin, Rpref)
    rm = rmin_arr()
    for k in range(1, len(pis) - 1):
        if delta[k] > 1e-6 and R[k] < rm[k] - 1e-6:
            varovani.append(
                f"Oblouk u vrcholu {k} má poloměr jen {R[k]:.0f} m (< {Rmin:.0f} m) – stanice/průjezdní body "
                "jsou příliš blízko sebe nebo v ostrém úhlu; v oblouku platí snížená rychlost."
            )
    return _generate(pis, R, delta, points_xy, ds, varovani)


def _generate(pis, R, delta, points_xy, ds, varovani) -> Alignment:
    n = len(pis)
    xs: list[np.ndarray] = []
    ks: list[np.ndarray] = []
    prvky: list[Prvek] = []
    s_cur = 0.0
    cur = pis[0].xy.copy()

    def add_line(p, q):
        nonlocal s_cur
        L = float(np.hypot(*(q - p)))
        if L < 1e-6:
            return
        m = max(1, int(np.ceil(L / ds)))
        tt = np.linspace(0, 1, m + 1)[1:]
        xs.append(p + np.outer(tt, q - p))
        ks.append(np.zeros(m))
        if prvky and prvky[-1].typ == "přímá":
            prvky[-1].s1 = s_cur + L
        else:
            prvky.append(Prvek("přímá", s_cur, s_cur + L))
        s_cur += L

    xs.append(cur[None, :])
    ks.append(np.zeros(1))
    for k in range(1, n - 1):
        if delta[k] < 1e-6 or not np.isfinite(R[k]):
            add_line(cur, pis[k].xy)
            cur = pis[k].xy.copy()
            continue
        u = _unit(pis[k].xy - pis[k - 1].xy)
        v = _unit(pis[k + 1].xy - pis[k].xy)
        T = R[k] * np.tan(delta[k] / 2)
        tc = pis[k].xy - T * u
        ct = pis[k].xy + T * v
        add_line(cur, tc)
        left = (u[0] * v[1] - u[1] * v[0]) > 0
        nrm = np.array([-u[1], u[0]]) if left else np.array([u[1], -u[0]])
        c = tc + R[k] * nrm
        a0 = np.arctan2(tc[1] - c[1], tc[0] - c[0])
        sweep = delta[k] if left else -delta[k]
        La = R[k] * delta[k]
        m = max(2, int(np.ceil(La / ds)))
        ang = a0 + sweep * np.linspace(0, 1, m + 1)[1:]
        xs.append(np.column_stack([c[0] + R[k] * np.cos(ang), c[1] + R[k] * np.sin(ang)]))
        ks.append(np.full(m, (1 if left else -1) / R[k]))
        prvky.append(Prvek("oblouk", s_cur, s_cur + La, float(R[k]), "L" if left else "P"))
        s_cur += La
        cur = ct
    add_line(cur, pis[-1].xy)
    xy = np.vstack(xs)
    k_arr = np.concatenate(ks)
    s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
    # staničení zadaných bodů = nejbližší vzorek
    body_s = []
    for p in points_xy:
        d = np.hypot(xy[:, 0] - p[0], xy[:, 1] - p[1])
        body_s.append(float(s[int(np.argmin(d))]))
    return Alignment(xy=xy, s=s, krivost=k_arr, prvky=prvky, body_s=body_s, varovani=varovani)
