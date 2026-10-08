"""Správa aplikace z GUI: kontrola a instalace aktualizací, restart, ukončení, mazání cache.

Spouštěcí skripty (``start.ps1`` / ``start.sh``) běží ve smyčce a při návratovém kódu 75 aplikaci
spustí znovu – GUI proto restart provede ukončením procesu s kódem 75. Bez skriptu (ruční spuštění)
se proces nahradí novým voláním ``streamlit run``.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .paths import ROOT, cache_dir, data_dir

KOD_RESTARTU = 75


def _git(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def ma_git() -> bool:
    return shutil.which("git") is not None and (ROOT / ".git").exists()


def verze_gitu() -> str:
    """Zkrácený hash a datum aktuálního commitu (nebo prázdný řetězec)."""
    if not ma_git():
        return ""
    try:
        r = _git("log", "-1", "--format=%h, %cd", "--date=short")
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def zkontroluj() -> tuple[int | None, str]:
    """(počet nových commitů na serveru, popis). ``None`` = nelze zjistit."""
    if not ma_git():
        return None, "Program není nainstalován přes git – aktualizujte spuštěním start.ps1 / start.sh (stáhne ZIP)."
    try:
        r = _git("fetch", "--quiet")
        if r.returncode != 0:
            return None, "Nepodařilo se kontaktovat GitHub: " + (r.stderr.strip() or "chyba git fetch")[:300]
        r = _git("rev-list", "--count", "HEAD..@{u}")
        if r.returncode != 0:
            return None, "Větev nemá nastavený vzdálený protějšek (upstream)."
        n = int(r.stdout.strip() or 0)
        if n == 0:
            return 0, "Máte nejnovější verzi."
        log = _git("log", "--format=• %s", "HEAD..@{u}", "-n", "8").stdout.strip()
        return n, f"K dispozici {n} nových změn:\n{log}"
    except Exception as e:                       # noqa: BLE001
        return None, f"Kontrola selhala: {e}"


def _hash_pozadavku() -> str:
    return hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()


def _hash_soubor() -> Path:
    return Path(sys.prefix) / "requirements.sha"


def aktualizuj() -> tuple[bool, str]:
    """git pull + doinstalování knihoven, když se změnil requirements.txt. Vrací (úspěch, protokol)."""
    if not ma_git():
        return False, "Program není nainstalován přes git."
    log: list[str] = []
    try:
        r = _git("pull", "--ff-only", timeout=300)
        log.append((r.stdout + r.stderr).strip())
        if r.returncode != 0:
            return False, "\n".join(log) + "\n\nAktualizace selhala (lokální změny souborů?)."
        h = _hash_pozadavku()
        hf = _hash_soubor()
        stary = hf.read_text().strip() if hf.exists() else ""
        if h != stary:
            p = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")],
                               cwd=ROOT, capture_output=True, text=True, timeout=1800)
            log.append((p.stdout[-1500:] + p.stderr[-1500:]).strip())
            if p.returncode != 0:
                return False, "\n".join(log) + "\n\nInstalace knihoven selhala."
            try:
                hf.write_text(h)
            except OSError:
                pass
        return True, "\n".join(x for x in log if x)
    except Exception as e:                       # noqa: BLE001
        return False, "\n".join(log) + f"\n\nChyba: {e}"


def restartuj() -> None:
    """Restartuje aplikaci (nevrací se)."""
    sys.stdout.flush()
    sys.stderr.flush()
    if os.environ.get("PLANOVAC_LAUNCHER"):
        os._exit(KOD_RESTARTU)
    args = [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"), "--browser.gatherUsageStats", "false"]
    if os.name == "nt":                          # execv na Windows nechává starý proces → spustit nový a skončit
        subprocess.Popen(args, cwd=ROOT)
        os._exit(0)
    os.execv(sys.executable, args)


def ukonci() -> None:
    sys.stdout.flush()
    os._exit(0)


def velikost_cache_mb() -> float:
    d = data_dir() / "cache"
    if not d.exists():
        return 0.0
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e6


def smaz_cache(co: str = "vse") -> float:
    """Smaže cache stažených dat; ``co`` = 'vse' | 'osm' | 'overture' | 'dem'. Vrací uvolněné MB."""
    pred = velikost_cache_mb()
    for sub in (["osm", "overture", "dem"] if co == "vse" else [co]):
        d = data_dir() / "cache" / sub
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        cache_dir(sub)
    return pred - velikost_cache_mb()


def otevri_slozku(cesta: Path) -> bool:
    """Otevře složku ve správci souborů (jen při lokálním běhu)."""
    try:
        cesta.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(cesta))             # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(cesta)])
        else:
            subprocess.Popen(["xdg-open", str(cesta)])
        return True
    except Exception:
        return False
