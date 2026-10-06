from pathlib import Path

import numpy as np

from planovac.config import Project
from planovac.pipeline import run_project
from planovac.report import export_all, souhrn

ROOT = Path(__file__).resolve().parent.parent


def test_demo_end_to_end(tmp_path):
    p = Project.load(ROOT / "projekty" / "demo.yaml")
    p.vypocet.demo = True
    p.vypocet.rozliseni_m = 100
    r = run_project(p)
    S = souhrn(r)
    assert S["delka_km"] > 40
    assert S["max_sklon"] <= p.navrh.max_sklon_promile + 1e-6
    assert S["cena_mld"] > 0
    assert r.jizda.celkem_s > 0
    for _, _, L, d, pct in r.prodlouzeni_useku():
        assert pct <= p.navrh.max_prodlouzeni_pct + 3
    files = export_all(r, tmp_path)
    for f in files.values():
        assert f.exists() and f.stat().st_size > 0
    assert "<html" in files["report"].read_text(encoding="utf-8")


def test_yaml_roundtrip():
    p = Project.load(ROOT / "projekty" / "cb_jh_jihlava.yaml")
    q = Project.from_yaml(p.to_yaml())
    assert q.to_dict() == p.to_dict()
    assert not q.validate()
