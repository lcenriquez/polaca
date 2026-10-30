"""Extrae acuerdos de cabildo de un PDF con Muse Spark y los guarda en SQLite.

Uso:
    python auditor/extraer.py GACETA_AGOSTO-DICIEMBRE_2025.pdf [--paginas 1-20]

El PDF se parte en tramos de TRAMO páginas (Meta solo ve texto de las primeras
100 e imágenes de las primeras 50 de cada PDF). Cada acuerdo trae un fragmento
textual que se verifica contra el texto de la página citada: si no aparece ahí,
queda como no_encontrado (o sin_texto si la página es escaneada).
"""
import argparse
import base64
import io
import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader, PdfWriter

import llm

RAIZ = Path(__file__).resolve().parent.parent
# Todo lo persistente vive en DATA_DIR (en Fly: /data, el volumen). Sin la variable, la carpeta datos/ del repo.
DATA_DIR = Path(os.environ.get("DATA_DIR", RAIZ / "datos"))
RAW = DATA_DIR / "raw"
DB = DATA_DIR / "auditor.db"
TRAMO = 20


def nulo(tipo, **extra):
    return {"type": [tipo, "null"], **extra}


ESQUEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["acuerdos"],
    "properties": {
        "acuerdos": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["acuerdo", "tipo_sesion", "fecha_sesion", "propuesto_por", "monto_mxn",
                             "proveedor", "resultado_votacion", "pagina", "fragmento"],
                "properties": {
                    "acuerdo": {"type": "string", "description": "Qué se aprobó o resolvió, en una oración."},
                    "tipo_sesion": {"type": ["string", "null"],
                                    "enum": ["ordinaria", "extraordinaria", "solemne", "abierta", None]},
                    "fecha_sesion": nulo("string", description="AAAA-MM-DD"),
                    "propuesto_por": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["nombre", "cargo"],
                            "properties": {"nombre": {"type": "string"}, "cargo": nulo("string")},
                        },
                    },
                    "monto_mxn": nulo("number"),
                    "proveedor": nulo("string"),
                    "resultado_votacion": {"type": ["string", "null"],
                                           "enum": ["unanimidad", "mayoria", "rechazado", "aprobado", None]},
                    "pagina": {"type": "integer", "description": "Página dentro de ESTE archivo (1 = primera)."},
                    "fragmento": {"type": "string",
                                  "description": "Copia literal del documento (máx. 300 caracteres) que respalda el acuerdo."},
                },
            },
        }
    },
}

INSTRUCCIONES = """Eres un extractor de datos de documentos oficiales del Ayuntamiento de Atlixco, Puebla.
Extrae cada acuerdo, dictamen o punto aprobado (o rechazado) por el Cabildo que aparezca en el archivo.

Reglas estrictas:
- Usa solo lo que está escrito en el documento. Si un dato no aparece, usa null. Nunca adivines ni completes.
- "fragmento" debe ser una copia LITERAL de texto del documento, sin corregir ortografía ni resumir, de la página indicada.
- "pagina" es la página dentro de este archivo (la primera página del archivo es 1), no el folio impreso.
- "propuesto_por": personas que presentan el dictamen o propuesta, con el cargo tal como aparece. Lista vacía si no se indica.
- "monto_mxn": solo si el acuerdo menciona un monto en pesos; número sin comas ni símbolos.
- "resultado_votacion": "unanimidad" o "mayoria" si el texto lo dice; "aprobado" si dice aprobado sin detalle de votación; "rechazado" si se rechazó.
- "fecha_sesion": fecha de la sesión de Cabildo en la que se aprobó, en formato AAAA-MM-DD.
- Un índice o tabla de contenido que enumera acuerdos también cuenta; registra cada acuerdo una sola vez por archivo.
- Lenguaje neutral y descriptivo. Si no hay acuerdos, devuelve una lista vacía."""


def normalizar(texto: str) -> str:
    """Minúsculas y sin espacios: pypdf mete espacios espurios ("CAB ILDO", "Puebla .")."""
    texto = unicodedata.normalize("NFKC", texto).lower()
    texto = re.sub(r"-\s*\n", "", texto)  # palabras partidas al final de línea
    return re.sub(r"\s+", "", texto)


def verificar(fragmento: str, paginas: dict[int, str], pagina: int) -> tuple[int, str]:
    """Devuelve (pagina_corregida, verificacion): 'ok', 'sin_texto' (página escaneada) o 'no_encontrado'."""
    frag = normalizar(fragmento)
    if not frag:
        return pagina, "no_encontrado"
    if frag in paginas.get(pagina, ""):
        return pagina, "ok"
    encontradas = [p for p, t in paginas.items() if frag in t]
    if len(encontradas) == 1:
        return encontradas[0], "ok"
    # El fragmento puede empezar en la página citada y terminar en la siguiente.
    if frag in paginas.get(pagina, "") + paginas.get(pagina + 1, ""):
        return pagina, "ok"
    # ponytail: páginas escaneadas no se pueden cotejar sin OCR; agregar OCR si son muchas.
    return pagina, "sin_texto" if len(paginas.get(pagina, "")) < 20 else "no_encontrado"


def pdf_tramo(reader: PdfReader, inicio: int, fin: int) -> bytes:
    w = PdfWriter()
    for i in range(inicio - 1, fin):
        w.add_page(reader.pages[i])
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def extraer_tramo(archivo: str, reader: PdfReader, inicio: int, fin: int) -> list[dict]:
    datos = base64.b64encode(pdf_tramo(reader, inicio, fin)).decode()
    resp = llm.llamar(
        f"extraer:{archivo}:{inicio}-{fin}",
        model=llm.MODELO_PUBLICO,
        reasoning_effort="medium",
        messages=[
            {"role": "system", "content": INSTRUCCIONES},
            {"role": "user", "content": [
                {"type": "text", "text": f"Archivo: {archivo}, páginas {inicio} a {fin} del documento original."},
                {"type": "file", "file": {"filename": archivo, "file_data": f"data:application/pdf;base64,{datos}"}},
            ]},
        ],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "acuerdos", "strict": True, "schema": ESQUEMA}},
    )
    acuerdos = json.loads(resp["choices"][0]["message"]["content"])["acuerdos"]
    textos = {inicio + i: normalizar(reader.pages[inicio - 1 + i].extract_text() or "")
              for i in range(fin - inicio + 1)}
    for a in acuerdos:
        a["pagina"], a["verificacion"] = verificar(a["fragmento"], textos, inicio - 1 + a["pagina"])
    return acuerdos


# Palabras que no distinguen un acuerdo de otro.
VACIAS = set("""a al con de del el en la las lo los o para por que se su sus un una y
             municipio ayuntamiento atlixco puebla reglamento cabildo regula aprobo aprueba aprobado aprobacion expide emitio""".split())


def plano(texto: str | None) -> str:
    """Sin acentos, minúsculas y espacios colapsados."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", texto).strip()


def palabras(texto: str | None) -> set[str]:
    return set(re.findall(r"\w+", plano(texto))) - VACIAS


def parecido(a: str, b: str) -> float:
    """Fracción de palabras del texto más corto que aparecen en el otro."""
    pa, pb = palabras(a), palabras(b)
    return len(pa & pb) / min(len(pa), len(pb)) if pa and pb else 0.0


def agrupar(con):
    """Agrupa menciones del mismo acuerdo (índice, dictamen, cierre) sin llamar a la API.

    Misma fecha de sesión (o mismo documento si alguna fecha es null) y ≥80 % de palabras en común.
    La mención canónica es la de fragmento verificado con más campos llenos.
    """
    filas = con.execute("""SELECT id, documento_id, fecha_sesion, acuerdo, verificacion = 'ok',
                                  (tipo_sesion IS NOT NULL) + (fecha_sesion IS NOT NULL) + (monto_mxn IS NOT NULL)
                                  + (proveedor IS NOT NULL) + (resultado_votacion IS NOT NULL) + (propuesto_por != '[]')
                           FROM acuerdos ORDER BY id""").fetchall()
    # ponytail: heurística de palabras; si junta acuerdos distintos, pedirle a Muse que agrupe con cita.
    grupos = []  # [{"fecha", "docs", "miembros"}]
    for f in filas:
        id_, doc, fecha, texto = f[:4]
        for g in grupos:
            compatible = fecha == g["fecha"] if fecha and g["fecha"] else doc in g["docs"]
            if compatible and any(parecido(texto, m[3]) >= 0.8 for m in g["miembros"]):
                g["miembros"].append(f)
                g["docs"].add(doc)
                g["fecha"] = g["fecha"] or fecha
                break
        else:
            grupos.append({"fecha": fecha, "docs": {doc}, "miembros": [f]})
    for g in grupos:
        canonico = max(g["miembros"], key=lambda m: (m[4], m[5], -m[0]))[0]
        con.executemany("UPDATE acuerdos SET grupo_id = ? WHERE id = ?", [(canonico, m[0]) for m in g["miembros"]])


def conectar() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS documentos (
            id INTEGER PRIMARY KEY,
            archivo TEXT NOT NULL UNIQUE,
            url TEXT,
            sha256 TEXT,
            paginas INTEGER
        );
        CREATE TABLE IF NOT EXISTS acuerdos (
            id INTEGER PRIMARY KEY,
            documento_id INTEGER NOT NULL REFERENCES documentos(id),
            acuerdo TEXT NOT NULL,
            tipo_sesion TEXT,
            fecha_sesion TEXT,
            propuesto_por TEXT NOT NULL,      -- JSON: [{"nombre", "cargo"}]
            monto_mxn REAL,
            proveedor TEXT,
            resultado_votacion TEXT,
            pagina INTEGER NOT NULL,
            fragmento TEXT NOT NULL,
            verificacion TEXT NOT NULL CHECK (verificacion IN ('ok', 'sin_texto', 'no_encontrado')),
            modelo TEXT NOT NULL,
            extraido TEXT NOT NULL,
            grupo_id INTEGER                  -- id de la mención canónica del mismo acuerdo
        );
        -- Un acuerdo por grupo; sus citas son las filas de acuerdos con ese grupo_id.
        CREATE VIEW IF NOT EXISTS acuerdos_canonicos AS
            SELECT a.*, (SELECT count(*) FROM acuerdos m WHERE m.grupo_id = a.id) AS menciones
            FROM acuerdos a WHERE a.id = a.grupo_id;
    """)
    return con


def guardar(con, archivo: str, paginas: int, acuerdos: list[dict], rango: tuple[int, int]):
    manifiesto = {m["archivo"]: m for m in json.loads((RAW / "manifiesto.json").read_text())}.get(archivo, {})
    con.execute("""INSERT INTO documentos (archivo, url, sha256, paginas) VALUES (?, ?, ?, ?)
                   ON CONFLICT(archivo) DO UPDATE SET url=excluded.url, sha256=excluded.sha256, paginas=excluded.paginas""",
                (archivo, manifiesto.get("url"), manifiesto.get("sha256"), paginas))
    doc_id = con.execute("SELECT id FROM documentos WHERE archivo = ?", (archivo,)).fetchone()[0]
    # Re-extraer un rango reemplaza lo anterior de ese rango (gratis gracias a la caché).
    con.execute("DELETE FROM acuerdos WHERE documento_id = ? AND pagina BETWEEN ? AND ?", (doc_id, *rango))
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.executemany("""INSERT INTO acuerdos (documento_id, acuerdo, tipo_sesion, fecha_sesion, propuesto_por, monto_mxn,
                       proveedor, resultado_votacion, pagina, fragmento, verificacion, modelo, extraido)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(doc_id, a["acuerdo"], a["tipo_sesion"], a["fecha_sesion"],
                      json.dumps(a["propuesto_por"], ensure_ascii=False), a["monto_mxn"], a["proveedor"],
                      a["resultado_votacion"], a["pagina"], a["fragmento"], a["verificacion"],
                      llm.MODELO_PUBLICO, ahora) for a in acuerdos])
    agrupar(con)
    con.commit()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("archivo", help="nombre del PDF dentro de datos/raw/")
    p.add_argument("--paginas", help="rango, p. ej. 1-20 (por defecto todo)")
    args = p.parse_args()

    reader = PdfReader(RAW / args.archivo)
    total = len(reader.pages)
    ini, fin = map(int, args.paginas.split("-")) if args.paginas else (1, total)
    fin = min(fin, total)

    acuerdos = []
    for i in range(ini, fin + 1, TRAMO):
        # ponytail: un acuerdo que cruza el borde entre tramos puede salir duplicado o partido; deduplicar si pasa.
        tramo = extraer_tramo(args.archivo, reader, i, min(i + TRAMO - 1, fin))
        print(f"  págs {i}-{min(i + TRAMO - 1, fin)}: {len(tramo)} acuerdos")
        acuerdos += tramo

    with conectar() as con:
        guardar(con, args.archivo, total, acuerdos, (ini, fin))
    estados = {e: sum(a["verificacion"] == e for a in acuerdos) for e in ("ok", "sin_texto", "no_encontrado")}
    print(f"{len(acuerdos)} acuerdos, verificación de fragmento: {estados} → {DB}")
    print("Gasto acumulado:", llm.resumen_costos())


if __name__ == "__main__":
    main()
