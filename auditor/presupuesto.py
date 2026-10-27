"""Extrae partidas del Presupuesto de Egresos 2026 (versión ciudadana) a SQLite.
Uso: python auditor/presupuesto.py VERSION_CIUDADANA_PRESUPUESTO_EGRESOS_2026.pdf [--paginas 1-3]
Infografía: Muse Spark lee el PDF como en extraer.py y cada fragmento se
verifica con verificar() de extraer.py contra el texto de la página.
"""
import argparse
import base64
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import llm
import extraer
from extraer import TRAMO, conectar as _conectar_base, normalizar, nulo, pdf_tramo, verificar
from pypdf import PdfReader

RAW = extraer.RAW

ESQUEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["partidas"],
    "properties": {
        "partidas": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["capitulo", "nombre", "monto_mxn", "pagina", "fragmento"],
                "properties": {
                    "capitulo": nulo("string", description="Capítulo del Clasificador por Objeto del Gasto, p. ej. '1000'."),
                    "nombre": {"type": "string", "description": "Nombre completo de la partida tal como aparece, sin abreviar ni usar puntos suspensivos, p. ej. 'Servicios Personales'."},
                    "monto_mxn": nulo("number", description="Monto en pesos, sin comas ni símbolo."),
                    "pagina": {"type": "integer", "description": "Página dentro de ESTE archivo (1 = primera)."},
                    "fragmento": {"type": "string",
                                  "description": "Copia literal breve (máx. 120 caracteres) que incluya el monto tal como está impreso."},
                },
            },
        }
    },
}

INSTRUCCIONES = """Eres un extractor de datos de documentos oficiales del Ayuntamiento de Atlixco, Puebla.
Extrae las partidas del Clasificador por Objeto del Gasto (capítulos 1000 a 9000) que aparezcan en el archivo, con su nombre y monto.

Reglas estrictas:
- Usa solo lo que está escrito en el documento. Si un dato no aparece, usa null. Nunca adivines ni completes.
- No incluyas totales de ingresos o egresos, porcentajes ni dependencias (p. ej. Tesorería Municipal): solo capítulos del Clasificador por Objeto del Gasto.
- "fragmento" debe ser una copia LITERAL de texto del documento que incluya el monto tal como está impreso; si el nombre y el monto no están juntos en el diseño, usa solo el monto impreso.
- "pagina" es la página dentro de este archivo (la primera página del archivo es 1).
- "monto_mxn": número sin comas ni símbolos.
- "nombre": únicamente el rótulo del capítulo en español, completo y tal como está impreso en la infografía; nunca la palabra "null" ni texto de otro tema.
- Lenguaje neutral y descriptivo. Si no hay partidas, devuelve una lista vacía."""


def conectar() -> sqlite3.Connection:
    con = _conectar_base()
    con.execute("""
        CREATE TABLE IF NOT EXISTS partidas (
            id INTEGER PRIMARY KEY,
            documento_id INTEGER NOT NULL REFERENCES documentos(id),
            capitulo TEXT,
            nombre TEXT NOT NULL,
            monto_mxn REAL,
            pagina INTEGER NOT NULL,
            fragmento TEXT NOT NULL,
            verificacion TEXT NOT NULL CHECK (verificacion IN ('ok', 'sin_texto', 'no_encontrado')),
            verificacion_nombre TEXT NOT NULL DEFAULT 'no_encontrado'
                CHECK (verificacion_nombre IN ('ok', 'sin_texto', 'no_encontrado')),
            modelo TEXT NOT NULL,
            extraido TEXT NOT NULL
        )""")
    # DBs creadas antes de verificacion_nombre no la tienen.
    if "verificacion_nombre" not in {f[1] for f in con.execute("PRAGMA table_info(partidas)")}:
        con.execute("ALTER TABLE partidas ADD COLUMN verificacion_nombre TEXT NOT NULL DEFAULT 'no_encontrado' "
                    "CHECK (verificacion_nombre IN ('ok', 'sin_texto', 'no_encontrado'))")
    con.commit()
    return con


def verificar_nombre(nombre: str, paginas: dict[int, str], pagina: int) -> str:
    """'ok' solo si el nombre aparece en el texto de SU página (no en otra del tramo).

    No reusa verificar(): esta busca en todas las páginas y daría por bueno un
    nombre que solo aparece en la prosa de otra página (p. ej. 'Participaciones
    y Aportaciones' se menciona en la pág. 5, pero no es rótulo en la 6).
    """
    if normalizar(nombre) in paginas.get(pagina, ""):
        return "ok"
    return "sin_texto" if len(paginas.get(pagina, "")) < 20 else "no_encontrado"


def extraer_tramo(archivo: str, reader: PdfReader, inicio: int, fin: int) -> list[dict]:
    datos = base64.b64encode(pdf_tramo(reader, inicio, fin)).decode()
    resp = llm.llamar(
        f"presupuesto:{archivo}:{inicio}-{fin}",
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
                         "json_schema": {"name": "partidas", "strict": True, "schema": ESQUEMA}},
    )
    partidas = json.loads(resp["choices"][0]["message"]["content"])["partidas"]
    textos = {inicio + i: normalizar(reader.pages[inicio - 1 + i].extract_text() or "")
              for i in range(fin - inicio + 1)}
    for a in partidas:
        a["pagina"], a["verificacion"] = verificar(a["fragmento"], textos, inicio - 1 + a["pagina"])
        a["verificacion_nombre"] = verificar_nombre(a["nombre"], textos, a["pagina"])
    return partidas


def guardar(con, archivo: str, paginas: int, partidas: list[dict], rango: tuple[int, int]):
    manifiesto_path = extraer.RAW / "manifiesto.json"
    manifiesto = ({m["archivo"]: m for m in json.loads(manifiesto_path.read_text())}
                  if manifiesto_path.exists() else {}).get(archivo, {})
    con.execute("""INSERT INTO documentos (archivo, url, sha256, paginas) VALUES (?, ?, ?, ?)
                   ON CONFLICT(archivo) DO UPDATE SET url=excluded.url, sha256=excluded.sha256, paginas=excluded.paginas""",
                (archivo, manifiesto.get("url"), manifiesto.get("sha256"), paginas))
    doc_id = con.execute("SELECT id FROM documentos WHERE archivo = ?", (archivo,)).fetchone()[0]
    con.execute("DELETE FROM partidas WHERE documento_id = ? AND pagina BETWEEN ? AND ?", (doc_id, *rango))
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.executemany("""INSERT INTO partidas (documento_id, capitulo, nombre, monto_mxn, pagina, fragmento,
                       verificacion, verificacion_nombre, modelo, extraido) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(doc_id, a["capitulo"], a["nombre"], a["monto_mxn"], a["pagina"], a["fragmento"],
                      a["verificacion"], a.get("verificacion_nombre", "no_encontrado"),
                      llm.MODELO_PUBLICO, ahora) for a in partidas])
    con.commit()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("archivo", help="nombre del PDF dentro de datos/raw/")
    p.add_argument("--paginas", help="rango, p. ej. 1-3 (por defecto todo)")
    args = p.parse_args()

    reader = PdfReader(extraer.RAW / args.archivo)
    total = len(reader.pages)
    ini, fin = map(int, args.paginas.split("-")) if args.paginas else (1, total)
    fin = min(fin, total)

    partidas = []
    for i in range(ini, fin + 1, TRAMO):
        tramo = extraer_tramo(args.archivo, reader, i, min(i + TRAMO - 1, fin))
        print(f"  págs {i}-{min(i + TRAMO - 1, fin)}: {len(tramo)} partidas")
        partidas += tramo

    with conectar() as con:
        guardar(con, args.archivo, total, partidas, (ini, fin))
    estados = {e: sum(a["verificacion"] == e for a in partidas) for e in ("ok", "sin_texto", "no_encontrado")}
    nombres = {e: sum(a.get("verificacion_nombre") == e for a in partidas) for e in ("ok", "sin_texto", "no_encontrado")}
    suma = sum(a["monto_mxn"] or 0 for a in partidas)
    print(f"{len(partidas)} partidas, suma de montos extraídos: ${suma:,.2f}, verificación de fragmento: {estados}, "
          f"verificación de nombre: {nombres} → {extraer.DB}")
    print("Gasto acumulado:", llm.resumen_costos())


if __name__ == "__main__":
    main()
