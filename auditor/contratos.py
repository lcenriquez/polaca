"""Extrae contratos, licitaciones y adjudicaciones (y metas del PMD) con Muse Spark a SQLite.

Uso:
    python auditor/contratos.py licitaciones-ago-2026.pdf [--paginas 1-3] [--municipio 17007]
    python auditor/contratos.py PLAN_MUNICIPAL_DE_DESARROLLO_2024-2027.pdf --pmd [--municipio 21019]

Mismo patrón que extraer.py: el PDF se lee por tramos y cada fila trae un
fragmento literal que se verifica contra el texto de la página citada
(ok, sin_texto o no_encontrado). Solo se guarda lo que está escrito.
"""
import argparse
import base64
import json
import re
from datetime import datetime, timezone

from pypdf import PdfReader

import extraer
import llm
from extraer import TRAMO, normalizar, nulo, pdf_tramo, plano, verificar

PROCEDIMIENTOS = ["licitacion", "invitacion", "adjudicacion_directa"]

ESQUEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["contratos"],
    "properties": {
        "contratos": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["numero", "objeto", "proveedor", "monto_con_iva_mxn", "monto_sin_iva_mxn", "monto_planeado_mxn", "fecha",
                             "procedimiento", "area_solicitante", "partida_presupuestal", "pagina", "fragmento"],
                "properties": {
                    "numero": nulo("string", description="Número o clave del contrato, licitación o adjudicación tal como está impreso."),
                    "objeto": {"type": "string", "description": "Qué se contrata, en una oración."},
                    "proveedor": nulo("string", description="Empresa o persona adjudicada, tal como aparece."),
                    "monto_con_iva_mxn": nulo("number", description="Monto total con IVA en pesos."),
                    "monto_sin_iva_mxn": nulo("number", description="Monto antes de IVA (subtotal) en pesos."),
                    "monto_planeado_mxn": nulo("number", description="Monto planeado o autorizado de un proyecto de obra (no contratado)."),
                    "fecha": nulo("string", description="AAAA-MM-DD: fecha del contrato, fallo o convocatoria."),
                    "procedimiento": {"type": ["string", "null"], "enum": PROCEDIMIENTOS + [None]},
                    "area_solicitante": nulo("string"),
                    "partida_presupuestal": nulo("string", description="Partida o capítulo del gasto impreso, p. ej. '5411' o '6000'."),
                    "pagina": {"type": "integer", "description": "Página dentro de ESTE archivo (1 = primera)."},
                    "fragmento": {"type": "string",
                                  "description": "Copia literal (máx. 300 caracteres) que incluya el número o el monto tal como están impresos."},
                },
            },
        }
    },
}

INSTRUCCIONES = """Eres un extractor de datos de documentos oficiales de un Ayuntamiento de México.
Extrae cada contrato, licitación, invitación o adjudicación directa que aparezca en el archivo (convocatorias, fallos, padrones, informes de obra pública o tablas de contratos).
También cada proyecto de obra pública con folio o número y monto (p. ej. la Matriz de Inversión para el Desarrollo Social, FISMDF): su folio va en "numero" y su monto planeado en "monto_planeado_mxn".

Reglas estrictas:
- Usa solo lo que está escrito en el documento. Si un dato no aparece, usa null. Nunca adivines, calcules ni completes.
- "fragmento": copia LITERAL de texto del documento, de la página indicada, sin corregir ni resumir.
  En tablas, copia el texto seguido de UNA sola celda (p. ej. el monto o el objeto); nunca juntes celdas ni encabezados.
- "pagina": página dentro de este archivo (la primera es 1), no el folio impreso.
- "procedimiento": "licitacion" (licitación pública), "invitacion" (invitación restringida o a cuando menos tres) o "adjudicacion_directa", solo si el documento lo dice.
- "monto_con_iva_mxn" solo si el monto impreso de un contrato incluye IVA o es el total; "monto_sin_iva_mxn" si es subtotal o dice "sin IVA".
  Un monto planeado, autorizado o a invertir de un proyecto va solo en "monto_planeado_mxn". Números sin comas ni símbolos.
- "area_solicitante": dependencia que solicita o ejecuta, tal como aparece.
- Registra cada contrato una sola vez por archivo. Lenguaje neutral y descriptivo. Si no hay contratos, devuelve una lista vacía."""

ESQUEMA_PMD = {
    "type": "object",
    "additionalProperties": False,
    "required": ["metas"],
    "properties": {
        "metas": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["meta", "tema", "cantidad", "unidad", "pagina", "fragmento"],
                "properties": {
                    "meta": {"type": "string", "description": "La meta o compromiso, en una oración."},
                    "tema": {"type": "string", "description": "2 a 4 palabras del documento que nombran qué se hará, p. ej. 'luminarias LED'."},
                    "cantidad": {"type": "number", "description": "La cifra medible prometida."},
                    "unidad": nulo("string", description="Unidad de la cifra, p. ej. 'kilómetros', 'pozos', '%'."),
                    "pagina": {"type": "integer", "description": "Página dentro de ESTE archivo (1 = primera)."},
                    "fragmento": {"type": "string", "description": "Copia literal (máx. 300 caracteres) que incluya la cifra."},
                },
            },
        }
    },
}

INSTRUCCIONES_PMD = """Eres un extractor de datos del Plan Municipal de Desarrollo de un Ayuntamiento de México.
Extrae solo metas o compromisos MEDIBLES: los que traen una cifra concreta de algo que se construirá, comprará, instalará o atenderá (p. ej. "rehabilitar 20 km de calles").

Reglas estrictas:
- Sin cifra concreta en el texto, no es meta medible: no la incluyas. No incluyas diagnósticos, estadísticas del pasado ni porcentajes de población.
- "fragmento": copia LITERAL del documento que incluya la cifra, de la página indicada.
- "pagina": página dentro de este archivo (la primera es 1).
- "tema": palabras tomadas del documento, no inventadas.
- Lenguaje neutral. Si no hay metas medibles, devuelve una lista vacía."""


def conectar(con=None):
    """Crea contratos y metas_pmd en `con` (o en una conexión nueva a la base del auditor)."""
    con = con or extraer.conectar()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS contratos (
            id INTEGER PRIMARY KEY,
            documento_id INTEGER NOT NULL REFERENCES documentos(id),
            municipio_id TEXT,
            numero TEXT, objeto TEXT NOT NULL, proveedor TEXT,
            monto_con_iva_mxn REAL, monto_sin_iva_mxn REAL, monto_planeado_mxn REAL, fecha TEXT,
            procedimiento TEXT, area_solicitante TEXT, partida_presupuestal TEXT,
            capitulo TEXT,                    -- '5000' si la partida impresa empieza con 5
            pagina INTEGER NOT NULL, fragmento TEXT NOT NULL,
            verificacion TEXT NOT NULL CHECK (verificacion IN ('ok', 'sin_texto', 'no_encontrado')),
            modelo TEXT NOT NULL, extraido TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS metas_pmd (
            id INTEGER PRIMARY KEY,
            documento_id INTEGER NOT NULL REFERENCES documentos(id),
            municipio_id TEXT,
            meta TEXT NOT NULL, tema TEXT NOT NULL, cantidad REAL, unidad TEXT,
            pagina INTEGER NOT NULL, fragmento TEXT NOT NULL,
            verificacion TEXT NOT NULL CHECK (verificacion IN ('ok', 'sin_texto', 'no_encontrado')),
            modelo TEXT NOT NULL, extraido TEXT NOT NULL
        );
    """)
    if "monto_planeado_mxn" not in {c[1] for c in con.execute("PRAGMA table_info(contratos)")}:
        con.execute("ALTER TABLE contratos ADD COLUMN monto_planeado_mxn REAL")
    return con


def capitulo(partida: str | None) -> str | None:
    """'5411' → '5000'; '6000' → '6000'. Solo si es una clave numérica del clasificador (4 o 5 dígitos)."""
    m = re.fullmatch(r"\s*([1-9])\d{3,4}\s*", partida or "")
    return f"{m.group(1)}000" if m else None


def clave_numero(numero: str | None) -> str | None:
    """Número de contrato comparable entre documentos: sin espacios, guiones ni diagonales.

    Claves cortas ("1", "A-2") se descartan: coincidirían por casualidad. Un folio MIDS tiene 5 dígitos."""
    clave = re.sub(r"[^a-z0-9]", "", plano(numero))
    return clave if len(clave) >= 5 else None


def extraer_tramo(archivo: str, reader: PdfReader, inicio: int, fin: int, pmd: bool = False) -> list[dict]:
    nombre, esquema, instrucciones = ("metas", ESQUEMA_PMD, INSTRUCCIONES_PMD) if pmd else ("contratos", ESQUEMA, INSTRUCCIONES)
    datos = base64.b64encode(pdf_tramo(reader, inicio, fin)).decode()
    resp = llm.llamar(
        f"{nombre}:{archivo}:{inicio}-{fin}",
        model=llm.MODELO_PUBLICO,
        reasoning_effort="medium",
        messages=[
            {"role": "system", "content": instrucciones},
            {"role": "user", "content": [
                {"type": "text", "text": f"Archivo: {archivo}, páginas {inicio} a {fin} del documento original."},
                {"type": "file", "file": {"filename": archivo, "file_data": f"data:application/pdf;base64,{datos}"}},
            ]},
        ],
        response_format={"type": "json_schema", "json_schema": {"name": nombre, "strict": True, "schema": esquema}},
    )
    filas = json.loads(resp["choices"][0]["message"]["content"])[nombre]
    textos = {inicio + i: normalizar(reader.pages[inicio - 1 + i].extract_text() or "")
              for i in range(fin - inicio + 1)}
    for f in filas:
        f["pagina"], f["verificacion"] = verificar(f["fragmento"], textos, inicio - 1 + f["pagina"])
        if f["verificacion"] == "ok" and not montos_impresos(f, textos.get(f["pagina"], "")):
            f["verificacion"] = "no_encontrado"  # el fragmento está, pero algún monto no aparece en su página
    return filas


def montos_impresos(fila: dict, texto_pagina: str) -> bool:
    """Cada monto extraído debe estar impreso en la página citada (con o sin comas de miles)."""
    for campo in ("monto_con_iva_mxn", "monto_sin_iva_mxn", "monto_planeado_mxn"):
        v = fila.get(campo)
        if v is not None and not any(normalizar(f) in texto_pagina for f in (f"{v:,.2f}", f"{v:.2f}")):
            return False
    return True


def guardar(con, archivo: str, paginas: int, filas: list[dict], rango: tuple[int, int],
            municipio: str | None = None, pmd: bool = False):
    ruta_m = extraer.RAW / "manifiesto.json"
    manifiesto = ({m["archivo"]: m for m in json.loads(ruta_m.read_text())} if ruta_m.exists() else {}).get(archivo, {})
    con.execute("""INSERT INTO documentos (archivo, url, sha256, paginas) VALUES (?, ?, ?, ?)
                   ON CONFLICT(archivo) DO UPDATE SET url=excluded.url, sha256=excluded.sha256, paginas=excluded.paginas""",
                (archivo, manifiesto.get("url"), manifiesto.get("sha256"), paginas))
    doc_id = con.execute("SELECT id FROM documentos WHERE archivo = ?", (archivo,)).fetchone()[0]
    if municipio and "municipio_id" in {c[1] for c in con.execute("PRAGMA table_info(documentos)")}:
        con.execute("UPDATE documentos SET municipio_id = ? WHERE id = ?", (municipio, doc_id))
    tabla = "metas_pmd" if pmd else "contratos"
    con.execute(f"DELETE FROM {tabla} WHERE documento_id = ? AND pagina BETWEEN ? AND ?", (doc_id, *rango))
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if pmd:
        con.executemany("""INSERT INTO metas_pmd (documento_id, municipio_id, meta, tema, cantidad, unidad, pagina,
                           fragmento, verificacion, modelo, extraido) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [(doc_id, municipio, f["meta"], f["tema"], f["cantidad"], f["unidad"], f["pagina"],
                          f["fragmento"], f["verificacion"], llm.MODELO_PUBLICO, ahora) for f in filas])
    else:
        con.executemany("""INSERT INTO contratos (documento_id, municipio_id, numero, objeto, proveedor,
                           monto_con_iva_mxn, monto_sin_iva_mxn, monto_planeado_mxn, fecha, procedimiento,
                           area_solicitante, partida_presupuestal, capitulo, pagina, fragmento, verificacion, modelo,
                           extraido) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [(doc_id, municipio, f["numero"], f["objeto"], f["proveedor"], f["monto_con_iva_mxn"],
                          f["monto_sin_iva_mxn"], f.get("monto_planeado_mxn"), f["fecha"], f["procedimiento"], f["area_solicitante"],
                          f["partida_presupuestal"], capitulo(f["partida_presupuestal"]), f["pagina"],
                          f["fragmento"], f["verificacion"], llm.MODELO_PUBLICO, ahora) for f in filas])
    con.commit()


def leer(archivo: str, rango: tuple[int, int] | None = None, municipio: str | None = None, pmd: bool = False,
         antes_de_cada_tramo=lambda i, fin, total: None) -> list[dict]:
    """Lee el PDF por tramos y guarda. `antes_de_cada_tramo` deja al indexador revisar topes y avisar."""
    reader = PdfReader(extraer.RAW / archivo)
    total = len(reader.pages)
    ini, fin = rango or (1, total)
    fin = min(fin, total)
    filas = []
    for i in range(ini, fin + 1, TRAMO):
        antes_de_cada_tramo(i, min(i + TRAMO - 1, fin), total)
        filas += extraer_tramo(archivo, reader, i, min(i + TRAMO - 1, fin), pmd=pmd)
    with conectar() as con:
        guardar(con, archivo, total, filas, (ini, fin), municipio, pmd)
    return filas


def main():
    p = argparse.ArgumentParser()
    p.add_argument("archivo", help="nombre del PDF dentro de datos/raw/")
    p.add_argument("--paginas", help="rango, p. ej. 1-3 (por defecto todo)")
    p.add_argument("--municipio", help="clave INEGI, p. ej. 17007")
    p.add_argument("--pmd", action="store_true", help="el archivo es un Plan Municipal de Desarrollo")
    args = p.parse_args()
    rango = tuple(map(int, args.paginas.split("-"))) if args.paginas else None
    filas = leer(args.archivo, rango, args.municipio, args.pmd)
    estados = {e: sum(f["verificacion"] == e for f in filas) for e in ("ok", "sin_texto", "no_encontrado")}
    print(f"{len(filas)} {'metas' if args.pmd else 'contratos'}, verificación de fragmento: {estados}")
    print("Gasto acumulado:", llm.resumen_costos())


if __name__ == "__main__":
    main()
