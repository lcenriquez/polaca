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
import explicar
import extraer
import gobierno
from extraer import plano

app = FastAPI(title="Auditor de Atlixco")

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #111827; background: #f8fafc; line-height: 1.5; font-size: 18px; }
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
details.ayuda { background: #fff; border: 1px solid #cbd5e1; border-radius: .5rem; padding: .6rem .8rem; margin: .5rem 0; }
details.ayuda summary { min-height: 44px; cursor: pointer; font-weight: 600; display: flex; align-items: center; }
.sencillo { border-left: 4px solid #334155; }
textarea { width: 100%; min-height: 88px; font-size: 1rem; }
details.fuente { background: #f1f5f9; border-left: 4px solid #475569; padding: .5rem .75rem; margin-top: .75rem; font-size: .92rem; overflow-wrap: anywhere; }
details.fuente summary { min-height: 44px; cursor: pointer; font-weight: 600; display: flex; align-items: center; }
.avatar { display: inline-flex; align-items: center; justify-content: center; width: 64px; height: 64px; border-radius: 50%; background: #334155; color: #fff; font-weight: 700; font-size: 1.3rem; flex: none; }
.persona { display: flex; gap: .9rem; align-items: flex-start; }
.temas { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: .75rem; }
.tema { background: #fff; border: 1px solid #cbd5e1; border-radius: .75rem; padding: 1rem; text-align: center; }
.tema a { font-weight: 700; text-decoration: none; }
.icono { width: 48px; height: 48px; stroke: #334155; fill: none; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.monedas { line-height: 1; letter-spacing: 2px; overflow-wrap: anywhere; }
.moneda { font-size: 1.05rem; }
.paso-num { display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px; border-radius: 50%; background: #334155; color: #fff; font-weight: 700; margin-right: .5rem; }
input[type=search] { width: 100%; min-height: 48px; font-size: 1.05rem; padding: .5rem; }
"""


def e(v) -> str:
    return html.escape("" if v is None else str(v))


JS = """<script>
function escuchar(){ try{ speechSynthesis.cancel(); var u = new SpeechSynthesisUtterance(document.querySelector('main').innerText); u.lang = 'es-MX'; speechSynthesis.speak(u); }catch(err){} }
function detener(){ try{ speechSynthesis.cancel(); }catch(err){} }
function copiar(id){ var x = document.getElementById(id); if(!x) return; x.select(); if(navigator.clipboard) navigator.clipboard.writeText(x.value); else document.execCommand('copy'); }
function saltarBienvenida(){ try{ localStorage.setItem('bienvenida-vista', '1'); }catch(err){} var b = document.getElementById('bienvenida'); if(b) b.remove(); }
function filtrar(input, id){ var q = input.value.toLowerCase(); document.querySelectorAll('#' + id + ' [data-nombre]').forEach(function(el){ el.style.display = el.getAttribute('data-nombre').toLowerCase().includes(q) ? '' : 'none'; }); }
try{ if(localStorage.getItem('bienvenida-vista')){ var b = document.getElementById('bienvenida'); if(b) b.remove(); } }catch(err){}
</script>"""


def pagina(titulo: str, cuerpo: str) -> HTMLResponse:
    nav = "".join(f'<a href="{href}">{texto}</a>' for href, texto in
                  [("/", "1. ¿Dónde vives?"), ("/representantes", "2. ¿Quién te representa?"),
                   ("/temas", "3. ¿Qué te preocupa?"), ("/revisar", "4. Revisa su trabajo"), ("/actua", "5. Actúa")])
    return HTMLResponse(f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(titulo)} — Auditor de Atlixco</title>
<style>{CSS}</style></head><body><header><strong>Auditor de Atlixco</strong><nav>{nav}</nav>
<p><button type="button" onclick="escuchar()">🔊 Escuchar esta página</button>
<button type="button" onclick="detener()">⏹ Detener lectura</button></p></header>
<main><h1>{e(titulo)}</h1>{cuerpo}</main>
<footer class="debil">Datos de documentos públicos oficiales, mostrados con su fuente.</footer>{JS}</body></html>""")


def _con() -> sqlite3.Connection:
    with evidencia.conectar():  # asegura la tabla evidencias en la misma base
        pass
    with explicar.conectar():  # asegura glosario, resúmenes y rutas
        pass
    with gobierno.conectar():  # asegura funcionarios, comisiones, funciones, juntas y contacto
        pass
    return cruzar.conectar()  # asegura hallazgos, partidas, acuerdos y documentos


def _filas(con, sql, params=()):
    con.row_factory = sqlite3.Row
    return [dict(f) for f in con.execute(sql, params)]


def _urls(con) -> dict:
    urls = {f["archivo"]: f["url"] for f in _filas(con, "SELECT archivo, url FROM documentos")}
    for m in _manifiesto():  # las fuentes nuevas (ley, páginas oficiales) viven en el manifiesto
        urls.setdefault(m["archivo"], m.get("url", ""))
    return urls


def fuente_html(archivo, pagina_, fragmento, urls=None) -> str:
    """'Ver la fuente', cerrado por defecto: archivo, página, fragmento literal y enlaces."""
    local = f'/fuentes/{e(archivo)}#page={e(pagina_)}' if archivo else ""
    oficial = (urls or {}).get(archivo)
    enlaces = (f'<a href="{local}">Abrir el documento guardado en la página {e(pagina_)}</a>' if local else "")
    if oficial:
        enlaces += f' · <a href="{e(oficial)}">Página oficial de la fuente</a>'
    return (f'<details class="fuente"><summary>📄 Ver la fuente</summary>'
            f'Documento: {e(archivo)}, página {e(pagina_)}<br>“{e(fragmento)}”<br>{enlaces}</details>')


def _dinero(v) -> str:
    return "sin monto registrado" if v is None else f"${v:,.2f}"


def en_palabras(v) -> str:
    """Monto en palabras simples, p. ej. 244276746.96 -> '244 millones de pesos'."""
    if v >= 1_000_000:
        m = v / 1_000_000
        n = f"{m:,.0f}" if m >= 100 else f"{m:,.1f}".removesuffix(".0")
        return f"{n} millones de pesos"
    if v >= 1_000:
        return f"{v / 1_000:,.0f} mil pesos"
    return f"{v:,.0f} pesos"


def _glosario(con) -> dict:
    try:
        return {f["termino"]: f for f in _filas(con, "SELECT * FROM glosario")}
    except sqlite3.OperationalError:
        return {}


def ayuda(termino: str, glos: dict, urls=None) -> str:
    """Desplegable '¿Qué es esto?' con la definición y su fuente, o la marca de sin fuente local."""
    g = glos.get(termino)
    if not g:
        return ""
    fuente = (fuente_html(g["archivo"], g["pagina"], g["fragmento"], urls) if g["archivo"]
              else '<p class="debil">Explicación general, sin fuente local. No es un dato oficial.</p>')
    return (f'<details class="ayuda"><summary>❓ ¿Qué es esto? {e(termino)}</summary>'
            f'<p>{e(g["definicion"])}</p>{fuente}</details>')


def _resumen_html(con, tipo: str, id_: int, urls=None) -> str:
    try:
        filas = _filas(con, "SELECT * FROM resumenes WHERE tipo = ? AND id = ?", (tipo, id_))
    except sqlite3.OperationalError:
        return ""
    if not filas:
        return ""
    r = filas[0]
    return (f'<div class="tarjeta sencillo"><strong>En palabras simples:</strong> {e(r["resumen"])}'
            f'<p class="debil">Resumen hecho a partir de la fuente citada. El texto original está en esta misma página.</p>'
            f'{fuente_html(r["archivo"], r["pagina"], r["fragmento"], urls)}</div>')


def _rutas_html(con, tema: str, urls=None) -> str:
    """Sección '¿Qué puedes hacer?' solo con rutas cuyo fundamento está guardado y verificado."""
    try:
        rutas = _filas(con, "SELECT * FROM rutas ORDER BY clave")
    except sqlite3.OperationalError:
        return ""
    if not rutas:
        return ""
    partes = ["<h2>¿Qué puedes hacer?</h2><p>Estas son rutas con su fundamento. Tú decides si las usas y tú envías cualquier solicitud.</p>"]
    for r in rutas:
        pasos = "".join(f"<li>{e(p)}</li>" for p in json.loads(r["pasos"]))
        plantilla = ""
        if r["plantilla"]:
            texto = r["plantilla"].replace("{tema}", tema)
            plantilla = (f'<label for="plantilla-{e(r["clave"])}">Texto listo para copiar:</label>'
                         f'<textarea id="plantilla-{e(r["clave"])}" readonly>{e(texto)}</textarea>'
                         f'<button type="button" onclick="copiar(\'plantilla-{e(r["clave"])}\')">📋 Copiar el texto</button>')
        enlace = (f'<p><a href="{e(r["fundamento_url"])}">Sitio oficial relacionado</a></p>' if r["fundamento_url"] else "")
        partes.append(f'<div class="tarjeta"><strong>{e(r["titulo"])}</strong><ol>{pasos}</ol>{plantilla}{enlace}'
                      f'{fuente_html(r["fundamento_archivo"], r["fundamento_pagina"], r["fundamento_fragmento"], urls)}</div>')
    return "".join(partes)


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


_ICONOS = {
    "casa": '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "personas": '<circle cx="9" cy="8" r="3.5"/><path d="M3 20c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5"/><circle cx="17.5" cy="9" r="2.8"/><path d="M16 14.6c2.9.3 5 2.3 5 5.4"/>',
    "calle": '<path d="M4 21L10 3M20 21L14 3"/><path d="M12 18v-3M12 12V9M12 6V4"/>',
    "agua": '<path d="M12 3c3.5 4.2 6 7.3 6 10.2A6 6 0 0 1 6 13.2C6 10.3 8.5 7.2 12 3z"/>',
    "basura": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/>',
    "alumbrado": '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 1 3.6 10.8c-.7.6-1.1 1.2-1.3 2.2h-4.6c-.2-1-.6-1.6-1.3-2.2A6 6 0 0 1 12 3z"/>',
    "seguridad": '<path d="M12 3l7 3v5c0 4.5-3 8.2-7 10-4-1.8-7-5.5-7-10V6l7-3z"/><path d="M9 12l2 2 4-4"/>',
    "mercados": '<path d="M4 10l1.5-5h13L20 10"/><path d="M4 10a2.7 2.7 0 0 0 5.3 0A2.7 2.7 0 0 0 14.7 10 2.7 2.7 0 0 0 20 10"/><path d="M5.5 12.5V20h13v-7.5"/><path d="M9.5 20v-5h5v5"/>',
    "otros": '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>',
    "dinero": '<circle cx="12" cy="12" r="8.5"/><path d="M12 6.5v11M15 8.8c-.7-1-1.8-1.4-3-1.4-1.7 0-3 1-3 2.3 0 3 6 1.6 6 4 0 1.3-1.3 2.3-3 2.3-1.2 0-2.3-.5-3-1.4"/>',
    "foto": '<rect x="3" y="7" width="18" height="13" rx="2"/><circle cx="12" cy="13" r="3.5"/><path d="M8.5 7L10 4h4l1.5 3"/>',
    "accion": '<path d="M4 10v4h3l6 5V5l-6 5H4z"/><path d="M16.5 9.5a4 4 0 0 1 0 5M19 7a7.5 7.5 0 0 1 0 10"/>',
    "mesa": '<circle cx="12" cy="12" r="3.2"/><circle cx="12" cy="4.5" r="2"/><circle cx="19" cy="16" r="2"/><circle cx="5" cy="16" r="2"/><path d="M12 8.5v.5M17.5 14.5l-.4.3M6.9 14.8l-.4-.3"/>',
}


def icono(clave: str, texto: str) -> str:
    """Icono SVG en línea, de un solo estilo, siempre con texto alternativo."""
    return (f'<svg class="icono" viewBox="0 0 24 24" role="img" aria-label="{e(texto)}">'
            f'<title>{e(texto)}</title>{_ICONOS[clave]}</svg>')


def _gob(con, tabla: str) -> list[dict]:
    try:
        return _filas(con, f"SELECT * FROM {tabla} WHERE verificacion = 'ok' ORDER BY id")
    except sqlite3.OperationalError:
        return []


def _buscar_fila(filas, *claves):
    for f in filas:
        texto = plano(" ".join(str(f.get(c) or "") for c in ("cargo", "oficina", "nombre")))
        if any(plano(c) in texto for c in claves):
            return f
    return None


def _iniciales(nombre: str) -> str:
    partes = [p for p in nombre.split() if p]
    return "".join(p[0] for p in partes[:2]).upper() or "?"


def _fuente_de(fila, urls) -> str:
    return fuente_html(fila["archivo"], fila["pagina"], fila["fragmento"], urls) if fila else ""


def monedas_100(partidas) -> dict:
    """Reparte 100 monedas entre partidas según su monto (resto mayor). La suma es siempre 100."""
    con_monto = [p for p in partidas if p["monto_mxn"]]
    total = sum(p["monto_mxn"] for p in con_monto)
    if not total:
        return {}
    exactas = {p["id"]: p["monto_mxn"] * 100 / total for p in con_monto}
    monedas = {i: int(v) for i, v in exactas.items()}
    for i in sorted(exactas, key=lambda i: exactas[i] - monedas[i], reverse=True)[:100 - sum(monedas.values())]:
        monedas[i] += 1
    return monedas


def _monedas_html(partidas, urls) -> str:
    monedas = monedas_100(partidas)
    if not monedas:
        return ""
    por_id = {p["id"]: p for p in partidas}
    puntos = "".join(f'<span class="moneda" style="color:{["#334155", "#0f766e", "#7c2d12", "#1d4ed8", "#4d7c0f", "#6d28d9", "#9d174d", "#854d0e", "#155e75"][n % 9]}">●</span>'
                     for n, (pid, c) in enumerate(sorted(monedas.items())) for _ in range(c))
    leyenda = "".join(f'<li>{e(por_id[pid]["nombre"])}: {c} de cada 100 pesos '
                      f'({_dinero(por_id[pid]["monto_mxn"])}, {e(en_palabras(por_id[pid]["monto_mxn"]))}).</li>'
                      for pid, c in sorted(monedas.items(), key=lambda x: -x[1]))
    return (f'<div class="tarjeta"><h2>El dinero, en 100 monedas</h2>'
            f'<p>Imagina que todo el gasto del año son 100 monedas. Así se reparte:</p>'
            f'<p class="monedas" role="img" aria-label="Cuadrícula de 100 monedas que reparte el presupuesto por partida">{puntos}</p>'
            f'<ul>{leyenda}</ul>'
            f'<p class="debil">Cada moneda es el 1% del total. Los montos y su fuente están en '
            f'<a href="/presupuesto">Presupuesto</a>.</p></div>')


# Temas del Paso 3: (clave, icono, título, comisión, es orientación general)
TEMAS = [
    ("baches", "calle", "Baches y calles", "De Desarrollo Urbano, Obras y Servicios Públicos", False),
    ("agua", "agua", "Agua", "De Desarrollo Urbano, Obras y Servicios Públicos", True),
    ("basura", "basura", "Basura", "De Desarrollo Urbano, Obras y Servicios Públicos", True),
    ("alumbrado", "alumbrado", "Alumbrado", "De Desarrollo Urbano, Obras y Servicios Públicos", True),
    ("seguridad", "seguridad", "Seguridad", "De Gobernación, Justicia y Seguridad Pública", False),
    ("mercados", "mercados", "Mercados y comercio", "De Industria, Comercio, Agricultura y Ganadería", True),
    ("otros", "otros", "Otro tema", "", True),
]


def _tarjeta_persona(titulo, nombre, hace, fila_fuente, contacto, urls, enlace, distancia):
    contacto_html = ""
    if contacto:
        datos = " · ".join(x for x in [contacto.get("telefono"), contacto.get("direccion"), contacto.get("horario")] if x)
        contacto_html = (f'<p><strong>Cómo encontrarle:</strong> {e(contacto["oficina"])}'
                         f'{(" — " + e(datos)) if datos else ""}</p>{_fuente_de(contacto, urls)}')
    return (f'<div class="tarjeta persona"><div class="avatar" aria-hidden="true">{e(_iniciales(nombre))}</div><div>'
            f'<span class="marca">{e(distancia)}</span><br><strong>{e(nombre)}</strong><br>'
            f'<span class="debil">{e(titulo)}</span>'
            f'<p><strong>Qué hace:</strong> {e(hace)}</p>{_fuente_de(fila_fuente, urls)}{contacto_html}'
            f'<p><a class="boton" href="{e(enlace)}">👀 Revisa su trabajo</a></p></div></div>')


@app.get("/representantes", response_class=HTMLResponse)
def representantes(junta: int = 0):
    with _con() as con:
        funcionarios = _gob(con, "funcionarios")
        juntas = _gob(con, "juntas_auxiliares")
        funciones = _gob(con, "funciones_cargo")
        contactos = _gob(con, "contacto_institucional")
        urls = _urls(con)
    elegida = next((j for j in juntas if j["id"] == junta), None)
    tarjetas = []
    if elegida:
        f_aux = _buscar_fila(funciones, "presidente auxiliar")
        tarjetas.append(_tarjeta_persona(
            f"Presidente auxiliar de {elegida['nombre']}: la autoridad de tu junta auxiliar",
            elegida["presidente"] or elegida["nombre"],
            f_aux["funcion"] if f_aux else "Atiende los asuntos de su junta auxiliar.",
            elegida, _buscar_fila(contactos, "atención ciudadana", "ayuntamiento de atlixco"), urls,
            f"/actua?para={elegida['nombre']}", "Lo más cercano a ti"))
    f_insp = _buscar_fila(funciones, "inspector")
    tarjetas.append(f"""<div class="tarjeta persona"><div class="avatar" aria-hidden="true">IN</div><div>
<span class="marca">Lo más cercano a ti</span><br><strong>El inspector o inspectora de tu colonia</strong><br>
<p><strong>Qué hace:</strong> {e(f_insp['funcion']) if f_insp else ''}</p>
<p class="debil">Su nombre no está en las fuentes oficiales revisadas; pregunta por él en tu junta auxiliar o en el Ayuntamiento.</p>
{_fuente_de(f_insp, urls) if f_insp else ''}</div></div>""")
    regidores = [f for f in funcionarios if f["comision"]]
    f_reg = _buscar_fila(funciones, "regidores")
    for f in regidores:
        tarjetas.append(_tarjeta_persona(
            f"Regiduría de {f['comision']}: vota en el Cabildo y vigila ese tema",
            f["nombre"], f_reg["funcion"] if f_reg else "Participa en las decisiones del Cabildo.",
            f, _buscar_fila(contactos, f["comision"]), urls, f"/revisar/{f['id']}", "Representa a todo el municipio"))
    sindico = _buscar_fila(funcionarios, "sindicatura")
    if sindico:
        f_sin = _buscar_fila(funciones, "síndico", "sindico")
        tarjetas.append(_tarjeta_persona(
            "Síndico municipal: representa legalmente al municipio", sindico["nombre"],
            f_sin["funcion"] if f_sin else "", sindico,
            _buscar_fila(contactos, "atención ciudadana", "ayuntamiento de atlixco"), urls,
            f"/revisar/{sindico['id']}", "Representa a todo el municipio"))
    presidenta = _buscar_fila(funcionarios, "presidenta")
    if presidenta:
        f_pre = _buscar_fila(funciones, "presidente municipal")
        tarjetas.append(_tarjeta_persona(
            "Presidenta municipal: encabeza el gobierno del municipio", presidenta["nombre"],
            f_pre["funcion"] if f_pre else "", presidenta,
            _buscar_fila(contactos, "presidencia municipal"), urls, f"/revisar/{presidenta['id']}",
            "Representa a todo el municipio"))
    visual = (f'<p>{icono("mesa", "Dibujo de personas sentadas alrededor de una mesa: así decide el Cabildo")}</p>'
              '<p class="debil">Primero ves a quien tienes más cerca de tu casa y al final a quien gobierna para todo el municipio. '
              'Todas deciden juntas en el Cabildo.</p>')
    cuerpo = visual + "".join(tarjetas) + """<div class="tarjeta"><strong>El Cabildo completo</strong>
<p>Presidenta, síndico y regidores se reúnen, discuten y votan. Lo que acuerdan queda en documentos públicos.</p>
<p><a class="boton" href="/temas">❓ Paso 3: ¿Qué te preocupa?</a> <a class="boton" href="/acuerdos">Ver los acuerdos</a></p></div>"""
    return pagina("2. ¿Quién te representa?", cuerpo)


@app.get("/temas", response_class=HTMLResponse)
def temas():
    with _con() as con:
        comisiones = _gob(con, "comisiones")
        funcionarios = _gob(con, "funcionarios")
        urls = _urls(con)
    tarjetas = []
    for clave, ic, titulo, nombre_comision, orientacion in TEMAS:
        comision = _buscar_fila(comisiones, nombre_comision.replace("De ", "", 1)) if nombre_comision else None
        regidor = None
        if comision:
            regidor = _buscar_fila(funcionarios, comision["nombre"].replace("De ", "", 1))
        marca = ('<span class="marca">Orientación general, no es un dato oficial</span>' if orientacion
                 else '<span class="marca">Según el Reglamento de Cabildo</span>')
        destino = (f'<p><strong>Comisión:</strong> {e(comision["nombre"])}</p>{_fuente_de(comision, urls)}'
                   f'<p><strong>Regidor o regidora de ese tema:</strong> {e(regidor["nombre"])}</p>{_fuente_de(regidor, urls)}'
                   f'<p><a class="boton" href="/revisar/{regidor["id"]}">👀 Revisa su trabajo</a></p>'
                   if comision and regidor else
                   '<p>Para cualquier tema puedes pedir información y acudir a una sesión pública.</p>'
                   '<p><a class="boton" href="/actua">✋ Paso 5: Actúa</a></p>')
        tarjetas.append(f'<div class="tema">{icono(ic, titulo)}<br><a href="/temas/{clave}">{e(titulo)}</a><br>{marca}{destino}</div>')
    return pagina("3. ¿Qué te preocupa?",
                  "<p>Toca un tema. Te decimos qué comisión y qué regidor lo atienden, con su fuente.</p>"
                  f'<div class="temas">{"".join(tarjetas)}</div>')


@app.get("/temas/{clave}", response_class=HTMLResponse)
def tema(clave: str):
    return temas()


@app.get("/revisar", response_class=HTMLResponse)
def revisar():
    with _con() as con:
        funcionarios = _gob(con, "funcionarios")
        juntas = _gob(con, "juntas_auxiliares")
    tarjetas = "".join(
        f'<div class="tarjeta persona"><div class="avatar" aria-hidden="true">{e(_iniciales(f["nombre"]))}</div><div>'
        f'<strong>{e(f["nombre"])}</strong><br><span class="debil">{e(f["cargo"])}</span>'
        f'<p><a class="boton" href="/revisar/{f["id"]}">👀 Revisa su trabajo</a></p></div></div>' for f in funcionarios)
    tarjetas += "".join(
        f'<div class="tarjeta persona"><div class="avatar" aria-hidden="true">{e(_iniciales(j["presidente"] or j["nombre"]))}</div><div>'
        f'<strong>{e(j["presidente"] or "")}</strong><br><span class="debil">Presidente auxiliar de {e(j["nombre"])}</span>'
        f'<p><a class="boton" href="/actua?para={e(j["nombre"])}">✋ Actúa</a></p></div></div>' for j in juntas)
    return pagina("4. Revisa su trabajo", "<p>Elige a una persona para ver qué propuso y qué se aprobó.</p>" + tarjetas)


@app.get("/revisar/{id_}", response_class=HTMLResponse)
def revisar_persona(id_: int):
    with _con() as con:
        funcionarios = _gob(con, "funcionarios")
        urls = _urls(con)
        f = next((x for x in funcionarios if x["id"] == id_), None)
        if not f:
            return HTMLResponse("<p>No se encontró a la persona.</p>", status_code=404)
        acuerdos = [a for a in cruzar._acuerdos(con)
                    if any(plano(p["nombre"]) == plano(f["nombre"]) for p in json.loads(a["propuesto_por"]))]
        partidas = cruzar._partidas(con)
        evidencias = _filas(con, "SELECT * FROM evidencias ORDER BY id DESC LIMIT 3")
    lista = "".join(f'<div class="tarjeta"><a href="/acuerdos/{a["id"]}">{e(a["acuerdo"])}</a>'
                    f'{fuente_html(a["archivo"], a["pagina"], a["fragmento"], urls)}</div>' for a in acuerdos)
    fotos = "".join(f'<div class="tarjeta"><strong>Evidencia ciudadana: {e(ev["objeto"])}</strong><br>'
                    + (f'<img class="foto" src="/evidencia-img/{e(Path(ev["superpuesta"]).name)}" '
                       f'alt="Foto ciudadana con la parte observada marcada en color">'
                       if ev["superpuesta"] else "")
                    + f'<p><a href="/evidencia/{ev["id"]}">Ver la evidencia completa</a></p></div>' for ev in evidencias)
    cuerpo = (f'<div class="tarjeta persona"><div class="avatar" aria-hidden="true">{e(_iniciales(f["nombre"]))}</div><div>'
              f'<strong>{e(f["nombre"])}</strong><br><span class="debil">{e(f["cargo"])}</span>{_fuente_de(f, urls)}</div></div>'
              f'<h2>Lo que propuso y lo que se aprobó</h2>'
              + (lista or '<p>En los acuerdos revisados no aparece como proponente. Esto solo cubre los documentos cargados hasta hoy.</p>')
              + _monedas_html(partidas, urls)
              + '<h2>Evidencia ciudadana</h2>' + (fotos or '<p>Todavía no hay fotos ciudadanas registradas.</p>')
              + f'<p><a class="boton" href="/evidencia">📷 Subir una foto</a> '
                f'<a class="boton" href="/actua?para={e(f["nombre"])}">✋ Paso 5: Actúa</a></p>')
    return pagina(f"Revisa su trabajo: {f['nombre']}", cuerpo)


@app.get("/actua", response_class=HTMLResponse)
def actua(para: str = ""):
    tema = f"el trabajo de {para}" if para else "un tema del Ayuntamiento de Atlixco"
    with _con() as con:
        urls = _urls(con)
        rutas = _rutas_html(con, tema, urls)
    visual = f'<p>{icono("accion", "Dibujo de una persona alzando la voz con un megáfono")}</p>'
    return pagina("5. Actúa", visual + "<p>No necesitas saber de política. Estas son rutas con su fundamento; "
                  "tú decides si las usas y tú envías cualquier solicitud.</p>" + rutas)


@app.get("/", response_class=HTMLResponse)
def inicio():
    with _con() as con:
        juntas = _gob(con, "juntas_auxiliares")
        urls = _urls(con)
        cobertura = _cobertura_html(cruzar.cobertura(con))
    opciones = "".join(
        f'<div class="tarjeta" data-nombre="{e(j["nombre"])} {e(j["presidente"] or "")}"><div class="persona">'
        f'{icono("casa", "Dibujo de una casa")}<div><strong>{e(j["nombre"])}</strong><br>'
        f'<span class="debil">Presidente auxiliar: {e(j["presidente"] or "sin nombre en la fuente")}</span>'
        f'{_fuente_de(j, urls)}<p><a class="boton" href="/representantes?junta={j["id"]}">🏠 Vivo aquí</a></p></div></div></div>'
        for j in juntas)
    tecnicos = "".join(
        f"""<div class="tarjeta"><strong>{e(m['archivo'])}</strong><br>
        <span class="debil">Descargado: {e(m.get('descargado', 'sin fecha registrada'))}<br>SHA-256: {e(m.get('sha256', ''))}</span><br>
        <a href="{e(m.get('url', ''))}">Página oficial de la fuente</a> · <a href="/fuentes/{e(m['archivo'])}">Documento guardado</a></div>"""
        for m in _manifiesto())
    bienvenida = """<section id="bienvenida" class="tarjeta"><h2>Hola. No necesitas saber de política</h2>
<ol><li><strong>Di dónde vives</strong> y te mostramos a las personas que te representan, de la más cercana a la más lejana.</li>
<li><strong>Conócelas:</strong> qué hace cada una y cómo encontrarla.</li>
<li><strong>Revisa su trabajo y actúa:</strong> qué propusieron, en qué se gasta y qué puedes hacer tú.</li></ol>
<button type="button" onclick="saltarBienvenida()">Saltar y no mostrar de nuevo</button></section>"""
    cuerpo = f"""{bienvenida}
<p>{icono("personas", "Dibujo de un grupo de personas: las que gobiernan tu municipio")}</p>
<p>Esta página lee documentos públicos del Ayuntamiento de Atlixco y te los muestra en palabras simples.
Cada dato trae su fuente, para que puedas comprobarlo tú mismo.</p>
<p class="aviso">Los hallazgos son discrepancias verificables entre documentos públicos, no acusaciones.</p>
<h2><span class="paso-num">1</span>¿Dónde vives?</h2>
<p>Busca tu junta auxiliar. Tu elección no se guarda en ningún servidor: solo ordena lo que ves en esta visita.</p>
<label for="buscar-junta">Escribe el nombre de tu lugar</label>
<input id="buscar-junta" type="search" placeholder="Por ejemplo: Metepec" oninput="filtrar(this, 'lista-juntas')">
<div id="lista-juntas">{opciones}
<div class="tarjeta" data-nombre="cabecera centro colonias"><div class="persona">{icono("casa", "Dibujo de una casa")}
<div><strong>Cabecera municipal y colonias</strong><br>
<span class="debil">Si vives en la ciudad de Atlixco o tu lugar no aparece, sigue desde aquí. Las colonias que atiende cada junta no están en la fuente oficial revisada.</span>
<p><a class="boton" href="/representantes">🏠 Seguir desde aquí</a></p></div></div></div></div>
<details class="tarjeta"><summary><strong>Detalles técnicos y fuentes revisadas</strong></summary>{tecnicos}{cobertura}</details>"""
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
        glos = _glosario(con)
        urls = _urls(con)
    p = personas.get(clave)
    if not p:
        return HTMLResponse("<p>No se encontró a la persona.</p>", status_code=404)
    acuerdos = "".join(
        f"""<div class="tarjeta"><a href="/acuerdos/{a['id']}">{e(a['acuerdo'])}</a>
        {fuente_html(a['archivo'], a['pagina'], a['fragmento'], p['urls'])}</div>""" for a in p["acuerdos"])
    ayudas = "".join(ayuda(t, glos, urls) for t in ("Presidenta Municipal", "Síndico Municipal", "Regidor", "Ayuntamiento")
                     if any(t.split()[0].lower().rstrip("a") in (c or "").lower() or t.lower() in (c or "").lower()
                            for c in p["cargos"]))
    cuerpo = f"""<p><span class="debil">Cargo tal como consta en la fuente:</span>
{e(', '.join(sorted(c for c in p['cargos'] if c)) or 'sin cargo registrado')}</p>{ayudas}
<p>Acuerdos propuestos: {len(p['acuerdos'])} · Menciones: {p['menciones']} ({p['verificadas']} verificadas,
{p['menciones'] - p['verificadas']} no verificadas) · Hallazgos relacionados: {p['hallazgos']}</p>{acuerdos}"""
    return pagina(p["nombre"], cuerpo)


@app.get("/acuerdos", response_class=HTMLResponse)
def acuerdos():
    with _con() as con:
        lista = cruzar._acuerdos(con)
        glos = _glosario(con)
        urls = _urls(con)
    tarjetas = "".join(
        f"""<div class="tarjeta"><a href="/acuerdos/{a['id']}"><strong>{e(a['acuerdo'])}</strong></a><br>
        <span class="debil">Sesión: {e(a['fecha_sesion'] or 'sin fecha registrada')} · {e(a['menciones'])} mención(es)</span></div>"""
        for a in lista)
    intro = ("<p>Estos son acuerdos que tomó el Ayuntamiento en sus reuniones. "
             "Abre uno para verlo en palabras simples, con el texto original y su fuente.</p>"
             + ayuda("Cabildo", glos, urls) + ayuda("Dictamen", glos, urls))
    return pagina("Acuerdos de Cabildo", intro + (tarjetas or "<p>Sin acuerdos registrados.</p>"))


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
        glos = _glosario(con)
        resumen = _resumen_html(con, "acuerdo", id_, urls)
        rutas = _rutas_html(con, f"el acuerdo «{a['acuerdo'][:120]}» del Ayuntamiento de Atlixco", urls)
    personas = "".join(f"<li>{e(p['nombre'])} — {e(p['cargo'] or 'sin cargo registrado')}</li>"
                       for p in json.loads(a["propuesto_por"])) or "<li>Sin proponentes registrados</li>"
    detalle_menciones = "".join(
        f"""<div class="tarjeta"><span class="marca">{e(m['verificacion'])}</span>
        Página {e(m['pagina'])} de {e(m['archivo'])}{fuente_html(m['archivo'], m['pagina'], m['fragmento'], urls)}</div>"""
        for m in menciones)
    termino_sesion = {"ordinaria": "Sesión ordinaria", "extraordinaria": "Sesión extraordinaria",
                      "solemne": "Sesión solemne"}.get((a["tipo_sesion"] or "").lower(), "")
    cuerpo = f"""{resumen}<h2>Texto original del registro</h2><p>{e(a['acuerdo'])}</p>
<p>Tipo de sesión: {e(a['tipo_sesion'] or 'sin dato')} · Fecha de sesión: {e(a['fecha_sesion'] or 'sin dato')} ·
Resultado de votación: {e(a['resultado_votacion'] or 'sin dato')} · Monto: {_dinero(a['monto_mxn'])} ·
Proveedor: {e(a['proveedor'] or 'sin dato')}</p>
{ayuda(termino_sesion, glos, urls) if termino_sesion else ''}{ayuda("Sesión pública", glos, urls)}
<h2>Propuesto por</h2><ul>{personas}</ul>
<h2>Menciones y sus citas</h2>{detalle_menciones}{rutas}"""
    return pagina("Acuerdo", cuerpo)


@app.get("/presupuesto", response_class=HTMLResponse)
def presupuesto_():
    with _con() as con:
        partidas = cruzar._partidas(con)
        urls = _urls(con)
        glos = _glosario(con)
        resumenes = {p["id"]: _resumen_html(con, "partida", p["id"], urls) for p in partidas}
        rutas = _rutas_html(con, "el Presupuesto de Egresos 2026 del Ayuntamiento de Atlixco", urls)
    filas = "".join(
        f"""<tr><td>{e(p['capitulo'] or 'sin capítulo')}<br>{e(p['nombre'])}
        {'<span class="marca">nombre no verificado</span>' if p['verificacion_nombre'] != 'ok' else ''}
        {resumenes[p['id']]}</td>
        <td>{_dinero(p['monto_mxn'])}<br><span class="debil">{e(en_palabras(p['monto_mxn'])) if p['monto_mxn'] is not None else ''}</span></td>
        <td><span class="marca">monto: {e(p['verificacion'])}</span><span class="marca">nombre: {e(p['verificacion_nombre'])}</span>
        {fuente_html(p['archivo'], p['pagina'], p['fragmento'], urls)}</td></tr>""" for p in partidas)
    intro = ("<p>Este es el plan de gastos del municipio para 2026. Cada renglón es un grupo de gasto, "
             "con su monto en números y en palabras, y su fuente.</p>"
             + ayuda("Presupuesto de Egresos", glos, urls) + ayuda("Capítulo del gasto", glos, urls)
             + ayuda("Partida", glos, urls) + ayuda("Inversión Pública", glos, urls)
             + ayuda("Servicios Personales", glos, urls))
    return pagina("Presupuesto de Egresos 2026",
                  intro + f"<table><tr><th>Capítulo y partida</th><th>Monto</th><th>Verificación y cita</th></tr>{filas}</table>" + rutas)


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
    with _con() as con:
        filas = _filas(con, "SELECT * FROM hallazgos WHERE id = ?", (id_,))
        urls = _urls(con)
        rutas = _rutas_html(con, "la diferencia entre documentos públicos descrita en esta página", urls) if filas else ""
    if not filas:
        return HTMLResponse("<p>No se encontró el hallazgo.</p>", status_code=404)
    h = filas[0]
    cuerpo = f"""<p>{e(h['descripcion'])}</p><h2>Cita del presupuesto</h2>
{fuente_html(h['archivo_presupuesto'], h['pagina_presupuesto'], h['fragmento_presupuesto'], urls)}
<h2>Cita del acuerdo</h2>{fuente_html(h['archivo_acuerdo'], h['pagina_acuerdo'], h['fragmento_acuerdo'], urls)}{rutas}"""
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
    if ruta.parent != extraer.RAW.resolve() or ruta.suffix.lower() not in (".pdf", ".html") or not ruta.exists():
        return HTMLResponse("<p>Archivo no encontrado.</p>", status_code=404)
    return FileResponse(ruta, media_type="application/pdf" if ruta.suffix.lower() == ".pdf" else "text/html")


@app.get("/evidencia-img/{nombre:path}")
def evidencia_img(nombre: str):
    ruta = (evidencia.EVIDENCIA / nombre).resolve()
    if ruta.parent != evidencia.EVIDENCIA.resolve() or ruta.suffix.lower() not in (".jpg", ".jpeg", ".png") or not ruta.exists():
        return HTMLResponse("<p>Imagen no encontrada.</p>", status_code=404)
    return FileResponse(ruta)
