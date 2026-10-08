"""Paralelní výpočet: procesy pro Dijkstru (drží GIL), vlákna pro dlouhé numpy/scipy úlohy."""
from __future__ import annotations

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import contextmanager


def pocet_vlaken(pozadovano: int = 0) -> int:
    """0 = všechna dostupná vlákna procesoru."""
    n = os.cpu_count() or 1
    return max(1, min(int(pozadovano) if pozadovano and pozadovano > 0 else n, 64))


@contextmanager
def _bez_importu_hlavniho_modulu():
    """Spawnutý proces nesmí znovu importovat hlavní skript.

    Standardně ``spawn`` v dítěti spustí hlavní modul rodiče. Pod ``streamlit run app.py`` by tedy každý pracovní
    proces spustil celou aplikaci (a výpočet by visel); funkce pro pracovní procesy leží v importovatelných
    modulech balíčku, hlavní skript tedy není potřeba.
    """
    import multiprocessing.spawn as sp

    puvodni = sp.get_preparation_data

    def priprava(name):
        d = puvodni(name)
        d.pop("init_main_from_path", None)
        d.pop("init_main_from_name", None)
        return d

    sp.get_preparation_data = priprava
    try:
        yield
    finally:
        sp.get_preparation_data = puvodni


@contextmanager
def procesy(n: int):
    """Procesový pool (spawn – funguje stejně na Windows, Linuxu i v Streamlitu); při ``n <= 1`` vrací None."""
    if n <= 1:
        yield None
        return
    with _bez_importu_hlavniho_modulu():
        ex = ProcessPoolExecutor(max_workers=n, mp_context=multiprocessing.get_context("spawn"))
        try:
            yield ex
        finally:
            ex.shutdown(wait=True, cancel_futures=True)


@contextmanager
def vlakna(n: int):
    if n <= 1:
        yield None
        return
    ex = ThreadPoolExecutor(max_workers=n)
    try:
        yield ex
    finally:
        ex.shutdown(wait=True)


def map_procesy(ex):
    """Vrátí ``map_fn(fn, ulohy, lams)`` pro ``corridor.find_segment`` (None = sériově)."""
    if ex is None:
        return None

    def map_fn(fn, ulohy, lams):
        return list(ex.map(fn, [ulohy] * len(lams), lams))

    return map_fn
