"""Diagnostika GUI: log chyb prohlížeče a zip."""
import urllib.request
import zipfile
import io

from planovac import diagnostika


def test_logovaci_server_zapise_chybu_prohlizece(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANOVAC_DATA", str(tmp_path))
    port = diagnostika.spust_server()
    assert port
    req = urllib.request.Request(f"http://127.0.0.1:{port}/log", data="error: boom".encode(), method="POST")
    assert urllib.request.urlopen(req, timeout=5).status == 204
    assert "boom" in diagnostika.posledni_chyby()
    assert f"127.0.0.1:{port}" in diagnostika.skript(port)


def test_zip_diagnostiky(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANOVAC_DATA", str(tmp_path))
    diagnostika.zapis("ahoj")
    z = zipfile.ZipFile(io.BytesIO(diagnostika.zip_diagnostiky({"x": 1})))
    assert "info.json" in z.namelist() and "gui_chyby.log" in z.namelist()
