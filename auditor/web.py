"""Interfaz web de la demo del auditor de Atlixco.

Uso (desde auditor/):
    ../.venv/bin/python -m uvicorn web:app --host 127.0.0.1 --port 8000

HTML generado en el servidor, sin frameworks de frontend. Leer páginas no
llama a la API: solo la subida de evidencia llama a SAM 3.1 y a Muse Spark
privado, vía evidencia.py. Todo texto que viene de los PDF o de los modelos
se escapa. Lenguaje neutral: los datos se muestran con su fuente, sin
calificaciones.
"""
import html
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

import cruzar
import evidencia
import extraer
from extraer import plano

app = FastAPI(title="Auditor de Atlixco")

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #111827; background: #f8fafc; line-height: 1.5; }
header, main, footer { max-width: 46rem; margin: 0 auto; padding: 1rem; }
header { padding-bottom: 0; }
nav { display: flex; flex-wrap: wrap; gap: .5rem; }
nav a, button, .boton { display: inline-block; min-height: 44px; padding: .6rem .9rem; border-radius: .5rem; background: #334155; color: #fff; text-decoration: none; border: 0; font-size: 1rem; cursor: pointer; }
nav a { background: #e2e8f0; color: #111827; }
a { color: #1e293b; }
a:focus-visible, button:focus-visible, input:focus-visible { outline: 3px solid #111827; outline-offset: 2px; }
h1 { font-size: 1.6rem; margin: .5rem 0; } h2 { font-size: 1.25rem; margin-top: 1.5rem; }
.tarjeta { background: #fff; border: 1px solid #cbd5e1; border-radius: .75rem; padding: 1rem; margin: .75rem 0; }
.fuente { background: #f1f5f9; border-left: 4px solid #475569; padding: .75rem; margin-top: .75rem; font-size: .92rem; overflow-wrap: anywhere; }
.aviso { background: #fef9c3; border: 1px solid #a16207; color: #713f12; border-radius: .5rem; padding: .75rem; }
.marca { display: inline-block; background: #e2e8f0; border-radius: 999px; padding: .1rem .6rem; font-size: .85rem; margin-right: .35rem; }
img.foto { max-width: 100%; height: auto; border-radius: .5rem; }
label { display: block; margin: .75rem 0 .25rem; font-weight: 600; }
input[type=text], input[type=file], select { width: 100%; min-height: 44px; font-size: 1rem; }
table { border-collapse: collapse; width: 100%; } th, td { text-align: left; padding: .5rem; border-bottom: 1px solid #cbd5e1; vertical-align: top; }
.debil { color: #374151; font-size: .92rem; }
"""


def e(v) -> str:
    return html.escape("" if v is None else str(v))


def pagina(titulo: str, cuerpo: str) -> HTMLResponse:
    nav = "".join(f'<a href="{href}">{texto}</a>' for href, texto in
                  [("/", "Inicio"), ("/funcionarios", "Funcionarios"), ("/acuerdos", "Acuerdos"),
                   ("/presupuesto", "Presupuesto"), ("/hallazgos", "Hallazgos"), ("/evidencia", "Evidencia ciudadana")])
    return HTMLResponse(f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(titulo)} — Auditor de Atlixco</title>
<style>{CSS}</style></head><body><header><strong>Auditor de Atlixco</strong><nav>{nav}</nav></header>
<main><h1>{e(titulo)}</h1>{cuerpo}</main>
<footer class="debil">Datos de documentos públicos oficiales, mostrados con su fuente.</footer></body></html>""")


def _con() -> sqlite3.Connection:
    with evidencia.conectar():  # asegura la tabla evidencias en la misma base
        pass
    return cruzar.conectar()  # asegura hallazgos, partidas, acuerdos y documentos


def _filas(con, sql, params=()):
    con.row_factory = sqlite3.Row
    return [dict(f) for f in con.execute(sql, params)]


def _urls(con) -> dict:
    return {f["archivo"]: f["url"] for f in _filas(con, "SELECT archivo, url FROM documentos")}


def fuente_html(archivo, pagina_, fragmento, urls=None) -> str:
    """Componente de fuente: cada dato muestra de dónde viene (archivo, página, fragmento y enlaces)."""
    local = f'/fuentes/{e(archivo)}#page={e(pagina_)}' if archivo else ""
    oficial = (urls or {}).get(archivo)
    enlaces = (f'<a href="{local}">Abrir el PDF local en la página {e(pagina_)}</a>' if local else "")
    if oficial:
        enlaces += f' · <a href="{e(oficial)}">URL oficial</a>'
    return (f'<div class="fuente"><strong>Fuente:</strong> {e(archivo)}, página {e(pagina_)}<br>'
            f'“{e(fragmento)}”<br>{enlaces}</div>')


def _dinero(v) -> str:
    return "sin monto registrado" if v is None else f"${v:,.2f}"


def _manifiesto() -> list[dict]:
    ruta = extraer.RAW / "manifiesto.json"
    return json.loads(ruta.read_text()) if ruta.exists() else []


def _cobertura_html(c: dict) -> str:
    faltan = "".join(f"<li>{e(f)}</li>" for f in c["fuentes_faltantes"])
    return f"""<div class="tarjeta"><h2>Reporte de cobertura</h2>
<p>Partidas: {c['partidas']} ({c['partidas_con_monto']} con monto, suma ${_dinero(c['suma_partidas'])[1:]},
{c['partidas_nombre_no_verificado']} con nombre no verificado).</p>
<p>Acuerdos canónicos: {c['acuerdos_canonicos']} ({c['acuerdos_con_monto']} con monto,
{c['acuerdos_con_proveedor']} con proveedor).</p>
<p>Pares comparables entre ambas fuentes: {c['pares_comparables']}.</p>
<h3>Fuentes que faltan para poder cruzar</h3><ul>{faltan}</ul></div>"""


@app.get("/", response_class=HTMLResponse)
def inicio():
    fuentes = "".join(
        f"""<div class="tarjeta"><strong>{e(m['archivo'])}</strong><br>
        <span class="debil">Descargado: {e(m.get('descargado', 'sin fecha registrada'))}<br>SHA-256: {e(m.get('sha256', ''))}</span><br>
        <a href="{e(m.get('url', ''))}">URL oficial</a> · <a href="/fuentes/{e(m['archivo'])}">PDF local</a></div>"""
        for m in _manifiesto())
    with _con() as con:
        cobertura = _cobertura_html(cruzar.cobertura(con))
    cuerpo = f"""<p>El auditor lee documentos públicos del Ayuntamiento de Atlixco (gacetas, acuerdos de Cabildo y
el Presupuesto de Egresos), extrae los datos con su cita —archivo, página y fragmento textual— y los muestra aquí
para que cualquier persona pueda revisarlos en la fuente.</p>
<p class="aviso">Los hallazgos son discrepancias verificables entre documentos públicos, no acusaciones.</p>
<h2>Fuentes revisadas</h2>{fuentes or '<p>Sin fuentes registradas.</p>'}{cobertura}"""
    return pagina("Auditor de Atlixco", cuerpo)


def _personas(con) -> dict:
    """Personas de propuesto_por, agrupadas por nombre sin importar mayúsculas. Datos, sin calificaciones."""
    urls = _urls(con)
    personas: dict[str, dict] = {}
    for a in cruzar._acuerdos(con):
        for p in json.loads(a["propuesto_por"]):
            clave = plano(p["nombre"]).replace(" ", "-")
            per = personas.setdefault(clave, {"clave": clave, "nombre": p["nombre"], "cargos": set(),
                                              "acuerdos": [], "urls": urls})
            per["cargos"].add(p["cargo"])
            per["acuerdos"].append(a)
    for per in personas.values():
        ids = [a["id"] for a in per["acuerdos"]]
        marcas = ",".join("?" * len(ids))
        menciones = _filas(con, f"SELECT verificacion FROM acuerdos WHERE grupo_id IN ({marcas})", ids) if ids else []
        per["menciones"] = len(menciones)
        per["verificadas"] = sum(m["verificacion"] == "ok" for m in menciones)
        per["hallazgos"] = (con.execute(f"SELECT count(*) FROM hallazgos WHERE acuerdo_id IN ({marcas})", ids).fetchone()[0]
                            if ids else 0)
    return personas


@app.get("/funcionarios", response_class=HTMLResponse)
def funcionarios():
    with _con() as con:
        personas = _personas(con)
    tarjetas = "".join(
        f"""<div class="tarjeta"><a href="/funcionarios/{e(p['clave'])}"><strong>{e(p['nombre'])}</strong></a><br>
        <span class="debil">{e(', '.join(sorted(c for c in p['cargos'] if c)))}</span><br>
        Acuerdos propuestos: {len(p['acuerdos'])} · Menciones: {p['menciones']} ({p['verificadas']} verificadas) ·
        Hallazgos relacionados: {p['hallazgos']}</div>"""
        for p in sorted(personas.values(), key=lambda x: x["nombre"]))
    return pagina("Funcionarios", tarjetas or "<p>Sin personas registradas en los acuerdos.</p>")


@app.get("/funcionarios/{clave}", response_class=HTMLResponse)
def funcionario(clave: str):
    with _con() as con:
        personas = _personas(con)
    p = personas.get(clave)
    if not p:
        return HTMLResponse("<p>No se encontró a la persona.</p>", status_code=404)
    acuerdos = "".join(
        f"""<div class="tarjeta"><a href="/acuerdos/{a['id']}">{e(a['acuerdo'])}</a>
        {fuente_html(a['archivo'], a['pagina'], a['fragmento'], p['urls'])}</div>""" for a in p["acuerdos"])
    cuerpo = f"""<p><span class="debil">Cargo tal como consta en la fuente:</span>
{e(', '.join(sorted(c for c in p['cargos'] if c)) or 'sin cargo registrado')}</p>
<p>Acuerdos propuestos: {len(p['acuerdos'])} · Menciones: {p['menciones']} ({p['verificadas']} verificadas,
{p['menciones'] - p['verificadas']} no verificadas) · Hallazgos relacionados: {p['hallazgos']}</p>{acuerdos}"""
    return pagina(p["nombre"], cuerpo)


@app.get("/acuerdos", response_class=HTMLResponse)
def acuerdos():
    with _con() as con:
        lista = cruzar._acuerdos(con)
    tarjetas = "".join(
        f"""<div class="tarjeta"><a href="/acuerdos/{a['id']}"><strong>{e(a['acuerdo'])}</strong></a><br>
        <span class="debil">Sesión: {e(a['fecha_sesion'] or 'sin fecha registrada')} · {e(a['menciones'])} mención(es)</span></div>"""
        for a in lista)
    return pagina("Acuerdos de Cabildo", tarjetas or "<p>Sin acuerdos registrados.</p>")


@app.get("/acuerdos/{id_}", response_class=HTMLResponse)
def acuerdo(id_: int):
    with _con() as con:
        filas = _filas(con, """SELECT a.*, d.archivo, d.url FROM acuerdos_canonicos a
                               JOIN documentos d ON d.id = a.documento_id WHERE a.id = ?""", (id_,))
        if not filas:
            return HTMLResponse("<p>No se encontró el acuerdo.</p>", status_code=404)
        a = filas[0]
        menciones = _filas(con, """SELECT a.*, d.archivo FROM acuerdos a JOIN documentos d ON d.id = a.documento_id
                                   WHERE a.grupo_id = ? ORDER BY a.id""", (id_,))
        urls = _urls(con)
    personas = "".join(f"<li>{e(p['nombre'])} — {e(p['cargo'] or 'sin cargo registrado')}</li>"
                       for p in json.loads(a["propuesto_por"])) or "<li>Sin proponentes registrados</li>"
    detalle_menciones = "".join(
        f"""<div class="tarjeta"><span class="marca">{e(m['verificacion'])}</span>
        Página {e(m['pagina'])} de {e(m['archivo'])}{fuente_html(m['archivo'], m['pagina'], m['fragmento'], urls)}</div>"""
        for m in menciones)
    cuerpo = f"""<p>{e(a['acuerdo'])}</p>
<p>Tipo de sesión: {e(a['tipo_sesion'] or 'sin dato')} · Fecha de sesión: {e(a['fecha_sesion'] or 'sin dato')} ·
Resultado de votación: {e(a['resultado_votacion'] or 'sin dato')} · Monto: {_dinero(a['monto_mxn'])} ·
Proveedor: {e(a['proveedor'] or 'sin dato')}</p>
<h2>Propuesto por</h2><ul>{personas}</ul>
<h2>Menciones y sus citas</h2>{detalle_menciones}"""
    return pagina("Acuerdo", cuerpo)


@app.get("/presupuesto", response_class=HTMLResponse)
def presupuesto_():
    with _con() as con:
        partidas = cruzar._partidas(con)
        urls = _urls(con)
    filas = "".join(
        f"""<tr><td>{e(p['capitulo'] or 'sin capítulo')}<br>{e(p['nombre'])}
        {'<span class="marca">nombre no verificado</span>' if p['verificacion_nombre'] != 'ok' else ''}</td>
        <td>{_dinero(p['monto_mxn'])}</td>
        <td><span class="marca">monto: {e(p['verificacion'])}</span><span class="marca">nombre: {e(p['verificacion_nombre'])}</span>
        {fuente_html(p['archivo'], p['pagina'], p['fragmento'], urls)}</td></tr>""" for p in partidas)
    return pagina("Presupuesto de Egresos 2026",
                  f"<table><tr><th>Capítulo y partida</th><th>Monto</th><th>Verificación y cita</th></tr>{filas}</table>")


@app.get("/hallazgos", response_class=HTMLResponse)
def hallazgos():
    with _con() as con:
        lista = _filas(con, "SELECT * FROM hallazgos ORDER BY id")
        cobertura = _cobertura_html(cruzar.cobertura(con))
    if not lista:
        cuerpo = "<p>Sin hallazgos registrados. Esto es lo que hay hoy para cruzar y lo que falta:</p>" + cobertura
    else:
        cuerpo = "".join(f'<div class="tarjeta"><a href="/hallazgos/{h["id"]}">{e(h["tipo"])}</a><br>{e(h["descripcion"])}</div>'
                         for h in lista)
    return pagina("Hallazgos", cuerpo)


@app.get("/hallazgos/{id_}", response_class=HTMLResponse)
def hallazgo(id_: int):
    with _con() as con:
        filas = _filas(con, "SELECT * FROM hallazgos WHERE id = ?", (id_,))
        urls = _urls(con)
    if not filas:
        return HTMLResponse("<p>No se encontró el hallazgo.</p>", status_code=404)
    h = filas[0]
    cuerpo = f"""<p>{e(h['descripcion'])}</p><h2>Cita del presupuesto</h2>
{fuente_html(h['archivo_presupuesto'], h['pagina_presupuesto'], h['fragmento_presupuesto'], urls)}
<h2>Cita del acuerdo</h2>{fuente_html(h['archivo_acuerdo'], h['pagina_acuerdo'], h['fragmento_acuerdo'], urls)}"""
    return pagina(h["tipo"], cuerpo)


def _evidencia_html(ev: dict, con) -> str:
    sugerencias = json.loads(ev["sugerencias"])
    sam = json.loads(ev["sam_resultado"])
    partes = [f"<p>Objeto descrito: {e(ev['objeto'])} · Fecha: {e(ev['fecha'])} · "
              f"Objetos segmentados: {len(sam.get('objetos', []))}</p>"]
    if ev["superpuesta"]:
        partes.append(f'<img class="foto" src="/evidencia-img/{e(Path(ev["superpuesta"]).name)}" alt="Foto con la segmentación superpuesta">')
    if ev["acuerdo_id"] or ev["partida_id"]:
        partes.append(f"<p>Liga confirmada por la persona: {'acuerdo' if ev['acuerdo_id'] else 'partida'} "
                      f"id={e(ev['acuerdo_id'] or ev['partida_id'])}</p>")
    for s in sugerencias:
        partes.append(f"""<div class="tarjeta"><span class="marca">sugerencia sin confirmar</span>
        {e(s['tipo'])} id={e(s['id'])} — {e(s['justificacion'])}
        {fuente_html(s['archivo'], s['pagina'], s['fragmento'], _urls(con))}</div>""")
    return "".join(partes)


@app.get("/evidencia", response_class=HTMLResponse)
def evidencia_form():
    with _con() as con:
        lista = _filas(con, "SELECT * FROM evidencias ORDER BY id DESC")
    tarjetas = "".join(f'<div class="tarjeta"><a href="/evidencia/{ev["id"]}">Evidencia {ev["id"]}: {e(ev["objeto"])}</a>'
                       f'<span class="debil"> · {e(ev["fecha"])}</span></div>' for ev in lista)
    cuerpo = f"""<p>Sube una foto y describe el objeto observado (por ejemplo, un bache). El sistema segmenta el
objeto con SAM 3.1 y puede sugerir acuerdos o partidas relacionados; la liga la confirmas tú. La foto se guarda
sin metadatos de ubicación.</p>
<form method="post" action="/evidencia" enctype="multipart/form-data">
<label for="foto">Foto (JPEG o PNG, máximo 10 MB)</label>
<input id="foto" type="file" name="foto" accept="image/jpeg,image/png" required>
<label for="objeto">Objeto observado</label>
<input id="objeto" type="text" name="objeto" required>
<button type="submit">Enviar evidencia</button></form>
<h2>Evidencias registradas</h2>{tarjetas or '<p>Sin evidencias registradas.</p>'}"""
    return pagina("Evidencia ciudadana", cuerpo)


@app.post("/evidencia")
async def evidencia_subir(foto: UploadFile = File(...), objeto: str = Form(...)):
    contenido = await foto.read()
    if len(contenido) > 10 * 1024 * 1024:
        return HTMLResponse("<p>La foto supera el máximo de 10 MB.</p>", status_code=400)
    # Solo JPEG y PNG, por contenido (no por el nombre que mande la persona).
    extension = ".jpg" if contenido[:3] == b"\xff\xd8\xff" else ".png" if contenido[:8] == b"\x89PNG\r\n\x1a\n" else None
    if extension is None:
        return HTMLResponse("<p>Solo se aceptan fotos JPEG o PNG.</p>", status_code=400)

    evidencia.EVIDENCIA.mkdir(parents=True, exist_ok=True)
    sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid4().hex[:8]  # nombre del servidor, nunca el de la persona
    origen = evidencia.EVIDENCIA / f"subida-{sello}{extension}"
    origen.write_bytes(contenido)
    try:
        base = evidencia.EVIDENCIA / sello
        limpia = evidencia.guardar_sin_exif(origen, evidencia.EVIDENCIA / f"{sello}_limpia.jpg")
        seg = evidencia.segmentar(limpia, objeto)
        ruta_mascara, ruta_superpuesta = evidencia.guardar_salidas(limpia, seg, base)
        with _con() as con:
            sugerencias = evidencia.sugerir(con, objeto, seg)
            id_ = evidencia.guardar(con, str(limpia.relative_to(extraer.RAIZ)), objeto, evidencia.resumen_sam(seg),
                                    str(ruta_mascara.relative_to(extraer.RAIZ)) if ruta_mascara else None,
                                    str(ruta_superpuesta.relative_to(extraer.RAIZ)) if ruta_superpuesta else None,
                                    None, None, sugerencias)
    finally:
        origen.unlink(missing_ok=True)
    return RedirectResponse(f"/evidencia/{id_}", status_code=303)


@app.get("/evidencia/{id_}", response_class=HTMLResponse)
def evidencia_detalle(id_: int):
    with _con() as con:
        filas = _filas(con, "SELECT * FROM evidencias WHERE id = ?", (id_,))
        if not filas:
            return HTMLResponse("<p>No se encontró la evidencia.</p>", status_code=404)
        ev = filas[0]
        detalle = _evidencia_html(ev, con)
        acuerdos = cruzar._acuerdos(con)
        partidas = cruzar._partidas(con)
    opciones_a = "".join(f'<option value="{a["id"]}">{e(a["id"])} — {e(a["acuerdo"][:70])}</option>' for a in acuerdos)
    opciones_p = "".join(f'<option value="{p["id"]}">{e(p["id"])} — capítulo {e(p["capitulo"])} {e(p["nombre"][:50])}</option>' for p in partidas)
    cuerpo = detalle + f"""<h2>Confirmar la liga</h2>
<p>Solo tú confirmas si esta evidencia se relaciona con un acuerdo o una partida.</p>
<form method="post" action="/evidencia/{id_}/confirmar">
<label for="tipo">Tipo</label><select id="tipo" name="tipo">
<option value="acuerdo">Acuerdo</option><option value="partida">Partida</option></select>
<label for="destino">Acuerdo</label><select id="destino" name="destino_acuerdo">{opciones_a}</select>
<label for="destino_p">Partida</label><select id="destino_p" name="destino_partida">{opciones_p}</select>
<button type="submit">Confirmar liga</button></form>"""
    return pagina(f"Evidencia {id_}", cuerpo)


@app.post("/evidencia/{id_}/confirmar")
def evidencia_confirmar(id_: int, tipo: str = Form(...), destino_acuerdo: int = Form(0), destino_partida: int = Form(0)):
    destino = destino_acuerdo if tipo == "acuerdo" else destino_partida if tipo == "partida" else 0
    with _con() as con:
        existe = (con.execute("SELECT 1 FROM acuerdos_canonicos WHERE id = ?", (destino,)).fetchone() if tipo == "acuerdo"
                  else con.execute("SELECT 1 FROM partidas WHERE id = ?", (destino,)).fetchone() if tipo == "partida" else None)
        if not existe:
            return HTMLResponse("<p>El acuerdo o partida indicado no existe.</p>", status_code=400)
        columna = "acuerdo_id" if tipo == "acuerdo" else "partida_id"
        con.execute(f"UPDATE evidencias SET {columna} = ? WHERE id = ?", (destino, id_))
        con.commit()
    return RedirectResponse(f"/evidencia/{id_}", status_code=303)


@app.get("/fuentes/{nombre:path}")
def fuente_pdf(nombre: str):
    ruta = (extraer.RAW / nombre).resolve()
    if ruta.parent != extraer.RAW.resolve() or ruta.suffix.lower() != ".pdf" or not ruta.exists():
        return HTMLResponse("<p>Archivo no encontrado.</p>", status_code=404)
    return FileResponse(ruta, media_type="application/pdf")


@app.get("/evidencia-img/{nombre:path}")
def evidencia_img(nombre: str):
    ruta = (evidencia.EVIDENCIA / nombre).resolve()
    if ruta.parent != evidencia.EVIDENCIA.resolve() or ruta.suffix.lower() not in (".jpg", ".jpeg", ".png") or not ruta.exists():
        return HTMLResponse("<p>Imagen no encontrada.</p>", status_code=404)
    return FileResponse(ruta)
