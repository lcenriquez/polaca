"""Interfaz web del auditor ciudadano de POLACA.

Uso (desde auditor/):
    ../.venv/bin/python -m uvicorn web:app --host 127.0.0.1 --port 8000

HTML generado en el servidor, sin frameworks de frontend. Leer páginas no
llama a la API: solo la subida de evidencia llama a SAM 3.1 y a Muse Spark
privado, vía evidencia.py. Todo texto que viene de los PDF o de los modelos
se escapa. Lenguaje neutral: los datos se muestran con su fuente, sin
calificaciones.
"""
import contextvars
import html
import io
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from uuid import uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont

import cruzar
import evidencia
import explicar
import extraer
import gobierno
import municipios
from extraer import plano

app = FastAPI(title="POLACA")
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")

# Municipio elegido por la persona: solo vive en su cookie, nunca en un valor por omisión.
_MUN_COOKIE = contextvars.ContextVar("municipio_cookie", default="")


@app.middleware("http")
async def _recordar_municipio(request: Request, call_next):
    _MUN_COOKIE.set(request.cookies.get("municipio", ""))
    resp = await call_next(request)
    # Cabeceras de seguridad en todo (también /static y errores): sin recursos de otros orígenes.
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                               "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                                               "frame-ancestors 'none'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def _elegida(request: Request, m: str = "") -> str | None:
    """Clave del municipio elegido: ?m= manda, luego la cookie; sin elección, None."""
    return m or request.cookies.get("municipio") or None


def _fijar(resp: HTMLResponse, clave: str | None) -> HTMLResponse:
    if clave:
        resp.set_cookie("municipio", clave, max_age=60 * 60 * 24 * 365, path="/", samesite="lax")
    return resp


@app.get("/salud")
def salud():
    return {"estado": "ok"}  # health check de Fly: responde sin tocar la base


def _nombre_municipio(con, clave: str | None) -> tuple[str, str] | None:
    if not clave:
        return None
    filas = _filas(con, "SELECT nombre, estado FROM municipios WHERE clave_inegi = ?", (clave,))
    return (filas[0]["nombre"], filas[0]["estado"]) if filas else None

CSS = """
@font-face { font-family: "Atkinson Hyperlegible"; src: url("/static/fonts/AtkinsonHyperlegible-Regular.ttf") format("truetype"); font-weight: 400; font-display: swap; }
@font-face { font-family: "Atkinson Hyperlegible"; src: url("/static/fonts/AtkinsonHyperlegible-Bold.ttf") format("truetype"); font-weight: 700; font-display: swap; }
body, .btn, .boton, .seg button, .filters button, .search input, input, select, textarea, button { font-family: "Atkinson Hyperlegible", system-ui, -apple-system, "Segoe UI", sans-serif; }
:root { color-scheme: light; --bg:#f7f6fb; --surface:#fff; --surface-2:#f0eef8; --ink:#1c1a2b; --muted:#5d5a73; --muted-2:#44415e; --line:#e3e0ef;
  --accent:#5b3fd1; --accent-ink:#fff; --accent-soft:#ece8fc; --ok:#1e7a4c; --ok-soft:#e3f4ea; --warn:#8a5a00; --warn-soft:#fdf3dc;
  --shadow:0 1px 2px #1c1a2b0f,0 8px 24px #1c1a2b0f; --r:18px;
  --card:#fff; --accent-tx:#5b3fd1; --aviso-bg:#fdf3dc; --aviso-line:#8a5a00; --aviso-ink:#5c3d00; --copy-bg:#f0eef8; --dash:#c9c3e6;
  --c1:#5b3fd1; --c2:#c2410c; --c3:#0e7490; --c4:#a21caf; --c5:#4d7c0f; --c6:#b45309; --c7:#475569; --c8:#be123c; --c9:#0f766e; --mapa:#8a76d9; --panel:rgba(255,255,255,.87); }
@media (prefers-color-scheme: dark) {
:root:not([data-theme="light"]) { color-scheme: dark; --bg:#12101a; --surface:#1c1a27; --surface-2:#252233; --ink:#efedf7; --muted:#a9a5bd; --muted-2:#d6d2e6; --line:#2f2c40;
  --accent:#9d8cff; --accent-ink:#141024; --accent-soft:#2a2547; --ok:#5fd39a; --ok-soft:#173226; --warn:#f2c46b; --warn-soft:#352a12; --shadow:0 1px 2px #0008,0 8px 24px #0006; --r:18px;
  --card:#1c1a27; --accent-tx:#9d8cff; --aviso-bg:#352a12; --aviso-line:#f2c46b; --aviso-ink:#f7e3ac; --copy-bg:#252233; --dash:#4a4568;
  --c1:#5b3fd1; --c2:#c2410c; --c3:#0e7490; --c4:#a21caf; --c5:#4d7c0f; --c6:#b45309; --c7:#475569; --c8:#be123c; --c9:#0f766e; --mapa:#7563b8; --panel:rgba(18,16,26,.85); } }
:root[data-theme="dark"] { color-scheme: dark; --bg:#12101a; --surface:#1c1a27; --surface-2:#252233; --ink:#efedf7; --muted:#a9a5bd; --muted-2:#d6d2e6; --line:#2f2c40;
  --accent:#9d8cff; --accent-ink:#141024; --accent-soft:#2a2547; --ok:#5fd39a; --ok-soft:#173226; --warn:#f2c46b; --warn-soft:#352a12; --shadow:0 1px 2px #0008,0 8px 24px #0006; --r:18px;
  --card:#1c1a27; --accent-tx:#9d8cff; --aviso-bg:#352a12; --aviso-line:#f2c46b; --aviso-ink:#f7e3ac; --copy-bg:#252233; --dash:#4a4568;
  --c1:#5b3fd1; --c2:#c2410c; --c3:#0e7490; --c4:#a21caf; --c5:#4d7c0f; --c6:#b45309; --c7:#475569; --c8:#be123c; --c9:#0f766e; --mapa:#7563b8; --panel:rgba(18,16,26,.85); }
* { box-sizing: border-box; margin: 0; }
body { font: 18px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--ink); background: var(--bg); overflow-x: clip; padding-bottom: 84px; }
@media (min-width: 768px) { body { padding-bottom: 0; } }
a { color: inherit; }
h1 { font-size: clamp(32px,6vw,56px); line-height: 1.05; letter-spacing: -.02em; margin: .4rem 0; }
h2 { font-size: clamp(24px,3.4vw,34px); line-height: 1.15; letter-spacing: -.01em; margin: 1.2rem 0 .5rem; }
h3 { font-size: 19px; line-height: 1.25; margin: .2rem 0; }
.muted, .sub, .debil { color: var(--muted); } .small, .debil { font-size: 15px; } .sub { font-size: 17px; }
.wrap, main, footer.cola { max-width: 1120px; margin: 0 auto; padding: 0 16px; }
@media (min-width: 768px) { .wrap, main, footer.cola { padding: 0 32px; } }
main { display: flex; flex-direction: column; gap: 16px; padding-top: 24px; padding-bottom: 32px; }
footer.cola { padding-bottom: 24px; font-size: 15px; color: var(--muted); }
svg.i { width: 24px; height: 24px; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; flex: none; }
header.top { position: sticky; top: 0; z-index: 10; background: color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter: blur(10px); border-bottom: 1px solid var(--line); }
header.top .wrap { display: flex; align-items: center; gap: 16px; height: 64px; }
.logo { display: flex; align-items: center; gap: 10px; font-weight: 900; letter-spacing: .04em; font-size: 20px; text-decoration: none; }
.logo b { width: 34px; height: 34px; border-radius: 10px; background: var(--accent); color: var(--accent-ink); display: grid; place-items: center; font-size: 18px; }
nav.topmenu, .topnav { display: none; gap: 4px; margin-left: 24px; }
nav.topmenu a, .topnav a { padding: 10px 14px; border-radius: 12px; text-decoration: none; font-weight: 600; color: var(--muted); display: inline-flex; align-items: center; gap: 6px; }
nav.topmenu a.on, .topnav a.on { color: var(--ink); background: var(--surface-2); }
@media (min-width: 768px) { nav.topmenu, .topnav { display: flex; } }
.place { margin-left: auto; display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; padding: 8px 12px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface); text-decoration: none; }
.place svg.i { width: 18px; height: 18px; color: var(--accent); }
.iconbtn { width: 44px; height: 44px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface); color: var(--ink); display: grid; place-items: center; cursor: pointer; }
.a11y { position: relative; }
.a11y summary { list-style: none; } .a11y summary::-webkit-details-marker { display: none; }
.menu, .a11y-panel { position: absolute; right: 0; top: 52px; width: 290px; max-width: 86vw; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r); box-shadow: var(--shadow); padding: 16px; display: flex; flex-direction: column; gap: 14px; z-index: 20; }
.seg { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); background: var(--surface-2); border-radius: 12px; padding: 4px; gap: 4px; }
.seg button { min-height: 44px; border: 0; border-radius: 9px; background: transparent; color: var(--muted); font: 600 15px system-ui; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; cursor: pointer; }
.seg button[aria-pressed="true"] { background: var(--surface); color: var(--ink); box-shadow: var(--shadow); }
.seg svg.i { width: 18px; height: 18px; }
.row { display: flex; align-items: center; gap: 12px; min-height: 44px; }
nav.bottom { position: fixed; bottom: 0; left: 0; right: 0; display: flex; background: var(--surface); border-top: 1px solid var(--line); z-index: 10; }
nav.bottom a { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 8px 0 12px; font-size: 12px; font-weight: 600; color: var(--muted); text-decoration: none; }
nav.bottom a.on { color: var(--accent); }
nav.bottom a svg.i { width: 24px; height: 24px; }
@media (min-width: 768px) { nav.bottom { display: none; } }
.lbl { font: 700 12px/1 system-ui; letter-spacing: .08em; text-transform: uppercase; color: var(--accent); margin-bottom: 14px; }
.card, .tarjeta { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r); padding: 20px; box-shadow: var(--shadow); }
.card, .tarjeta, .regcard, .tile, .btn, .boton, .place, .sugg a, .list a { transition: box-shadow .18s ease, transform .18s ease, border-color .18s ease, background-color .18s ease; }
@media (hover: hover) { .tile:hover, .regcard:hover { transform: translateY(-2px); box-shadow: var(--shadow); } .sugg a:hover, .list a:hover { background: var(--surface-2); } }
.ilu { width: 100%; max-width: 320px; height: auto; }
.skel i { display: block; height: 14px; border-radius: 7px; background: var(--surface-2); margin: 10px 0; animation: p 1.4s infinite; }
button:disabled { opacity: .65; cursor: wait; }
@media (prefers-reduced-motion: reduce) { .card, .tarjeta, .regcard, .tile, .btn, .boton, .place, .sugg a, .list a, .skel i { transition: none; animation: none; } }
.btn, .boton { display: inline-flex; align-items: center; justify-content: center; gap: 10px; min-height: 52px; padding: 0 22px; border-radius: 14px; background: var(--accent); color: var(--accent-ink); font: 700 17px system-ui; border: 0; text-decoration: none; cursor: pointer; }
.btn.ghost, .boton.ghost { background: transparent; color: var(--accent); border: 2px solid var(--accent); }
main .btn, main .boton { display: flex; width: 100%; }
@media (min-width: 768px) { main .btn, main .boton { width: auto; } .btnrow { display: flex; gap: 10px; flex-wrap: wrap; } }
.chip, .tag, .marca { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 99px; font-size: 14px; font-weight: 600; background: var(--accent-soft); color: var(--accent); margin-right: .35rem; }
.chip.ok { background: var(--ok-soft); color: var(--ok); } .chip.warn { background: var(--warn-soft); color: var(--warn); }
.chip svg.i, .tag svg.i { width: 16px; height: 16px; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; }
.grid { display: grid; gap: 16px; grid-template-columns: minmax(0,1fr); }
@media (min-width: 768px) { .g2 { grid-template-columns: minmax(0,1fr) minmax(0,1fr); } .g3 { grid-template-columns: repeat(3,minmax(0,1fr)); } .g-side { grid-template-columns: minmax(0,1.4fr) minmax(0,1fr); align-items: start; } }
.hero { position: relative; min-width: 0; }
.mapa-base { position: relative; overflow: hidden; border: 1px solid var(--line); border-radius: 24px; background: var(--surface); box-shadow: var(--shadow); }
.hero-panel { position: relative; z-index: 2; display: flex; flex-direction: column; gap: 14px; margin: -68px 10px 0; padding: 22px; border: 1px solid var(--line); border-radius: 24px; background: var(--panel); box-shadow: var(--shadow); backdrop-filter: blur(14px) saturate(1.15); -webkit-backdrop-filter: blur(14px) saturate(1.15); }
.hero-panel h1 { font-size: clamp(2.25rem, 6vw, 4.5rem); line-height: .98; letter-spacing: -.03em; margin: 0; }
.hero-sub { color: var(--muted); font-size: 19px; line-height: 1.4; }
.hero-panel .aviso { font-size: 15px; }
.mapa-pie { position: absolute; right: 10px; bottom: 62px; z-index: 1; display: flex; flex-direction: column; align-items: flex-end; gap: 2px; max-width: min(430px, calc(100% - 20px)); padding: 8px 10px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); color: var(--ink); font-size: 12px; line-height: 1.25; text-align: right; pointer-events: none; }
.mapa-pie b { font-size: 16px; }
.mapa-fuente { color: var(--muted); }
@media (max-width: 899px) {
  .mapa-pie { bottom: 76px; }
  .hero-panel { padding: 18px; gap: 12px; }
  .hero-panel .chip { display: none; }
  .hero-sub { font-size: 17px; line-height: 1.35; }
}
@media (min-width: 900px) {
  .hero { min-height: 70vh; }
  .hero .mx { min-height: 70vh; }
  .hero-panel { position: absolute; left: 24px; top: 50%; transform: translateY(-50%); width: min(500px, 44%); margin: 0; padding: 26px; }
  .mapa-pie { bottom: 10px; }
}
.search { display: flex; align-items: center; gap: 10px; background: var(--surface); border: 2px solid var(--accent); border-radius: 16px; padding: 6px 6px 6px 16px; box-shadow: var(--shadow); }
.search input { flex: 1; border: 0; background: transparent; font: 18px system-ui; color: var(--ink); min-height: 48px; outline: none; min-width: 0; width: auto; }
.sugg { margin-top: 8px; padding: 6px; }
.sugg a { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 12px; text-decoration: none; }
.sugg a:hover { background: var(--surface-2); }
.sugg small { margin-left: auto; }
.mx { width: 100%; height: auto; }
.mx .st { fill: var(--mapa); stroke: var(--bg); stroke-width: 1; }
.mx .st.on { fill: var(--accent); }
.mx a .st { transition: fill .18s ease, stroke .18s ease; }
.mx a:hover .st, .mx a:focus-visible .st { fill: var(--accent); stroke: var(--bg); }
.mx a:focus-visible { outline: 3px solid var(--ink); outline-offset: 2px; }
.mx .punto { fill: var(--accent); stroke: var(--surface); stroke-width: 2; }
.mx .pulso { fill: none; stroke: var(--accent); stroke-width: 2; pointer-events: none; animation: pulso 2.2s ease-out infinite; }
@keyframes pulso { from { r: 10px; opacity: .75; } to { r: 26px; opacity: 0; } }
.mx .mapa-etiqueta { font-size: 13px; font-weight: 700; fill: var(--ink); paint-order: stroke; stroke: var(--bg); stroke-width: 3px; }
@media (prefers-reduced-motion: reduce) { .mx a .st { transition: none; } .mx .pulso { animation: none; opacity: 0; } }
.meter { height: 10px; border-radius: 5px; background: var(--surface-2); overflow: hidden; } .meter i { display: block; height: 100%; background: var(--accent); min-width: 6px; }
.step { display: flex; gap: 14px; } .n, .num { width: 44px; height: 44px; border-radius: 50%; background: var(--accent-soft); color: var(--accent); display: grid; place-items: center; font-weight: 800; flex: none; }
.steps { display: flex; flex-direction: column; gap: 12px; }
.live { display: inline-flex; align-items: center; gap: 8px; font-weight: 700; color: var(--ok); }
.live i { width: 10px; height: 10px; border-radius: 50%; background: var(--ok); animation: p 1.4s infinite; }
@keyframes p { 50% { opacity: .25; } }
.feed { display: flex; flex-direction: column; }
.ev { display: grid; grid-template-columns: 40px minmax(0,1fr); gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--line); animation: entrar .45s ease; }
.ev:last-child { border: 0; }
@keyframes entrar { from { opacity: 0; transform: translateY(-6px); } }
@media (prefers-reduced-motion: reduce) { .live i, .ev { animation: none; } }
.dot { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; background: var(--surface-2); color: var(--muted); }
.dot svg.i { width: 22px; height: 22px; }
.dot.ok { background: var(--ok-soft); color: var(--ok); } .dot.warn { background: var(--warn-soft); color: var(--warn); } .dot.now { background: var(--accent); color: var(--accent-ink); }
.ev time { font-size: 13px; color: var(--muted); }
.kpis { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 10px; }
.kpi { background: var(--surface-2); border-radius: 14px; padding: 12px; text-align: center; } .kpi b { display: block; font-size: 26px; }
.doc { display: flex; gap: 12px; align-items: center; padding: 12px; border-radius: 14px; background: var(--surface-2); }
.thumb { width: 44px; height: 56px; border-radius: 6px; background: var(--surface); border: 1px solid var(--line); display: grid; place-items: center; color: var(--muted); flex: none; }
.ring { position: relative; width: 100%; max-width: 420px; aspect-ratio: 1; margin: 0 auto; }
.ring .c { position: absolute; border-radius: 50%; border: 2px dashed var(--line); inset: 0; } .ring .c2 { inset: 17%; } .ring .c3 { inset: 34%; border-style: solid; background: var(--accent-soft); border-color: transparent; }
.ring .p { position: absolute; transform: translate(-50%,-50%); text-align: center; font-size: 13px; font-weight: 600; width: 96px; line-height: 1.2; }
.nodo, .nodo-tu { text-decoration: none; color: inherit; background: none; border: 0; font: inherit; cursor: pointer; min-width: 44px; min-height: 44px; padding: 2px; }
.nodo .tip, .nodo-tu .tip { position: absolute; left: 50%; bottom: 100%; transform: translateX(-50%); background: var(--ink); color: var(--bg); padding: 8px 10px; border-radius: 10px; font-size: 13px; line-height: 1.25; width: max-content; max-width: 190px; opacity: 0; pointer-events: none; transition: opacity .15s ease; z-index: 6; }
.nodo:hover .tip, .nodo:focus-visible .tip, .nodo.show .tip, .nodo-tu:hover .tip, .nodo-tu:focus-visible .tip, .nodo-tu.show .tip { opacity: 1; }
.tip .vf { display: none; margin-top: 6px; background: var(--accent); color: var(--accent-ink); border-radius: 8px; padding: 8px 10px; font-weight: 700; }
@media (hover: none) { .tip .vf { display: block; } }
.ring.filtrando .nodo:not(.on) { opacity: .35; }
.nodo.hl .av { box-shadow: 0 0 0 3px var(--accent); }
.card.hl, .regcard.hl { outline: 3px solid var(--accent); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { .nodo .tip, .nodo-tu .tip { transition: none; } }
.av, .avatar { width: 52px; height: 52px; border-radius: 50%; display: grid; place-items: center; font-weight: 800; color: #fff; margin: 0 auto 4px; flex: none; background: var(--accent); font-size: 17px; }
.av.l { width: 84px; height: 84px; font-size: 28px; }
.av.you, .v4 { background: var(--ink); color: var(--bg); } .v1, .av { background: #5b3fd1; } .v2, .av.a2 { background: #0e7490; } .v3, .av.a3 { background: #475569; }
.empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 14px; padding: 32px 20px; border: 2px dashed var(--line); border-radius: var(--r); background: var(--surface); }
.empty .ico { width: 72px; height: 72px; border-radius: 50%; background: var(--accent-soft); color: var(--accent); display: grid; place-items: center; }
.empty .ico svg.i { width: 36px; height: 36px; }
.empty .acts { display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; }
[id] { scroll-margin-top: 84px; }
.tier { display: flex; flex-direction: column; gap: 10px; }
.tier h3 { display: flex; align-items: center; gap: 8px; font-size: 15px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.tier h3 svg.i { width: 18px; height: 18px; }
.person, .persona { display: flex; gap: 14px; align-items: center; }
.reg, .reggrid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; }
@media (min-width: 1000px) { .reg, .reggrid { grid-template-columns: repeat(3,minmax(0,1fr)); } }
.reg.filtrando .regcard:not(.on), .reggrid.filtrando .regcard:not(.on) { opacity: .45; }
.rg, .regcard { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 16px; display: flex; flex-direction: column; gap: 10px; min-width: 0; font-size: 14px; line-height: 1.25; }
.rg.on, .regcard.on { border: 2px solid var(--accent); background: var(--accent-soft); }
.regcard .av { width: 44px; height: 44px; font-size: 15px; margin: 0; }
.regcard b.nombre { font-size: 16px; line-height: 1.25; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.regcard .t { display: flex; align-items: center; gap: 6px; font-size: 14px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.regcard .t svg.i { width: 16px; height: 16px; color: var(--accent); }
.filters { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; scrollbar-width: none; }
.filters button { flex: none; display: flex; align-items: center; gap: 6px; min-height: 44px; padding: 0 14px; border-radius: 99px; border: 1px solid var(--line); background: var(--surface); color: var(--ink); font: 600 15px system-ui; cursor: pointer; }
.filters button.on { background: var(--ink); color: var(--bg); border-color: var(--ink); }
.filters svg.i { width: 18px; height: 18px; }
.sticky { position: sticky; top: 84px; }
.tl { border-left: 3px solid var(--line); margin-left: 8px; padding-left: 20px; display: flex; flex-direction: column; gap: 16px; }
.tl div { position: relative; } .tl div:before { content: ""; position: absolute; left: -29px; top: 5px; width: 15px; height: 15px; border-radius: 50%; background: var(--accent); border: 3px solid var(--surface); }
.src { display: flex; align-items: center; gap: 6px; font-size: 14px; color: var(--muted); }
.src svg.i { width: 16px; height: 16px; color: var(--ok); }
.zero { display: flex; gap: 14px; align-items: flex-start; background: var(--warn-soft); border-radius: 14px; padding: 14px; color: var(--ink); }
.zero b { font-size: 34px; line-height: 1; color: var(--warn); }
.list a { display: flex; align-items: center; gap: 12px; min-height: 56px; padding: 4px; border-bottom: 1px solid var(--line); color: var(--ink); text-decoration: none; }
.list a:last-child { border: 0; }
.grid2, .temas { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 12px; }
@media (min-width: 768px) { .grid2, .temas { grid-template-columns: repeat(3,minmax(0,1fr)); } }
.tile, .tema { background: var(--surface); border: 2px solid var(--line); border-radius: var(--r); min-height: 120px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; font-weight: 700; text-align: center; padding: 12px; color: var(--ink); text-decoration: none; }
.tile.on, .tema.on { border-color: var(--accent); background: var(--accent-soft); }
.tile svg.i { width: 44px; height: 44px; }
.stat { display: flex; gap: 12px; } .stat .card { flex: 1; text-align: center; padding: 14px 8px; } .stat b { display: block; font-size: 30px; color: var(--accent); }
.coins { display: grid; grid-template-columns: repeat(10, minmax(0,1fr)); gap: 5px; } .coins i { aspect-ratio: 1; border-radius: 50%; display: block; }
.leg { display: flex; flex-direction: column; gap: 10px; } .leg div { display: flex; align-items: center; gap: 12px; }
.leg .sw { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; color: #fff; flex: none; } .leg .sw svg.i { color: #fff; width: 22px; height: 22px; } .leg b { margin-left: auto; font-size: 20px; }
.big { font-size: 44px; font-weight: 800; line-height: 1; color: var(--accent); }
.cols { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
@media (min-width: 768px) { .cols { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); align-items: start; } }
.stack { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.aviso { background: var(--aviso-bg); border: 1px solid var(--aviso-line); color: var(--aviso-ink); border-radius: 16px; padding: .75rem; }
.fuente, details.fuente { font-size: 14px; color: var(--muted); background: transparent; border: 0; padding: 0; margin-top: .5rem; overflow-wrap: anywhere; }
details.fuente summary, details.why summary { color: var(--accent); font-weight: 600; min-height: 44px; cursor: pointer; display: flex; align-items: center; }
details.ayuda { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: .6rem .8rem; margin: .5rem 0; font-size: 16px; }
details.ayuda summary { min-height: 44px; cursor: pointer; font-weight: 600; display: flex; align-items: center; color: var(--accent); }
.sencillo { border-left: 4px solid var(--accent); }
img.foto { max-width: 100%; height: auto; border-radius: var(--r); }
label { display: block; margin: .75rem 0 .25rem; font-weight: 600; }
input[type=text], input[type=file], input[type=search], input[type=password], select, textarea { width: 100%; min-height: 48px; font-size: 1rem; }
textarea { min-height: 88px; }
table { border-collapse: collapse; width: 100%; } th, td { text-align: left; padding: .5rem; border-bottom: 1px solid var(--line); vertical-align: top; }
.grid>*, .hero>*, .kpis>*, .ev>*, .reg>*, .reggrid>*, .regcard>*, .grid2>*, .temas>*, .cols>*, .seg>* { min-width: 0; }
.card, .tarjeta, .doc>div, .person>div, .leg>div, .step>div { min-width: 0; }
.ev div, .src, .doc, .tarjeta, .copy, code, td { overflow-wrap: anywhere; }
@media (max-width: 767px) { table.cards, table.cards tr, table.cards td { display: block; } table.cards tr:first-child { display: none; } table.cards tr { border: 1px solid var(--line); border-radius: 14px; padding: 12px; margin-bottom: 12px; background: var(--surface); } table.cards td { border: 0; padding: .25rem 0; } }
.copy { background: var(--copy-bg); border: 2px dashed var(--dash); border-radius: 16px; padding: 14px; font-size: 16px; }
.prog { display: flex; gap: 6px; max-width: 300px; } .prog i { flex: 1; height: 6px; border-radius: 3px; background: var(--line); } .prog i.on { background: var(--accent); }
.back, .listen { width: 44px; height: 44px; border-radius: 50%; background: var(--surface); border: 1px solid var(--line); display: inline-grid; place-items: center; color: var(--accent); cursor: pointer; flex: none; }
a:focus-visible, button:focus-visible, input:focus-visible, summary:focus-visible, select:focus-visible { outline: 3px solid var(--ink); outline-offset: 2px; }
.tema-btns { display: flex; gap: 6px; } .tema-btns button { flex: 1; min-height: 44px; border-radius: 10px; border: 2px solid var(--line); background: var(--surface); color: var(--ink); font-weight: 600; cursor: pointer; }
u.term { text-decoration: underline dotted var(--accent) 2px; text-underline-offset: 4px; }
.place { min-width: 0; flex: 0 1 auto; } .place-t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.ev { color: var(--ink); } .ev b { color: var(--ink); } .ev time { color: var(--muted-2); font-weight: 600; }
.ev a { color: var(--accent); font-weight: 700; overflow-wrap: anywhere; }
.resumen-ind { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; }
.resumen-ind .kpi { text-align: left; } .resumen-ind .kpi b { font-size: 22px; }
details.anteriores, details.cap { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r); padding: 14px 16px; }
details.anteriores summary, details.cap summary { min-height: 44px; cursor: pointer; font-weight: 700; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
details.cap .partida { padding: 10px 0; border-top: 1px solid var(--line); }
.compacta { padding: 12px 14px; } .compacta .av, .compacta .avatar { width: 38px; height: 38px; font-size: 14px; margin: 0; }
@media (min-width: 768px) { .resumen-ind { grid-template-columns: minmax(0,1fr) minmax(0,1fr) minmax(0,1fr) minmax(0,1fr); } }
@media (max-width: 767px) {
  header.top .wrap { gap: 8px; } .logo { flex: none; } .place { max-width: 44vw; padding: 8px 10px; }
  .reg, .reggrid { grid-template-columns: minmax(0,1fr); gap: 8px; }
  .regcard { flex-direction: row; align-items: center; padding: 8px 10px; gap: 10px; }
  .regcard .av { width: 36px; height: 36px; font-size: 13px; }
  .regcard b.nombre { flex: 1 1 auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; -webkit-line-clamp: 1; }
  .regcard .t { flex: none; max-width: 38%; }
  .regcard .small, .regcard .btn, .regcard details.fuente { display: none; }
  .ring { max-width: 250px; } .card.person, .card .person { padding: 14px; }
  .kpis { gap: 8px; } .kpi b { font-size: 22px; }
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
function filtrarTemaBtn(btn, tema){ document.querySelectorAll('.filters button').forEach(function(b){ b.classList.toggle('on', b === btn); }); var g = document.querySelector('.reggrid'); if(g){ g.classList.toggle('filtrando', !!tema); g.querySelectorAll('[data-tema]').forEach(function(el){ el.classList.toggle('on', !!tema && el.getAttribute('data-tema') === tema); }); } var r = document.querySelector('.ring'); if(r){ r.classList.toggle('filtrando', !!tema); r.querySelectorAll('.nodo').forEach(function(el){ var ts = el.getAttribute('data-temas') || el.getAttribute('data-tema') || ''; el.classList.toggle('on', !!tema && ts.split('|').indexOf(tema) !== -1); }); } }
function expandirRegidores(){ document.querySelectorAll('.regcard.mas').forEach(function(el){ el.hidden = false; }); }
function verMasRegidores(btn){ expandirRegidores(); btn.remove(); }
function buscando(f){ var b = f.querySelector('button[type=submit]'); if(b){ b.disabled = true; b.textContent = 'Buscando…'; } var s = document.getElementById('lista-resultados'); if(s) s.setAttribute('aria-busy', 'true'); return true; }
async function compartir(url, texto){ try{ var r = await fetch(url); var b = await r.blob(); var f = new File([b], 'tarjeta.png', {type: 'image/png'}); if(navigator.canShare && navigator.canShare({files: [f]})){ await navigator.share({files: [f], text: texto}); return; } }catch(err){} var a = document.createElement('a'); a.href = url; a.download = 'tarjeta.png'; a.click(); }
</script>"""

# Script de tema del mockup nacional, tal cual: claro / sistema / oscuro, guardado por persona.
TEMA_JS = """<script>
// Tema: claro / sistema / oscuro, guardado por persona en este navegador.
const btns=[...document.querySelectorAll('.seg button')];
function setTheme(t){
  if(t==='system')document.documentElement.removeAttribute('data-theme');else document.documentElement.dataset.theme=t;
  btns.forEach(b=>b.setAttribute('aria-pressed',b.dataset.t===t));
  try{localStorage.setItem('tema',t)}catch(e){}
}
btns.forEach(b=>b.onclick=()=>setTheme(b.dataset.t));
try{setTheme(localStorage.getItem('tema')||'system')}catch(e){setTheme('system')}
</script>"""


ABREV_ESTADO = {"Aguascalientes": "Ags.", "Baja California": "B.C.", "Baja California Sur": "B.C.S.",
                "Campeche": "Camp.", "Chiapas": "Chis.", "Chihuahua": "Chih.", "Ciudad de México": "CDMX",
                "Coahuila": "Coah.", "Colima": "Col.", "Durango": "Dgo.", "Guanajuato": "Gto.",
                "Guerrero": "Gro.", "Hidalgo": "Hgo.", "Jalisco": "Jal.", "México": "Méx.",
                "Michoacán": "Mich.", "Morelos": "Mor.", "Nayarit": "Nay.", "Nuevo León": "N.L.",
                "Oaxaca": "Oax.", "Puebla": "Pue.", "Querétaro": "Qro.", "Quintana Roo": "Q. Roo",
                "San Luis Potosí": "S.L.P.", "Sinaloa": "Sin.", "Sonora": "Son.", "Tabasco": "Tab.",
                "Tamaulipas": "Tamps.", "Tlaxcala": "Tlax.", "Veracruz": "Ver.", "Yucatán": "Yuc.",
                "Zacatecas": "Zac."}


def _lugar_chip(lugar: str | None) -> str:
    if not lugar or "," not in lugar:
        return lugar or "¿Dónde vives?"
    nombre, estado = lugar.rsplit(",", 1)
    estado = estado.strip()
    return f"{nombre.strip()}, {ABREV_ESTADO.get(estado, estado)}"


def pagina(titulo: str, cuerpo: str, paso: int | None = None, seccion: str | None = None,
           sin_titulo: bool = False, lugar: str | None = None) -> HTMLResponse:
    if lugar is None and _MUN_COOKIE.get():  # el chip muestra el municipio de la cookie en toda página
        try:
            with _con() as con:
                mun = _nombre_municipio(con, _MUN_COOKIE.get())
            lugar = f"{mun[0]}, {mun[1]}" if mun else None
        except Exception:
            lugar = None
    items = [("/", "home", "Inicio", "inicio"), ("/representantes", "ppl", "Tu gobierno", "gobierno"),
             ("/gastos", "coin", "Gastos", "gastos"), ("/actua", "mega", "Actúa", "actua")]
    topmenu = '<nav class="topmenu" aria-label="Principal">' + "".join(
        f'<a href="{h}" class="{"on" if k == seccion else ""}">{t}</a>'
        for h, ic, t, k in items) + "</nav>"
    chip = (f'<a class="place" href="/donde"><svg class="i" aria-hidden="true"><use href="#i-pin"/></svg>'
            f'<span class="place-t">{e(_lugar_chip(lugar))}</span></a>')
    a11y = ('<details class="a11y"><summary class="iconbtn" aria-label="Accesibilidad y tema">'
            '<svg class="i" aria-hidden="true"><use href="#i-a11y"/></svg></summary>'
            '<div class="menu" id="menu-a11y"><b>Ver y escuchar</b>'
            '<button class="btn" type="button" style="width:100%" onclick="escuchar()">'
            '<svg class="i" aria-hidden="true"><use href="#i-spk"/></svg>Escuchar esta página</button>'
            '<button class="btn ghost" type="button" style="width:100%" onclick="detener()">Detener lectura</button>'
            '<div><span class="small muted">Tema</span>'
            '<div class="seg" role="group" aria-label="Tema">'
            '<button data-t="light" aria-pressed="false"><svg class="i" aria-hidden="true"><use href="#i-sun"/></svg>Claro</button>'
            '<button data-t="system" aria-pressed="true"><svg class="i" aria-hidden="true"><use href="#i-sys"/></svg>Sistema</button>'
            '<button data-t="dark" aria-pressed="false"><svg class="i" aria-hidden="true"><use href="#i-moon"/></svg>Oscuro</button>'
            '</div></div></div></details>')
    nav = ""
    if seccion:
        nav = '<nav class="bottom" aria-label="Principal">' + "".join(
            f'<a href="{h}" class="{"on" if k == seccion else ""}"><svg class="i" aria-hidden="true"><use href="#i-{ic}"/></svg>{t}</a>'
            for h, ic, t, k in items) + "</nav>"
    volver = ""
    if paso:
        prog = "".join(f'<i class="{"on" if i < paso else ""}"></i>' for i in range(4))
        volver = (f'<div style="display:flex;align-items:center;gap:12px"><button class="back" type="button" onclick="history.back()" aria-label="Volver">'
                  f'<svg class="i" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg></button><div class="prog" style="flex:1">{prog}</div></div>')
    simbolos = "".join(f'<symbol id="i-{k}" viewBox="0 0 24 24">{v}</symbol>' for k, v in _ICONOS.items())
    return HTMLResponse(f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(titulo)} — POLACA</title>
<script>try{{ var t = localStorage.getItem('tema'); if(t && t !== 'system') document.documentElement.dataset.theme = t; }}catch(err){{}}</script>
<style>{CSS}</style></head><body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>{simbolos}</defs></svg>
<header class="top"><div class="wrap"><a class="logo" href="/"><b>P</b>POLACA</a>{topmenu}{chip}{a11y}</div></header>
<main class="wrap">{volver}{'' if sin_titulo else f'<h1>{e(titulo)}</h1>'}{cuerpo}</main>
<footer class="cola">POLACA · Datos de documentos públicos oficiales, mostrados con su fuente. La política no te ignora. ¿La ignoras tú?</footer>{nav}{JS}{TEMA_JS}</body></html>""")


def _con() -> sqlite3.Connection:
    with municipios.conectar():  # asegura municipios, localidades, solicitudes, eventos y municipio_id
        pass
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
    faltan_html = (f"<h3>Fuentes que faltan para poder cruzar</h3><ul>{faltan}</ul>" if faltan else
                   "<h3>Fuentes que faltan para poder cruzar</h3><p>Ya están las fuentes básicas para cruzar; "
                   "si aun así no hay pares comparables, es porque hablan de cosas distintas.</p>")
    return f"""<div class="tarjeta"><h2>Reporte de cobertura</h2>
<p>Partidas: {c['partidas']} ({c['partidas_con_monto']} con monto, suma ${_dinero(c['suma_partidas'])[1:]},
{c['partidas_nombre_no_verificado']} con nombre no verificado).</p>
<p>Acuerdos canónicos: {c['acuerdos_canonicos']} ({c['acuerdos_con_monto']} con monto,
{c['acuerdos_con_proveedor']} con proveedor).</p>
<p>Pares comparables entre ambas fuentes: {c['pares_comparables']}.</p>
{faltan_html}</div>"""


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
    "a11y": '<circle cx="12" cy="4.5" r="1.8"/><path d="M5 8l7 1.5L19 8M12 9.5V14l-3 6M12 14l3 6"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5"/>',
    "moon": '<path d="M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z"/>',
    "sys": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/>',
    "read": '<path d="M3 5h7a2 2 0 012 2v12a2 2 0 00-2-2H3zM21 5h-7a2 2 0 00-2 2v12a2 2 0 012-2h7z"/>',
    "chk": '<path d="M5 12l5 5L20 7"/>',
    "alert": '<path d="M12 3l9 16H3zM12 10v4M12 17v.5"/>',
    "spark": '<path d="M12 3l2 5.5L19.5 10 14 12l-2 5.5L10 12 4.5 10 10 8.5z"/>',
    "share": '<circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4"/>',
    "book": '<path d="M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2zM4 5v16"/>',
    "leaf": '<path d="M5 19c0-9 6-14 15-14 0 9-5 15-14 15M5 19l7-7"/>',
    "heart": '<path d="M12 20s-8-4.5-8-10.5A4.5 4.5 0 0112 7a4.5 4.5 0 018 2.5C20 15.5 12 20 12 20z"/>',
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


def _vacio(icono_: str, titulo: str, texto: str, acciones: list) -> str:
    """Tarjeta de estado vacío (sección F del mockup): icono, una explicación y 1 o 2 acciones."""
    botones = "".join(f'<a class="btn{" ghost" if fantasma else ""}" href="{e(href)}">{e(texto_)}</a>'
                      for href, texto_, fantasma in acciones)
    return (f'<div class="empty"><img class="ilu" src="/static/ilustraciones/vacio.svg" alt="" width="240" height="160">'
            f'<span class="ico">{icono(icono_, "Dibujo decorativo")}</span>'
            f'<h3>{e(titulo)}</h3><p class="small muted">{e(texto)}</p>'
            f'<div class="acts">{botones}</div></div>')


def _sin_resultados(q: str) -> str:
    return _vacio("srch", f"No encontramos “{q}”",
                  "Revisa cómo se escribe o busca tu municipio en lugar de tu colonia.",
                  [("/donde", "Buscar por municipio", False),
                   ("/", "Ver el mapa de municipios", True)])


def _gob(con, tabla: str, clave: str | None = None) -> list[dict]:
    """Filas con cita verificada de un municipio (null = dato anterior al esquema).

    clave=None devuelve las de TODOS los municipios: hace falta al buscar a una
    persona por id, porque su ficha no sabe de qué municipio viene el enlace."""
    try:
        if clave is None:
            return _filas(con, f"SELECT * FROM {tabla} WHERE verificacion = 'ok' ORDER BY id")
        return _filas(con, f"SELECT * FROM {tabla} WHERE verificacion = 'ok' AND (municipio_id = ? OR municipio_id IS NULL) ORDER BY id",
                      (clave,))
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

# Tema corto por comisión: explicación general en palabras sencillas, no es el nombre
# oficial (ese va en la ficha de la persona). Clave: denominación oficial sin acentos.
TEMAS_CORTOS = {
    "industria comercio agricultura y ganaderia": ("store", "Comercio y campo"),
    "grupos vulnerables y personas con discapacidad": ("hand", "Apoyo a la gente"),
    "educacion publica y actividades culturales deportivas y sociales": ("book", "Educación"),
    "turismo arte y pueblos originarios": ("pin", "Turismo y cultura"),
    "gobernacion justicia y seguridad publica": ("shield", "Seguridad"),
    "patrimonio y hacienda publica municipal": ("coin", "Dinero del municipio"),
    "bienestar juventud proteccion y atencion a la ninez": ("heart", "Bienestar y niñez"),
    "desarrollo urbano obras y servicios publicos": ("road", "Obras y calles"),
    "igualdad de genero prevencion atencion y erradicacion de la violencia contra las mujeres": ("ppl", "Igualdad"),
    "salud y asistencia publica": ("heart", "Salud"),
    "medio ambiente y ecologia": ("leaf", "Medio ambiente"),
    "proteccion civil y prevencion de riesgos": ("alert", "Protección civil"),
}


def tema_corto(comision: str) -> tuple[str, str]:
    """(icono, tema corto) para tarjetas y filtros; el nombre oficial no se acorta aquí."""
    clave = plano(comision or "").removeprefix("de ")
    if clave in TEMAS_CORTOS:
        return TEMAS_CORTOS[clave]
    for palabra, tema in [("proteccion civil", ("alert", "Protección civil")), ("desarrollo urbano", ("road", "Obras y calles")),
                          ("obras", ("road", "Obras y calles")), ("seguridad", ("shield", "Seguridad")),
                          ("gobernacion", ("shield", "Seguridad")), ("salud", ("heart", "Salud")),
                          ("educacion", ("book", "Educación")), ("cultura", ("book", "Cultura")),
                          ("hacienda", ("coin", "Dinero del municipio")), ("patrimonio", ("coin", "Dinero del municipio")),
                          ("bienestar", ("heart", "Bienestar y niñez")), ("ambiente", ("leaf", "Medio ambiente")),
                          ("ecologia", ("leaf", "Medio ambiente")), ("turismo", ("pin", "Turismo y cultura")),
                          ("comercio", ("store", "Comercio y campo")), ("agricultura", ("store", "Comercio y campo")),
                          ("igualdad", ("ppl", "Igualdad")), ("vulnerables", ("hand", "Apoyo a la gente")),
                          ("discapacidad", ("hand", "Apoyo a la gente")), ("agua", ("drop", "Agua"))]:
        if palabra in clave:
            return tema
    return "otros", "Otro tema"


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
    d.text((70, 90), "POLACA", font=titulo, fill="#ffffff")
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
        filas = [f for f in _gob(con, "funcionarios", None) if f["id"] == id_]
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
def gastos(request: Request, m: str = ""):
    """Pantalla 6 del recorrido: el gasto del año en 100 monedas (mayor residuo, suma exacta 100)."""
    clave = _elegida(request, m)
    if not clave:
        return RedirectResponse("/donde", status_code=303)
    with _con() as con:
        partidas = [p for p in cruzar._partidas(con)
                    if p["monto_mxn"] and p.get("municipio_id") in (clave, None)]
        urls = _urls(con)
        mun = _nombre_municipio(con, clave)
    nombre = mun[0] if mun else "tu municipio"
    monedas = monedas_100(partidas)
    if not monedas:
        return _fijar(pagina("En qué se gasta", _vacio(
            "coin", "Todavía no tenemos el gasto con montos",
            "Sí sabemos que el gasto sale del Presupuesto de Egresos, pero en las fuentes revisadas "
            "todavía no hay partidas con monto para repartir en 100 monedas.",
            [("/actua", "Pide el presupuesto por transparencia", False),
             ("/evidencia", "Ayúdanos a revisar más", True)]), seccion="gastos",
            lugar=f"{mun[0]}, {mun[1]}" if mun else None), clave)
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
    cuerpo = (f'<div><p class="sub">En 2026 {e(nombre)} planea gastar</p>'
              f'<p class="big">{e(en_palabras(total).removesuffix(" de pesos"))}</p>'
              f'<p class="sub">de pesos. Imagina que fueran 100 monedas:</p></div>'
              f'<div class="card"><p class="small">{e(aria)}</p><div class="coins" role="img" aria-label="{e(aria)}">{circulos}</div>'
              f'<div class="leg" style="margin-top:14px">{leyenda}</div></div>'
              f'<p class="sub" style="font-size:16px">Los nombres en palabras sencillas de arriba son una explicación '
              f'general. El nombre oficial de cada grupo de gasto, su monto exacto y su fuente están aquí:</p>'
              f'<details class="cap"><summary>Nombres oficiales y montos</summary>{oficiales}</details>')
    return _fijar(pagina("En qué se gasta", cuerpo, seccion="gastos",
                         lugar=f"{mun[0]}, {mun[1]}" if mun else None), clave)


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


def _tarjeta_persona(titulo, nombre, hace, fila_fuente, contacto, urls, enlace, distancia, color="", data_id=""):
    contacto_html = ""
    if contacto:
        datos = " · ".join(x for x in [contacto.get("telefono"), contacto.get("direccion"), contacto.get("horario")] if x)
        contacto_html = (f'<p style="font-size:16px"><strong>Cómo encontrarle:</strong> {e(contacto["oficina"])}'
                         f'{(" — " + e(datos)) if datos else ""}</p>{_fuente_de(contacto, urls)}')
    hace_html = (f'<p style="font-size:16px"><strong>Qué hace:</strong> {e(hace)}</p>' if hace else
                 '<p style="font-size:16px"><strong>Qué hace:</strong> todavía no tenemos la descripción de este '
                 'cargo en las fuentes revisadas de este municipio. Sí sabemos su cargo oficial, el de arriba; '
                 'la descripción puedes pedirla por transparencia.</p>')
    return (f'<div class="card person"{" data-tarjeta=\"" + e(data_id) + "\"" if data_id else ""}><div class="av {color}" style="margin:0" aria-hidden="true">{e(_iniciales(nombre))}</div><div>'
            f'<span class="tag">{e(distancia)}</span><h3>{e(nombre)}</h3>'
            f'<p class="sub" style="font-size:16px">{e(titulo)}</p>'
            f'{hace_html}{_fuente_de(fila_fuente, urls)}{contacto_html}'
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


def _rol_corto(fila) -> str:
    """Rol breve para el nombre accesible del nodo: 'regidora o regidor de obras y calles'."""
    cargo, comision = fila.get("cargo") or "", fila.get("comision") or ""
    p = plano(cargo)
    if "presidenta" in p:
        return "presidenta municipal"
    if "presidente" in p:
        return "presidente municipal"
    if "sindic" in p:
        return "síndico municipal"
    if comision:
        return f"regidora o regidor de {tema_corto(comision)[1].lower()}"
    return (cargo or "funcionaria o funcionario").lower()


@app.get("/representantes", response_class=HTMLResponse)
def representantes(request: Request, junta: int = 0, m: str = ""):
    clave_elegida = _elegida(request, m)
    if not clave_elegida:
        return RedirectResponse("/donde", status_code=303)
    m = clave_elegida
    with _con() as con:
        funcionarios = _gob(con, "funcionarios", m)
        juntas = _gob(con, "juntas_auxiliares", m)
        funciones = _gob(con, "funciones_cargo", m)
        contactos = _gob(con, "contacto_institucional", m)
        urls = _urls(con)
        mun_fila = _filas(con, "SELECT * FROM municipios WHERE clave_inegi = ?", (m,))
    if mun_fila and mun_fila[0]["estado_indexacion"] != "indexado":
        # Sección F: sin revisar, toda la vista es la tarjeta de invitación, sin niveles vacíos.
        mun = mun_fila[0]
        estado = mun["estado_indexacion"]
        if estado == "indexando":
            accion = (f"/indexando/{m}", "Ver la revisión en vivo", False)
        elif estado == "error":
            accion = (f"/indexando/{m}", "Ver lo que pasó", False)
        else:
            accion = (f"/municipio/{m}", "Pídele a Muse que lo revise", False)
        cuerpo = _vacio("spark", f"Aún no revisamos {mun['nombre']}",
                        "Por eso todavía no sabemos quiénes integran su Cabildo. Muse puede buscar los "
                        "documentos oficiales y leerlos por ti; cada dato llevará su fuente.",
                        [accion, ("/donde", "Elige otro municipio", True)])
        return _fijar(pagina("Estas personas trabajan para ti", cuerpo, paso=2,
                             lugar=f'{mun["nombre"]}, {mun["estado"]}'), m)
    elegida = next((j for j in juntas if j["id"] == junta), None)
    nivel_comunidad, nivel_presidencia = [], []
    if elegida:
        f_aux = _buscar_fila(funciones, "presidente auxiliar")
        nivel_comunidad.append(_tarjeta_persona(
            f"Presidente auxiliar de {elegida['nombre']}: la autoridad de tu junta auxiliar",
            elegida["presidente"] or elegida["nombre"],
            f_aux["funcion"] if f_aux else "Atiende los asuntos de su junta auxiliar.",
            elegida, _buscar_fila(contactos, "atención ciudadana"), urls,
            f"/actua?para={elegida['nombre']}", "Lo más cercano a ti", data_id=f"j{elegida['id']}"))
    f_insp = _buscar_fila(funciones, "inspector")
    # Junta auxiliar e inspectoría son figuras de Puebla: solo salen si este
    # municipio las tiene en sus fuentes (juntas guardadas o función con cita).
    hay_local = bool(juntas) or f_insp is not None
    hace_insp = (f'<p><strong>Qué hace:</strong> {e(f_insp["funcion"])}</p>' if f_insp else
                 '<p><strong>Qué hace:</strong> es la autoridad de tu colonia ante el Ayuntamiento.</p>')
    inspector_html = ""
    if hay_local:
        inspector_html = f"""<div class="card persona compacta"><div class="avatar" aria-hidden="true">IN</div><div>
<strong>El inspector o inspectora de tu colonia</strong> <span class="marca">Lo más cercano a ti</span><br>
{hace_insp}
<p class="debil">Su nombre no está en las fuentes oficiales revisadas.</p>
<p><a class="btn ghost" href="/actua">Pídelo por transparencia</a></p>
{_fuente_de(f_insp, urls) if f_insp else ''}</div></div>"""
    # Regidor también sin comisión: hay ayuntamientos que solo publican «Regidor»
    # a secas (Cuernavaca); exigir comisión los hacía invisibles en esta vista.
    regidores = [f for f in funcionarios if f["comision"] or "regidor" in plano(f["cargo"])]
    f_reg = _buscar_fila(funciones, "regidores")
    sindico = _buscar_fila(funcionarios, "sindic")
    if sindico:
        f_sin = _buscar_fila(funciones, "síndico", "sindico")
        nivel_presidencia.append(_tarjeta_persona(
            "Síndico municipal: representa legalmente al municipio", sindico["nombre"],
            f_sin["funcion"] if f_sin else "", sindico,
            _buscar_fila(contactos, "atención ciudadana"), urls,
            f"/revisar/{sindico['id']}", "Representa a todo el municipio", "a3", data_id=str(sindico["id"])))
    presidenta = _buscar_fila(funcionarios, "presidenta municipal", "presidente municipal")
    if presidenta:
        f_pre = _buscar_fila(funciones, "presidente municipal")
        nivel_presidencia.append(_tarjeta_persona(
            f"{presidenta['cargo']}: encabeza el gobierno del municipio", presidenta["nombre"],
            f_pre["funcion"] if f_pre else "", presidenta,
            _buscar_fila(contactos, "presidencia municipal"), urls, f"/revisar/{presidenta['id']}",
            "Representa a todo el municipio", "a3", data_id=str(presidenta["id"])))
    # Diagrama interactivo de círculos concéntricos: tú al centro y cada autoridad más lejos.
    # Cada persona es un enlace a su ficha; el presidente auxiliar, sin ficha propia,
    # lleva a su página para preguntarle. Solo entran personas en la base con cita (_gob).
    lugar = elegida["nombre"] if elegida else "Tu comunidad"
    reg_obras = _buscar_fila(funcionarios, "desarrollo urbano") or (regidores[0] if regidores else None)
    n_reg = f"+{len(regidores) - 1}" if len(regidores) > 1 else ""

    def nodo(x, y, color, nombre, rol, tema, href, clave, tema_dato=""):
        return (f'<a class="p nodo" style="left:{x};top:{y}" href="{e(href)}" data-nodo="{e(clave)}" '
                f'data-tema="{e(tema_dato)}" aria-label="{e(nombre)}, {e(rol)}, ver su ficha">'
                f'<span class="av {color}" aria-hidden="true">{e(_iniciales(nombre))}</span>{e(tema)}'
                f'<span class="tip" aria-hidden="true"><b>{e(nombre)}</b> · {e(tema)}'
                f'<span class="vf">Ver ficha</span></span></a>')

    nodos = [f'<button type="button" class="p nodo-tu" id="tu-nodo" style="left:50%;top:50%" '
             f'aria-label="Tú, en {e(lugar)}. Más cerca del centro = más cerca de ti">'
             f'<span class="av you" aria-hidden="true">Tú</span>{e(lugar)}'
             f'<span class="tip" aria-hidden="true">Más cerca del centro = más cerca de ti</span></button>']
    if elegida and elegida["presidente"]:
        nodos.append(nodo("50%", "22%", "", elegida["presidente"],
                          f"presidente auxiliar de {elegida['nombre']}", "Presidente auxiliar",
                          f"/actua?para={elegida['nombre']}", f"j{elegida['id']}"))
    if reg_obras:
        nodos.append(nodo("16%", "40%", "a2", reg_obras["nombre"], _rol_corto(reg_obras),
                          tema_corto(reg_obras["comision"])[1], f"/revisar/{reg_obras['id']}",
                          str(reg_obras["id"]), tema_corto(reg_obras["comision"])[1]))
    if n_reg:
        temas_grupo = "|".join(dict.fromkeys(tema_corto(f["comision"])[1] for f in regidores))
        nodos.append(f'<button type="button" class="p nodo grupo" id="grupo-reg" style="left:84%;top:40%" '
                     f'aria-expanded="false" aria-controls="reggrid" data-temas="{e(temas_grupo)}" '
                     f'aria-label="Ver las {len(regidores)} regidurías">'
                     f'<span class="av a2" aria-hidden="true">{e(n_reg)}</span>Regidores'
                     f'<span class="tip" aria-hidden="true">{len(regidores)} regidurías: ver la lista completa'
                     f'<span class="vf">Ver regidurías</span></span></button>')
    if sindico:
        nodos.append(nodo("24%", "86%", "a3", sindico["nombre"], _rol_corto(sindico), "Síndico",
                          f"/revisar/{sindico['id']}", str(sindico["id"])))
    if presidenta:
        etiqueta_pre = "Presidenta" if "presidenta" in plano(presidenta["cargo"]) else "Presidente"
        nodos.append(nodo("76%", "86%", "a3", presidenta["nombre"], _rol_corto(presidenta), etiqueta_pre,
                          f"/revisar/{presidenta['id']}", str(presidenta["id"])))
    visual = (f'<div class="ring"><div class="c"></div><div class="c c2"></div><div class="c c3"></div>'
              f'{"".join(nodos)}</div>'
              '<p class="sub" style="font-size:16px">Primero ves a quien tienes más cerca de tu casa y al final a quien '
              'gobierna para todo el municipio. Todas deciden juntas en el Cabildo.</p>')
    cortos_unicos = []
    for f in regidores:
        corto = tema_corto(f["comision"])
        if corto not in cortos_unicos:
            cortos_unicos.append(corto)
    botones = ('<button class="on" type="button" onclick="filtrarTemaBtn(this, \'\')">Todos</button>' + "".join(
        f'<button type="button" onclick="filtrarTemaBtn(this, \'{e(corto)}\')">{icono(ic, "Icono del tema " + corto)}{e(corto)}</button>'
        for ic, corto in cortos_unicos))
    tarjetas_reg = []
    for i, f in enumerate(regidores):
        ic_corto, corto = tema_corto(f["comision"])
        etiqueta = corto if f["comision"] else f["cargo"]  # sin comisión publicada: su cargo, no un tema inventado
        tarjetas_reg.append(
            f'<div class="regcard{" mas" if i >= 5 else ""}" data-tema="{e(corto)}" data-tarjeta="{f["id"]}"{" hidden" if i >= 5 else ""}>'
            f'<span class="av a2" aria-hidden="true">{e(_iniciales(f["nombre"]))}</span>'
            f'<b class="nombre"><a href="/revisar/{f["id"]}">{e(f["nombre"])}</a></b>'
            f'<span class="t">{icono(ic_corto, "Icono del tema " + corto)}{e(etiqueta)}</span>'
            f'<span class="small muted">{"Tema corto: explicación general. El nombre oficial está en su ficha." if f["comision"] else "Su comisión no viene en la fuente revisada."}</span>'
            f'{_fuente_de(f, urls)}'
            f'<a class="btn ghost" href="/revisar/{f["id"]}">Ver su trabajo</a></div>')
    reggrid = "".join(tarjetas_reg)
    ver_mas = ('<p><button class="btn ghost" type="button" onclick="verMasRegidores(this)">Ver todos</button></p>'
               if len(regidores) > 5 else "")
    if regidores:
        cabildo_html = (f'<div class="filters" role="group" aria-label="¿De qué se encarga?">{botones}</div>'
                        f'<div class="tier"><h3>{icono("ppl", "Dibujo de personas")}Cabildo · {len(regidores)} regidurías</h3>'
                        f'<div class="reggrid" id="reggrid" tabindex="-1">{reggrid}</div>{ver_mas}</div>')
    else:
        cabildo_html = (f'<div class="tier"><h3>{icono("ppl", "Dibujo de personas")}Cabildo</h3>'
                        + _vacio("ppl", "Todavía no encontramos las regidurías de este municipio",
                                 "Sí sabemos que la presidencia, la sindicatura y las regidurías deciden juntas "
                                 "en el Cabildo; sus nombres no están en las fuentes revisadas hasta hoy.",
                                 [("/actua", "Pide información", False), ("/acuerdos", "Ver los acuerdos", True)]) + '</div>')
    presidencia_html = "".join(nivel_presidencia) or _vacio(
        "home", "Todavía no encontramos quién encabeza la presidencia",
        "Sí sabemos que la presidencia encabeza el gobierno del municipio; su nombre no está en las "
        "fuentes revisadas hasta hoy.",
        [("/actua", "Pide información", False), ("/acuerdos", "Ver los acuerdos", True)])
    # Gabinete y direcciones del directorio oficial: no son Cabildo, pero también
    # son personas funcionarias con cita y la gente debe poder verlas y revisarlas.
    usados = {f["id"] for f in regidores} | {x["id"] for x in (sindico, presidenta) if x}
    otros = [f for f in funcionarios if f["id"] not in usados]
    gabinete_html = ""
    if otros:
        tarjetas_otros = "".join(
            f'<div class="regcard"><span class="av a2" aria-hidden="true">{e(_iniciales(f["nombre"]))}</span>'
            f'<b class="nombre"><a href="/revisar/{f["id"]}">{e(f["nombre"])}</a></b><span class="t">{e(f["cargo"])}</span>'
            f'{_fuente_de(f, urls)}'
            f'<a class="btn ghost" href="/revisar/{f["id"]}">Ver su trabajo</a></div>' for f in otros)
        gabinete_html = (f'<details class="cap"><summary>{icono("ppl", "Dibujo de personas")}'
                         f'Gabinete y direcciones · {len(otros)}</summary>'
                         f'<div class="reggrid">{tarjetas_otros}</div></details>')
    comunidad_html = (f'<div class="tier"><h3>{icono("pin", "Dibujo de un pin de mapa")}Tu comunidad</h3>'
                      + "".join(nivel_comunidad) + '</div>') if nivel_comunidad else ""
    izquierda = ('<div style="display:flex;flex-direction:column;gap:20px">'
                 + comunidad_html
                 + cabildo_html
                 + f'<div class="tier"><h3>{icono("home", "Dibujo de una casa")}Presidencia</h3>'
                 + presidencia_html + '</div>'
                 + gabinete_html
                 + """<div class="card"><h3>El Cabildo completo</h3>
<p style="font-size:16px">Presidenta, síndico y regidores se reúnen, discuten y votan. Lo que acuerdan queda en documentos públicos.</p>
<p><a class="btn" href="/temas">¿Qué te preocupa?</a></p>
<p><a class="btn ghost" href="/acuerdos">Ver los acuerdos</a></p></div>"""
                 + inspector_html + '</div>')
    if len(nodos) > 1:
        derecha = (f'<div class="card sticky" style="text-align:center">'
                   '<img class="ilu" src="/static/ilustraciones/gobierno.svg" alt="Ilustración de las personas de tu gobierno" width="240" height="160" style="max-width:180px">'
                   f'{visual}'
                   '<p class="small muted">Más cerca del centro = más cerca de ti.</p></div>')
    else:
        derecha = _vacio("ppl", "Todavía no podemos dibujar tu gobierno",
                         "Aún no tenemos personas con cita verificada para poner en el diagrama; "
                         "en cuanto las encontremos, aparecerán aquí alrededor de ti.",
                         [("/actua", "Pide información", False), ("/acuerdos", "Ver los acuerdos", True)])
    # JS mínimo y en línea: resalta la tarjeta pareja del nodo (y al revés), en teléfono el
    # primer toque solo muestra la etiqueta, "Tú" explica el centro y el grupo despliega
    # la cuadrícula. Sin JS, cada nodo sigue siendo un enlace normal a su ficha.
    guion = """<script>
(function(){
 document.querySelectorAll('.nodo[data-nodo]').forEach(function(n){
  var t=document.querySelector('[data-tarjeta="'+n.getAttribute('data-nodo')+'"]'); if(!t) return;
  ['mouseenter','focus'].forEach(function(ev){ n.addEventListener(ev,function(){ t.classList.add('hl'); n.classList.add('hl'); }); });
  ['mouseleave','blur'].forEach(function(ev){ n.addEventListener(ev,function(){ t.classList.remove('hl'); n.classList.remove('hl'); }); });
 });
 document.querySelectorAll('[data-tarjeta]').forEach(function(t){
  var n=document.querySelector('.nodo[data-nodo="'+t.getAttribute('data-tarjeta')+'"]'); if(!n) return;
  ['mouseenter','focusin'].forEach(function(ev){ t.addEventListener(ev,function(){ n.classList.add('hl'); t.classList.add('hl'); }); });
  ['mouseleave','focusout'].forEach(function(ev){ t.addEventListener(ev,function(){ n.classList.remove('hl'); t.classList.remove('hl'); }); });
 });
 if(window.matchMedia('(hover: none)').matches){
  document.querySelectorAll('a.nodo').forEach(function(n){ n.addEventListener('click',function(ev){
   if(!n.classList.contains('show')){ ev.preventDefault();
    document.querySelectorAll('.nodo.show,.nodo-tu.show').forEach(function(x){ x.classList.remove('show'); });
    n.classList.add('show'); } }); });
 }
 var tu=document.getElementById('tu-nodo');
 if(tu) tu.addEventListener('click',function(){ tu.classList.toggle('show'); });
 var g=document.getElementById('grupo-reg');
 if(g) g.addEventListener('click',function(){ expandirRegidores(); g.setAttribute('aria-expanded','true');
  var grid=document.getElementById('reggrid'); if(grid) grid.focus(); });
})();
</script>"""
    cuerpo = f'<div class="grid g-side">{izquierda}{derecha}</div>{guion}'
    with _con() as con:
        mun = _filas(con, "SELECT nombre, estado FROM municipios WHERE clave_inegi = ?", (m,))
    lugar = f'{mun[0]["nombre"]}, {mun[0]["estado"]}' if mun else None
    return _fijar(pagina("Estas personas trabajan para ti", cuerpo, paso=2, lugar=lugar), m)


def _temas_grid(seleccion=""):
    return '<div class="grid2">' + "".join(
        f'<a class="tile {"on" if clave == seleccion else ""}" href="/temas/{clave}">{icono(ic, titulo)}{e(titulo)}</a>'
        for clave, ic, titulo, _, _ in TEMAS) + "</div>"


@app.get("/temas", response_class=HTMLResponse)
def temas():
    cuerpo = ('<p class="sub">Te decimos quién se encarga.</p>' + _temas_grid())
    return pagina("¿Qué te preocupa en tu comunidad?", cuerpo, paso=3)


@app.get("/temas/{clave}", response_class=HTMLResponse)
def tema(request: Request, clave: str):
    elegido = next((t for t in TEMAS if t[0] == clave), None)
    if not elegido:
        return HTMLResponse("<p>No se encontró el tema.</p>", status_code=404)
    _, ic, titulo, nombre_comision, orientacion = elegido
    clave_mun = _elegida(request)
    with _con() as con:
        comisiones = _gob(con, "comisiones", clave_mun)
        funcionarios = _gob(con, "funcionarios", clave_mun)
        funciones = _gob(con, "funciones_cargo", clave_mun)
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
                   f'<p style="font-size:16px"><strong>Qué hace:</strong> {e(f_reg["funcion"]) if f_reg else "todavía no tenemos la descripción de qué hacen las regidurías en las fuentes revisadas; sí sabemos qué comisión atiende este tema, la de arriba."}</p>'
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
        funcionarios = _gob(con, "funcionarios", None)  # todos los municipios revisados
        juntas = _gob(con, "juntas_auxiliares", None)
        try:
            municipios = {m["clave_inegi"]: m for m in _filas(con, "SELECT * FROM municipios")}
        except sqlite3.OperationalError:
            municipios = {}

    def lugar_de(f):
        m = municipios.get(f.get("municipio_id") or "")
        return f' · {e(m["nombre"])}, {e(m["estado"])}' if m else ""

    tarjetas = "".join(
        f'<div class="card person"><div class="av a2" style="margin:0" aria-hidden="true">{e(_iniciales(f["nombre"]))}</div><div>'
        f'<h3>{e(f["nombre"])}</h3><p class="sub" style="font-size:16px">{e(f["cargo"])}{lugar_de(f)}</p>'
        f'<p><a class="btn ghost" href="/revisar/{f["id"]}">Revisa su trabajo</a></p></div></div>' for f in funcionarios)
    tarjetas += "".join(
        f'<div class="card person"><div class="av" style="margin:0" aria-hidden="true">{e(_iniciales(j["presidente"] or j["nombre"]))}</div><div>'
        f'<h3>{e(j["presidente"] or j["nombre"])}</h3><p class="sub" style="font-size:16px">'
        f'{"Presidente auxiliar de " + e(j["nombre"]) if j["presidente"] else "Junta auxiliar de " + e(j["nombre"]) + ": todavía no tenemos el nombre de su presidente auxiliar en las fuentes revisadas"}</p>'
        f'<p><a class="btn ghost" href="/actua?para={e(j["nombre"])}">Pregúntale o pide información</a></p></div></div>' for j in juntas)
    if not tarjetas:
        return pagina("Revisa su trabajo", _vacio(
            "ppl", "Todavía no tenemos personas para revisar",
            "Aún no hay funcionarios ni juntas con cita verificada en las fuentes revisadas.",
            [("/representantes", "Ver tu gobierno", False), ("/acuerdos", "Ver los acuerdos", True)]), paso=4)
    return pagina("Revisa su trabajo", "<p>Elige a una persona para ver qué propuso y qué se aprobó.</p>"
                  f'<div class="cols">{tarjetas}</div>', paso=4)


@app.get("/revisar/{id_}", response_class=HTMLResponse)
def revisar_persona(id_: int):
    with _con() as con:
        # Por id y de cualquier municipio: el enlace viene de la página del
        # municipio de la persona, no de un municipio fijo.
        funcionarios = _gob(con, "funcionarios", None)
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
        funciones = _gob(con, "funciones_cargo", f.get("municipio_id"))
        evidencias = _filas(con, "SELECT * FROM evidencias ORDER BY id DESC LIMIT 3")
    plano_cargo = plano(f["cargo"])
    claves = ("presidenta municipal", "presidente municipal") if \
        ("presidenta municipal" in plano_cargo or "presidente municipal" in plano_cargo) else \
        ("síndico", "sindico") if "sindic" in plano_cargo else ("regidores",)
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
    if f["comision"]:
        ic_corto, corto = tema_corto(f["comision"])
        tag = (f'<span class="tag">{icono(ic_corto, "Icono del tema")} {e(corto)}</span>'
               f'<p class="small muted">Nombre oficial de su comisión: {e(f["comision"])}. '
               'El tema corto de arriba es una explicación general, no el nombre oficial.</p>')
    else:
        tag = f'<span class="tag">{e(f["cargo"])}</span>'
    n_fotos = len(evidencias)
    contacto_f = "".join(f'<p style="font-size:16px">{e(etiqueta)}: {e(f[campo])}</p>'
                         for campo, etiqueta in (("correo", "Correo institucional"), ("telefono", "Teléfono de oficina"),
                                                 ("direccion", "Oficina"))
                         if f.get(campo))
    if contacto_f:
        contacto_f = f'<div class="card"><h3>Contacto institucional</h3>{contacto_f}</div>'
    izquierda = (f'<div style="display:flex;flex-direction:column;gap:16px">'
                 f'<div class="person"><div class="av a2 l" aria-hidden="true">{e(_iniciales(f["nombre"]))}</div>'
                 f'<div><h2 style="margin:0">{e(f["nombre"])}</h2>{tag}{_fuente_de(f, urls)}</div></div>'
                 f'{contacto_f}'
                 f'<div class="card"><h3>¿Qué hace?</h3>'
                 + (f'<p style="font-size:16px">{e(f_fun["funcion"])}</p>{_fuente_de(f_fun, urls)}' if f_fun else
                    '<p style="font-size:16px">Todavía no tenemos la descripción de qué hace este cargo en las '
                    'fuentes revisadas. Sí sabemos su cargo oficial, el de arriba, con su fuente.</p>'
                    f'<p><a class="btn ghost" href="/actua?para={e(f["nombre"])}">Pide la descripción por transparencia</a></p>')
                 + '</div>'
                 f'<div class="card"><h3 style="margin-bottom:14px">Lo que ha propuesto</h3>'
                 + (f'<div class="tl">{linea}</div>' if acuerdos else
                    '<p style="font-size:16px">En los acuerdos revisados no aparece como proponente. '
                    'Esto solo cubre los documentos cargados hasta hoy.</p>'
                    '<p><a class="btn ghost" href="/acuerdos">Ver los acuerdos de Cabildo</a></p>')
                 + '</div>'
                 + '<div class="card"><h3>Lo que reportan vecinos</h3>'
                 + (fotos or '<p style="font-size:16px">Todavía no hay fotos ciudadanas registradas.</p>')
                 + f'<p><a class="btn ghost" href="/evidencia">{icono("cam", "Dibujo de una cámara")} Subir una foto</a></p></div></div>')
    derecha = (f'<div style="display:flex;flex-direction:column;gap:16px" class="sticky">'
               f'<div class="kpis"><div class="kpi"><b>{len(acuerdos)}</b><span class="small">propuestas en los acuerdos revisados</span></div>'
               f'<div class="kpi"><b>{n_fotos}</b><span class="small">fotos de vecinos</span></div>'
               f'<div class="kpi"><b>{hallazgos_n}</b><span class="small">diferencias*</span></div></div>'
               f'<div class="zero"><b>{hallazgos_n}</b><span class="small">diferencias encontradas '
               f'<b style="font-size:inherit;color:inherit">en los {n_docs} documentos revisados hasta hoy</b>. '
               'Eso no significa que todo esté bien: faltan documentos. '
               '<a href="/evidencia">Ayúdanos a revisar más</a></span></div>'
               f'<p><a class="btn" href="/actua?para={e(f["nombre"])}">{icono("mega", "Dibujo de un megáfono")} Pregúntale o pide información</a></p>'
               + _compartir_html(f"/compartir/funcionario/{f['id']}.png",
                                 f"{f['nombre']} ({f['cargo']}): {len(acuerdos)} propuestas en los acuerdos revisados; "
                                 f"{hallazgos_n} diferencias en los {n_docs} documentos revisados. Fuente: {f['archivo']}, p. {f['pagina']}")
               + '</div>')
    cuerpo = f'<div class="grid g-side">{izquierda}{derecha}</div>'
    with _con() as con:
        mun = _filas(con, "SELECT nombre, estado FROM municipios WHERE clave_inegi = ?",
                     (f["municipio_id"],)) if f.get("municipio_id") else []
    lugar = f'{mun[0]["nombre"]}, {mun[0]["estado"]}' if mun else None
    return pagina(f["nombre"], cuerpo, paso=4, sin_titulo=True, lugar=lugar)


@app.get("/actua", response_class=HTMLResponse)
def actua(request: Request, para: str = "", tema: str = "", m: str = ""):
    clave = _elegida(request, m)
    if not clave:
        return RedirectResponse("/donde", status_code=303)
    with _con() as con:
        mun = _nombre_municipio(con, clave)
    nombre = mun[0] if mun else None
    asunto = tema or (f"el trabajo de {para}" if para else
                      (f"el gasto y las decisiones del Ayuntamiento de {nombre}" if nombre
                       else "el gasto y las decisiones de tu Ayuntamiento"))
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
              f'<p style="font-size:16px">{"Elige el Ayuntamiento de " + e(nombre) + "." if nombre else "Elige tu Ayuntamiento."}</p></div></div>'
              '<div class="step"><span class="n">4</span><div><b>Espera tu respuesta</b>'
              '<p style="font-size:16px">Te llega a tu correo.</p></div></div></div>'
              + boton + sesion_html
              + '<div class="card" style="display:flex;gap:12px;align-items:center">'
                f'{icono("cam", "Dibujo de una cámara")}<span style="font-size:16px">También puedes reportar con '
                f'una foto, por ejemplo un bache o una luminaria apagada.</span></div>'
                '<p><a class="btn ghost" href="/evidencia">Sube una foto</a></p>'
              + rutas)
    return _fijar(pagina("Pide información", cuerpo, seccion="actua",
                         lugar=f"{mun[0]}, {mun[1]}" if mun else None), clave)


def _chip_estado(estado_indexacion: str) -> tuple[str, str]:
    return {"indexado": ("Revisado", "ok"), "indexando": ("Revisando", ""),
            "solicitado": ("Solicitud en espera", "warn"), "error": ("Sin revisar", "warn"),
            }.get(estado_indexacion, ("Sin revisar", "warn"))


def _buscador_html(q: str, resultados: list[dict], action: str = "/") -> tuple[str, str]:
    """Buscador nacional con sugerencias y el estado de cada municipio. Devuelve (buscador, sugerencias)."""
    sugg = ""
    if q:
        items = ""
        for r in resultados:
            texto_chip, clase = _chip_estado(r["estado_indexacion"])
            enlace = (f'/representantes?m={e(r["clave_mun"])}' if r["estado_indexacion"] == "indexado"
                      else f'/municipio/{e(r["clave_mun"])}')
            items += (f'<a href="{enlace}" data-nombre="{e(r["nom_loc"])}">{icono("pin", "Dibujo de un pin de mapa")}'
                      f'<span><b>{e(r["nom_loc"])}</b><br><span class="small muted">{e(r["nom_mun"])}, {e(r["nom_ent"])}</span></span>'
                      f'<small class="chip {clase}">{texto_chip}</small></a>')
        sugg = (f'<div class="card sugg" id="lista-resultados">{items}</div>' if items else _sin_resultados(q))
    buscador = (f'<form method="get" action="{action}" onsubmit="return buscando(this)"><label class="search">{icono("srch", "Dibujo de una lupa")}'
                f'<input name="q" type="search" value="{e(q)}" placeholder="Escribe tu localidad o municipio" '
                'aria-label="Busca tu localidad o municipio">'
                '<button class="btn" type="submit" style="min-height:48px;width:auto">Buscar</button></label></form>')
    return buscador, sugg


_MAPA_SVG = Path(__file__).resolve().parent / "static" / "mapa-mexico.svg"


def _mapa_html(con) -> str:
    """Mapa real (scripts/generar_mapa.py): estados tocables y un punto por municipio revisado."""
    try:
        texto = _MAPA_SVG.read_text(encoding="utf-8")
        lon0, lat1, escala, coseno, ox, oy = (float(v) for v in re.search(r'data-proy="([^"]+)"', texto).group(1).split(","))
        vista = re.search(r'viewBox="([^"]+)"', texto).group(1)
    except (OSError, AttributeError, ValueError):
        return ""  # sin el SVG generado no se inventa un contorno a mano
    revisados = {f["estado"]: f["n"] for f in _filas(
        con, "SELECT estado, count(*) n FROM municipios WHERE estado_indexacion = 'indexado' GROUP BY estado")}
    conteo = _filas(con, """SELECT count(*) total,
                            sum(CASE WHEN estado_indexacion = 'indexado' THEN 1 ELSE 0 END) rev
                            FROM municipios""")[0]
    total_mun, revisados_n = conteo["total"] or 0, conteo["rev"] or 0

    def titulo(estado: str) -> str:
        n = revisados.get(estado, 0)
        return f"{estado} — {n} municipio{'s' if n != 1 else ''} revisado{'s' if n != 1 else ''}"

    estados = "".join(
        f'<a href="/donde?estado={quote(estado)}" aria-label="{e(titulo(estado))}. Toca para buscar en este estado.">'
        f'<title>{e(titulo(estado))}</title><path class="st{" on" if revisados.get(estado) else ""}" d="{d}"/></a>'
        for estado, d in re.findall(r'<path data-estado="([^"]+)" d="([^"]+)">', texto))
    puntos = ""
    for m in _filas(con, """SELECT m.clave_inegi, m.nombre, m.estado, c.lat, c.lon FROM municipios m
                            JOIN cabeceras c ON c.clave_mun = m.clave_inegi
                            WHERE m.estado_indexacion = 'indexado' AND c.lat IS NOT NULL AND c.lon IS NOT NULL"""):
        x, y = ox + (m["lon"] - lon0) * coseno * escala, oy + (lat1 - m["lat"]) * escala
        ancla, lx = ("end", x - 14) if x > 560 else ("start", x + 14)
        puntos += (f'<a href="/representantes?m={e(m["clave_inegi"])}"><title>{e(m["nombre"])}, {e(m["estado"])} — Revisado</title>'
                   f'<circle class="pulso" cx="{x:.1f}" cy="{y:.1f}" r="10"/>'
                   f'<circle class="punto" cx="{x:.1f}" cy="{y:.1f}" r="10"/>'
                   f'<text class="mapa-etiqueta" x="{lx:.1f}" y="{y + 4:.1f}" text-anchor="{ancla}">{e(m["nombre"])}</text></a>')
    return (f'<div class="mapa-base"><svg class="mx" viewBox="{vista}" role="img" aria-label="Mapa de México: toca un estado para buscar ahí; '
            f'los puntos son los municipios ya revisados">{estados}{puntos}</svg>'
            f'<div class="mapa-pie"><span><b>{revisados_n}</b> de {total_mun:,} municipios revisados</span>'
            '<span class="mapa-fuente">Límites estatales: Natural Earth (dominio público). '
            'Puntos: cabecera municipal, catálogo de INEGI.</span></div></div>')


@app.get("/", response_class=HTMLResponse)
def inicio(q: str = ""):
    with _con() as con:
        resultados = municipios.buscar_localidades(con, q) if q else []
        indexados = _filas(con, "SELECT * FROM municipios WHERE estado_indexacion = 'indexado' ORDER BY nombre")
        mapa = _mapa_html(con)
    buscador, sugg = _buscador_html(q, resultados)
    ya = "".join(f'<a href="/representantes?m={e(m["clave_inegi"])}">{icono("pin", "Dibujo de un pin de mapa")}'
                 f'{e(m["nombre"])}, {e(m["estado"])}<small class="chip ok">Revisado</small></a>' for m in indexados)
    cuerpo = f"""<div class="hero">
{mapa}
<div class="hero-panel">
<span class="chip" style="align-self:flex-start">{icono("globe", "Dibujo de un globo terráqueo")}Para todo México</span>
<h1>¿Quién<br>gobierna<br>donde vives?</h1>
<p class="hero-sub">Conoce a tus autoridades, revisa lo que hacen con documentos oficiales y aprende qué puedes hacer tú. La política no te ignora. ¿La ignoras tú?</p>
<div>{buscador}{sugg}</div>
<p class="aviso">Los hallazgos son discrepancias verificables entre documentos públicos, no acusaciones.</p>
</div></div>
<div class="grid g3" style="margin-top:8px">
<div class="step"><span class="num">1</span><div><h3>Busca dónde vives</h3><p class="small muted">Cualquier localidad del país, del catálogo oficial de INEGI. No guardamos tu respuesta.</p></div></div>
<div class="step"><span class="num">2</span><div><h3>Conoce a quien te representa</h3><p class="small muted">De la autoridad más cercana a la más lejana.</p></div></div>
<div class="step"><span class="num">3</span><div><h3>Revisa y actúa</h3><p class="small muted">Con documentos oficiales y pasos claros.</p></div></div>
</div>
<h2>Municipios que ya revisamos</h2>
{('<div class="card list">' + ya + '</div>') if ya else _vacio("spark", "Aún no revisamos ningún municipio", "Cuando Muse revise el primero, con aprobación de una persona del equipo, aparecerá aquí. Busca el tuyo aquí arriba y pídelo.", [("/donde", "Busca tu municipio", False)])}"""
    return pagina("¿Quién gobierna donde vives?", cuerpo, sin_titulo=True, seccion="inicio")


@app.get("/donde", response_class=HTMLResponse)
def donde(request: Request, q: str = "", estado: str = ""):
    clave_cookie = request.cookies.get("municipio") or None
    with _con() as con:
        juntas = _gob(con, "juntas_auxiliares", clave_cookie) if clave_cookie else []
        mun_cookie = _nombre_municipio(con, clave_cookie)
        urls = _urls(con)
        cobertura = _cobertura_html(cruzar.cobertura(con))
        resultados = municipios.buscar_localidades(con, q) if q else []
        indexados = _filas(con, "SELECT * FROM municipios WHERE estado_indexacion = 'indexado' ORDER BY nombre")
        del_estado = (_filas(con, "SELECT * FROM municipios WHERE estado = ? ORDER BY nombre", (estado,))
                      if estado else [])
    resultados_html = ""
    if q:
        items = ""
        for r in resultados:
            if r["estado_indexacion"] == "indexado":
                items += (f'<a href="/representantes?m={e(r["clave_mun"])}" data-nombre="{e(r["nom_loc"])}">'
                          f'{icono("pin", "Dibujo de un pin de mapa")}{e(r["nom_loc"])} — {e(r["nom_mun"])}, {e(r["nom_ent"])}'
                          f'<span class="tag">Ya lo revisamos</span></a>')
            else:
                items += (f'<a href="/municipio/{e(r["clave_mun"])}" data-nombre="{e(r["nom_loc"])}">'
                          f'{icono("pin", "Dibujo de un pin de mapa")}{e(r["nom_loc"])} — {e(r["nom_mun"])}, {e(r["nom_ent"])}</a>')
        resultados_html = (f'<div class="card list" id="lista-resultados">{items}</div>' if items else _sin_resultados(q))
    opciones = "".join(
        f'<a href="/representantes?junta={j["id"]}&m={e(clave_cookie or "")}" data-nombre="{e(j["nombre"])} {e(j["presidente"] or "")}">'
        f'{icono("pin", "Dibujo de un pin de mapa")}{e(j["nombre"])}</a>' for j in juntas)
    juntas_html = ""
    if mun_cookie and juntas:  # solo tras elegir un municipio que sí tiene juntas en sus fuentes
        juntas_html = f"""<h2>Si vives en {e(mun_cookie[0])}, elige tu junta auxiliar</h2>
<div class="card list" id="lista-juntas">
<a href="/representantes?m={e(clave_cookie or "")}" data-nombre="{e(municipios.sin_acentos(mun_cookie[0] + " centro colonias cabecera"))}">{icono("pin", "Dibujo de un pin de mapa")}{e(mun_cookie[0])} centro y colonias</a>
{opciones}</div>
<p class="debil">Las colonias que atiende cada junta no están en la fuente oficial revisada; por eso la lista es por junta auxiliar.</p>"""
    def _tec(m):
        guardado = (f' · <a href="/fuentes/{e(m["archivo"])}">Documento guardado</a>'
                    if m["archivo"].rsplit(".", 1)[-1].lower() in ("pdf", "html") else "")
        return (f'<div class="tarjeta"><strong>{e(m["archivo"])}</strong><br>'
                f'<span class="debil">Descargado: {e(m.get("descargado", "sin fecha registrada"))}<br>'
                f'SHA-256: {e(m.get("sha256", ""))}</span><br>'
                f'<a href="{e(m.get("url", ""))}">Página oficial de la fuente</a>{guardado}</div>')

    tecnicos = "".join(_tec(m) for m in _manifiesto())
    ya = "".join(f'<a href="/representantes?m={e(m["clave_inegi"])}">{icono("pin", "Dibujo de un pin de mapa")}'
                 f'{e(m["nombre"])}, {e(m["estado"])}</a>' for m in indexados)
    buscador, sugg = _buscador_html(q, resultados, action="/donde")
    estado_html = ""
    if estado:
        def _link_estado(m):
            href = (f'/representantes?m={m["clave_inegi"]}' if m["estado_indexacion"] == "indexado"
                    else f'/municipio/{m["clave_inegi"]}')
            chip = '<small class="chip ok">Revisado</small>' if m["estado_indexacion"] == "indexado" else ""
            return (f'<a href="{href}">{icono("pin", "Dibujo de un pin de mapa")}'
                    f'{e(m["nombre"])}, {e(m["estado"])}{chip}</a>')
        links = "".join(_link_estado(m) for m in del_estado)
        estado_html = (f'<h2>Municipios de {e(estado)}</h2><div class="card list">{links}</div>' if links else
                       _vacio("pin", f"No encontramos municipios de “{estado}”",
                              "Toca otro estado en el mapa del inicio o busca tu localidad aquí arriba.",
                              [("/", "Volver al mapa", False)]))
    cuerpo = f"""<p class="sub">Busca tu localidad en todo México (catálogo oficial de INEGI). Así te mostramos primero a las personas más cercanas a ti. No guardamos tu respuesta.</p>
{buscador}{sugg}{estado_html}
<h2>Municipios que ya revisamos</h2>
{('<div class="card list">' + ya + '</div>') if ya else _vacio("spark", "Aún no revisamos ningún municipio", "Cuando Muse revise el primero, con aprobación de una persona del equipo, aparecerá aquí.", [("/", "Busca tu municipio", False)])}
{juntas_html}
<details class="tarjeta"><summary><strong>Detalles técnicos y fuentes revisadas</strong></summary>{tecnicos}{cobertura}</details>"""
    return pagina("¿Dónde vives?", cuerpo, paso=1)


@app.get("/municipio/{clave}", response_class=HTMLResponse)
def municipio(clave: str):
    with _con() as con:
        filas = _filas(con, "SELECT * FROM municipios WHERE clave_inegi = ?", (clave,))
        if not filas:
            return HTMLResponse("<p>No se encontró el municipio.</p>", status_code=404)
        m = filas[0]
        pendiente = _filas(con, "SELECT * FROM solicitudes WHERE clave_inegi = ? AND estado = 'pendiente' ORDER BY id DESC", (clave,))
    despues = ('<div class="card"><h3>¿Qué pasa después?</h3><div class="tl" style="margin-top:14px">'
               '<div><b>Una persona del equipo revisa tu solicitud</b><p class="small muted">Para cuidar que solo se usen fuentes oficiales.</p></div>'
               '<div><b>Muse busca y lee los documentos</b><p class="small muted">Puedes verlo trabajar en vivo.</p></div>'
               '<div><b>Publicamos lo que encontró</b><p class="small muted">Con la fuente de cada dato.</p></div></div></div>')
    lugar = f'{m["nombre"]}, {m["estado"]}'
    if m["estado_indexacion"] == "indexado":
        cuerpo = (f'<div class="grid g-side"><div class="card" style="display:flex;flex-direction:column;gap:16px">'
                  '<span class="chip ok" style="align-self:flex-start">Revisado</span>'
                  f'<h2>Ya revisamos {e(m["nombre"])}</h2>'
                  '<p class="muted">Conoce a las personas que gobiernan tu municipio y revisa su trabajo con documentos oficiales, cada dato con su fuente.</p>'
                  f'<p><a class="btn" href="/representantes?m={e(clave)}">Ver quién te representa</a></p></div>{despues}</div>')
    elif m["estado_indexacion"] == "indexando":
        cuerpo = (f'<div class="grid g-side"><div class="card" style="display:flex;flex-direction:column;gap:16px">'
                  '<span class="chip" style="align-self:flex-start">Revisando</span>'
                  f'<h2>Ya estamos revisando {e(m["nombre"])}</h2>'
                  '<p class="muted">Una persona del equipo ya aprobó la revisión y Muse está buscando y leyendo '
                  'los documentos oficiales. Puedes verlo trabajar en vivo, paso a paso.</p>'
                  f'<p><a class="btn" href="/indexando/{e(clave)}">Ver la revisión en vivo</a></p></div>{despues}</div>')
    elif m["estado_indexacion"] == "error":
        cuerpo = (f'<div class="grid g-side"><div class="card" style="display:flex;flex-direction:column;gap:16px">'
                  '<span class="chip warn" style="align-self:flex-start">La revisión se detuvo</span>'
                  f'<h2>Aún no revisamos {e(m["nombre"])}</h2>'
                  '<p class="muted">Muse ya intentó revisar este municipio una vez, con aprobación de una persona '
                  'del equipo, y la revisión se detuvo antes de terminar. Para no repetir la misma petición ni el '
                  'mismo gasto, desde aquí ya no se puede pedir otra vez; el avance guarda paso a paso qué pasó.</p>'
                  f'<p><a class="btn" href="/indexando/{e(clave)}">Ver lo que pasó</a></p></div>{despues}</div>')
    elif pendiente:
        cuerpo = (f'<div class="grid g-side"><div class="card" style="display:flex;flex-direction:column;gap:16px">'
                  '<span class="chip warn" style="align-self:flex-start">Solicitud en espera</span>'
                  f'<h2>Aún no revisamos {e(m["nombre"])}</h2>'
                  '<p class="muted"><strong>Ya hay una solicitud para revisar este municipio.</strong> '
                  'Una persona del equipo debe aprobarla antes de que Muse empiece a leer documentos. '
                  'Nada se hace sin esa aprobación.</p>'
                  f'<p><a class="btn ghost" href="/indexando/{e(clave)}">Ver el avance</a></p></div>{despues}</div>')
    else:
        cuerpo = (f'<div class="grid g-side"><div class="card" style="display:flex;flex-direction:column;gap:16px">'
                  '<span class="chip warn" style="align-self:flex-start">Todavía sin revisar</span>'
                  f'<h2>Aún no revisamos {e(m["nombre"])}</h2>'
                  '<p class="muted">Muse, nuestro asistente de inteligencia artificial, puede buscar los documentos '
                  'oficiales del municipio, leerlos y mostrarte quién gobierna y en qué se gasta. Cada dato llevará su fuente.</p>'
                  '<div class="grid g3" style="gap:10px">'
                  f'<div class="kpi">{icono("globe", "Dibujo de un globo terráqueo")}<div class="small">Busca en sitios .gob.mx</div></div>'
                  f'<div class="kpi">{icono("read", "Dibujo de un libro abierto")}<div class="small">Lee gacetas y presupuesto</div></div>'
                  f'<div class="kpi">{icono("chk", "Dibujo de una palomita")}<div class="small">Verifica cada cita</div></div></div>'
                  + f'<div class="btnrow"><form method="post" action="/solicitar/{e(clave)}">'
                    f'<button class="btn" type="submit">{icono("spark", "Dibujo de una estrella")}Pídele a Muse que lo revise</button></form>'
                    '<a class="btn ghost" href="/donde">Elige otro municipio</a></div>'
                    '</div>' + despues + '</div>')
    return _fijar(pagina(f'{m["nombre"]}, {m["estado"]}', cuerpo, seccion="inicio", sin_titulo=True, lugar=lugar), clave)


@app.post("/solicitar/{clave}")
def solicitar(clave: str):
    with _con() as con:
        filas = _filas(con, "SELECT * FROM municipios WHERE clave_inegi = ?", (clave,))
        if not filas:
            return HTMLResponse("<p>No se encontró el municipio.</p>", status_code=404)
        if filas[0]["estado_indexacion"] == "indexado":
            return RedirectResponse(f"/representantes?m={clave}", status_code=303)
        if filas[0]["estado_indexacion"] == "indexando":
            return RedirectResponse(f"/indexando/{clave}", status_code=303)  # ya se está revisando: no duplicar ni pisar el estado
        ya_aprobada = _filas(con, "SELECT id FROM solicitudes WHERE clave_inegi = ? AND estado = 'aprobada'", (clave,))
        if ya_aprobada:
            return RedirectResponse(f"/indexando/{clave}", status_code=303)  # ya se aprobó una vez: la misma petición no se repite
        ya = _filas(con, "SELECT id FROM solicitudes WHERE clave_inegi = ? AND estado = 'pendiente'", (clave,))
        if not ya:
            try:
                con.execute("INSERT INTO solicitudes (clave_inegi, estado, creada) VALUES (?, 'pendiente', ?)",
                            (clave, datetime.now(timezone.utc).isoformat(timespec="seconds")))
                con.execute("UPDATE municipios SET estado_indexacion = 'solicitado' WHERE clave_inegi = ?", (clave,))
                con.commit()
            except sqlite3.IntegrityError:
                con.rollback()  # otra petición ganó la carrera: ya quedó una pendiente, no duplicar
    return RedirectResponse(f"/municipio/{clave}", status_code=303)


def _lanzar_indexador(clave: str):
    """Arranca el agente indexador como proceso aparte. Nada lo llama sin aprobación humana."""
    subprocess.Popen([sys.executable, "indexar.py", clave],
                     cwd=str(Path(__file__).resolve().parent),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _admin_activo() -> bool:
    """Sin ADMIN_TOKEN de al menos 32 caracteres, /admin no existe: responde 404."""
    return len(os.environ.get("ADMIN_TOKEN", "")) >= 32


def _token_ok(token: str) -> bool:
    esperado = os.environ.get("ADMIN_TOKEN", "")
    return _admin_activo() and bool(token) and secrets.compare_digest(token, esperado)


@app.get("/admin", response_class=HTMLResponse)
def admin(token: str = ""):
    if not _admin_activo():
        return HTMLResponse("<p>No se encontró la página.</p>", status_code=404)
    if not _token_ok(token):
        cuerpo = ('<p>Esta página es solo para el equipo que aprueba nuevas revisiones de municipios.</p>'
                  '<form method="get" action="/admin"><label for="token">Token de administración</label>'
                  '<input id="token" name="token" type="password" autocomplete="off">'
                  '<p><button class="btn" type="submit">Entrar</button></p></form>')
        return pagina("Administración", cuerpo)
    with _con() as con:
        pendientes = _filas(con, """SELECT s.*, m.nombre, m.estado FROM solicitudes s
                                    JOIN municipios m ON m.clave_inegi = s.clave_inegi
                                    WHERE s.estado = 'pendiente' ORDER BY s.id""")
        recientes = _filas(con, """SELECT s.*, m.nombre, m.estado FROM solicitudes s
                                   JOIN municipios m ON m.clave_inegi = s.clave_inegi
                                   WHERE s.estado != 'pendiente' ORDER BY s.id DESC LIMIT 10""")
    lista = ""
    for s in pendientes:
        lista += (f'<div class="card"><h3>{e(s["nombre"])}, {e(s["estado"])}</h3>'
                  f'<p style="font-size:16px">Solicitud #{s["id"]} · pedida el {e(s["creada"])} · '
                  'al aprobar, Muse buscará y leerá sus documentos públicos (tope de gasto por municipio).</p>'
                  f'<form method="post" action="/admin/decision">'
                  f'<input type="hidden" name="token" value="{e(token)}">'
                  f'<input type="hidden" name="solicitud" value="{s["id"]}">'
                  '<p><button class="btn" type="submit" name="decision" value="aprobar">Aprobar y empezar la revisión</button></p>'
                  '<p><button class="btn ghost" type="submit" name="decision" value="rechazar">Rechazar</button></p></form></div>')
    hist = "".join(f'<div class="tarjeta">{e(s["nombre"])}, {e(s["estado"])}: solicitud {e(s["estado"])} '
                   f'(decidida el {e(s["decidida"] or "—")}) · <a href="/indexando/{e(s["clave_inegi"])}">ver avance</a></div>'
                   for s in recientes)
    cuerpo = ('<h2>Solicitudes por decidir</h2>' + (lista or '<p>No hay solicitudes pendientes. Cuando una persona pida revisar un municipio, aparecerá aquí para que la apruebes o la rechaces.</p>')
              + '<h2>Decisiones recientes</h2>' + (hist or '<p>Todavía no hay decisiones. Las solicitudes que apruebes o rechaces quedarán aquí.</p>'))
    return pagina("Administración", cuerpo)


@app.post("/admin/decision")
def admin_decision(token: str = Form(""), solicitud: int = Form(0), decision: str = Form("")):
    if not _admin_activo():
        return HTMLResponse("<p>No se encontró la página.</p>", status_code=404)
    if not _token_ok(token):
        return HTMLResponse("<p>Token no válido.</p>", status_code=403)
    with _con() as con:
        filas = _filas(con, "SELECT * FROM solicitudes WHERE id = ? AND estado = 'pendiente'", (solicitud,))
        if not filas:
            return HTMLResponse("<p>La solicitud ya fue decidida o no existe.</p>", status_code=404)
        s = filas[0]
        ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if decision == "aprobar":
            con.execute("UPDATE solicitudes SET estado = 'aprobada', decidida = ? WHERE id = ?", (ahora, solicitud))
            con.execute("UPDATE municipios SET estado_indexacion = 'indexando' WHERE clave_inegi = ?", (s["clave_inegi"],))
            con.commit()
            municipios.registrar_evento(con, s["clave_inegi"], "aprobada",
                                        "Una persona del equipo aprobó la solicitud. Muse empieza a buscar los documentos públicos.")
            _lanzar_indexador(s["clave_inegi"])  # solo aquí, tras la aprobación, se dispara el agente
        else:
            con.execute("UPDATE solicitudes SET estado = 'rechazada', decidida = ? WHERE id = ?", (ahora, solicitud))
            con.execute("UPDATE municipios SET estado_indexacion = 'sin_revisar' WHERE clave_inegi = ?", (s["clave_inegi"],))
            con.commit()
    return RedirectResponse(f"/admin?token={quote(token)}", status_code=303)


def _evento_presentacion(paso: str, mensaje: str) -> tuple[str, str]:
    """(icono, clase del punto) según el tipo de evento, como en el mockup nacional."""
    texto = plano(mensaje)
    if paso in ("correccion", "descartado", "tope") or texto.startswith("no encontre") or texto.startswith("no pude"):
        return "alert", "warn"
    if paso == "verificacion":
        return "chk", "ok"
    if paso == "descarga":
        return "doc", "ok"
    if paso == "portal":
        return "globe", "ok" if texto.startswith("encontre") else "now"
    if paso == "lectura":
        return "read", "now"
    if paso == "aprobada":
        return "ppl", ""
    if paso == "fin":
        return "chk", "ok"
    return "spark", "now" if paso in ("inicio", "gaceta", "presupuesto", "directorio") else ""


_URL_RE = re.compile(r"https?://[^\s<]+")

def _mensaje_html(mensaje: str) -> str:
    """Texto del evento escapado; cada URL se ve solo como dominio + «ver documento»."""
    partes, pos = [], 0
    for m_ in _URL_RE.finditer(mensaje or ""):
        url = m_.group(0).rstrip(".,;:)")
        cola = m_.group(0)[len(url):]
        partes.append(e(mensaje[pos:m_.start()]))
        partes.append(f'<a href="{e(url)}">{e(urlparse(url).hostname or url)} · ver documento</a>{e(cola)}')
        pos = m_.end()
    partes.append(e(mensaje[pos:]))
    return "".join(partes)


def _evento_html(ev: dict) -> str:
    ic, clase = _evento_presentacion(ev["paso"], ev["mensaje"])
    return (f'<div class="ev"><span class="dot {clase}">{icono(ic, "Icono del paso " + ev["paso"])}</span>'
            f'<div><b>{_mensaje_html(ev["mensaje"])}</b><br><time>{e(ev["ts"])}</time></div></div>')


def _costo_indexacion(clave: str) -> float:
    import llm
    if not llm.LOG_COSTOS.exists():
        return 0.0
    total = 0.0
    for linea in llm.LOG_COSTOS.read_text().splitlines():
        if linea.strip():
            g = json.loads(linea)
            if clave in g.get("etiqueta", ""):
                total += g.get("usd", 0.0)
    return total


@app.get("/indexando/{clave}", response_class=HTMLResponse)
def indexando(clave: str):
    with _con() as con:
        filas = _filas(con, "SELECT * FROM municipios WHERE clave_inegi = ?", (clave,))
        if not filas:
            return HTMLResponse("<p>No se encontró el municipio.</p>", status_code=404)
        m = filas[0]
        eventos = _filas(con, "SELECT * FROM eventos_indexacion WHERE clave_inegi = ? ORDER BY id", (clave,))
        docs = _filas(con, "SELECT archivo FROM documentos WHERE municipio_id = ? ORDER BY id", (clave,))
        citas_ok = citas_total = 0
        for tabla in ("acuerdos", "partidas", "funcionarios"):
            try:
                f = con.execute(f"SELECT count(*), sum(verificacion = 'ok') FROM {tabla} WHERE municipio_id = ?",
                                (clave,)).fetchone()
                citas_total += f[0] or 0
                citas_ok += f[1] or 0
            except sqlite3.OperationalError:
                pass
    # Última corrida: desde el último «inicio» (con su «aprobada» previa, si la hay).
    inicios = [i for i, ev in enumerate(eventos) if ev["paso"] == "inicio"]
    if inicios:
        corte = inicios[-1]
        if corte > 0 and eventos[corte - 1]["paso"] == "aprobada":
            corte -= 1
    else:
        aprobadas = [i for i, ev in enumerate(eventos) if ev["paso"] == "aprobada"]
        corte = aprobadas[-1] if aprobadas else 0
    ultimos, anteriores = eventos[corte:], eventos[:corte]
    feed = "".join(_evento_html(ev) for ev in reversed(ultimos)) or _vacio(
        "spark", "Todavía no hay pasos de esta revisión",
        "Cuando una persona del equipo apruebe la solicitud, aquí verás paso a paso lo que Muse encuentra.",
        [(f"/municipio/{clave}", "Ver el municipio", False),
         ("/donde", "Elige otro municipio", True)])
    anteriores_html = ""
    if anteriores:
        anteriores_html = (f'<details class="anteriores"><summary>Revisiones anteriores ({len(anteriores)})</summary>'
                           f'<div class="feed">{"".join(_evento_html(ev) for ev in reversed(anteriores))}</div></details>')
    estado = {"indexado": "Ya terminamos de revisar este municipio.",
              "indexando": "Muse está leyendo los documentos públicos de este municipio…",
              "solicitado": "Solicitud registrada. Falta que una persona del equipo la apruebe.",
              "error": "La revisión se detuvo. Esto es lo que pasó:"}.get(
                  m["estado_indexacion"], "Todavía no se ha pedido revisar este municipio.")
    en_vivo = '<span class="live"><i></i>En vivo</span>' if m["estado_indexacion"] == "indexando" else ""
    enlace = (f'<p><a class="btn" href="/representantes?m={e(clave)}">Ver quién te representa</a></p>'
              if m["estado_indexacion"] == "indexado" else "")
    nombres_doc = [("gaceta", "Gaceta municipal"), ("presupuesto", "Presupuesto de egresos"),
                   ("directorio", "Directorio del Cabildo"), ("portal", "Portal de transparencia")]
    encontrados = {p for p, _ in nombres_doc for ev in ultimos
                   if ev["paso"] == p and plano(ev["mensaje"]).startswith("encontre")}
    no_encontrados = {p for p, _ in nombres_doc for ev in ultimos
                      if ev["paso"] == p and plano(ev["mensaje"]).startswith("no encontre")}
    costo = _costo_indexacion(clave)
    hallado = ", ".join(et for p, et in nombres_doc if p in encontrados) or "todavía nada"
    no_hallado = ", ".join(et for p, et in nombres_doc if p in no_encontrados) or "nada por ahora"
    resumen = (f'<div class="resumen-ind">'
               f'<div class="kpi"><b>{len(docs)}</b><span class="small">Documentos leídos</span></div>'
               f'<div class="kpi"><b style="color:var(--ok)">{citas_ok}/{citas_total}</b><span class="small">Citas verificadas</span></div>'
               f'<div class="kpi"><span class="small">Qué se encontró: {e(hallado)}. Qué no se encontró: {e(no_hallado)}.</span></div>'
               f'<div class="kpi"><b>${costo:.2f}</b><span class="small">Costo</span></div></div>')
    cuerpo = (f'<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px">'
              f'<h2 style="margin:0">Revisando {e(m["nombre"])}</h2>{en_vivo}</div>'
              f'<p class="sub">{e(estado)}</p>'
              f'{resumen}'
              f'<div class="card"><h3>Última revisión</h3><div class="feed" id="eventos">{feed}</div>'
              f'{"<div class=\"skel\" aria-hidden=\"true\"><i></i><i></i><i></i></div>" if m["estado_indexacion"] == "indexando" else ""}'
              '<p class="debil" id="en-vivo" aria-live="polite">Conectando con el avance en vivo…</p></div>'
              f'{anteriores_html}'
              + enlace
              + f"""<script>
var fuente = new EventSource('/indexando/{e(clave)}/eventos');
var ultimoEv = {eventos[-1]["id"] if eventos else 0};
fuente.onmessage = function(ev){{ var d = JSON.parse(ev.data); if(d.id <= ultimoEv) return; ultimoEv = d.id;
  fetch('/indexando/{e(clave)}/evento/' + d.id).then(function(r){{ return r.text(); }}).then(function(html_){{
  var tmp = document.createElement('div'); tmp.innerHTML = html_;
  document.getElementById('eventos').prepend(tmp.firstChild); }}); }};
fuente.onerror = function(){{ document.getElementById('en-vivo').textContent = 'La conexión en vivo se cerró. Recarga la página para ver el avance.'; }};
</script>""")
    return pagina(f'Revisando {m["nombre"]}, {m["estado"]}', cuerpo, seccion="inicio", sin_titulo=True,
                  lugar=f'{m["nombre"]}, {m["estado"]}')


@app.get("/indexando/{clave}/evento/{id_}", response_class=HTMLResponse)
def indexando_evento(clave: str, id_: int):
    """Un evento ya renderizado, para insertarlo arriba del feed sin recargar."""
    with municipios.conectar() as con:
        filas = _filas(con, "SELECT * FROM eventos_indexacion WHERE clave_inegi = ? AND id = ?", (clave, id_))
    if not filas:
        return HTMLResponse("", status_code=404)
    return HTMLResponse(_evento_html(filas[0]))


@app.get("/indexando/{clave}/eventos")
def indexando_eventos(clave: str):
    def generar():
        ultimo = 0
        for _ in range(900):  # ponytail: 15 min máx por conexión; el navegador reconecta solo
            with municipios.conectar() as con:
                filas = _filas(con, "SELECT * FROM eventos_indexacion WHERE clave_inegi = ? AND id > ? ORDER BY id",
                               (clave, ultimo))
                m = _filas(con, "SELECT estado_indexacion FROM municipios WHERE clave_inegi = ?", (clave,))
            for f in filas:
                ultimo = f["id"]
                yield f"data: {json.dumps(f, ensure_ascii=False)}\n\n"
            if m and m[0]["estado_indexacion"] in ("indexado", "error") and not filas:
                break
            yield ": latido\n\n"
            time.sleep(1)
    return StreamingResponse(generar(), media_type="text/event-stream")


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
    return pagina("Funcionarios", f'<div class="cols">{tarjetas}</div>' if tarjetas else _vacio(
        "ppl", "Todavía no hay personas en los acuerdos revisados",
        "Cuando un acuerdo nombre a quien lo propuso, esa persona aparecerá aquí con su cita.",
        [("/acuerdos", "Ver los acuerdos", False), ("/representantes", "Ver tu gobierno", True)]))


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
{p['menciones'] - p['verificadas']} no verificadas) · Hallazgos relacionados: {p['hallazgos']}</p>{acuerdos or '<p>En los acuerdos revisados hasta hoy no aparece como proponente.</p>'}"""
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
    return pagina("Acuerdos de Cabildo", intro + (f'<div class="cols">{tarjetas}</div>' if tarjetas else _vacio(
        "doc", "Todavía no hay acuerdos registrados",
        "Cuando leamos la primera gaceta o acta, sus acuerdos aparecerán aquí con su fuente.",
        [("/actua", "Pide información", False), ("/representantes", "Ver tu gobierno", True)])))


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
        rutas = _rutas_html(con, f"el acuerdo «{a['acuerdo'][:120]}» de tu Ayuntamiento", urls)
    personas = "".join(f"<li>{e(p['nombre'])} — {e(p['cargo'] or 'sin cargo registrado')}</li>"
                       for p in json.loads(a["propuesto_por"])) or "<li>Sin proponentes registrados en la fuente revisada; puedes pedir ese dato por transparencia.</li>"
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
def presupuesto_(request: Request):
    with _con() as con:
        partidas = cruzar._partidas(con)
        urls = _urls(con)
        glos = _glosario(con)
        resumenes = {p["id"]: _resumen_html(con, "partida", p["id"], urls) for p in partidas}
        mun = _nombre_municipio(con, _elegida(request))
        rutas = _rutas_html(con, (f"el Presupuesto de Egresos 2026 del Ayuntamiento de {mun[0]}" if mun
                                  else "el Presupuesto de Egresos 2026 de tu municipio"), urls)
    grupos: dict[str, list] = {}
    for p in partidas:
        grupos.setdefault(p["capitulo"] or "sin capítulo", []).append(p)
    bloques = ""
    for cap, ps in grupos.items():
        ic_cap, comun_cap = CAPITULOS_COMUNES.get(cap, ("coin", "Otro gasto"))
        total_cap = sum(p["monto_mxn"] or 0 for p in ps)
        filas_cap = "".join(
            f"""<div class="partida"><strong>{e(p['nombre'])}</strong><br>
            {_dinero(p['monto_mxn'])}<br><span class="debil">{e(en_palabras(p['monto_mxn'])) if p['monto_mxn'] is not None else ''}</span><br>
            {'<span class="marca">nombre no verificado</span>' if p['verificacion_nombre'] != 'ok' else ''}
            {resumenes[p['id']]}
            <span class="marca">monto: {e(p['verificacion'])}</span><span class="marca">nombre: {e(p['verificacion_nombre'])}</span>
            {fuente_html(p['archivo'], p['pagina'], p['fragmento'], urls)}</div>""" for p in ps)
        bloques += (f'<details class="cap"><summary>{icono(ic_cap, "Icono de " + comun_cap)}'
                    f'<span><strong>{e(cap)} · {e(comun_cap)}</strong><br>'
                    f'<span class="small muted">{len(ps)} partida(s) · {e(en_palabras(total_cap)) if total_cap else "sin monto"}</span></span></summary>'
                    f'{filas_cap}</details>')
    intro = ("<p>Este es el plan de gastos del municipio para 2026. Cada renglón es un grupo de gasto, "
             "con su monto en números y en palabras, y su fuente.</p>"
             + ayuda("Presupuesto de Egresos", glos, urls) + ayuda("Capítulo del gasto", glos, urls)
             + ayuda("Partida", glos, urls) + ayuda("Inversión Pública", glos, urls)
             + ayuda("Servicios Personales", glos, urls))
    if not partidas:
        return pagina("Presupuesto de Egresos 2026", intro + _vacio(
            "coin", "Todavía no hay partidas en las fuentes revisadas",
            "El Presupuesto de Egresos es el plan de gastos del año; en cuanto lo leamos, cada grupo "
            "de gasto aparecerá aquí con su monto y su fuente.",
            [("/gastos", "Ver el gasto en 100 monedas", False), ("/actua", "Pide el presupuesto", True)]) + rutas)
    return pagina("Presupuesto de Egresos 2026",
                  intro + bloques + rutas)


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
                          f"Diferencia entre documentos públicos: {h['descripcion'][:180]} "
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


# ponytail: límites por IP en memoria de este proceso; Fly corre 1 máquina — si hay varias, contar en SQLite.
_LIMITES = {"buscar": 60, "evidencia": 10, "solicitar": 20, "admin": 10}  # máximo por minuto e IP
_hits: dict[tuple[str, str], list[float]] = {}


def _limite_para(request: Request) -> str | None:
    ruta, metodo = request.url.path, request.method
    if ruta.startswith("/admin"):
        return "admin"
    if metodo == "POST" and ruta == "/evidencia":
        return "evidencia"
    if metodo == "POST" and ruta.startswith("/solicitar/"):
        return "solicitar"
    if metodo == "GET" and ruta in ("/", "/donde") and request.query_params.get("q"):
        return "buscar"
    return None


@app.middleware("http")
async def _limite_peticiones(request: Request, call_next):
    clave = _limite_para(request)
    if clave:
        ip = request.client.host if request.client else "?"
        ahora = time.monotonic()
        recientes = [t for t in _hits.get((clave, ip), []) if ahora - t < 60]
        if len(recientes) >= _LIMITES[clave]:
            return HTMLResponse("<p>Estás haciendo muchas solicitudes muy rápido. "
                                "Espera un minuto y vuelve a intentarlo.</p>", status_code=429)
        _hits[(clave, ip)] = recientes + [ahora]
    return await call_next(request)


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
<h2>Evidencias registradas</h2>{tarjetas or _vacio("cam", "Todavía no hay fotos de vecinos", "Sube la primera: por ejemplo, un bache o una luminaria apagada. La foto se guarda sin datos de ubicación.", [("/evidencia#foto", "Sube una foto", False)])}"""
    return pagina("Evidencia ciudadana", cuerpo)


@app.post("/evidencia")
async def evidencia_subir(foto: UploadFile = File(...), objeto: str = Form(...)):
    contenido = await foto.read()
    if len(contenido) > 10 * 1024 * 1024:  # tamaño real leído, no el encabezado
        return HTMLResponse("<p>La foto supera el máximo de 10 MB. Sube una foto más ligera, por favor.</p>",
                            status_code=413)
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
            id_ = evidencia.guardar(con, str(limpia.relative_to(extraer.DATA_DIR)), objeto, evidencia.resumen_sam(seg),
                                    str(ruta_mascara.relative_to(extraer.DATA_DIR)) if ruta_mascara else None,
                                    str(ruta_superpuesta.relative_to(extraer.DATA_DIR)) if ruta_superpuesta else None,
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
