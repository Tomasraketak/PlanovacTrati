from .cli import main

if __name__ == "__main__":      # ochrana nutná kvůli paralelním procesům (spawn znovu importuje hlavní modul)
    raise SystemExit(main())
