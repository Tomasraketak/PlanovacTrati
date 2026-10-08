from planovac.body import nejblizsi_bod, nejlepsi_pozice, posun, pridej, prepni_typ, smaz, vychozi_nazev
from planovac.config import TYP_PRUJEZD, TYP_STANICE, Bod

B = [Bod("A", 49.0, 14.5), Bod("B", 49.0, 15.0), Bod("C", 49.0, 15.5)]


def test_vlozeni_mezi_spravne_body():
    assert nejlepsi_pozice(B, 49.05, 14.75) == 1      # mezi A a B
    assert nejlepsi_pozice(B, 48.95, 15.3) == 2       # mezi B a C
    assert nejlepsi_pozice(B, 49.0, 16.2) == 3        # daleko za C -> na konec
    assert nejlepsi_pozice(B, 49.0, 13.8) == 0        # daleko před A -> na začátek
    assert nejlepsi_pozice([], 49, 15) == 0 and nejlepsi_pozice(B[:1], 49, 15) == 1


def test_pridej_posun_smaz_prepni():
    nove, i = pridej(B, 49.05, 14.75, TYP_PRUJEZD, obec="Lišov")
    assert i == 1 and nove[1].typ == TYP_PRUJEZD and nove[1].nazev == "Průjezdní bod 1 (u Lišov)"
    nove2, j = posun(nove, 1, +1)
    assert j == 2 and nove2[2].nazev.startswith("Průjezdní")
    assert len(smaz(nove2, 2)) == 3
    assert prepni_typ(nove, 1)[1].typ == TYP_STANICE
    assert vychozi_nazev(B, TYP_STANICE) == "Stanice 4"
    assert nejblizsi_bod(B, 49.001, 15.001) == 1 and nejblizsi_bod(B, 50, 15) is None
