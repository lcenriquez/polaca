#!/usr/bin/env python3
"""Revisa que la base que se subirá a Fly no traiga correos ni teléfonos personales.

Uso: python scripts/revisar_privacidad.py [ruta/auditor.db]
     (sin argumento: $DATA_DIR/auditor.db, o datos/auditor.db del repo)

Sale con código 1 si encuentra algo; lo que imprime va enmascarado.
Regla, la misma que aplica gobierno.py al extraer:
- Un correo cuyo dominio no es .gob.mx se considera personal, en cualquier tabla.
- Un teléfono (10 dígitos, o 52 + 10) fuera de los campos de contacto
  institucional — contacto_institucional y los campos correo/telefono de
  funcionarios, donde el extractor solo guarda contacto institucional —
  se considera posible dato personal y se reporta.
Los hashes (p. ej. sha256) no cuentan: la secuencia debe ir delimitada por
algo que no sea letra ni dígito.
"""
import os
import re
import sqlite3
import sys
from pathlib import Path

CORREO = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
FONO = re.compile(r"(?<![0-9A-Za-z])\+?\d[\d\s().\-]{8,}\d(?![0-9A-Za-z])")
CONTACTO_OK = {("contacto_institucional", "telefono"), ("contacto_institucional", "fragmento"),
               ("funcionarios", "correo"), ("funcionarios", "telefono")}


def _telefonos(texto: str):
    for m in FONO.finditer(texto):
        d = re.sub(r"\D", "", m.group(0))
        if len(d) == 10 or (len(d) == 12 and d.startswith("52")):
            yield d


def revisar(ruta: Path) -> list[str]:
    hallazgos = []
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    tablas = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    for tabla in tablas:
        cols = [c[1] for c in con.execute(f"PRAGMA table_info({tabla})")
                if "TEXT" in (c[2] or "").upper() or not c[2]]
        for col in cols:
            for rid, valor in con.execute(f'SELECT rowid, "{col}" FROM "{tabla}"'):
                if not isinstance(valor, str):
                    continue
                for correo in CORREO.finditer(valor):
                    if not correo.group(1).lower().endswith(".gob.mx"):
                        hallazgos.append(f"{tabla}.{col} fila {rid}: correo no institucional "
                                         f"({correo.group(0)[:2]}***@{correo.group(1)})")
                if (tabla, col) in CONTACTO_OK:
                    continue
                for d in _telefonos(valor):
                    hallazgos.append(f"{tabla}.{col} fila {rid}: posible teléfono personal "
                                     f"({d[:2]}******{d[-2:]})")
    return hallazgos


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    ruta = (Path(sys.argv[1]) if len(sys.argv) > 1
            else Path(os.environ.get("DATA_DIR", repo / "datos")) / "auditor.db")
    if not ruta.exists():
        print(f"No existe {ruta}", file=sys.stderr)
        return 2
    hallazgos = revisar(ruta)
    for h in hallazgos:
        print("REVISAR:", h)
    if hallazgos:
        print(f"{len(hallazgos)} posible(s) dato(s) personal(es) en {ruta}. No subir esta base hasta resolverlos.")
        return 1
    print(f"Sin correos ni teléfonos personales en {ruta}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
