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
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from PIL import Image, ImageDraw, ImageFont

import cruzar
import evidencia
import explicar
import extraer
import gobierno
from extraer import plano

app = FastAPI(title="Auditor de Atlixco")

CSS = """
:root { color-scheme: light; --bg:#f6f5fb; --card:#fff; --ink:#1d1b2e; --muted:#59556f; --line:#e4e1f0;
  --accent:#5b3fd1; --accent-tx:#5b3fd1; --accent-soft:#ece8fc; --ok:#1f7a4d; --r:20px;
  --aviso-bg:#fef9c3; --aviso-line:#a16207; --aviso-ink:#713f12; --copy-bg:#f1effa; --dash:#c9c3e6;
  --c1:#5b3fd1; --c2:#c2410c; --c3:#0e7490; --c4:#a21caf; --c5:#4d7c0f; --c6:#b45309; --c7:#475569; --c8:#be123c; --c9:#0f766e; }
@media (prefers-color-scheme: dark) {
:root:not([data-theme="light"]) { color-scheme: dark; --bg:#141126; --card:#211c3a; --ink:#f4f2fc; --muted:#c2bde0; --line:#3d3866;
  --accent:#7a5af5; --accent-tx:#c4b5fd; --accent-soft:#2e2857; --ok:#5ec98a; --r:20px;
  --aviso-bg:#38300f; --aviso-line:#a58a2e; --aviso-ink:#fde9a8; --copy-bg:#2a2450; --dash:#574f92;
  --c1:#5b3fd1; --c2:#c2410c; --c3:#0e7490; --c4:#a21caf; --c5:#4d7c0f; --c6:#b45309; --c7:#475569; --c8:#be123c; --c9:#0f766e; } }
:root[data-theme="dark"] { color-scheme: dark; --bg:#141126; --card:#211c3a; --ink:#f4f2fc; --muted:#c2bde0; --line:#3d3866;
  --accent:#7a5af5; --accent-tx:#c4b5fd; --accent-soft:#2e2857; --ok:#5ec98a; --r:20px;
  --aviso-bg:#38300f; --aviso-line:#a58a2e; --aviso-ink:#fde9a8; --copy-bg:#2a2450; --dash:#574f92;
  --c1:#5b3fd1; --c2:#c2410c; --c3:#0e7490; --c4:#a21caf; --c5:#4d7c0f; --c6:#b45309; --c7:#475569; --c8:#be123c; --c9:#0f766e; }
* { box-sizing: border-box; }
body { margin: 0; font: 18px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--ink); background: var(--bg); overflow-x: clip; }
header.top, main, footer { max-width: 430px; margin: 0 auto; padding: 16px; }
header.top { display: flex; align-items: center; gap: 12px; padding-bottom: 8px; flex-wrap: wrap; }
nav.topmenu { display: none; }
.prog { flex: 1; display: flex; gap: 6px; } .prog i { flex: 1; height: 6px; border-radius: 3px; background: var(--line); } .prog i.on { background: var(--accent); }
.back, .listen { width: 44px; height: 44px; border-radius: 50%; background: var(--card); border: 1px solid var(--line); display: inline-grid; place-items: center; color: var(--accent-tx); cursor: pointer; flex: none; }
.a11y { position: relative; margin-left: auto; }
.a11y-panel { position: absolute; right: 0; top: 52px; z-index: 20; background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 14px; width: 280px; max-width: 86vw; box-shadow: 0 12px 32px rgba(0,0,0,.25); }
.a11y-panel .btn { min-height: 48px; margin-bottom: 8px; }
.tema-btns { display: flex; gap: 6px; } .tema-btns button { flex: 1; min-height: 44px; border-radius: 10px; border: 2px solid var(--line); background: var(--card); color: var(--ink); font-weight: 600; cursor: pointer; }
a:focus-visible, button:focus-visible, input:focus-visible, summary:focus-visible, select:focus-visible { outline: 3px solid var(--ink); outline-offset: 2px; }
h1 { font-size: 30px; line-height: 1.15; margin: .4rem 0; } h2 { font-size: 24px; line-height: 1.2; margin: 1.2rem 0 .5rem; } h3 { font-size: 19px; margin: .2rem 0; }
main { display: flex; flex-direction: column; gap: 16px; padding-top: 8px; }
.stack { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.cols { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.tarjeta, .card { background: var(--card); border: 1px solid var(--line); border-radius: var(--r); padding: 16px; }
button, .boton, nav a { cursor: pointer; }
.btn, .boton { display: flex; align-items: center; justify-content: center; gap: 10px; min-height: 56px; border-radius: 16px; background: var(--accent); color: #fff; font-weight: 700; font-size: 18px; border: 0; width: 100%; text-decoration: none; padding: .6rem 1rem; }
.btn.ghost, .boton.ghost { background: var(--card); color: var(--accent-tx); border: 2px solid var(--accent-tx); }
.hero { background: var(--accent); color: #fff; border-radius: var(--r); padding: 24px; display: flex; flex-direction: column; gap: 12px; }
.hero svg.h { width: 100%; height: auto; }
.search { display: flex; align-items: center; gap: 10px; background: var(--card); border: 2px solid var(--line); border-radius: 16px; padding: 0 14px; min-height: 56px; }
.list a { display: flex; align-items: center; gap: 12px; min-height: 56px; padding: 0 4px; border-bottom: 1px solid var(--line); color: var(--ink); text-decoration: none; }
.list a:last-child { border: 0; }
.ring { position: relative; width: 100%; aspect-ratio: 1; max-width: 330px; margin: 0 auto; }
.ring .c { position: absolute; border-radius: 50%; border: 2px dashed var(--dash); inset: 0; }
.ring .c2 { inset: 16%; } .ring .c3 { inset: 32%; border-style: solid; background: var(--accent-soft); }
.ring .p { position: absolute; transform: translate(-50%,-50%); text-align: center; font-size: 12px; width: 88px; line-height: 1.2; }
.av, .avatar { width: 52px; height: 52px; border-radius: 50%; display: grid; place-items: center; font-weight: 800; color: #fff; margin: 0 auto 4px; font-size: 17px; background: var(--accent); flex: none; }
.av.you { background: var(--ink); } .av.a2 { background: #0e7490; } .av.a3 { background: #475569; }
.person, .persona { display: flex; gap: 14px; align-items: center; }
.tag, .marca { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; padding: 4px 10px; border-radius: 99px; background: var(--accent-soft); color: var(--accent-tx); font-weight: 600; margin-right: .35rem; }
.grid2, .temas { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.tile, .tema { background: var(--card); border: 2px solid var(--line); border-radius: var(--r); min-height: 120px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; font-weight: 700; text-align: center; padding: 12px; color: var(--ink); text-decoration: none; }
.tile.on, .tema.on { border-color: var(--accent); background: var(--accent-soft); }
.reggrid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.regcard { background: var(--card); border: 1px solid var(--line); border-radius: var(--r); padding: 12px; }
.regcard summary { display: flex; flex-direction: column; align-items: center; gap: 6px; cursor: pointer; min-height: 44px; text-align: center; font-weight: 700; list-style: none; }
.regcard summary::-webkit-details-marker { display: none; }
svg.i, .icono { width: 28px; height: 28px; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; flex: none; color: var(--accent-tx); }
.tile svg.i { width: 44px; height: 44px; }
.stat { display: flex; gap: 12px; } .stat .card { flex: 1; text-align: center; padding: 14px 8px; } .stat b { display: block; font-size: 30px; color: var(--accent-tx); }
.tl { border-left: 3px solid var(--line); margin-left: 10px; padding-left: 18px; display: flex; flex-direction: column; gap: 14px; }
.tl div { position: relative; } .tl div:before { content: ""; position: absolute; left: -27px; top: 6px; width: 15px; height: 15px; border-radius: 50%; background: var(--accent); border: 3px solid var(--bg); }
.coins { display: grid; grid-template-columns: repeat(10, 1fr); gap: 5px; } .coins i { aspect-ratio: 1; border-radius: 50%; display: block; }
.leg { display: flex; flex-direction: column; gap: 10px; } .leg div { display: flex; align-items: center; gap: 12px; }
.leg .sw { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; color: #fff; flex: none; } .leg .sw svg.i { color: #fff; width: 22px; height: 22px; } .leg b { margin-left: auto; font-size: 20px; }
.big { font-size: 44px; font-weight: 800; line-height: 1; color: var(--accent-tx); }
.steps { display: flex; flex-direction: column; gap: 12px; } .step { display: flex; gap: 14px; align-items: flex-start; }
.n { width: 44px; height: 44px; border-radius: 50%; background: var(--accent-soft); color: var(--accent-tx); display: grid; place-items: center; font-weight: 800; flex: none; }
.copy { background: var(--copy-bg); border: 2px dashed var(--dash); border-radius: 16px; padding: 14px; font-size: 16px; }
nav.bottom { display: flex; border-top: 1px solid var(--line); background: var(--card); max-width: 1100px; margin: 0 auto; position: sticky; bottom: 0; }
nav.bottom a { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 10px 0 14px; font-size: 13px; color: var(--muted); text-decoration: none; font-weight: 600; min-height: 56px; }
nav.bottom a.on { color: var(--accent-tx); }
.aviso { background: var(--aviso-bg); border: 1px solid var(--aviso-line); color: var(--aviso-ink); border-radius: 16px; padding: .75rem; }
.fuente, details.fuente { font-size: 14px; color: var(--muted); background: transparent; border: 0; padding: 0; margin-top: .5rem; overflow-wrap: anywhere; }
details.fuente summary, details.why summary { color: var(--accent-tx); font-weight: 600; min-height: 44px; cursor: pointer; display: flex; align-items: center; }
details.ayuda { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: .6rem .8rem; margin: .5rem 0; font-size: 16px; }
details.ayuda summary { min-height: 44px; cursor: pointer; font-weight: 600; display: flex; align-items: center; color: var(--accent-tx); }
.sencillo { border-left: 4px solid var(--accent); }
img.foto { max-width: 100%; height: auto; border-radius: var(--r); }
label { display: block; margin: .75rem 0 .25rem; font-weight: 600; }
input[type=text], input[type=file], input[type=search], select, textarea { width: 100%; min-height: 48px; font-size: 1rem; }
textarea { min-height: 88px; }
table { border-collapse: collapse; width: 100%; } th, td { text-align: left; padding: .5rem; border-bottom: 1px solid var(--line); vertical-align: top; }
.debil, .sub { color: var(--muted); } .debil { font-size: .92rem; }
u.term { text-decoration: underline dotted var(--accent-tx) 2px; text-underline-offset: 4px; }
@media (min-width: 640px) {
  header.top, main, footer { max-width: 1100px; padding: 20px 32px; }
  nav.bottom { display: none; }
  nav.topmenu { display: flex; gap: 4px; margin-left: auto; }
  nav.topmenu a { display: inline-flex; align-items: center; gap: 6px; padding: 10px 14px; min-height: 44px; border-radius: 12px; color: var(--muted); text-decoration: none; font-weight: 600; font-size: 16px; }
  nav.topmenu a.on { color: var(--accent-tx); background: var(--accent-soft); }
  .a11y { margin-left: 0; }
  .cols { display: grid; grid-template-columns: 1fr 1fr; align-items: start; }
  .grid2, .temas { grid-template-columns: repeat(3, 1fr); }
  .reggrid { grid-template-columns: repeat(4, 1fr); }
  .ring { position: sticky; top: 16px; }
  h1 { font-size: 36px; }
}
"""


def e(v) -> str:
    return html.escape("" if v is None else str(v))


JS = """<script>
function escuchar(){ try{ speechSynthesis.cancel(); var u = new SpeechSynthesisUtterance(document.querySelector('main').innerText); u.lang = 'es-MX'; speechSynthesis.speak(u); }catch(err){} }
function detener(){ try{ speechSynthesis.cancel(); }catch(err){} }
function copiar(id){ var x = document.getElementById(id); if(!x) return; if(x.tagName === 'TEXTAREA' || x.tagName === 'INPUT'){ x.select(); } if(navigator.clipboard) navigator.clipboard.writeText(x.value || x.innerText); else document.execCommand('copy'); }
function copiarTexto(id){ var x = document.getElementById(id); if(x && navigator.clipboard) navigator.clipboard.writeText(x.innerText); }
function saltarBienvenida(){ try{ localStorage.setItem('bienvenida-vista', '1'); }catch(err){} var b = document.getElementById('bienvenida'); if(b) b.remove(); }
function empezar(){ try{ localStorage.setItem('bienvenida-vista', '1'); }catch(err){} }
function filtrar(input, id){ var q = input.value.toLowerCase(); document.querySelectorAll('#' + id + ' [data-nombre]').forEach(function(el){ el.style.display = el.getAttribute('data-nombre').toLowerCase().includes(q) ? '' : 'none'; }); }
function filtrarTema(sel){ document.querySelectorAll('[data-tema]').forEach(function(el){ el.style.display = (!sel.value || el.getAttribute('data-tema') === sel.value) ? '' : 'none'; }); }
function menuA11y(){ var m = document.getElementById('menu-a11y'); if(m) m.hidden = !m.hidden; }
function ponerTema(t){ try{ if(t === 'system'){ localStorage.removeItem('tema'); document.documentElement.removeAttribute('data-theme'); } else { localStorage.setItem('tema', t); document.documentElement.dataset.theme = t; } }catch(err){} }
async function compartir(url, texto){ try{ var r = await fetch(url); var b = await r.blob(); var f = new File([b], 'tarjeta.png', {type: 'image/png'}); if(navigator.canShare && navigator.canShare({files: [f]})){ await navigator.share({files: [f], text: texto}); return; } }catch(err){} var a = document.createElement('a'); a.href = url; a.download = 'tarjeta.png'; a.click(); }
</script>"""


def pagina(titulo: str, cuerpo: str, paso: int | None = None, seccion: str | None = None,
           sin_titulo: bool = False) -> HTMLResponse:
    if paso:
        prog = "".join(f'<i class="{"on" if i < paso else ""}"></i>' for i in range(4))
        top = (f'<button class="back" type="button" onclick="history.back()" aria-label="Volver">'
               f'<svg class="i" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg></button><div class="prog">{prog}</div>')
    else:
        top = '<b style="font-size:18px">Atlixco a la vista</b>'
    items = [("/", "home", "Inicio", "inicio"), ("/representantes", "ppl", "Gobierno", "gobierno"),
             ("/gastos", "coin", "Gastos", "gastos"), ("/actua", "mega", "Actúa", "actua")]
    topmenu = '<nav class="topmenu" aria-label="Secciones">' + "".join(
        f'<a href="{h}" class="{"on" if k == seccion else ""}"><svg class="i" aria-hidden="true"><use href="#i-{ic}"/></svg>{t}</a>'
        for h, ic, t, k in items) + "</nav>"
    a11y = ('<div class="a11y"><button class="listen" type="button" onclick="menuA11y()" aria-label="Accesibilidad: escuchar esta página y cambiar el tema">'
            '<svg class="i" aria-hidden="true"><path d="M11 5L6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 010 7M18.5 5.5a9 9 0 010 13"/></svg></button>'
            '<div class="a11y-panel" id="menu-a11y" hidden>'
            '<button class="btn" type="button" onclick="escuchar()">Escuchar esta página</button>'
            '<button class="btn ghost" type="button" onclick="detener()">Detener lectura</button>'
            '<p style="font-size:16px;margin:.4rem 0"><strong>Tema de la pantalla</strong></p>'
            '<div class="tema-btns"><button type="button" onclick="ponerTema(\'light\')">Claro</button>'
            '<button type="button" onclick="ponerTema(\'system\')">Sistema</button>'
            '<button type="button" onclick="ponerTema(\'dark\')">Oscuro</button></div></div></div>')
    top += topmenu + a11y
    nav = ""
    if seccion:
        nav = '<nav class="bottom">' + "".join(
            f'<a href="{h}" class="{"on" if k == seccion else ""}"><svg class="i" aria-hidden="true"><use href="#i-{ic}"/></svg>{t}</a>'
            for h, ic, t, k in items) + "</nav>"
    simbolos = "".join(f'<symbol id="i-{k}" viewBox="0 0 24 24">{v}</symbol>' for k, v in _ICONOS.items())
    return HTMLResponse(f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(titulo)} — Atlixco a la vista</title>
<script>try{{ var t = localStorage.getItem('tema'); if(t && t !== 'system') document.documentElement.dataset.theme = t; }}catch(err){{}}</script>
<style>{CSS}</style></head><body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>{simbolos}</defs></svg>
<header class="top">{top}</header>
<main>{'' if sin_titulo else f'<h1>{e(titulo)}</h1>'}{cuerpo}</main>
<footer class="debil">Datos de documentos públicos oficiales, mostrados con su fuente.</footer>{nav}{JS}</body></html>""")


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
    "back": '<path d="M15 18l-6-6 6-6"/>',
    "spk": '<path d="M11 5L6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 010 7M18.5 5.5a9 9 0 010 13"/>',
    "pin": '<path d="M12 21s-7-6.2-7-12a7 7 0 0114 0c0 5.8-7 12-7 12z"/><circle cx="12" cy="9" r="2.5"/>',
    "srch": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "road": '<path d="M5 21L9 3M19 21L15 3M12 4v3M12 11v3M12 18v2"/>',
    "drop": '<path d="M12 3s6 7 6 11a6 6 0 01-12 0c0-4 6-11 6-11z"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    "bulb": '<path d="M9 18h6M10 21h4M12 3a6 6 0 00-4 10.5c.8.8 1 1.6 1 2.5h6c0-.9.2-1.7 1-2.5A6 6 0 0012 3z"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8.5-8 9-4.5-1-8-4-8-9V6z"/>',
    "store": '<path d="M4 9l1.5-5h13L20 9M4 9h16v11H4zM4 9c0 2 4 2 4 0 0 2 4 2 4 0 0 2 4 2 4 0 0 2 4 2 4 0M10 20v-5h4v5"/>',
    "ppl": '<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.5 2.7-6 6-6s6 2.5 6 6"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14.2c2.9.2 5 2.5 5 5.8"/>',
    "box": '<path d="M3 7l9-4 9 4v10l-9 4-9-4zM3 7l9 4 9-4M12 11v10"/>',
    "tool": '<path d="M14.5 6.5a4 4 0 00-5 5L4 17l3 3 5.5-5.5a4 4 0 005-5l-2.5 2.5-2.5-.5-.5-2.5z"/>',
    "hand": '<path d="M3 14h4l4 3h6a2 2 0 000-4h-5M7 14V9a2 2 0 014 0v4M14 9a3 3 0 106 0 3 3 0 00-6 0"/>',
    "crane": '<path d="M6 21V4l14 3M6 4L3 7h3M17 7v5M15 12h4v3h-4zM3 21h8"/>',
    "truck": '<path d="M3 6h11v10H3zM14 10h4l3 3v3h-7"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
    "pig": '<path d="M5 11a7 6 0 0113-2h2v4h-2a7 6 0 01-3 4v3h-3v-2H9v2H6v-3.5A6 6 0 015 11z"/><circle cx="15" cy="10" r=".8"/>',
    "arrows": '<path d="M4 8h14l-3-3M20 16H6l3 3"/>',
    "doc": '<path d="M6 3h8l4 4v14H6zM14 3v4h4M9 14l2 2 4-4"/>',
    "home": '<path d="M3 11l9-7 9 7M5 10v10h14V10"/>',
    "coin": '<circle cx="12" cy="12" r="8"/><path d="M14.5 9.5c-.5-1-1.5-1.5-2.5-1.5-1.5 0-2.5.8-2.5 2s1 1.6 2.5 2 2.5.8 2.5 2-1 2-2.5 2c-1 0-2-.5-2.5-1.5M12 6.5v1.5M12 16v1.5"/>',
    "mega": '<path d="M3 10v4h3l8 4V6L6 10zM18 9a4 4 0 010 6"/>',
    "cam": '<path d="M4 7h3l2-3h6l2 3h3v12H4z"/><circle cx="12" cy="13" r="3.5"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/>',
    "cal": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "otros": '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>',
}
# Alias usados por las pantallas anteriores.
_ICONOS.update({"casa": _ICONOS["home"], "personas": _ICONOS["ppl"], "calle": _ICONOS["road"],
                "agua": _ICONOS["drop"], "basura": _ICONOS["trash"], "alumbrado": _ICONOS["bulb"],
                "seguridad": _ICONOS["shield"], "mercados": _ICONOS["store"], "dinero": _ICONOS["coin"],
                "foto": _ICONOS["cam"], "accion": _ICONOS["mega"],
                "mesa": _ICONOS["ppl"]})


def icono(clave: str, texto: str) -> str:
    """Icono SVG en línea, de un solo estilo, siempre con texto alternativo."""
    return (f'<svg class="i" viewBox="0 0 24 24" role="img" aria-label="{e(texto)}">'
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


# Nombre común por capítulo: explicación general en palabras sencillas, no es el nombre oficial.
CAPITULOS_COMUNES = {
    "1000": ("ppl", "Sueldos del personal"),
    "2000": ("box", "Materiales y cosas que se usan"),
    "3000": ("tool", "Servicios, como luz, agua y rentas"),
    "4000": ("hand", "Apoyos y ayuda a la gente"),
    "5000": ("truck", "Vehículos, muebles y equipo"),
    "6000": ("crane", "Obra pública"),
    "7000": ("pig", "Ahorros e inversiones"),
    "8000": ("arrows", "Dinero que se reparte"),
    "9000": ("doc", "Pago de deudas"),
}
PALETA_MONEDAS = ["var(--c1)", "var(--c3)", "var(--c6)", "var(--c2)", "var(--c4)",
                  "var(--c7)", "var(--c5)", "var(--c8)", "var(--c9)"]


def _n_documentos(con) -> int:
    try:
        return con.execute("SELECT count(*) FROM documentos").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def _envolver(draw, texto_: str, fuente_, ancho: int) -> list[str]:
    lineas, actual = [], ""
    for palabra in texto_.split():
        prueba = (actual + " " + palabra).strip()
        if draw.textlength(prueba, font=fuente_) <= ancho:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def _tarjeta_png(dato: str, nombre: str, cargo: str, fuente: str) -> bytes:
    """Tarjeta 1080x1350 para compartir: dato principal, nombre, cargo y fuente. Sin datos personales."""
    img = Image.new("RGB", (1080, 1350), "#f6f5fb")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1080, 300], fill="#5b3fd1")
    titulo = ImageFont.load_default(size=64)
    grande = ImageFont.load_default(size=88)
    medio = ImageFont.load_default(size=56)
    chico = ImageFont.load_default(size=40)
    d.text((70, 90), "Atlixco a la vista", font=titulo, fill="#ffffff")
    d.text((70, 180), "Datos de documentos públicos, con su fuente", font=chico, fill="#ddd3ff")
    y = 380
    for linea in _envolver(d, dato, grande, 940)[:6]:
        d.text((70, y), linea, font=grande, fill="#1d1b2e")
        y += 105
    y += 40
    for linea in _envolver(d, nombre, medio, 940)[:3]:
        d.text((70, y), linea, font=medio, fill="#1d1b2e")
        y += 70
    for linea in _envolver(d, cargo, chico, 940)[:3]:
        d.text((70, y), linea, font=chico, fill="#59556f")
        y += 55
    d.line([70, 1150, 1010, 1150], fill="#5b3fd1", width=6)
    fy = 1180
    for linea in _envolver(d, f"Fuente: {fuente}", chico, 940)[:3]:
        d.text((70, fy), linea, font=chico, fill="#59556f")
        fy += 52
    salida = io.BytesIO()
    img.save(salida, format="PNG")
    return salida.getvalue()


def _compartir_html(url_png: str, texto: str) -> str:
    wa = "https://wa.me/?text=" + quote(texto)
    return ('<div class="card"><h3>Compartir</h3>'
            '<p style="font-size:16px">Una imagen con el dato y su fuente, sin datos personales.</p>'
            f'<button class="btn ghost" type="button" onclick="compartir(\'{e(url_png)}\', \'{e(texto)}\')">Compartir</button>'
            f'<p style="font-size:16px"><a href="{e(url_png)}" download="tarjeta.png">Descargar la imagen</a> · '
            f'<a href="{e(wa)}">Enviar por WhatsApp</a></p></div>')


@app.get("/compartir/funcionario/{id_}.png")
def compartir_funcionario(id_: int):
    with _con() as con:
        filas = [f for f in _gob(con, "funcionarios") if f["id"] == id_]
        if not filas:
            return HTMLResponse("<p>No se encontró a la persona.</p>", status_code=404)
        f = filas[0]
        acuerdos = [a for a in cruzar._acuerdos(con)
                    if any(plano(p["nombre"]) == plano(f["nombre"]) for p in json.loads(a["propuesto_por"]))]
        ids = [a["id"] for a in acuerdos]
        hallazgos_n = (con.execute("SELECT count(*) FROM hallazgos WHERE acuerdo_id IN (%s)"
                                   % ",".join("?" * len(ids)), ids).fetchone()[0] if ids else 0)
        n_docs = _n_documentos(con)
    dato = (f"{len(acuerdos)} propuestas en los acuerdos revisados. "
            f"{hallazgos_n} diferencias encontradas en los {n_docs} documentos revisados hasta hoy.")
    png = _tarjeta_png(dato, f["nombre"], f["cargo"], f"{f['archivo']}, página {f['pagina']}")
    return Response(png, media_type="image/png")


@app.get("/compartir/hallazgo/{id_}.png")
def compartir_hallazgo(id_: int):
    with _con() as con:
        filas = _filas(con, "SELECT * FROM hallazgos WHERE id = ?", (id_,))
        n_docs = _n_documentos(con)
    if not filas:
        return HTMLResponse("<p>No se encontró el hallazgo.</p>", status_code=404)
    h = filas[0]
    png = _tarjeta_png(h["descripcion"][:300], "Diferencia entre documentos públicos",
                       f"Revisado en {n_docs} documentos públicos hasta hoy",
                       f"{h['archivo_presupuesto']}, página {h['pagina_presupuesto']}")
    return Response(png, media_type="image/png")


@app.get("/gastos", response_class=HTMLResponse)
def gastos():
    """Pantalla 6 del recorrido: el gasto del año en 100 monedas (mayor residuo, suma exacta 100)."""
    with _con() as con:
        partidas = [p for p in cruzar._partidas(con) if p["monto_mxn"]]
        urls = _urls(con)
    monedas = monedas_100(partidas)
    if not monedas:
        return pagina("En qué se gasta", "<p>Todavía no hay partidas con monto en las fuentes revisadas.</p>",
                      seccion="gastos")
    total = sum(p["monto_mxn"] for p in partidas)
    orden = sorted(partidas, key=lambda p: -monedas[p["id"]])
    color = {p["id"]: PALETA_MONEDAS[i % len(PALETA_MONEDAS)] for i, p in enumerate(orden)}
    comun = {p["id"]: CAPITULOS_COMUNES.get(p["capitulo"] or "", ("coin", "Otro gasto")) for p in orden}
    circulos = "".join(f'<i style="background:{color[p["id"]]}"></i>' * monedas[p["id"]] for p in orden)
    aria = "De cada 100 pesos: " + ", ".join(f'{monedas[p["id"]]} a {comun[p["id"]][1].lower()}' for p in orden)
    leyenda = "".join(f'<div><span class="sw" style="background:{color[p["id"]]}">{icono(comun[p["id"]][0], "Icono de " + comun[p["id"]][1])}</span>'
                      f'{e(comun[p["id"]][1])}<b>{monedas[p["id"]]}</b></div>' for p in orden)
    oficiales = "".join(f'<div><strong>{e(p["capitulo"] or "")} · {e(p["nombre"])}</strong>'
                        f'<br>{_dinero(p["monto_mxn"])} ({e(en_palabras(p["monto_mxn"]))}): {monedas[p["id"]]} de cada 100 pesos.'
                        f'{fuente_html(p["archivo"], p["pagina"], p["fragmento"], urls)}</div>' for p in orden)
    cuerpo = (f'<div><p class="sub">En 2026 Atlixco planea gastar</p>'
              f'<p class="big">{e(en_palabras(total).removesuffix(" de pesos"))}</p>'
              f'<p class="sub">de pesos. Imagina que fueran 100 monedas:</p></div>'
              f'<div class="cols"><div class="card"><div class="coins" role="img" aria-label="{e(aria)}">{circulos}</div></div>'
              f'<div class="leg">{leyenda}</div></div>'
              f'<p class="sub" style="font-size:16px">Los nombres en palabras sencillas de arriba son una explicación '
              f'general. El nombre oficial de cada grupo de gasto, su monto exacto y su fuente están aquí:</p>'
              f'<div class="card"><h3>Nombres oficiales y montos</h3>{oficiales}</div>')
    return pagina("En qué se gasta", cuerpo, seccion="gastos")


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


def _tarjeta_persona(titulo, nombre, hace, fila_fuente, contacto, urls, enlace, distancia, color=""):
    contacto_html = ""
    if contacto:
        datos = " · ".join(x for x in [contacto.get("telefono"), contacto.get("direccion"), contacto.get("horario")] if x)
        contacto_html = (f'<p style="font-size:16px"><strong>Cómo encontrarle:</strong> {e(contacto["oficina"])}'
                         f'{(" — " + e(datos)) if datos else ""}</p>{_fuente_de(contacto, urls)}')
    return (f'<div class="card person"><div class="av {color}" style="margin:0" aria-hidden="true">{e(_iniciales(nombre))}</div><div>'
            f'<span class="tag">{e(distancia)}</span><h3>{e(nombre)}</h3>'
            f'<p class="sub" style="font-size:16px">{e(titulo)}</p>'
            f'<p style="font-size:16px"><strong>Qué hace:</strong> {e(hace)}</p>{_fuente_de(fila_fuente, urls)}{contacto_html}'
            f'<p><a class="btn ghost" href="{e(enlace)}">Ver su trabajo</a></p></div></div>')


def _icono_tema(texto_: str) -> str:
    t = plano(texto_ or "")
    for clave, ic in [("desarrollo urbano", "crane"), ("obras", "crane"), ("seguridad", "shield"),
                      ("gobernacion", "shield"), ("salud", "hand"), ("educacion", "doc"), ("cultura", "doc"),
                      ("hacienda", "coin"), ("tesoreria", "coin"), ("agua", "drop"), ("comercio", "store"),
                      ("mercados", "store"), ("turismo", "pin"), ("agricultura", "truck"), ("campo", "truck"),
                      ("basura", "trash"), ("alumbrado", "bulb"), ("ecologia", "drop"), ("ambiente", "drop")]:
        if clave in t:
            return ic
    return "ppl"


@app.get("/representantes", response_class=HTMLResponse)
def representantes(junta: int = 0):
    with _con() as con:
        funcionarios = _gob(con, "funcionarios")
        juntas = _gob(con, "juntas_auxiliares")
        funciones = _gob(con, "funciones_cargo")
        contactos = _gob(con, "contacto_institucional")
        urls = _urls(con)
    elegida = next((j for j in juntas if j["id"] == junta), None)
    nivel_comunidad, nivel_presidencia = [], []
    if elegida:
        f_aux = _buscar_fila(funciones, "presidente auxiliar")
        nivel_comunidad.append(_tarjeta_persona(
            f"Presidente auxiliar de {elegida['nombre']}: la autoridad de tu junta auxiliar",
            elegida["presidente"] or elegida["nombre"],
            f_aux["funcion"] if f_aux else "Atiende los asuntos de su junta auxiliar.",
            elegida, _buscar_fila(contactos, "atención ciudadana", "ayuntamiento de atlixco"), urls,
            f"/actua?para={elegida['nombre']}", "Lo más cercano a ti"))
    f_insp = _buscar_fila(funciones, "inspector")
    nivel_comunidad.append(f"""<div class="tarjeta persona"><div class="avatar" aria-hidden="true">IN</div><div>
<span class="marca">Lo más cercano a ti</span><br><strong>El inspector o inspectora de tu colonia</strong><br>
<p><strong>Qué hace:</strong> {e(f_insp['funcion']) if f_insp else ''}</p>
<p class="debil">Su nombre no está en las fuentes oficiales revisadas; pregunta por él en tu junta auxiliar o en el Ayuntamiento.</p>
{_fuente_de(f_insp, urls) if f_insp else ''}</div></div>""")
    regidores = [f for f in funcionarios if f["comision"]]
    f_reg = _buscar_fila(funciones, "regidores")
    sindico = _buscar_fila(funcionarios, "sindicatura")
    if sindico:
        f_sin = _buscar_fila(funciones, "síndico", "sindico")
        nivel_presidencia.append(_tarjeta_persona(
            "Síndico municipal: representa legalmente al municipio", sindico["nombre"],
            f_sin["funcion"] if f_sin else "", sindico,
            _buscar_fila(contactos, "atención ciudadana", "ayuntamiento de atlixco"), urls,
            f"/revisar/{sindico['id']}", "Representa a todo el municipio", "a3"))
    presidenta = _buscar_fila(funcionarios, "presidenta")
    if presidenta:
        f_pre = _buscar_fila(funciones, "presidente municipal")
        nivel_presidencia.append(_tarjeta_persona(
            "Presidenta municipal: encabeza el gobierno del municipio", presidenta["nombre"],
            f_pre["funcion"] if f_pre else "", presidenta,
            _buscar_fila(contactos, "presidencia municipal"), urls, f"/revisar/{presidenta['id']}",
            "Representa a todo el municipio", "a3"))
    # Diagrama de círculos concéntricos: tú al centro y cada autoridad más lejos.
    lugar = elegida["nombre"] if elegida else "Tu comunidad"
    reg_obras = _buscar_fila(funcionarios, "desarrollo urbano") or (regidores[0] if regidores else None)
    n_reg = f"+{len(regidores) - 1}" if len(regidores) > 1 else ""
    puntos = [("50%", "50%", "you", "Tú", lugar)]
    if elegida:
        puntos.append(("50%", "22%", "", _iniciales(elegida["presidente"] or ""), "Presidente auxiliar"))
    if reg_obras:
        puntos.append(("16%", "40%", "a2", _iniciales(reg_obras["nombre"]), "Regidora o regidor de obras"))
    if n_reg:
        puntos.append(("84%", "40%", "a2", n_reg, "Regidores"))
    if sindico:
        puntos.append(("24%", "86%", "a3", _iniciales(sindico["nombre"]), "Síndico"))
    if presidenta:
        puntos.append(("76%", "86%", "a3", _iniciales(presidenta["nombre"]), "Presidenta"))
    anillos = "".join(f'<div class="p" style="left:{x};top:{y}"><div class="av {c}">{e(i)}</div>{e(t)}</div>'
                      for x, y, c, i, t in puntos)
    visual = (f'<div class="ring" role="img" aria-label="Tú al centro; cerca, tu presidente auxiliar; '
              f'luego regidoras y regidores; más lejos, el síndico y la presidenta municipal">'
              f'<div class="c"></div><div class="c c2"></div><div class="c c3"></div>{anillos}</div>'
              '<p class="sub" style="font-size:16px">Primero ves a quien tienes más cerca de tu casa y al final a quien '
              'gobierna para todo el municipio. Todas deciden juntas en el Cabildo.</p>')
    temas_unicos = sorted({f["comision"] for f in regidores})
    opciones = "".join(f'<option value="{e(t)}">{e(t)}</option>' for t in temas_unicos)
    hace_reg = f_reg["funcion"] if f_reg else "Participa en las decisiones del Cabildo."
    reggrid = "".join(
        f'<details class="regcard" data-tema="{e(f["comision"])}"><summary>'
        f'<span class="av a2" aria-hidden="true">{e(_iniciales(f["nombre"]))}</span>'
        f'{icono(_icono_tema(f["comision"]), "Icono del tema " + f["comision"])}<span>{e(f["nombre"])}</span>'
        f'<span class="sub" style="font-size:14px;font-weight:400">{e(f["comision"])}</span></summary>'
        f'<p style="font-size:16px">{e(f["cargo"])}</p>'
        f'<p style="font-size:16px"><strong>Qué hace:</strong> {e(hace_reg)}</p>{_fuente_de(f, urls)}'
        f'<p><a class="btn ghost" href="/revisar/{f["id"]}">Ver su trabajo</a></p></details>' for f in regidores)
    derecha = ('<div class="stack"><h2>Tu comunidad</h2>' + "".join(nivel_comunidad)
               + '<h2>Cabildo: regidoras y regidores</h2>'
                 '<label for="filtro-tema">¿De qué se encarga?</label>'
                 f'<select id="filtro-tema" onchange="filtrarTema(this)"><option value="">Todos los temas</option>{opciones}</select>'
               + f'<div class="reggrid">{reggrid}</div>'
                 '<h2>Presidencia</h2>' + "".join(nivel_presidencia)
               + """<div class="card"><h3>El Cabildo completo</h3>
<p style="font-size:16px">Presidenta, síndico y regidores se reúnen, discuten y votan. Lo que acuerdan queda en documentos públicos.</p>
<p><a class="btn" href="/temas">¿Qué te preocupa?</a></p>
<p><a class="btn ghost" href="/acuerdos">Ver los acuerdos</a></p></div></div>""")
    cuerpo = f'<div class="cols"><div>{visual}</div>{derecha}</div>'
    return pagina("Estas personas trabajan para ti", cuerpo, paso=2)


def _temas_grid(seleccion=""):
    return '<div class="grid2">' + "".join(
        f'<a class="tile {"on" if clave == seleccion else ""}" href="/temas/{clave}">{icono(ic, titulo)}{e(titulo)}</a>'
        for clave, ic, titulo, _, _ in TEMAS) + "</div>"


@app.get("/temas", response_class=HTMLResponse)
def temas():
    cuerpo = ('<p class="sub">Te decimos quién se encarga.</p>' + _temas_grid())
    return pagina("¿Qué te preocupa en tu comunidad?", cuerpo, paso=3)


@app.get("/temas/{clave}", response_class=HTMLResponse)
def tema(clave: str):
    elegido = next((t for t in TEMAS if t[0] == clave), None)
    if not elegido:
        return HTMLResponse("<p>No se encontró el tema.</p>", status_code=404)
    _, ic, titulo, nombre_comision, orientacion = elegido
    with _con() as con:
        comisiones = _gob(con, "comisiones")
        funcionarios = _gob(con, "funcionarios")
        funciones = _gob(con, "funciones_cargo")
        urls = _urls(con)
    comision = _buscar_fila(comisiones, nombre_comision.replace("De ", "", 1)) if nombre_comision else None
    regidor = _buscar_fila(funcionarios, comision["nombre"].replace("De ", "", 1)) if comision else None
    marca = ('<span class="tag">Orientación general, no es un dato oficial</span>' if orientacion
             else '<span class="tag">Según el Reglamento de Cabildo</span>')
    if comision and regidor:
        f_reg = _buscar_fila(funciones, "regidores")
        detalle = (f'<div class="card person" style="border:2px solid var(--accent)">'
                   f'<div class="av a2" style="margin:0" aria-hidden="true">{e(_iniciales(regidor["nombre"]))}</div><div>'
                   f'<p class="sub" style="font-size:15px">De {e(titulo.lower())} se encarga</p><h3>{e(regidor["nombre"])}</h3>'
                   f'<p style="font-size:16px">{e(regidor["cargo"])}</p>'
                   f'<p style="font-size:16px">Comisión: {e(comision["nombre"])}</p>{marca}'
                   f'<p style="font-size:16px"><strong>Qué hace:</strong> {e(f_reg["funcion"]) if f_reg else ""}</p>'
                   f'{_fuente_de(comision, urls)}{_fuente_de(regidor, urls)}'
                   f'<p><a class="btn" href="/revisar/{regidor["id"]}">Ver qué ha hecho</a></p></div></div>')
    else:
        detalle = ('<div class="card"><p style="font-size:16px">Para cualquier tema puedes pedir información y acudir a una sesión pública.</p>'
                   f'{marca}<p><a class="btn" href="/actua">Pide información</a></p></div>')
    cuerpo = ('<p class="sub">Te decimos quién se encarga.</p>' + _temas_grid(clave) + detalle)
    return pagina("¿Qué te preocupa en tu comunidad?", cuerpo, paso=3)


@app.get("/revisar", response_class=HTMLResponse)
def revisar():
    with _con() as con:
        funcionarios = _gob(con, "funcionarios")
        juntas = _gob(con, "juntas_auxiliares")
    tarjetas = "".join(
        f'<div class="card person"><div class="av a2" style="margin:0" aria-hidden="true">{e(_iniciales(f["nombre"]))}</div><div>'
        f'<h3>{e(f["nombre"])}</h3><p class="sub" style="font-size:16px">{e(f["cargo"])}</p>'
        f'<p><a class="btn ghost" href="/revisar/{f["id"]}">Revisa su trabajo</a></p></div></div>' for f in funcionarios)
    tarjetas += "".join(
        f'<div class="card person"><div class="av" style="margin:0" aria-hidden="true">{e(_iniciales(j["presidente"] or j["nombre"]))}</div><div>'
        f'<h3>{e(j["presidente"] or "")}</h3><p class="sub" style="font-size:16px">Presidente auxiliar de {e(j["nombre"])}</p>'
        f'<p><a class="btn ghost" href="/actua?para={e(j["nombre"])}">Pregúntale o pide información</a></p></div></div>' for j in juntas)
    return pagina("Revisa su trabajo", "<p>Elige a una persona para ver qué propuso y qué se aprobó.</p>"
                  f'<div class="cols">{tarjetas}</div>', paso=4)


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
        ids = [a["id"] for a in acuerdos]
        hallazgos_n = (con.execute("SELECT count(*) FROM hallazgos WHERE acuerdo_id IN (%s)"
                                   % ",".join("?" * len(ids)), ids).fetchone()[0] if ids else 0)
        n_docs = _n_documentos(con)
        funciones = _gob(con, "funciones_cargo")
        evidencias = _filas(con, "SELECT * FROM evidencias ORDER BY id DESC LIMIT 3")
    claves = ("presidenta",) if not f["comision"] and "presidenta" in plano(f["cargo"]) else \
             ("síndico", "sindico") if "sindicatura" in plano(f["cargo"]) else ("regidores",)
    f_fun = _buscar_fila(funciones, *claves)
    linea = "".join(f'<div><b>{e(a["fecha_sesion"] or "sin fecha registrada")}</b><br>'
                    f'<span style="font-size:16px">{e(a["acuerdo"])}</span>'
                    f'{fuente_html(a["archivo"], a["pagina"], a["fragmento"], urls)}</div>' for a in acuerdos)
    fotos = "".join(f'<div><strong>Evidencia ciudadana: {e(ev["objeto"])}</strong><br>'
                    + (f'<img class="foto" src="/evidencia-img/{e(Path(ev["superpuesta"]).name)}" '
                       f'alt="Foto ciudadana con la parte observada marcada en color">'
                       if ev["superpuesta"] else "")
                    + f'<p style="font-size:16px">{len(json.loads(ev["sam_resultado"]).get("objetos", []))} parte(s) marcada(s) · sin confirmar</p>'
                      f'<p><a href="/evidencia/{ev["id"]}">Ver la evidencia completa</a></p></div>' for ev in evidencias)
    tag = (f'<span class="tag">{icono("road" if "desarrollo urbano" in plano(f["comision"] or "") else "doc", "Icono del tema")} '
           f'{e(f["comision"])}</span>' if f["comision"] else f'<span class="tag">{e(f["cargo"])}</span>')
    cuerpo = (f'<div style="text-align:center"><div class="av a2" style="width:84px;height:84px;font-size:28px;margin:0 auto" aria-hidden="true">{e(_iniciales(f["nombre"]))}</div>'
              f'<h2>{e(f["nombre"])}</h2>{tag}{_fuente_de(f, urls)}</div>'
              f'<div class="card"><h3>¿Qué hace?</h3><p style="font-size:16px">{e(f_fun["funcion"]) if f_fun else ""}</p>'
              f'{_fuente_de(f_fun, urls) if f_fun else ""}</div>'
              f'<div class="stat"><div class="card"><b>{len(acuerdos)}</b><span style="font-size:15px">propuestas en los acuerdos revisados</span></div>'
              f'<div class="card"><b>{hallazgos_n}</b><span style="font-size:15px">diferencias encontradas en los {n_docs} documentos revisados hasta hoy</span></div></div>'
              f'<p style="font-size:16px">Esto solo cubre los {n_docs} documentos públicos revisados hasta hoy. '
              f'Si falta revisar más, el número puede cambiar.</p>'
              f'<p><a class="btn ghost" href="/evidencia">Ayúdanos a revisar más: sube una foto</a></p>'
              f'<div class="card"><h3 style="margin-bottom:12px">Lo que ha propuesto</h3>'
              + (f'<div class="tl">{linea}</div>' if acuerdos else
                 '<p style="font-size:16px">En los acuerdos revisados no aparece como proponente. Esto solo cubre los documentos cargados hasta hoy.</p>')
              + '</div>'
              + '<div class="card"><h3>Lo que reportan vecinos</h3>'
              + (fotos or '<p style="font-size:16px">Todavía no hay fotos ciudadanas registradas.</p>')
              + f'<p><a class="btn ghost" href="/evidencia">{icono("cam", "Dibujo de una cámara")} Subir una foto</a></p></div>'
              + f'<p><a class="btn" href="/actua?para={e(f["nombre"])}">{icono("mega", "Dibujo de un megáfono")} Pregúntale o pide información</a></p>'
              + _compartir_html(f"/compartir/funcionario/{f['id']}.png",
                                f"{f['nombre']} ({f['cargo']}): {len(acuerdos)} propuestas en los acuerdos revisados; "
                                f"{hallazgos_n} diferencias en los {n_docs} documentos revisados. Fuente: {f['archivo']}, p. {f['pagina']}"))
    return pagina(f["nombre"], cuerpo, paso=4)


@app.get("/actua", response_class=HTMLResponse)
def actua(para: str = "", tema: str = ""):
    asunto = tema or (f"el trabajo de {para}" if para else "el gasto y las decisiones del Ayuntamiento de Atlixco")
    with _con() as con:
        urls = _urls(con)
        try:
            crudas = _filas(con, "SELECT * FROM rutas ORDER BY clave")
        except sqlite3.OperationalError:
            crudas = []
        rutas = _rutas_html(con, asunto, urls)
    con_plantilla = next((r for r in crudas if r["plantilla"]), None)
    texto = (con_plantilla["plantilla"].replace("{tema}", asunto) if con_plantilla
             else f"Solicito conocer información sobre {asunto} en 2026, con su costo y ubicación.")
    enlace = con_plantilla["fundamento_url"] if con_plantilla and con_plantilla["fundamento_url"] else ""
    sesion = next((r for r in crudas if "sesion" in plano(r["clave"]) or "sesion" in plano(r["titulo"])), None)
    boton = (f'<p><a class="btn" href="{e(enlace)}">Ir a la Plataforma</a></p>' if enlace else "")
    fuente_sesion = (fuente_html(sesion["fundamento_archivo"], sesion["fundamento_pagina"],
                                 sesion["fundamento_fragmento"], urls) if sesion else "")
    sesion_html = ('<div class="card" style="display:flex;gap:12px;align-items:center">'
                   f'{icono("cal", "Dibujo de un calendario")}<span style="font-size:16px">También puedes ir a una '
                   f'<b>sesión de Cabildo</b>: son públicas.</span>{fuente_sesion}</div>')
    cuerpo = ('<p class="sub">Tienes derecho a preguntar al gobierno en qué gasta y qué hace. Es gratis.</p>'
              '<div class="steps">'
              f'<div class="step"><span class="n">1</span><div><b>Copia este texto</b>'
              f'<div class="copy" id="solicitud" style="margin-top:8px">{e(texto)}</div>'
              f'<button class="btn ghost" type="button" style="margin-top:8px;min-height:48px" '
              f'onclick="copiarTexto(\'solicitud\')">{icono("copy", "Dibujo de dos hojas, copiar")}Copiar texto</button></div></div>'
              '<div class="step"><span class="n">2</span><div><b>Entra a la Plataforma de Transparencia</b>'
              '<p style="font-size:16px">Crea tu cuenta con tu correo.</p></div></div>'
              '<div class="step"><span class="n">3</span><div><b>Pega y envía</b>'
              '<p style="font-size:16px">Elige "Ayuntamiento de Atlixco".</p></div></div>'
              '<div class="step"><span class="n">4</span><div><b>Espera tu respuesta</b>'
              '<p style="font-size:16px">Te llega a tu correo.</p></div></div></div>'
              + boton + sesion_html
              + '<div class="card" style="display:flex;gap:12px;align-items:center">'
                f'{icono("cam", "Dibujo de una cámara")}<span style="font-size:16px">También puedes reportar con '
                f'una foto, por ejemplo un bache o una luminaria apagada.</span></div>'
                '<p><a class="btn ghost" href="/evidencia">Sube una foto</a></p>'
              + rutas)
    return pagina("Pide información", cuerpo, seccion="actua")


@app.get("/", response_class=HTMLResponse)
def inicio():
    hero_svg = """<svg class="h" viewBox="0 0 300 150" role="img" aria-label="Una persona frente al Ayuntamiento, con una lupa">
<rect x="150" y="40" width="130" height="90" rx="6" fill="#ffffff22"/><path d="M140 44 215 12l75 32z" fill="#ffffff33"/>
<g fill="#ffffff44"><rect x="165" y="60" width="16" height="70"/><rect x="200" y="60" width="16" height="70"/><rect x="235" y="60" width="16" height="70"/></g>
<circle cx="70" cy="58" r="20" fill="#fff"/><path d="M38 140c0-30 14-52 32-52s32 22 32 52z" fill="#fff"/>
<circle cx="122" cy="74" r="16" fill="none" stroke="#fff" stroke-width="6"/><path d="M110 86 96 100" stroke="#fff" stroke-width="7" stroke-linecap="round"/></svg>"""
    cuerpo = f"""<section id="bienvenida" class="hero">{hero_svg}
<h1>Conoce a quienes gobiernan tu comunidad</h1>
<p>Te mostramos quiénes son, qué hacen y cómo revisar su trabajo. Toma 2 minutos.</p></section>
<div class="card" style="display:flex;gap:12px;align-items:center">{icono("doc", "Dibujo de un documento")}
<span style="font-size:16px">Todo sale de documentos públicos del Ayuntamiento. Siempre te mostramos de dónde.</span></div>
<p class="aviso">Los hallazgos son discrepancias verificables entre documentos públicos, no acusaciones.</p>
<div style="display:flex;flex-direction:column;gap:10px">
<a class="btn" href="/donde" onclick="empezar()">Empezar</a>
<a class="btn ghost" href="/representantes">Ya conozco, ir al inicio</a></div>"""
    return pagina("Atlixco a la vista", cuerpo, sin_titulo=True)


@app.get("/donde", response_class=HTMLResponse)
def donde():
    with _con() as con:
        juntas = _gob(con, "juntas_auxiliares")
        urls = _urls(con)
        cobertura = _cobertura_html(cruzar.cobertura(con))
    opciones = "".join(
        f'<a href="/representantes?junta={j["id"]}" data-nombre="{e(j["nombre"])} {e(j["presidente"] or "")}">'
        f'{icono("pin", "Dibujo de un pin de mapa")}{e(j["nombre"])}</a>' for j in juntas)
    tecnicos = "".join(
        f"""<div class="tarjeta"><strong>{e(m['archivo'])}</strong><br>
        <span class="debil">Descargado: {e(m.get('descargado', 'sin fecha registrada'))}<br>SHA-256: {e(m.get('sha256', ''))}</span><br>
        <a href="{e(m.get('url', ''))}">Página oficial de la fuente</a> · <a href="/fuentes/{e(m['archivo'])}">Documento guardado</a></div>"""
        for m in _manifiesto())
    cuerpo = f"""<p class="sub">Así te mostramos primero a las personas más cercanas a ti. No guardamos tu respuesta.</p>
<div class="search">{icono("srch", "Dibujo de una lupa")}
<input id="buscar-junta" type="search" placeholder="Escribe tu comunidad o colonia" aria-label="Escribe tu comunidad o colonia" oninput="filtrar(this, 'lista-juntas')" style="border:0;outline:none"></div>
<div class="card list" id="lista-juntas">
<a href="/representantes" data-nombre="atlixco centro colonias cabecera">{icono("pin", "Dibujo de un pin de mapa")}Atlixco centro y colonias</a>
{opciones}</div>
<p class="debil">Las colonias que atiende cada junta no están en la fuente oficial revisada; por eso la lista es por junta auxiliar.</p>
<details class="tarjeta"><summary><strong>Detalles técnicos y fuentes revisadas</strong></summary>{tecnicos}{cobertura}</details>"""
    return pagina("¿Dónde vives?", cuerpo, paso=1)


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
    return pagina("Funcionarios", f'<div class="cols">{tarjetas}</div>' if tarjetas else "<p>Sin personas registradas en los acuerdos.</p>")


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
    return pagina("Acuerdos de Cabildo", intro + (f'<div class="cols">{tarjetas}</div>' if tarjetas else "<p>Sin acuerdos registrados.</p>"))


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
        n_docs = _n_documentos(con)
    if not lista:
        cuerpo = (f"<p>0 diferencias encontradas en los {n_docs} documentos revisados hasta hoy. "
                  "Esto solo cubre los documentos públicos cargados hasta hoy; si falta revisar más, el número puede cambiar.</p>"
                  '<p><a class="btn ghost" href="/evidencia">Ayúdanos a revisar más: sube una foto</a></p>'
                  "<p>Esto es lo que hay hoy para cruzar y lo que falta:</p>" + cobertura)
    else:
        cuerpo = "".join(f'<div class="tarjeta"><a href="/hallazgos/{h["id"]}">{e(h["tipo"])}</a><br>{e(h["descripcion"])}</div>'
                         for h in lista)
    return pagina("Hallazgos", cuerpo)


@app.get("/hallazgos/{id_}", response_class=HTMLResponse)
def hallazgo(id_: int):
    with _con() as con:
        filas = _filas(con, "SELECT * FROM hallazgos WHERE id = ?", (id_,))
        urls = _urls(con)
        n_docs = _n_documentos(con)
        rutas = _rutas_html(con, "la diferencia entre documentos públicos descrita en esta página", urls) if filas else ""
    if not filas:
        return HTMLResponse("<p>No se encontró el hallazgo.</p>", status_code=404)
    h = filas[0]
    cuerpo = f"""<p>{e(h['descripcion'])}</p>
<p style="font-size:16px">Diferencia encontrada al revisar {n_docs} documentos públicos hasta hoy.</p>
<h2>Cita del presupuesto</h2>
{fuente_html(h['archivo_presupuesto'], h['pagina_presupuesto'], h['fragmento_presupuesto'], urls)}
<h2>Cita del acuerdo</h2>{fuente_html(h['archivo_acuerdo'], h['pagina_acuerdo'], h['fragmento_acuerdo'], urls)}{rutas}""" \
        + _compartir_html(f"/compartir/hallazgo/{h['id']}.png",
                          f"Diferencia entre documentos públicos de Atlixco: {h['descripcion'][:180]} "
                          f"Fuente: {h['archivo_presupuesto']}, p. {h['pagina_presupuesto']}")
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
