"""Gobierno cercano: funcionarios, comisiones, funciones, juntas y contacto oficial.

Uso: ../.venv/bin/python gobierno.py    (desde auditor/)

Extrae con Muse Spark (llm.llamar, MODELO_PUBLICO, json_schema) del directorio
de Cabildo, las juntas auxiliares y el contacto publicados en atlixco.gob.mx
(guardados como HTML en datos/raw/), de las comisiones del Reglamento Interior
de Cabildo y de las funciones de cada cargo en la Ley Orgánica Municipal de
Puebla (OJP). Cada fila guarda archivo, página y fragmento, verificados con
verificar() de extraer.py; solo se guardan filas con verificación ok.
Contacto es solo institucional (oficina, teléfono, dirección, horario): nunca
datos personales. Navegar en web.py no llama a la API.
"""
import html as _html
import json
import re
import sqlite3

from pypdf import PdfReader

import explicar
import extraer
import llm
from extraer import normalizar, nulo, pdf_tramo, verificar
import base64

CABILDO_HTML = "Cabildo.html"
JUNTAS_HTML = "Juntas_Auxiliares.html"
CONTACTO_HTML = "Contacto.html"
LEY = "Ley_Organica_Municipal_TEV_08062026.pdf"
REGLAMENTO = "Reglamento_Interior_de_Cabildo_del_Municipio_de_Atlixco_T2_08072025.pdf"


def conectar() -> sqlite3.Connection:
    con = explicar.conectar()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS funcionarios (
            id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, cargo TEXT NOT NULL, comision TEXT,
            archivo TEXT NOT NULL, pagina INTEGER NOT NULL, fragmento TEXT NOT NULL, verificacion TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS comisiones (
            id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, temas TEXT NOT NULL,
            archivo TEXT NOT NULL, pagina INTEGER NOT NULL, fragmento TEXT NOT NULL, verificacion TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS funciones_cargo (
            id INTEGER PRIMARY KEY, cargo TEXT NOT NULL, funcion TEXT NOT NULL,
            archivo TEXT NOT NULL, pagina INTEGER NOT NULL, fragmento TEXT NOT NULL, verificacion TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS juntas_auxiliares (
            id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, presidente TEXT, localidades TEXT NOT NULL,
            archivo TEXT NOT NULL, pagina INTEGER NOT NULL, fragmento TEXT NOT NULL, verificacion TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS contacto_institucional (
            id INTEGER PRIMARY KEY, oficina TEXT NOT NULL, telefono TEXT, direccion TEXT, horario TEXT,
            archivo TEXT NOT NULL, pagina INTEGER NOT NULL, fragmento TEXT NOT NULL, verificacion TEXT NOT NULL);
    """)
    con.commit()
    return con


def texto_html(archivo: str) -> str:
    crudo = (extraer.RAW / archivo).read_text(encoding="utf-8", errors="ignore")
    crudo = re.sub(r"<(script|style).*?</\1>", " ", crudo, flags=re.S | re.I)
    crudo = re.sub(r"<[^>]+>", "\n", crudo)
    return re.sub(r"\s*\n\s*", "\n", _html.unescape(crudo)).strip()


def _guardar(con, tabla: str, columnas: list[str], filas: list[dict]):
    marcas = ",".join("?" * len(columnas))
    con.execute(f"DELETE FROM {tabla}")
    con.executemany(f"INSERT INTO {tabla} ({','.join(columnas)}) VALUES ({marcas})",
                    [tuple(f.get(c) for c in columnas) for f in filas])
    con.commit()
    return [f for f in filas if f["verificacion"] == "ok"]


def _llamar(etiqueta, instrucciones, contenido, esquema, nombre):
    resp = llm.llamar(etiqueta, model=llm.MODELO_PUBLICO, reasoning_effort="medium",
                      messages=[{"role": "system", "content": instrucciones},
                                {"role": "user", "content": contenido}],
                      response_format={"type": "json_schema",
                                       "json_schema": {"name": nombre, "strict": True, "schema": esquema}})
    return json.loads(resp["choices"][0]["message"]["content"])


def _de_html(archivo, instrucciones, esquema, nombre, clave):
    texto = texto_html(archivo)
    datos = _llamar(f"gobierno:{archivo}", instrucciones,
                    [{"type": "text", "text": f"Página web oficial guardada como {archivo} (página 1).\n\n{texto}"}],
                    esquema, nombre)[clave]
    textos = {1: normalizar(texto)}
    for f in datos:
        f["pagina"], f["verificacion"] = verificar(f["fragmento"], textos, 1)
        f["archivo"] = archivo
    return datos


def _de_pdf(archivo, rango, instrucciones, esquema, nombre, clave):
    reader = PdfReader(extraer.RAW / archivo)
    ini, fin = rango
    datos64 = base64.b64encode(pdf_tramo(reader, ini, fin)).decode()
    datos = _llamar(f"gobierno:{archivo}:{ini}-{fin}", instrucciones,
                    [{"type": "text", "text": f"Archivo: {archivo}, páginas {ini} a {fin}."},
                     {"type": "file", "file": {"filename": archivo, "file_data": f"data:application/pdf;base64,{datos64}"}}],
                    esquema, nombre)[clave]
    textos = {ini + i: normalizar(reader.pages[ini - 1 + i].extract_text() or "") for i in range(fin - ini + 1)}
    for f in datos:
        f["pagina"], f["verificacion"] = verificar(f["fragmento"], textos, ini - 1 + f["pagina"])
        f["archivo"] = archivo
    return datos


BASE = """Extraes datos de una fuente oficial del Ayuntamiento de Atlixco, Puebla. Reglas: usa solo lo que dice la fuente; "fragmento" es copia literal (máx. 300 caracteres) de la página indicada que respalda la fila; si un dato no está, es null o no incluyes la fila. Sin opiniones."""

ESQ_FUNCIONARIOS = {"type": "object", "additionalProperties": False, "required": ["funcionarios"],
    "properties": {"funcionarios": {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "required": ["nombre", "cargo", "comision", "pagina", "fragmento"],
        "properties": {"nombre": {"type": "string"}, "cargo": {"type": "string"},
                       "comision": nulo("string", description="Para regidurías: la denominación temática sin 'Regiduría de'; en otro caso null."),
                       "pagina": {"type": "integer"}, "fragmento": {"type": "string"}}}}}}
ESQ_COMISIONES = {"type": "object", "additionalProperties": False, "required": ["comisiones"],
    "properties": {"comisiones": {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "required": ["nombre", "temas", "pagina", "fragmento"],
        "properties": {"nombre": {"type": "string"},
                       "temas": {"type": "string", "description": "Temas en lenguaje sencillo, solo los que se derivan de la denominación de la comisión."},
                       "pagina": {"type": "integer"}, "fragmento": {"type": "string"}}}}}}
ESQ_FUNCIONES = {"type": "object", "additionalProperties": False, "required": ["funciones"],
    "properties": {"funciones": {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "required": ["cargo", "funcion", "pagina", "fragmento"],
        "properties": {"cargo": {"type": "string"},
                       "funcion": {"type": "string", "description": "Qué hace ese cargo, en 1 frase sencilla, solo con lo que dice la ley."},
                       "pagina": {"type": "integer"}, "fragmento": {"type": "string"}}}}}}
ESQ_JUNTAS = {"type": "object", "additionalProperties": False, "required": ["juntas"],
    "properties": {"juntas": {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "required": ["nombre", "presidente", "localidades", "pagina", "fragmento"],
        "properties": {"nombre": {"type": "string"}, "presidente": nulo("string"),
                       "localidades": {"type": "array", "items": {"type": "string"},
                                         "description": "Localidades o colonias que atiende, solo si la fuente las nombra; si no, lista vacía."},
                       "pagina": {"type": "integer"}, "fragmento": {"type": "string"}}}}}}
ESQ_CONTACTO = {"type": "object", "additionalProperties": False, "required": ["contacto"],
    "properties": {"contacto": {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "required": ["oficina", "telefono", "direccion", "horario", "pagina", "fragmento"],
        "properties": {"oficina": {"type": "string"}, "telefono": nulo("string"),
                       "direccion": nulo("string"), "horario": nulo("string"),
                       "pagina": {"type": "integer"}, "fragmento": {"type": "string"}}}}}}


def generar(con):
    funcionarios = _de_html(CABILDO_HTML, BASE + "\nLista a cada integrante del Cabildo: nombre, cargo tal como viene (Presidenta Municipal, Sindicatura Municipal o Regiduría de ...) y su comisión temática.", ESQ_FUNCIONARIOS, "funcionarios", "funcionarios")
    juntas = _de_html(JUNTAS_HTML, BASE + "\nLista cada junta auxiliar con el nombre de su presidente auxiliar si la página lo da.", ESQ_JUNTAS, "juntas", "juntas")
    for j in juntas:
        j["localidades"] = json.dumps(j["localidades"], ensure_ascii=False)
    contacto = _de_html(CONTACTO_HTML, BASE + "\nLista oficinas institucionales con su teléfono público (solo Presidencia, Unidad de Transparencia y las Regidurías). Nunca nombres de personas ni datos personales.", ESQ_CONTACTO, "contacto", "contacto")
    # El fragmento de cada oficina solo respalda oficina y teléfono: la dirección y el
    # horario van en su propia fila, con el fragmento del pie oficial que los contiene.
    contacto = [{**c, "direccion": None, "horario": None} for c in contacto if c["oficina"].strip().upper() != "REGIDURIA"]
    pie = {"oficina": "Ayuntamiento de Atlixco (atención ciudadana)", "telefono": None,
           "direccion": "Plaza de Armas #1, Colonia Centro C.P. 74200, Atlixco, Puebla, México",
           "horario": "Lunes a Viernes de 8:00 a 16:00 horas",
           "fragmento": "Lunes a Viernes de 8:00 a 16:00 horas Dirección: Plaza de Armas #1, Colonia Centro C.P. 74200, Atlixco, Puebla, México"}
    pie["pagina"], pie["verificacion"] = verificar(pie["fragmento"], {1: normalizar(texto_html(JUNTAS_HTML))}, 1)
    pie["archivo"] = JUNTAS_HTML
    if pie["verificacion"] == "ok":
        contacto.append(pie)
    comisiones = _de_pdf(REGLAMENTO, (21, 22), BASE + "\nLista las comisiones permanentes del artículo 41 con los temas que se derivan de su denominación.", ESQ_COMISIONES, "comisiones", "comisiones")
    funciones = (_de_pdf(LEY, (64, 66), BASE + "\nExplica en una frase qué hace el Presidente Municipal según la ley.", ESQ_FUNCIONES, "funciones", "funciones")
                 + _de_pdf(LEY, (71, 76), BASE + "\nExplica en una frase qué hacen los Regidores y qué hace el Síndico según la ley, un cargo por fila.", ESQ_FUNCIONES, "funciones", "funciones")
                 + _de_pdf(LEY, (138, 140), BASE + "\nExplica en una frase qué hacen las Juntas Auxiliares (su Presidente Auxiliar) y qué hacen los Inspectores de colonia según la ley, un cargo por fila.", ESQ_FUNCIONES, "funciones", "funciones"))

    ok = {}
    ok["funcionarios"] = _guardar(con, "funcionarios", ["nombre", "cargo", "comision", "archivo", "pagina", "fragmento", "verificacion"], funcionarios)
    ok["juntas_auxiliares"] = _guardar(con, "juntas_auxiliares", ["nombre", "presidente", "localidades", "archivo", "pagina", "fragmento", "verificacion"], juntas)
    ok["contacto_institucional"] = _guardar(con, "contacto_institucional", ["oficina", "telefono", "direccion", "horario", "archivo", "pagina", "fragmento", "verificacion"], contacto)
    ok["comisiones"] = _guardar(con, "comisiones", ["nombre", "temas", "archivo", "pagina", "fragmento", "verificacion"], comisiones)
    ok["funciones_cargo"] = _guardar(con, "funciones_cargo", ["cargo", "funcion", "archivo", "pagina", "fragmento", "verificacion"], funciones)
    return {k: len(v) for k, v in ok.items()}


def main():
    with conectar() as con:
        conteos = generar(con)
    print("Filas con cita verificada:", conteos)
    print("Gasto acumulado:", llm.resumen_costos())


if __name__ == "__main__":
    main()
