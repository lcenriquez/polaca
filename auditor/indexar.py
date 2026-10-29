"""Agente indexador: lleva el auditor a un municipio nuevo, solo tras aprobación humana.

Uso: ../.venv/bin/python indexar.py <clave_inegi>    (lo lanza web.py al aprobar en /admin)

Primero confirma el dominio oficial del municipio y lo RECORRE (menú, sitemap,
robots.txt, búsqueda interna de WordPress y recorrido en anchura sin API)
antes de volver a la búsqueda web. Solo descarga del dominio propio o de
fuentes estatales/federales oficiales .gob.mx: un dominio de otro municipio
se descarta sin descargar. Cada paso queda en eventos_indexacion, que la
página /indexando/<clave> muestra en vivo por SSE. Antes de decir «no
encontré» de un tipo de documento, agota todos los caminos de
CAMINOS_AGOTAMIENTO y registra cuáles probó. Si una fuente no aparece tras
agotarlos, lo dice y no la inventa.

Topes de gasto: $1.00 por municipio y $5.00 por día (leídos de costos.jsonl,
que llm.py escribe en cada llamada). Al llegar al tope se detiene y lo reporta.
"""
import hashlib
import html as _html
import json
import re
import sys
import urllib.request
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import extraer
import gobierno
import llm
import municipios
import presupuesto

TOPE_MUNICIPIO = 1.00
TOPE_DIA = 5.00
MAX_INTENTOS = 5  # candidatas por fuente: la búsqueda confunde municipios, se prueba hasta dar con el correcto
MAX_PAGINAS_PDF = 40  # ponytail: primera pasada acotada; subir si el tope de gasto lo permite
MAX_PAGINAS_RECORRIDO = 150
MAX_PROFUNDIDAD = 3
PALABRAS_RECORRIDO = ("cabildo", "regidor", "regiduria", "organigrama", "directorio", "ayuntamiento",
                      "gaceta", "acta", "sesion", "presupuesto", "egresos", "licitaciones",
                      "obra publica", "contratos", "transparencia")
RUTAS_TECNICAS = ("/wp-content/plugins/", "/wp-includes/", "/wp-content/cache/")
EXT_TECNICAS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".css", ".js", ".zip", ".mp4", ".woff", ".woff2")
CORREOS_PERSONALES = {"gmail.com", "hotmail.com", "hotmail.es", "yahoo.com", "yahoo.com.mx", "outlook.com",
                      "outlook.es", "live.com", "live.com.mx", "icloud.com", "protonmail.com", "aol.com"}
TIPOS_DOC = {"directorio": "el directorio", "gaceta": "la gaceta o actas",
             "presupuesto": "el presupuesto", "contratos": "contratos u obra pública"}
# Antes de decir «no encontré» de un tipo hay que haber probado TODOS estos caminos.
CAMINOS_AGOTAMIENTO = ("menú del sitio", "sitemap", "búsqueda en el sitio", "recorrido del sitio",
                       "búsqueda web en el dominio propio", "búsqueda web", "fuentes estatales oficiales")
SINONIMOS = {
    "directorio": ["integrantes del cabildo", "regidores", "síndico", "directorio de cabildo", "organigrama"],
    "gaceta": ["gaceta municipal", "actas de cabildo", "sesión de cabildo"],
    "presupuesto": ["presupuesto de egresos 2026", "presupuesto de egresos"],
    "contratos": ["licitaciones", "contratos", "obra pública"],
}
PALABRAS_TIPO = {
    "directorio": ["cabildo", "regidor", "regiduria", "organigrama", "directorio", "integrantes"],
    "gaceta": ["gaceta", "acta", "sesion"],
    "presupuesto": ["presupuesto", "egresos"],
    "contratos": ["licitaciones", "contrato", "obra publica", "obra-publica", "obras"],
}


class TopeAlcanzado(Exception):
    pass


def es_gob_mx(url: str) -> bool:
    """Solo dominios oficiales: el host es gob.mx o termina en .gob.mx."""
    host = (urlparse(url).hostname or "").lower()
    return host == "gob.mx" or host.endswith(".gob.mx")


def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", municipios.sin_acentos(texto))


def variantes_dominio(nombre: str, estado: str) -> list[str]:
    """Variantes comunes del dominio oficial a probar antes de buscar en la web."""
    m, e = _slug(nombre), _slug(estado)
    return [f"{m}.gob.mx", f"{m}{e}.gob.mx", f"transparencia{m}.gob.mx", f"transparencia.{m}.gob.mx"]


def dominio_permitido(url: str, nombre: str, estado: str = "", dominios=()) -> bool:
    """True solo para el dominio propio confirmado o una fuente estatal/federal oficial.

    Un .gob.mx de OTRO municipio (zihuatanejodeazueta.gob.mx para Cuernavaca) se
    descarta aquí, sin descargar. Las fuentes estatales se reconocen porque el
    nombre del estado es una etiqueta completa del host (morelos.gob.mx,
    transparencia.morelos.gob.mx), no parte del nombre de otro municipio
    (tepalcingomorelos.gob.mx no pasa)."""
    if not es_gob_mx(url):
        return False
    host = (urlparse(url).hostname or "").lower()
    if host in dominios or any(host.endswith("." + d) for d in dominios):
        return True
    compacto = host.replace(".", "").replace("-", "")
    if _slug(nombre) and _slug(nombre) in compacto:
        return True
    etiquetas = host.split(".")
    if _slug(estado) and _slug(estado) in etiquetas:
        return True
    return host in ("gob.mx", "www.gob.mx")


def correo_institucional(correo: str | None, dominios=()) -> str | None:
    """El correo solo si es del dominio oficial; nunca uno personal (gmail, hotmail…)."""
    if not correo or "@" not in correo:
        return None
    correo = correo.strip().lower()
    dominio = correo.rsplit("@", 1)[-1]
    if dominio in CORREOS_PERSONALES:
        return None
    if dominios:
        return correo if any(dominio == d or dominio.endswith("." + d) for d in dominios) else None
    return correo if dominio.endswith(".gob.mx") else None


def filtrar_contacto(fila: dict, dominios=()) -> dict:
    """Privacidad: fuera correos personales y, sin correo institucional que lo respalde,
    también el teléfono suelto (no se distingue un celular personal de uno de oficina)."""
    f = dict(fila)
    f["correo"] = correo_institucional(f.get("correo"), dominios)
    if not f["correo"]:
        f["telefono"] = None
    return f


def texto_plano(html_crudo: str) -> str:
    crudo = re.sub(r"<(script|style).*?</\1>", " ", html_crudo or "", flags=re.S | re.I)
    crudo = re.sub(r"<[^>]+>", "\n", crudo)
    return re.sub(r"\s*\n\s*", "\n", _html.unescape(crudo)).strip()


def obtener(url: str) -> str | None:
    """GET sin API (recorrido, sitemaps, WP-JSON). None si falla o no es texto."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (auditor-atlixco)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            datos = r.read(3_000_000)
    except Exception:
        return None
    if datos.startswith(b"%PDF"):
        return None
    return datos.decode("utf-8", errors="ignore")


class _Enlaces(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.enlaces, self._href, self._texto = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._texto = dict(attrs).get("href"), []

    def handle_data(self, data):
        if self._href is not None:
            self._texto.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.enlaces.append((self._href, " ".join(self._texto).strip()))
            self._href = None


def extraer_enlaces(html_crudo: str, base: str) -> list[tuple[str, str]]:
    p = _Enlaces()
    try:
        p.feed(html_crudo or "")
    except Exception:
        return []
    vistos, salida = set(), []
    for href, texto in p.enlaces:
        url = urljoin(base, href).split("#", 1)[0]
        if url.startswith(("http://", "https://")) and url not in vistos:
            vistos.add(url)
            salida.append((url, texto))
    return salida


def es_ruta_tecnica(url: str) -> bool:
    ruta = urlparse(url).path.lower()
    return any(t in ruta for t in RUTAS_TECNICAS) or ruta.endswith(EXT_TECNICAS)


def _puntos_enlace(url: str, texto: str) -> int:
    plano = municipios.sin_acentos(url + " " + texto)
    return sum(p in plano for p in PALABRAS_RECORRIDO)


def recorrer_sitio(fetch, inicio: str, max_paginas: int = MAX_PAGINAS_RECORRIDO,
                   max_profundidad: int = MAX_PROFUNDIDAD) -> dict[str, str]:
    """Recorrido en anchura dentro del mismo dominio, sin API.

    Prioriza enlaces cuyo texto o URL suene a cabildo/gaceta/presupuesto/etc. e
    ignora rutas técnicas (plugins, imágenes, CSS…). `fetch(url) -> str|None`
    es inyectable para probar sin red."""
    host = urlparse(inicio).hostname
    paginas: dict[str, str] = {}
    vistos = {inicio}
    cola = deque([(inicio, 0)])
    while cola and len(paginas) < max_paginas:
        url, profundidad = cola.popleft()
        html_crudo = fetch(url)
        if not html_crudo:
            continue
        paginas[url] = html_crudo
        if profundidad >= max_profundidad:
            continue
        enlaces = [(u, t) for u, t in extraer_enlaces(html_crudo, url)
                   if urlparse(u).hostname == host and not es_ruta_tecnica(u)
                   and not urlparse(u).path.lower().endswith(".pdf")]
        for u, _t in sorted(enlaces, key=lambda x: -_puntos_enlace(x[0], x[1])):
            if u not in vistos:
                vistos.add(u)
                cola.append((u, profundidad + 1))
    return paginas


def urls_sitemap(fetch, raiz: str) -> list[str]:
    """robots.txt + sitemap.xml + wp-sitemap.xml del dominio."""
    base = raiz.rstrip("/")
    candidatas = []
    robots = fetch(base + "/robots.txt") or ""
    candidatas += re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots)
    candidatas += [base + "/sitemap.xml", base + "/wp-sitemap.xml"]
    urls = []
    for c in dict.fromkeys(candidatas):
        xml = fetch(c) or ""
        urls += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
    return list(dict.fromkeys(u for u in urls if not es_ruta_tecnica(u)))


def buscar_en_sitio_wp(fetch, raiz: str) -> list[str]:
    """Si es WordPress: /wp-json/wp/v2/pages?search=… Sin API de Muse."""
    urls = []
    for palabra in ("cabildo", "regidores", "organigrama", "gaceta", "presupuesto", "transparencia"):
        crudo = fetch(f"{raiz.rstrip('/')}/wp-json/wp/v2/pages?search={quote(palabra)}&per_page=20")
        try:
            for pagina in json.loads(crudo or "[]"):
                if pagina.get("link"):
                    urls.append(pagina["link"])
        except (ValueError, AttributeError):
            continue
    return list(dict.fromkeys(urls))


def candidatas_recorrido(paginas: dict[str, str], tipo: str) -> list[str]:
    """Páginas del recorrido (y PDF enlazados) que suenan al tipo de documento."""
    palabras = PALABRAS_TIPO[tipo]
    es_pdf_tipo = tipo in ("gaceta", "presupuesto", "contratos")
    puntos: dict[str, int] = {}

    def anota(url, n):
        if n > 0 and not es_ruta_tecnica(url):
            puntos[url] = max(puntos.get(url, 0), n)

    for url, html_crudo in paginas.items():
        texto = texto_plano(html_crudo)
        plano = municipios.sin_acentos(texto[:6000])
        if not es_pdf_tipo:
            # La URL manda (…/organigrama va antes que la portada, que también menciona cargos),
            # y una página que nombra regidores varias veces manda sobre la que solo nombra al presidente.
            anota(url, 3 * sum(p in municipios.sin_acentos(url) for p in palabras)
                  + (2 if sum(p in plano for p in palabras) >= 2 else 0)
                  + (min(plano.count("regidor"), 5) if tipo == "directorio" else 0))
        for destino, etiqueta in extraer_enlaces(html_crudo, url):
            if not (urlparse(destino).hostname == urlparse(url).hostname or es_gob_mx(destino)):
                continue
            plano_e = municipios.sin_acentos(destino + " " + etiqueta)
            n = sum(p in plano_e for p in palabras)
            if urlparse(destino).path.lower().endswith(".pdf"):
                if es_pdf_tipo:
                    anota(destino, n)
            elif not es_pdf_tipo:
                anota(destino, n)
    return sorted(puntos, key=lambda u: -puntos[u])


_CARGOS = ("presidente municipal", "presidenta municipal", "presidente", "presidenta", "sindico", "sindica",
           "regidor", "regidora", "regiduria", "secretario", "secretaria", "tesorero", "tesorera",
           "contralor", "contralora", "contraloria", "director general", "directora general",
           "direccion general", "consejeria", "coordinador", "coordinadora")
_NO_NOMBRE = {"regidurias", "gabinete", "presidencia", "direcciones", "coordinaciones", "municipio", "conoce"}


def _es_nombre(linea: str) -> bool:
    palabras = [p for p in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ.]+", linea) if p.lower() not in ("lic.", "mtro.", "ing.", "c.")]
    plano = municipios.sin_acentos(linea)
    return (2 <= len(palabras) <= 6 and "@" not in linea and len(linea) <= 60
            and not any(c in plano for c in _CARGOS) and bool(plano.split()) and plano.split()[0] not in _NO_NOMBRE
            and not any(p in plano for p in ("direccion", "secretaria", "tesoreria", "contraloria", "instituto", "sistema")))


def extraer_directorio_texto(texto: str, archivo: str) -> list[dict]:
    """Integrantes del Cabildo en el texto plano de una página, con cita verificada.

    Reconoce «Nombre / Cargo» en líneas vecinas y aplica el filtro de privacidad:
    solo correo del dominio oficial; el teléfono solo viaja con ese correo."""
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    textos = {1: extraer.normalizar(texto)}
    salida, vistos = [], set()
    for i, linea in enumerate(lineas):
        plano = municipios.sin_acentos(linea)
        if not any(plano == c or plano.startswith(c + " ") or plano.startswith(c + " de") for c in _CARGOS):
            continue
        cargo = linea
        nombre = next((lineas[j] for j in (i - 1, i + 1, i - 2, i + 2)
                       if 0 <= j < len(lineas) and _es_nombre(lineas[j])), None)
        # Sin títulos (Lic., Ing.…): la misma persona no se duplica por su tratamiento.
        clave_persona = re.sub(r"^(lic|mtro|ing|dra|dr)\.?\s+", "", municipios.sin_acentos(nombre or ""))
        if not nombre or clave_persona in vistos:
            continue
        vistos.add(clave_persona)
        correo = telefono = None
        for vecina in lineas[i + 1:i + 5]:
            if _es_nombre(vecina) or any(municipios.sin_acentos(vecina).startswith(c) for c in _CARGOS):
                break  # empezó la siguiente persona: su contacto no es de esta
            m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", vecina)
            if m and correo is None:
                correo = m.group(0)
            digitos = re.sub(r"\D", "", vecina)
            if len(digitos) == 10 and telefono is None and "@" not in vecina:
                telefono = digitos
        pagina, verif = extraer.verificar(f"{nombre} {cargo}", textos, 1)
        fila = filtrar_contacto({"nombre": nombre, "cargo": cargo, "comision": None,
                                 "correo": correo, "telefono": telefono, "direccion": None,
                                 "archivo": archivo, "pagina": pagina,
                                 "fragmento": f"{nombre} {cargo}", "verificacion": verif},
                                set(re.findall(r"@([\w.-]+\.gob\.mx)", texto.lower())))
        salida.append(fila)
    return [f for f in salida if f["verificacion"] == "ok"]


def anotar_camino(registro: dict, tipo: str, camino: str):
    registro.setdefault(tipo, [])
    if camino not in registro[tipo]:
        registro[tipo].append(camino)


def registrar_no_encontrado(con, clave: str, tipo: str, registro: dict) -> bool:
    """Solo dice «no encontré» tras probar TODOS los caminos; si faltan, lo dice y vuelve False."""
    probados = [c for c in CAMINOS_AGOTAMIENTO if c in registro.get(tipo, [])]
    faltan = [c for c in CAMINOS_AGOTAMIENTO if c not in probados]
    if faltan:
        municipios.registrar_evento(
            con, clave, tipo,
            f"Todavía no puedo decir que no está {TIPOS_DOC[tipo]}: faltan caminos por probar ({', '.join(faltan)}).")
        return False
    municipios.registrar_evento(
        con, clave, tipo,
        f"No encontré {TIPOS_DOC[tipo]}. Probé {len(probados)} caminos para {tipo}: "
        f"{', '.join(probados)}. No apareció; no invento la fuente.")
    return True



def _gastos() -> list[dict]:
    if not llm.LOG_COSTOS.exists():
        return []
    return [json.loads(l) for l in llm.LOG_COSTOS.read_text().splitlines() if l.strip()]


def verificar_topes(inicio: str):
    """Lanza TopeAlcanzado si esta corrida ya gastó $1.00 o si hoy ya se gastaron $5.00."""
    gastos = _gastos()
    hoy = datetime.now(timezone.utc).date().isoformat()
    del_municipio = sum(g["usd"] for g in gastos if g["ts"] >= inicio)
    del_dia = sum(g["usd"] for g in gastos if g["ts"][:10] == hoy)
    if del_municipio >= TOPE_MUNICIPIO:
        raise TopeAlcanzado(f"Tope por municipio alcanzado: ${del_municipio:.2f} de ${TOPE_MUNICIPIO:.2f}. Me detengo.")
    if del_dia >= TOPE_DIA:
        raise TopeAlcanzado(f"Tope diario alcanzado: ${del_dia:.2f} de ${TOPE_DIA:.2f}. Me detengo.")


def urls_de_respuesta(resp: dict) -> list[tuple[str, str]]:
    """URLs candidatas de una respuesta con búsqueda: resultados, páginas abiertas y el texto final."""
    candidatas = []
    for item in resp.get("output", []):
        if item.get("type") == "web_search_call":
            for r in item.get("results") or []:
                if r.get("url"):
                    candidatas.append((r["url"], (r.get("title", "") + " " + (r.get("snippet") or "")).strip()))
            if (item.get("action") or {}).get("url"):
                candidatas.append((item["action"]["url"], ""))
        if item.get("type") == "message":
            for c in item.get("content", []):
                for a in c.get("annotations", []):
                    if a.get("url"):
                        candidatas.append((a["url"], a.get("title", "")))
                candidatas += [(u, "") for u in re.findall(r"https?://[^\s\]\)\"']+", c.get("text", ""))]
    return candidatas


def elegir_candidatas(candidatas: list[tuple[str, str]], palabras: list[str], pdf: bool = False,
                      nombre: str = "") -> list[str]:
    """URLs .gob.mx ordenadas: más palabras clave primero y, a igualdad, las que mencionan al municipio.

    La búsqueda confunde municipios (Cuernavaca con Zihuatanejo): por eso se devuelve la
    lista entera y el llamador prueba una por una hasta que el documento sí mencione al
    municipio, en vez de quedarse con la primera."""
    vistas = {}
    for url, titulo in candidatas:
        if not es_gob_mx(url):
            continue
        if pdf and ".pdf" not in urlparse(url).path.lower():
            continue
        texto = (url + " " + titulo).lower()
        puntos = sum(p in texto for p in palabras) + (3 if nombre and menciona_municipio(texto, nombre) else 0)
        if nombre:  # el dominio propio del municipio pesa más que cualquier palabra clave suelta
            palabras_n = [p for p in municipios.sin_acentos(nombre).split() if len(p) >= 4]
            if palabras_n and max(palabras_n, key=len) in (urlparse(url).hostname or ""):
                puntos += 5
        vistas[url] = max(vistas.get(url, -1), puntos)
    buenas = sorted((u for u, n in vistas.items() if n > 0), key=lambda u: -vistas[u])
    return buenas


def elegir(candidatas: list[tuple[str, str]], palabras: list[str], pdf: bool = False,
           nombre: str = "") -> str | None:
    """La mejor URL .gob.mx de la lista ordenada; None si ninguna sirve."""
    ordenadas = elegir_candidatas(candidatas, palabras, pdf=pdf, nombre=nombre)
    return ordenadas[0] if ordenadas else None


def buscar(con, clave: str, inicio: str, paso: str, descripcion: str, consulta: str, palabras: list[str],
           pdf: bool = False, nombre: str = "") -> list[str]:
    """Busca y devuelve las URLs candidatas ordenadas (el llamador prueba hasta 3, una por una)."""
    municipios.registrar_evento(con, clave, paso, f"Buscando {descripcion}…")
    verificar_topes(inicio)
    resp = llm.llamar_responses_texto(
        f"indexar:{clave}:{paso}", model=llm.MODELO_PUBLICO, reasoning={"effort": "low"},
        input=(f"Busca en la web {descripcion}. Responde solo con la URL oficial (.gob.mx) más directa "
               f"al documento o página. Si no la encuentras, responde NO_ENCONTRADO. Búsqueda sugerida: {consulta}"),
        tools=[{"type": "web_search", "search_context_size": "medium"}],
        include=["web_search_call.results"])
    urls = elegir_candidatas(urls_de_respuesta(resp), palabras, pdf=pdf, nombre=nombre)
    # Sin «no encontré» aquí: eso solo se dice tras agotar todos los caminos
    # (registrar_no_encontrado), no tras una sola búsqueda web.
    return urls


def descargar(con, clave: str, tipo: str, url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (auditor-atlixco)"})
    with urllib.request.urlopen(req, timeout=120) as r:
        datos = r.read()
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", urlparse(url).path.rsplit("/", 1)[-1] or "pagina")
    if base.endswith(".aspx"):
        base = base[:-5] + ".html"
    if "." not in base:
        base += ".pdf" if datos.startswith(b"%PDF") else ".html"
    archivo = f"{clave}_{tipo}_{base}"
    if not datos.startswith(b"%PDF") and b"<html" not in datos[:2000].lower():
        raise ValueError(f"{url} no devolvió un PDF ni una página HTML")
    extraer.RAW.mkdir(parents=True, exist_ok=True)
    (extraer.RAW / archivo).write_bytes(datos)
    ruta_m = extraer.RAW / "manifiesto.json"
    manifiesto = [m for m in json.loads(ruta_m.read_text()) if m["archivo"] != archivo] if ruta_m.exists() else []
    manifiesto.append({"archivo": archivo, "url": url,
                       "sha256": hashlib.sha256(datos).hexdigest(), "bytes": len(datos),
                       "descargado": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    ruta_m.write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False))
    municipios.registrar_evento(con, clave, "descarga", f"Descargué {archivo} ({len(datos) // 1024} KB) desde {url}")
    return archivo


def menciona_municipio(texto: str, nombre: str) -> bool:
    """Un .gob.mx puede ser de OTRO municipio (la búsqueda confundió Cuetzalan del
    Progreso con Progreso, Yucatán): el documento debe mencionar al municipio."""
    palabras = [p for p in municipios.sin_acentos(nombre).split() if len(p) >= 4]
    if not palabras:
        return True
    return max(palabras, key=len) in municipios.sin_acentos(texto)


def _descartar(con, clave: str, archivo: str, nombre: str):
    (extraer.RAW / archivo).unlink(missing_ok=True)
    ruta_m = extraer.RAW / "manifiesto.json"
    if ruta_m.exists():
        ruta_m.write_text(json.dumps([m for m in json.loads(ruta_m.read_text()) if m["archivo"] != archivo],
                                     indent=2, ensure_ascii=False))
    municipios.registrar_evento(con, clave, "descartado",
                                f"El documento {archivo} no menciona a {nombre}; parece de otro municipio. Lo descarto y no guardo ninguno de sus datos.")
    raise ValueError(f"{archivo} no menciona a {nombre}")


def _marcar(con, clave: str, archivo: str, tabla_hija: str):
    """Asigna municipio_id al documento y a las filas extraídas de él."""
    con.execute("UPDATE documentos SET municipio_id = ? WHERE archivo = ?", (clave, archivo))
    con.execute(f"""UPDATE {tabla_hija} SET municipio_id = ? WHERE documento_id =
                    (SELECT id FROM documentos WHERE archivo = ?)""", (clave, archivo))
    con.commit()


def leer_pdf(con, clave: str, inicio: str, archivo: str, tipo: str, nombre: str) -> tuple[int, int]:
    """Corre el extractor que toca según el tipo; devuelve (citas ok, citas totales) guardadas."""
    from pypdf import PdfReader
    reader = PdfReader(extraer.RAW / archivo)
    portada = "".join((p.extract_text() or "") for p in reader.pages[:3])
    if not menciona_municipio(portada, nombre):
        _descartar(con, clave, archivo, nombre)
    total = len(reader.pages)
    fin = min(total, MAX_PAGINAS_PDF)
    if fin < total:
        municipios.registrar_evento(con, clave, "lectura",
                                    f"El documento tiene {total} páginas; en esta primera pasada leo las primeras {fin}.")
    filas, modulo, hija = [], (presupuesto if tipo == "presupuesto" else extraer), ("partidas" if tipo == "presupuesto" else "acuerdos")
    for i in range(1, fin + 1, extraer.TRAMO):
        verificar_topes(inicio)
        tope = min(i + extraer.TRAMO - 1, fin)
        municipios.registrar_evento(con, clave, "lectura", f"Leyendo las páginas {i} a {tope} de {total}…")
        filas += modulo.extraer_tramo(archivo, reader, i, tope)
    if tipo == "presupuesto":
        presupuesto.guardar(con, archivo, total, filas, (1, fin))
    else:
        extraer.guardar(con, archivo, total, filas, (1, fin))
    _marcar(con, clave, archivo, hija)
    ok = sum(f["verificacion"] == "ok" for f in filas)
    municipios.registrar_evento(con, clave, "verificacion",
                                f"Verifiqué {ok} de {len(filas)} citas de {archivo} contra el texto de su página.")
    return ok, len(filas)


def leer_directorio(con, clave: str, inicio: str, archivo: str, nombre: str, estado: str,
                    dominios=()) -> tuple[int, int]:
    verificar_topes(inicio)
    municipios.registrar_evento(con, clave, "lectura", f"Leyendo el directorio de cabildo ({archivo})…")
    if archivo.endswith(".pdf"):
        from pypdf import PdfReader
        portada = "".join((p.extract_text() or "") for p in PdfReader(extraer.RAW / archivo).pages[:3])
    else:
        portada = gobierno.texto_html(archivo)
    if not menciona_municipio(portada, nombre):
        _descartar(con, clave, archivo, nombre)
    # Primero el extractor sin API (nombre + cargo en líneas vecinas); solo si no
    # encuentra a nadie se le pide a Muse que extraiga de la misma página.
    datos = [] if archivo.endswith(".pdf") else extraer_directorio_texto(portada, archivo)
    if not datos:
        instrucciones = gobierno.BASE.replace("del Ayuntamiento de Atlixco, Puebla",
                                              f"del Ayuntamiento de {nombre}, {estado}") + \
            "\nLista a cada integrante del Cabildo: nombre, cargo tal como viene y su comisión temática si la página la indica." \
            "\nContacto solo institucional: correo únicamente si es del dominio oficial, teléfono y dirección de oficina; " \
            "nunca correos personales (gmail, hotmail, yahoo…) ni celulares personales: en esos casos null."
        if archivo.endswith(".pdf"):
            from pypdf import PdfReader
            datos = gobierno._de_pdf(archivo, (1, min(10, len(PdfReader(extraer.RAW / archivo).pages))),
                                     instrucciones, gobierno.ESQ_FUNCIONARIOS, "funcionarios", "funcionarios")
        else:
            datos = gobierno._de_html(archivo, instrucciones, gobierno.ESQ_FUNCIONARIOS, "funcionarios", "funcionarios")
    datos = [filtrar_contacto(f, dominios) for f in datos]  # privacidad, también sobre lo que devuelva Muse
    con.execute("DELETE FROM funcionarios WHERE archivo = ? AND municipio_id = ?", (archivo, clave))
    con.executemany("""INSERT INTO funcionarios (nombre, cargo, comision, correo, telefono, direccion,
                       archivo, pagina, fragmento, verificacion, municipio_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(f["nombre"], f["cargo"], f["comision"], f.get("correo"), f.get("telefono"),
                      f.get("direccion"), f["archivo"], f["pagina"], f["fragmento"],
                      f["verificacion"], clave) for f in datos])
    con.commit()
    ok = sum(f["verificacion"] == "ok" for f in datos)
    municipios.registrar_evento(con, clave, "verificacion",
                                f"Verifiqué {ok} de {len(datos)} citas del directorio contra el texto de la página.")
    return ok, len(datos)


def indexar(clave: str) -> int:
    with extraer.conectar(), presupuesto.conectar(), gobierno.conectar():
        pass  # asegura todas las tablas antes de que municipios agregue municipio_id
    con = municipios.conectar()
    fila = con.execute("SELECT * FROM municipios WHERE clave_inegi = ?", (clave,)).fetchone()
    if not fila:
        print(f"Municipio {clave} no está en el catálogo.", file=sys.stderr)
        return 2
    _, estado, nombre, estado_idx = fila
    if estado_idx != "indexando":
        print(f"{nombre}: estado_indexacion = {estado_idx}; el agente solo corre tras una aprobación en /admin.",
              file=sys.stderr)
        return 2
    inicio = datetime.now(timezone.utc).isoformat(timespec="seconds")
    citas_ok = citas_total = fuentes_ok = 0
    registro = {tipo: [] for tipo in TIPOS_DOC}
    try:
        municipios.registrar_evento(con, clave, "inicio",
                                    f"Empiezo a revisar {nombre}, {estado}. Solo uso fuentes oficiales .gob.mx "
                                    "y cada dato que guarde llevará su cita.")
        # 1) Dominio oficial: variantes comunes y búsqueda web; solo se acepta si
        #    su página de inicio nombra al municipio. Se guardan todos (principal
        #    y portal de transparencia) en el evento, visibles en /indexando.
        dominios: set[str] = set()

        def confirma(url_raiz: str) -> bool:
            html_crudo = obtener(url_raiz)
            host = urlparse(url_raiz).hostname or ""
            if html_crudo and host and menciona_municipio(texto_plano(html_crudo), nombre):
                dominios.add(host)
                return True
            return False

        for variante in variantes_dominio(nombre, estado):
            confirma(f"https://{variante}/")
        candidatas_portal = buscar(con, clave, inicio, "portal", f"el portal de transparencia de {nombre}, {estado}",
                                   f"portal de transparencia Ayuntamiento de {nombre} {estado} sitio gob.mx",
                                   ["transparencia"], nombre=nombre)
        for url in candidatas_portal:
            p = urlparse(url)
            if p.hostname and p.hostname not in dominios:
                confirma(f"{p.scheme}://{p.netloc}/")
        if dominios:
            municipios.registrar_evento(con, clave, "dominio",
                                        f"Dominios oficiales confirmados de {nombre} (su página de inicio lo nombra): "
                                        f"{', '.join(sorted(dominios))}. Los guardo para esta revisión.")
        else:
            municipios.registrar_evento(con, clave, "dominio",
                                        f"No confirmé el dominio oficial de {nombre} probando variantes ni con la "
                                        "búsqueda del portal; sigo con búsqueda web y fuentes estatales.")
        principal = next((d for d in sorted(dominios) if "transparencia" not in d), None) \
            or next(iter(sorted(dominios)), None)
        raiz = f"https://{principal}" if principal else ""

        # 2) Recorrido del sitio oficial, sin API: sitemap, WP-JSON, menú y BFS.
        paginas: dict[str, str] = {}
        pool: dict[str, list[str]] = {tipo: [] for tipo in TIPOS_DOC}
        if raiz:
            del_sitemap = urls_sitemap(obtener, raiz)
            de_wp = buscar_en_sitio_wp(obtener, raiz)
            for tipo in TIPOS_DOC:
                anotar_camino(registro, tipo, "sitemap")
                anotar_camino(registro, tipo, "búsqueda en el sitio")
            municipios.registrar_evento(con, clave, "recorrido",
                                        f"Revisé robots.txt y los sitemaps de {raiz}: {len(del_sitemap)} direcciones; "
                                        f"la búsqueda interna del sitio devolvió {len(de_wp)} páginas.")
            paginas = recorrer_sitio(obtener, raiz + "/")
            for tipo in TIPOS_DOC:
                anotar_camino(registro, tipo, "menú del sitio")
                anotar_camino(registro, tipo, "recorrido del sitio")
                pool[tipo] = list(dict.fromkeys(
                    candidatas_recorrido(paginas, tipo)
                    + [u for u in de_wp + del_sitemap
                       if any(p in municipios.sin_acentos(u) for p in PALABRAS_TIPO[tipo])]))
            municipios.registrar_evento(con, clave, "recorrido",
                                        f"Recorrí el sitio oficial: {len(paginas)} páginas (profundidad máximo "
                                        f"{MAX_PROFUNDIDAD}, tope {MAX_PAGINAS_RECORRIDO}), ignorando rutas técnicas "
                                        "como wp-content/plugins. De ahí salen las primeras candidatas de cada documento.")
        else:
            for tipo in TIPOS_DOC:  # sin sitio no hay menú que recorrer: caminos intentados y fallidos
                for camino in CAMINOS_AGOTAMIENTO[:4]:
                    anotar_camino(registro, tipo, camino)

        def intentar(tipo: str, urls: list[str]) -> tuple[int, int] | None:
            """Prueba candidatas: descarta SIN descargar las de otro municipio."""
            nonlocal citas_ok, citas_total, fuentes_ok
            for url in list(dict.fromkeys(urls))[:MAX_INTENTOS]:
                if not dominio_permitido(url, nombre, estado, dominios):
                    municipios.registrar_evento(con, clave, "descartado",
                                                f"Descarté sin descargar {url}: su dominio no es el oficial de "
                                                f"{nombre} ni una fuente estatal o federal oficial.")
                    continue
                if es_ruta_tecnica(url):
                    continue
                try:
                    archivo = descargar(con, clave, tipo, url)
                    if tipo == "directorio":
                        ok, total = leer_directorio(con, clave, inicio, archivo, nombre, estado, dominios)
                    else:
                        ok, total = leer_pdf(con, clave, inicio, archivo,
                                             "presupuesto" if tipo == "presupuesto" else "gaceta", nombre)
                except TopeAlcanzado:
                    raise
                except Exception as e:
                    municipios.registrar_evento(con, clave, tipo, f"No pude leer {url}: {e}. Pruebo la siguiente candidata.")
                    continue
                municipios.registrar_evento(con, clave, tipo, f"Encontré {TIPOS_DOC[tipo]} de {nombre}: {url}")
                citas_ok, citas_total = citas_ok + ok, citas_total + total
                fuentes_ok += 1
                return ok, total
            return None

        def buscar_y_probar(tipo: str, camino: str, consultas: list[tuple[str, bool]]) -> bool:
            anotar_camino(registro, tipo, camino)
            for consulta, es_pdf in consultas:
                urls = buscar(con, clave, inicio, tipo, f"{TIPOS_DOC[tipo]} de {nombre}",
                              consulta, PALABRAS_TIPO[tipo], pdf=es_pdf, nombre=nombre)
                if intentar(tipo, urls):
                    return True
            return False

        for tipo in ("directorio", "gaceta", "presupuesto"):
            if intentar(tipo, pool[tipo]):
                continue
            # 3) Búsquedas dentro del dominio propio, con sinónimos.
            encontrado = False
            for dominio in sorted(dominios):
                if buscar_y_probar(tipo, "búsqueda web en el dominio propio",
                                   [(f"site:{dominio} {s} {nombre} {estado}", tipo != "directorio")
                                    for s in SINONIMOS[tipo][:3]]):
                    encontrado = True
                    break
            if encontrado:
                continue
            if not dominios:
                anotar_camino(registro, tipo, "búsqueda web en el dominio propio")
            # Búsqueda web general (filtrada antes de descargar) y fuentes estatales:
            # periódico oficial del estado, transparencia estatal y congreso local.
            if buscar_y_probar(tipo, "búsqueda web",
                               [(f'{TIPOS_DOC[tipo]} del Ayuntamiento de "{nombre}", {estado} '
                                 + ("filetype:pdf" if tipo != "directorio" else "presidente municipal y regidores"),
                                 tipo != "directorio")]):
                continue
            buscar_y_probar(tipo, "fuentes estatales oficiales",
                            [(f'"{nombre}" {s} periódico oficial {estado} gob.mx', tipo != "directorio")
                             for s in SINONIMOS[tipo][:2]]
                            + [(f'"{nombre}" {TIPOS_DOC[tipo]} transparencia {estado} congreso gob.mx',
                                tipo != "directorio")])
            registrar_no_encontrado(con, clave, tipo, registro)
        # Contratos u obra pública: no hay extractor propio; se agotan los caminos
        # y, si aparece una candidata permitida, queda registrada sin inventar datos.
        tipo = "contratos"
        candidatas_c = [u for u in pool[tipo] if dominio_permitido(u, nombre, estado, dominios)]
        if candidatas_c:
            municipios.registrar_evento(con, clave, tipo,
                                        f"En el recorrido aparecieron candidatas de contratos u obra pública de {nombre}: "
                                        f"{candidatas_c[0]}. Queda registrada para lectura; no guardo datos sin leerla.")
        else:
            encontrado = False
            for dominio in sorted(dominios):
                anotar_camino(registro, tipo, "búsqueda web en el dominio propio")
                urls = []
                for s in SINONIMOS[tipo]:
                    urls += buscar(con, clave, inicio, tipo, f"contratos u obra pública de {nombre}",
                                   f"site:{dominio} {s} {nombre}", PALABRAS_TIPO[tipo], nombre=nombre)
                if any(dominio_permitido(u, nombre, estado, dominios) for u in urls):
                    encontrado = True
                    break
            if not encontrado:
                for camino, consultas in (
                        ("búsqueda web", [f'licitaciones contratos obra pública Ayuntamiento "{nombre}", {estado} gob.mx']),
                        ("fuentes estatales oficiales",
                         [f'"{nombre}" licitaciones contratos periódico oficial {estado} gob.mx'])):
                    anotar_camino(registro, tipo, camino)
                    urls = buscar(con, clave, inicio, tipo, f"contratos u obra pública de {nombre}",
                                  consultas[0], PALABRAS_TIPO[tipo], nombre=nombre)
                    permitidas = [u for u in urls if dominio_permitido(u, nombre, estado, dominios)]
                    if permitidas:
                        municipios.registrar_evento(con, clave, tipo,
                                                    f"Apareció una candidata de contratos u obra pública de {nombre}: "
                                                    f"{permitidas[0]}. Queda registrada para lectura; no guardo datos sin leerla.")
                        encontrado = True
                        break
            if not encontrado:
                registrar_no_encontrado(con, clave, tipo, registro)
    except TopeAlcanzado as e:
        municipios.registrar_evento(con, clave, "tope", str(e))
        con.execute("UPDATE municipios SET estado_indexacion = 'error' WHERE clave_inegi = ?", (clave,))
        con.commit()
        print(str(e), file=sys.stderr)
        return 1
    exito = citas_total > 0
    con.execute("UPDATE municipios SET estado_indexacion = ? WHERE clave_inegi = ?",
                ("indexado" if exito else "error", clave))
    con.commit()
    gasto = sum(g["usd"] for g in _gastos() if g["ts"] >= inicio)
    municipios.registrar_evento(
        con, clave, "fin",
        (f"Terminé. Fuentes encontradas y leídas: {fuentes_ok}. Citas verificadas: {citas_ok} de {citas_total}. "
         f"Gasto de esta revisión: ${gasto:.4f} USD." if exito else
         "No logré leer ningún documento con citas verificables. Lo dejo marcado para revisión manual; no inventé datos."))
    print(f"{nombre}: {'indexado' if exito else 'sin datos'}, {citas_ok}/{citas_total} citas, ${gasto:.4f}")
    return 0 if exito else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: indexar.py <clave_inegi>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(indexar(sys.argv[1]))
