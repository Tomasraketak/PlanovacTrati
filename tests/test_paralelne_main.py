"""Pracovní procesy nesmí znovu spouštět hlavní skript (pod Streamlitem by spustily celou aplikaci)."""
import subprocess
import sys
import textwrap


def test_deti_neimportuji_hlavni_skript(tmp_path):
    skript = tmp_path / "hlavni.py"
    stopa = tmp_path / "stopa.txt"
    skript.write_text(textwrap.dedent(f"""
        import os
        with open({str(stopa)!r}, "a") as f:
            f.write(os.path.basename(__file__) + ":" + str(os.getpid()) + "\\n")
        from planovac import paralelne
        from planovac.paralelne import pocet_vlaken
        if __name__ == "__main__":
            pass
        # ne-guardovaný kód: s __main__ guardem by test nic neprokázal
        with paralelne.procesy(2) as ex:
            print(list(ex.map(pocet_vlaken, [1, 2, 3])))
    """))
    r = subprocess.run([sys.executable, str(skript)], capture_output=True, text=True, timeout=120,
                       env={**__import__("os").environ, "PYTHONPATH": str(__import__("pathlib").Path(__file__).parent.parent)})
    assert "[1, 2, 3]" in r.stdout, r.stderr[-800:]
    assert len(stopa.read_text().splitlines()) == 1        # hlavní skript proběhl jen v rodiči
