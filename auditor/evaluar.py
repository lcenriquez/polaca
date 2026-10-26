"""Compara la extracción en SQLite contra datos/eval/etiquetado.csv (etiquetado a mano).

Uso:
    python auditor/evaluar.py              # ignora las filas con es_ejemplo=1
    python auditor/evaluar.py --ejemplos   # las incluye (para probar la plantilla)

Cada etiqueta se empareja con una mención extraída del mismo archivo, en la misma
página o una contigua, con ≥50 % de palabras en común en el texto del acuerdo.
La precisión por campo se mide solo sobre las parejas. Null en ambos lados es acierto.
"""
import argparse
import csv
import json
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

from extraer import DB, RAIZ, normalizar, parecido, plano

CSV = RAIZ / "datos" / "eval" / "etiquetado.csv"
CAMPOS = ["pagina", "tipo_sesion", "fecha_sesion", "propuesto_por", "cargo", "monto_mxn",
          "proveedor", "resultado_votacion", "fragmento"]


def nulo(v):
    v = str(v).strip() if v is not None else ""
    return None if v == "" or v.lower() == "null" else v


def lista(v) -> list[str]:
    return sorted(plano(x) for x in (v or "").split(";") if x.strip())


def monto(v):
    v = nulo(v)
    return None if v is None else float(str(v).replace(",", "").replace("$", ""))


def traslapan(a: str, b: str, minimo: int = 20) -> bool:
    """¿Son dos tramos del mismo texto que se enciman? (uno contiene al otro, o el final de uno es el inicio del otro)"""
    if not a or not b:
        return a == b
    if a in b or b in a:
        return True
    m = SequenceMatcher(None, a, b, autojunk=False).find_longest_match()
    return m.size >= minimo and ((m.a + m.size == len(a) and m.b == 0) or (m.b + m.size == len(b) and m.a == 0))


def comparar(campo: str, etiqueta: dict, extraido: dict) -> bool:
    et = etiqueta.get(campo)
    if campo in ("propuesto_por", "cargo"):
        clave = "nombre" if campo == "propuesto_por" else "cargo"
        personas = json.loads(extraido["propuesto_por"])
        return lista(et) == sorted(plano(p[clave]) for p in personas if p[clave])
    if campo == "monto_mxn":
        a, b = monto(et), extraido["monto_mxn"]
        return a == b if a is None or b is None else abs(a - b) < 0.01
    if campo == "pagina":
        return int(et) == extraido["pagina"]
    if campo == "fragmento":
        return traslapan(normalizar(nulo(et) or ""), normalizar(extraido["fragmento"] or ""))
    return plano(nulo(et)) == plano(extraido[campo])


def emparejar(etiquetas: list[dict], extraidos: list[dict]) -> list[tuple[dict, dict | None]]:
    usados, parejas = set(), []
    for et in etiquetas:
        candidatos = [(parecido(et["acuerdo"], ex["acuerdo"]), -abs(int(et["pagina"]) - ex["pagina"]), ex["id"], ex)
                      for ex in extraidos
                      if ex["archivo"] == et["archivo"] and ex["id"] not in usados
                      and abs(int(et["pagina"]) - ex["pagina"]) <= 1]
        candidatos = [c for c in candidatos if c[0] >= 0.5]
        mejor = max(candidatos, key=lambda c: c[:3])[3] if candidatos else None
        if mejor:
            usados.add(mejor["id"])
        parejas.append((et, mejor))
    return parejas


def evaluar(etiquetas: list[dict], extraidos: list[dict]) -> dict:
    parejas = emparejar(etiquetas, extraidos)
    ok = [(et, ex) for et, ex in parejas if ex]
    # Precisión a nivel acuerdo canónico: grupos de los archivos etiquetados con al menos una mención emparejada.
    archivos = {et["archivo"] for et in etiquetas}
    grupos = {ex["grupo_id"] for ex in extraidos if ex["archivo"] in archivos}
    acertados = {ex["grupo_id"] for _, ex in ok}
    return {
        "etiquetas": len(etiquetas),
        "emparejadas": len(ok),
        "recall": len(ok) / len(etiquetas) if etiquetas else 0.0,
        "acuerdos_extraidos": len(grupos),
        "precision_acuerdos": len(acertados) / len(grupos) if grupos else 0.0,
        "campos": {c: (sum(comparar(c, et, ex) for et, ex in ok), len(ok)) for c in CAMPOS},
        "sin_emparejar": [et for et, ex in parejas if not ex],
    }


def cargar_extraidos() -> list[dict]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    filas = con.execute("SELECT a.*, d.archivo FROM acuerdos a JOIN documentos d ON d.id = a.documento_id")
    return [dict(f) for f in filas]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ejemplos", action="store_true", help="incluir filas con es_ejemplo=1")
    args = p.parse_args()
    with CSV.open(newline="") as f:
        etiquetas = [r for r in csv.DictReader(f) if args.ejemplos or nulo(r.get("es_ejemplo")) != "1"]
    if not etiquetas:
        print(f"No hay etiquetas en {CSV.relative_to(RAIZ)} (las de ejemplo se ignoran sin --ejemplos).")
        return
    r = evaluar(etiquetas, cargar_extraidos())
    print(f"Etiquetas: {r['etiquetas']} · emparejadas: {r['emparejadas']} · recall de acuerdos: {r['recall']:.0%}")
    print(f"Precisión de acuerdos: {r['precision_acuerdos']:.0%} de {r['acuerdos_extraidos']} acuerdos canónicos "
          "(asume que etiquetaste completos los archivos del CSV)")
    print(f"\n{'campo':<20}{'aciertos':>9}{'total':>7}{'%':>7}")
    for campo, (bien, total) in r["campos"].items():
        print(f"{campo:<20}{bien:>9}{total:>7}{(bien / total if total else 0):>7.0%}")
    for et in r["sin_emparejar"]:
        print(f"\nSin emparejar: {et['archivo']} p.{et['pagina']}: {et['acuerdo'][:80]}")


if __name__ == "__main__":
    main()
