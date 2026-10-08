"""Příkazová řádka: ``python -m planovac run projekty/demo.yaml -o vystupy/demo``."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="planovac", description="Plánovač tratí – návrh osy VRT z výškového modelu a OSM")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="spočítá projekt a uloží výstupy")
    run.add_argument("projekt", help="cesta k YAML projektu (např. projekty/demo.yaml)")
    run.add_argument("-o", "--out", default=None, help="výstupní složka (výchozí vystupy/<název souboru>)")
    run.add_argument("--demo", action="store_true", help="použít syntetický terén (bez internetu)")
    run.add_argument("--rozliseni", type=float, default=None, help="rozlišení rastru v metrech")
    run.add_argument("--auto", action="store_true",
                     help="porovnat jízdní dobu s autem (Mapy.cz při MAPY_API_KEY, jinak OSRM)")
    run.add_argument("-q", "--quiet", action="store_true")
    new = sub.add_parser("novy", help="vytvoří šablonu projektu")
    new.add_argument("soubor")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.WARNING if getattr(args, "quiet", False) else logging.INFO,
                        format="%(message)s")
    from .config import Bod, Project

    if args.cmd == "novy":
        p = Project(nazev="Nová trať", body=[Bod("Start", 49.0, 14.5), Bod("Cíl", 49.4, 15.6)])
        p.save(args.soubor)
        print(f"Vytvořeno: {args.soubor}")
        return 0

    from .pipeline import run_project
    from .report import export_all, souhrn_text

    p = Project.load(args.projekt)
    if args.demo:
        p.vypocet.demo = True
    if args.rozliseni:
        p.vypocet.rozliseni_m = args.rozliseni
    out = Path(args.out) if args.out else Path("vystupy") / Path(args.projekt).stem
    res = run_project(p)
    if args.auto:
        from .auto import jizda_autem
        from .report import stanice_pro_auto

        res.auto, res.auto_varovani = jizda_autem(stanice_pro_auto(res))
    files = export_all(res, out)
    print()
    print(souhrn_text(res))
    print()
    print(f"Výstupy uloženy do: {out.resolve()}")
    for k, f in files.items():
        print(f"  {k:8s} {f.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
