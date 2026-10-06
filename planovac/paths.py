"""Cesty k datovým složkám (cache, projekty, výstupy)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = ROOT / "projekty"
OUTPUT_DIR = ROOT / "vystupy"


def data_dir() -> Path:
    """Kořen datové cache – lze změnit proměnnou prostředí PLANOVAC_DATA."""
    return Path(os.environ.get("PLANOVAC_DATA", ROOT / "data"))


def cache_dir(sub: str) -> Path:
    p = data_dir() / "cache" / sub
    p.mkdir(parents=True, exist_ok=True)
    return p
