"""Jede Bibliothek, die app.py und oa_*.py importieren, steht in requirements.txt (die Cloud installiert nur diese Datei)."""
import ast
import sys
from pathlib import Path

ORDNER = Path(__file__).resolve().parent.parent
# Importname → Paketname auf PyPI, wo er abweicht
PAKET = {"yaml": "pyyaml"}


def _importe(datei: Path) -> set[str]:
    namen: set[str] = set()
    for knoten in ast.walk(ast.parse(datei.read_text(encoding="utf-8"))):
        if isinstance(knoten, ast.Import):
            namen.update(a.name.split(".")[0] for a in knoten.names)
        elif isinstance(knoten, ast.ImportFrom) and knoten.level == 0 and knoten.module:
            namen.add(knoten.module.split(".")[0])
    return namen


def test_alle_fremden_importe_stehen_in_requirements_txt():
    eigene = {p.stem for p in ORDNER.glob("*.py")}
    gebraucht = set()
    for datei in [ORDNER / "app.py", *ORDNER.glob("oa_*.py")]:
        gebraucht |= {n for n in _importe(datei) if n not in sys.stdlib_module_names and n not in eigene and n != "__future__"}
    zeilen = (ORDNER / "requirements.txt").read_text(encoding="utf-8").splitlines()
    eingetragen = {z.split(">")[0].split("=")[0].split("<")[0].strip().lower() for z in zeilen if z.strip() and not z.startswith("#")}
    assert {PAKET.get(n, n).lower() for n in gebraucht} <= eingetragen
    assert gebraucht == {"streamlit", "yaml"}  # sonst Test und Liste bewusst nachziehen


def test_requirements_txt_ist_ungepinnt():
    for zeile in (ORDNER / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if zeile.strip():
            assert ">=" in zeile and "==" not in zeile
