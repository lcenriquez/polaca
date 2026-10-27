"""Agente indexador: lleva el auditor a un municipio nuevo, solo tras aprobación humana.

Uso: ../.venv/bin/python indexar.py <clave_inegi>    (lo lanza web.py al aprobar en /admin)

Con Muse Spark (llm.MODELO_PUBLICO) y búsqueda web (Responses API, el único
API de Meta con web_search) busca SOLO en dominios .gob.mx el portal de
transparencia, la gaceta más reciente, el presupuesto de egresos y el directorio
de cabildo del municipio. Descarga lo encontrado a datos/raw/ y corre los
extractores existentes (extraer.py, presupuesto.py, gobierno.py) con las
mismas citas y verificaciones. Cada paso queda en eventos_indexacion, que la
página /indexando/<clave> muestra en vivo por SSE. Si una fuente no aparece,
lo dice y no la inventa.

Topes de gasto: $1.00 por municipio y $5.00 por día (leídos de costos.jsonl,
que llm.py escribe en cada llamada). Al llegar al tope se detiene y lo reporta.
"""
import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import extraer
import gobierno
import llm
import municipios
import presupuesto

TOPE_MUNICIPIO = 1.00
TOPE_DIA = 5.00
MAX_INTENTOS = 5  # candidatas por fuente: la búsqueda confunde municipios, se prueba hasta dar con el correcto
MAX_PAGINAS_PDF = 40  # ponytail: primera pasada acotada; subir si el tope de gasto lo permite


class TopeAlcanzado(Exception):
    pass


def es_gob_mx(url: str) -> bool:
    """Solo dominios oficiales: el host es gob.mx o termina en .gob.mx."""
    host = (urlparse(url).hostname or "").lower()
    return host == "gob.mx" or host.endswith(".gob.mx")


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
    if not urls:
        municipios.registrar_evento(con, clave, paso,
                                    f"No encontré {descripcion} en un sitio .gob.mx. Lo dejo pendiente; no invento la fuente.")
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


def leer_directorio(con, clave: str, inicio: str, archivo: str, nombre: str, estado: str) -> tuple[int, int]:
    verificar_topes(inicio)
    municipios.registrar_evento(con, clave, "lectura", f"Leyendo el directorio de cabildo ({archivo})…")
    if archivo.endswith(".pdf"):
        from pypdf import PdfReader
        portada = "".join((p.extract_text() or "") for p in PdfReader(extraer.RAW / archivo).pages[:3])
    else:
        portada = gobierno.texto_html(archivo)
    if not menciona_municipio(portada, nombre):
        _descartar(con, clave, archivo, nombre)
    instrucciones = gobierno.BASE.replace("del Ayuntamiento de Atlixco, Puebla",
                                          f"del Ayuntamiento de {nombre}, {estado}") + \
        "\nLista a cada integrante del Cabildo: nombre, cargo tal como viene y su comisión temática si la página la indica."
    if archivo.endswith(".pdf"):
        from pypdf import PdfReader
        datos = gobierno._de_pdf(archivo, (1, min(10, len(PdfReader(extraer.RAW / archivo).pages))),
                                 instrucciones, gobierno.ESQ_FUNCIONARIOS, "funcionarios", "funcionarios")
    else:
        datos = gobierno._de_html(archivo, instrucciones, gobierno.ESQ_FUNCIONARIOS, "funcionarios", "funcionarios")
    con.execute("DELETE FROM funcionarios WHERE archivo = ? AND municipio_id = ?", (archivo, clave))
    con.executemany("""INSERT INTO funcionarios (nombre, cargo, comision, archivo, pagina, fragmento, verificacion, municipio_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(f["nombre"], f["cargo"], f["comision"], f["archivo"], f["pagina"], f["fragmento"],
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
    try:
        municipios.registrar_evento(con, clave, "inicio",
                                    f"Empiezo a revisar {nombre}, {estado}. Solo uso fuentes oficiales .gob.mx "
                                    "y cada dato que guarde llevará su cita.")
        candidatas = buscar(con, clave, inicio, "portal", f"el portal de transparencia de {nombre}, {estado}",
                            f"portal de transparencia Ayuntamiento de {nombre} {estado} sitio gob.mx",
                            ["transparencia"], nombre=nombre)
        if candidatas:
            portal = candidatas[0]
            fuentes_ok += 1
            municipios.registrar_evento(con, clave, "portal",
                                        f"Encontré el portal de transparencia de {nombre}, {estado}: {portal}")
            raiz = urlparse(portal)
            municipios.registrar_evento(con, clave, "portal",
                                        f"El sitio oficial es {raiz.scheme}://{raiz.netloc}; de ahí salen las demás búsquedas.")
        host_oficial = urlparse(candidatas[0]).netloc if candidatas else ""
        for tipo, descripcion, palabras, modulo in (
                ("gaceta", f"la gaceta municipal más reciente de {nombre}", ["gaceta"], "gaceta"),
                ("presupuesto", f"el presupuesto de egresos de {nombre}", ["presupuesto", "egresos"], "presupuesto")):
            urls = buscar(con, clave, inicio, tipo, descripcion,
                          f'{descripcion} del Ayuntamiento de "{nombre}", {estado} filetype:pdf'
                          + (f" publicado en {host_oficial}" if host_oficial else " gob.mx"),
                          palabras, pdf=True, nombre=nombre)
            for url in urls[:MAX_INTENTOS]:  # si el documento es de otro municipio, pruebo la siguiente candidata
                try:
                    archivo = descargar(con, clave, tipo, url)
                    ok, total = leer_pdf(con, clave, inicio, archivo, modulo, nombre)
                except TopeAlcanzado:
                    raise
                except Exception as e:
                    municipios.registrar_evento(con, clave, tipo, f"No pude leer {url}: {e}. Pruebo la siguiente candidata.")
                    continue
                municipios.registrar_evento(con, clave, tipo, f"Encontré {descripcion}: {url}")
                citas_ok, citas_total = citas_ok + ok, citas_total + total
                fuentes_ok += 1
                break
        descripcion = f"el directorio de cabildo de {nombre}"
        urls = buscar(con, clave, inicio, "directorio", descripcion,
                      f'directorio del Cabildo del Ayuntamiento de "{nombre}", {estado} presidente municipal '
                      'y regidores, en el sitio oficial del Ayuntamiento',
                      ["cabildo", "directorio", "integrantes"], nombre=nombre)
        for url in urls[:MAX_INTENTOS]:
            try:
                archivo = descargar(con, clave, "directorio", url)
                ok, total = leer_directorio(con, clave, inicio, archivo, nombre, estado)
            except TopeAlcanzado:
                raise
            except Exception as e:
                municipios.registrar_evento(con, clave, "directorio", f"No pude leer {url}: {e}. Pruebo la siguiente candidata.")
                continue
            municipios.registrar_evento(con, clave, "directorio", f"Encontré {descripcion}: {url}")
            citas_ok, citas_total = citas_ok + ok, citas_total + total
            fuentes_ok += 1
            break
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
