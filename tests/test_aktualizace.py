"""Správa aplikace: kontrola/instalace aktualizací přes git v dočasném repozitáři."""
import subprocess

import pytest

from planovac import aktualizace


def _git(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"], "HOME": str(cwd)})


@pytest.fixture
def repa(tmp_path, monkeypatch):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-b", "main")
    (origin / "requirements.txt").write_text("numpy\n")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-m", "prvni")
    klon = tmp_path / "klon"
    subprocess.run(["git", "clone", "-q", str(origin), str(klon)], check=True)
    monkeypatch.setattr(aktualizace, "ROOT", klon)
    monkeypatch.setattr(aktualizace, "_hash_soubor", lambda: tmp_path / "req.sha")
    return origin, klon


def test_kontrola_a_aktualizace(repa, monkeypatch):
    origin, klon = repa
    assert aktualizace.zkontroluj()[0] == 0
    (origin / "novy.txt").write_text("x")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-m", "druhy")
    n, popis = aktualizace.zkontroluj()
    assert n == 1 and "druhy" in popis
    # requirements se nezměnily vůči uloženému hashi → pip se nespouští
    (aktualizace._hash_soubor()).write_text(aktualizace._hash_pozadavku())
    monkeypatch.setattr(subprocess, "run", subprocess.run)
    ok, _ = aktualizace.aktualizuj()
    assert ok and (klon / "novy.txt").exists()
    assert aktualizace.zkontroluj()[0] == 0


def test_bez_gitu(tmp_path, monkeypatch):
    monkeypatch.setattr(aktualizace, "ROOT", tmp_path)
    assert aktualizace.zkontroluj()[0] is None


def test_smaz_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANOVAC_DATA", str(tmp_path))
    d = tmp_path / "cache" / "osm"
    d.mkdir(parents=True)
    (d / "a.json").write_text("x" * 1000)
    aktualizace.smaz_cache("osm")
    assert not (d / "a.json").exists()
