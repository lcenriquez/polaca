"""Explicaciones en lenguaje sencillo: glosario con fuente, resúmenes y rutas de acción.

Uso:
    python auditor/explicar.py [--acuerdos 3 --partidas 3]   # prueba chica primero

Genera una sola vez y guarda en SQLite (navegar en web.py no llama a la API):
- glosario: definiciones sencillas extraídas con Muse (MODELO_PUBLICO) del
  Reglamento Interior de Cabildo y de la versión ciudadana del Presupuesto.
  Cada una guarda archivo, página y fragmento, verificados con verificar() de
  extraer.py. Si el fragmento no se verifica o el término no está en nuestras
  fuentes, queda con archivo null y la interfaz lo marca como
  "explicación general, sin fuente local", nunca como dato oficial.
- resumenes: resumen sencillo de 1-2 frases por acuerdo y partida, redactado
  por Muse solo con lo que dice la fuente. Se guarda con la cita de la fila
  de SQLite (no la del modelo) y se muestra junto al texto original.
- rutas: qué puede hacer la persona, solo con fundamento verificable en los
  documentos locales (sin API). Si el fragmento no se verifica, la ruta no se incluye.
"""
import argparse
import base64
import json
import sqlite3
from datetime import datetime, timezone

from pypdf import PdfReader

import llm
import presupuesto
from extraer import RAW, normalizar, pdf_tramo, verificar

REGLAMENTO = "Reglamento_Interior_de_Cabildo_del_Municipio_de_Atlixco_T2_08072025.pdf"
PRESUPUESTO = "VERSION_CIUDADANA_PRESUPUESTO_EGRESOS_2026.pdf"

# Explicaciones generales de respaldo: solo se usan marcadas "sin fuente local".
GENERALES = {
    "Cabildo": "Es la reunión del Ayuntamiento, donde se discuten y votan las decisiones del municipio.",
    "Ayuntamiento": "Es el grupo de personas que gobierna el municipio: la presidencia, la sindicatura y las regidurías.",
    "Presidenta Municipal": "Es la persona que encabeza el gobierno del municipio.",
    "Síndico Municipal": "Es quien representa legalmente al municipio y vigila que se cumpla la ley.",
    "Regidor": "Es una persona del Ayuntamiento que representa a la población y vota las decisiones en Cabildo.",
    "Dictamen": "Es un documento donde una comisión explica un tema y propone qué decidir, antes de votarlo.",
    "Sesión ordinaria": "Es la reunión normal del Cabildo, que se hace cada mes.",
    "Sesión extraordinaria": "Es una reunión especial del Cabildo para temas urgentes o únicos.",
    "Sesión solemne": "Es una reunión formal del Cabildo para actos importantes, sin debate.",
    "Sesión pública": "Es una reunión del Cabildo a la que puede entrar cualquier persona a escuchar.",
    "Presupuesto de Egresos": "Es el plan de gastos del municipio para un año: cuánto dinero hay y en qué se va a usar.",
    "Capítulo del gasto": "Es una forma de agrupar los gastos por tipo: personal, materiales, obras y otros.",
    "Partida": "Es cada grupo de gasto del presupuesto, con su nombre y su monto.",
    "Inversión Pública": "Es el gasto en obras para el municipio, como calles, parques o edificios públicos.",
    "Servicios Personales": "Es el gasto en sueldos y pagos del personal que trabaja en el municipio.",
}


def conectar() -> sqlite3.Connection:
    con = presupuesto.conectar()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS glosario (
            termino TEXT PRIMARY KEY,
            definicion TEXT NOT NULL,
            archivo TEXT, pagina INTEGER, fragmento TEXT,
            verificacion TEXT NOT NULL CHECK (verificacion IN ('ok', 'sin_texto', 'no_encontrado', 'sin_fuente'))
        );
        CREATE TABLE IF NOT EXISTS resumenes (
            tipo TEXT NOT NULL CHECK (tipo IN ('acuerdo', 'partida')),
            id INTEGER NOT NULL,
            resumen TEXT NOT NULL,
            archivo TEXT NOT NULL, pagina INTEGER NOT NULL, fragmento TEXT NOT NULL,
            modelo TEXT NOT NULL, creado TEXT NOT NULL,
            PRIMARY KEY (tipo, id)
        );
        CREATE TABLE IF NOT EXISTS rutas (
            clave TEXT PRIMARY KEY,
            titulo TEXT NOT NULL,
            pasos TEXT NOT NULL,            -- JSON: lista de pasos en lenguaje sencillo
            plantilla TEXT,                 -- texto de solicitud con {tema}, o null
            fundamento_archivo TEXT, fundamento_pagina INTEGER, fundamento_fragmento TEXT,
            fundamento_url TEXT,
            verificacion TEXT NOT NULL
        );
    """)
    con.commit()
    return con


ESQUEMA_GLOSARIO = {
    "type": "object", "additionalProperties": False, "required": ["terminos"],
    "properties": {"terminos": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["termino", "definicion", "pagina", "fragmento"],
        "properties": {
            "termino": {"type": "string"},
            "definicion": {"type": "string", "description": "Definición en lenguaje sencillo, 1-2 frases, solo con lo que dice el documento."},
            "pagina": {"type": "integer", "description": "Página dentro de ESTE archivo (1 = primera)."},
            "fragmento": {"type": "string", "description": "Copia literal del documento (máx. 300 caracteres) que respalda la definición."},
        }}}},
}

ESQUEMA_RESUMENES = {
    "type": "object", "additionalProperties": False, "required": ["resumenes"],
    "properties": {"resumenes": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "resumen"],
        "properties": {
            "id": {"type": "integer"},
            "resumen": {"type": "string", "description": "Resumen sencillo de 1-2 frases, solo con lo que dice la fuente."},
        }}}},
}


def _extraer_terminos(archivo: str, rango: tuple[int, int], terminos: list[str]) -> list[dict]:
    reader = PdfReader(RAW / archivo)
    ini, fin = rango
    datos = base64.b64encode(pdf_tramo(reader, ini, fin)).decode()
    resp = llm.llamar(
        f"glosario:{archivo}:{ini}-{fin}",
        model=llm.MODELO_PUBLICO,
        reasoning_effort="medium",
        messages=[
            {"role": "system", "content": """Extrae definiciones de un documento oficial del Ayuntamiento de Atlixco, Puebla, en lenguaje sencillo.
Reglas: usa solo lo que dice el documento; "fragmento" debe ser copia literal de la página indicada; "pagina" es la página dentro de este archivo (1 = primera).
Si un término no se explica en el documento, no lo incluyas. Definiciones de 1-2 frases, sin jerga, sin afirmar nada que no esté en el texto."""},
            {"role": "user", "content": [
                {"type": "text", "text": f"Archivo: {archivo}, páginas {ini} a {fin}. Define estos términos si el documento los explica: {', '.join(terminos)}."},
                {"type": "file", "file": {"filename": archivo, "file_data": f"data:application/pdf;base64,{datos}"}},
            ]},
        ],
        response_format={"type": "json_schema", "json_schema": {"name": "glosario", "strict": True, "schema": ESQUEMA_GLOSARIO}},
    )
    encontrados = json.loads(resp["choices"][0]["message"]["content"])["terminos"]
    textos = {ini + i: normalizar(reader.pages[ini - 1 + i].extract_text() or "") for i in range(fin - ini + 1)}
    for t in encontrados:
        t["pagina"], t["verificacion"] = verificar(t["fragmento"], textos, ini - 1 + t["pagina"])
        t["archivo"] = archivo
    return encontrados


def guardar_glosario(con, definiciones: list[dict]):
    con.executemany("""INSERT INTO glosario (termino, definicion, archivo, pagina, fragmento, verificacion)
                       VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(termino) DO UPDATE SET definicion=excluded.definicion,
                       archivo=excluded.archivo, pagina=excluded.pagina, fragmento=excluded.fragmento,
                       verificacion=excluded.verificacion""",
                    [(t["termino"], t["definicion"], t.get("archivo"), t.get("pagina"), t.get("fragmento"),
                      t["verificacion"]) for t in definiciones])
    con.commit()


def generar_glosario(con):
    gobierno = ["Cabildo", "Ayuntamiento", "Presidenta Municipal", "Síndico Municipal", "Regidor", "Dictamen",
                "Sesión ordinaria", "Sesión extraordinaria", "Sesión solemne", "Sesión pública"]
    gasto = ["Presupuesto de Egresos", "Capítulo del gasto", "Partida", "Inversión Pública", "Servicios Personales"]
    encontrados = (_extraer_terminos(REGLAMENTO, (4, 18), gobierno)
                   + _extraer_terminos(PRESUPUESTO, (5, 8), gasto))
    por_termino = {t["termino"]: t for t in encontrados}
    finales = []
    for termino in gobierno + gasto:
        t = por_termino.get(termino)
        if t and t["verificacion"] == "ok":
            finales.append(t)  # con fuente verificada
        elif t:  # definición redactada pero fragmento no verificado: queda como explicación general
            finales.append({**t, "archivo": None, "pagina": None, "fragmento": None, "verificacion": "sin_fuente"})
        else:  # no está en nuestras fuentes
            finales.append({"termino": termino, "definicion": GENERALES[termino], "archivo": None,
                            "pagina": None, "fragmento": None, "verificacion": "sin_fuente"})
    guardar_glosario(con, finales)
    return finales


def guardar_resumenes(con, resumenes: list[dict]):
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.executemany("""INSERT INTO resumenes (tipo, id, resumen, archivo, pagina, fragmento, modelo, creado)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(tipo, id) DO UPDATE SET resumen=excluded.resumen,
                       archivo=excluded.archivo, pagina=excluded.pagina, fragmento=excluded.fragmento,
                       modelo=excluded.modelo, creado=excluded.creado""",
                    [(r["tipo"], r["id"], r["resumen"], r["archivo"], r["pagina"], r["fragmento"],
                      llm.MODELO_PUBLICO, ahora) for r in resumenes])
    con.commit()


def _resumir(tipo: str, filas: list[dict], texto) -> list[dict]:
    if not filas:
        return []
    lista = "\n".join(f"id={f['id']}: {texto(f)} | fragmento: \"{f['fragmento']}\"" for f in filas)
    resp = llm.llamar(
        f"resumenes:{tipo}",
        model=llm.MODELO_PUBLICO,
        reasoning_effort="medium",
        messages=[
            {"role": "system", "content": """Redacta resúmenes en lenguaje sencillo de registros públicos del Ayuntamiento de Atlixco, Puebla, para personas sin experiencia en estos temas.
Reglas: 1-2 frases por registro, en palabras simples; usa solo lo que dice cada registro y su fragmento; si un dato no está, no lo digas; lenguaje neutral, sin opiniones ni calificaciones."""},
            {"role": "user", "content": lista},
        ],
        response_format={"type": "json_schema", "json_schema": {"name": "resumenes", "strict": True, "schema": ESQUEMA_RESUMENES}},
    )
    por_id = {f["id"]: f for f in filas}
    return [{"tipo": tipo, "id": r["id"], "resumen": r["resumen"], "archivo": por_id[r["id"]]["archivo"],
             "pagina": por_id[r["id"]]["pagina"], "fragmento": por_id[r["id"]]["fragmento"]}
            for r in json.loads(resp["choices"][0]["message"]["content"])["resumenes"] if r["id"] in por_id]


def generar_resumenes(con, max_acuerdos: int | None, max_partidas: int | None):
    con.row_factory = sqlite3.Row
    acuerdos = [dict(f) for f in con.execute(
        "SELECT a.id, a.acuerdo, a.fragmento, a.pagina, d.archivo FROM acuerdos_canonicos a "
        "JOIN documentos d ON d.id = a.documento_id ORDER BY a.id")]
    partidas = [dict(f) for f in con.execute(
        "SELECT p.id, p.capitulo, p.nombre, p.monto_mxn, p.fragmento, p.pagina, d.archivo FROM partidas p "
        "JOIN documentos d ON d.id = p.documento_id ORDER BY p.id")]
    resumenes = (_resumir("acuerdo", acuerdos[:max_acuerdos] if max_acuerdos else acuerdos,
                          lambda f: f["acuerdo"])
                 + _resumir("partida", partidas[:max_partidas] if max_partidas else partidas,
                            lambda f: f"Capítulo {f['capitulo']} {f['nombre']}, ${f['monto_mxn']:,.2f}"))
    guardar_resumenes(con, resumenes)
    return resumenes


def _buscar(archivo: str, fragmento: str) -> tuple[int, str]:
    """(página, verificación) de un fragmento buscado en todo el PDF, sin llamar a la API."""
    reader = PdfReader(RAW / archivo)
    textos = {i + 1: normalizar(p.extract_text() or "") for i, p in enumerate(reader.pages)}
    return verificar(fragmento, textos, 1)


RUTAS = [
    {"clave": "sesion-publica", "titulo": "Ir a una sesión de Cabildo",
     "pasos": ["Las sesiones de Cabildo, por regla general, son públicas: puedes entrar a escuchar.",
               "Pregunta en el Ayuntamiento por el calendario de sesiones (hay una sesión ordinaria cada mes).",
               "Durante la sesión guarda el orden y abstente de hacer manifestaciones ruidosas."],
     "plantilla": None, "archivo": REGLAMENTO,
     "fragmento": "Por regla general, las sesiones de Cabildo serán públicas", "url": None},
    {"clave": "solicitud-pnt", "titulo": "Pedir información en la Plataforma Nacional de Transparencia",
     "pasos": ["Entra a la Plataforma Nacional de Transparencia (el enlace está en el fundamento).",
               "Crea tu cuenta y busca al Ayuntamiento de Atlixco, Puebla.",
               "Copia el texto de solicitud de abajo, ajústalo a tu caso y envíalo tú desde tu cuenta."],
     "plantilla": "Solicito conocer {tema}. Pido la información en formato digital y sin costo, por esta plataforma.",
     "archivo": PRESUPUESTO, "fragmento": "Visitar la Plataforma Nacional de Transparencia",
     "url": "https://www.plataformadetransparencia.org.mx"},
    {"clave": "unidad-transparencia", "titulo": "Preguntar en la Unidad de Transparencia del municipio",
     "pasos": ["Acude a la Unidad de Transparencia del Ayuntamiento de Atlixco o entra a la página del municipio.",
               "Explica qué dato quieres conocer; también puedes hacerlo por la Plataforma Nacional de Transparencia."],
     "plantilla": None, "archivo": PRESUPUESTO,
     "fragmento": "Recurrir a la Unidad de Transparencia para consultas ciudadanas", "url": "https://atlixco.gob.mx"},
    {"clave": "participacion", "titulo": "Participar con tu colonia",
     "pasos": ["Busca al inspector o inspectora de tu colonia.",
               "Participa en las actividades de la Coordinación de Participación Ciudadana y plantea ahí tu caso."],
     "plantilla": None, "archivo": PRESUPUESTO,
     "fragmento": "Participar en las actividades que la Coordinación de Participación Ciudadana realiza a través de inspectores",
     "url": None},
]


def guardar_rutas(con, rutas: list[dict]):
    con.executemany("""INSERT INTO rutas (clave, titulo, pasos, plantilla, fundamento_archivo, fundamento_pagina,
                       fundamento_fragmento, fundamento_url, verificacion) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(clave) DO UPDATE SET titulo=excluded.titulo, pasos=excluded.pasos,
                       plantilla=excluded.plantilla, fundamento_archivo=excluded.fundamento_archivo,
                       fundamento_pagina=excluded.fundamento_pagina, fundamento_fragmento=excluded.fundamento_fragmento,
                       fundamento_url=excluded.fundamento_url, verificacion=excluded.verificacion""",
                    [(r["clave"], r["titulo"], json.dumps(r["pasos"], ensure_ascii=False), r["plantilla"],
                      r["fundamento_archivo"], r["fundamento_pagina"], r["fundamento_fragmento"],
                      r["fundamento_url"], r["verificacion"]) for r in rutas])
    con.commit()


def generar_rutas(con):
    rutas = []
    for r in RUTAS:  # solo entran rutas cuyo fundamento se verifica en el documento citado
        pagina, verificacion = _buscar(r["archivo"], r["fragmento"])
        if verificacion == "ok":
            rutas.append({**r, "fundamento_archivo": r["archivo"], "fundamento_pagina": pagina,
                          "fundamento_fragmento": r["fragmento"], "fundamento_url": r["url"],
                          "verificacion": verificacion})
    guardar_rutas(con, rutas)
    return rutas


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--acuerdos", type=int, help="máximo de acuerdos a resumir (prueba chica)")
    p.add_argument("--partidas", type=int, help="máximo de partidas a resumir (prueba chica)")
    args = p.parse_args()
    with conectar() as con:
        glosario = generar_glosario(con)
        resumenes = generar_resumenes(con, args.acuerdos, args.partidas)
        rutas = generar_rutas(con)
    con_fuente = sum(t["verificacion"] == "ok" for t in glosario)
    print(f"Glosario: {len(glosario)} términos ({con_fuente} con fuente verificada, {len(glosario) - con_fuente} sin fuente local)")
    print(f"Resúmenes: {len(resumenes)} (cada uno con su cita de SQLite)")
    print(f"Rutas de acción con fundamento verificado: {len(rutas)} de {len(RUTAS)}")
    print("Gasto acumulado:", llm.resumen_costos())


if __name__ == "__main__":
    main()
