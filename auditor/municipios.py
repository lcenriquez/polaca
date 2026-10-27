"""Municipios de todo México: catálogo INEGI, solicitudes y eventos de indexación.

Uso: ../.venv/bin/python municipios.py    (desde auditor/)

Descarga el Catálogo Único de Claves de Áreas Geoestadísticas Estatales,
Municipales y Localidades de INEGI (una exportación oficial por entidad, en
datos/raw/) y lo carga a SQLite: municipios (clave INEGI de 5 dígitos) y
localidades con el nombre sin acentos para buscar tolerando acentos.
Atlixco es el primer municipio indexado; su clave se verifica contra el
catálogo (Puebla/Atlixco), no se supone. Las demás tablas ganan la columna
municipio_id y lo ya extraído se marca como Atlixco. Las juntas auxiliares
son propias de Puebla: quedan como autoridades locales opcionales (columna
tipo) y solo aparecen si el municipio las tiene.
"""
import hashlib
import json
import re
import sqlite3
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import extraer

URL_CATALOGO = ("https://www.inegi.org.mx/app/api/cateml/catuniAPI/EXPLOCAGEML/?nquery=4&entidad={ent}"
                "&busqueda=cve_ent={ent}&fecha=01/01/2016&forNom=3&ri=0&rf=100000&orden=0%20asc&union=0"
                "&type_=1&encodingType=utf8")
TABLAS_MUNICIPIO = ["documentos", "acuerdos", "partidas", "funcionarios", "comisiones", "funciones_cargo",
                    "juntas_auxiliares", "contacto_institucional", "evidencias", "hallazgos"]


def sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c)).lower()


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(extraer.DB)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS municipios (
            clave_inegi TEXT PRIMARY KEY, estado TEXT NOT NULL, nombre TEXT NOT NULL,
            estado_indexacion TEXT NOT NULL DEFAULT 'sin_revisar');
        CREATE TABLE IF NOT EXISTS localidades (
            clave_geo TEXT PRIMARY KEY, clave_mun TEXT NOT NULL, nom_loc TEXT NOT NULL,
            nom_mun TEXT NOT NULL, nom_ent TEXT NOT NULL, nombre_norm TEXT NOT NULL, mun_norm TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_loc_norm ON localidades(nombre_norm);
        CREATE TABLE IF NOT EXISTS solicitudes (
            id INTEGER PRIMARY KEY, clave_inegi TEXT NOT NULL, estado TEXT NOT NULL DEFAULT 'pendiente',
            creada TEXT NOT NULL, decidida TEXT, notas TEXT);
        CREATE TABLE IF NOT EXISTS eventos_indexacion (
            id INTEGER PRIMARY KEY, clave_inegi TEXT NOT NULL, ts TEXT NOT NULL, paso TEXT NOT NULL, mensaje TEXT NOT NULL);
    """)
    for tabla in TABLAS_MUNICIPIO:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({tabla})")]
        if cols and "municipio_id" not in cols:
            con.execute(f"ALTER TABLE {tabla} ADD COLUMN municipio_id TEXT")
    cols = [r[1] for r in con.execute("PRAGMA table_info(juntas_auxiliares)")]
    if cols and "tipo" not in cols:
        con.execute("ALTER TABLE juntas_auxiliares ADD COLUMN tipo TEXT DEFAULT 'junta auxiliar'")
    con.commit()
    return con


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def registrar_evento(con, clave: str, paso: str, mensaje: str):
    con.execute("INSERT INTO eventos_indexacion (clave_inegi, ts, paso, mensaje) VALUES (?, ?, ?, ?)",
                (clave, _ahora(), paso, mensaje))
    con.commit()


def sembrar_atlixco(con) -> str | None:
    """Primer municipio indexado: su clave sale del catálogo INEGI cargado, verificada por nombre."""
    fila = con.execute("SELECT DISTINCT clave_mun FROM localidades WHERE nom_ent = 'Puebla' AND nom_mun = 'Atlixco'").fetchone()
    if not fila:
        return None
    clave = fila[0]
    con.execute("""INSERT INTO municipios (clave_inegi, estado, nombre, estado_indexacion) VALUES (?, 'Puebla', 'Atlixco', 'indexado')
                   ON CONFLICT(clave_inegi) DO UPDATE SET estado_indexacion = 'indexado'""", (clave,))
    for tabla in TABLAS_MUNICIPIO:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({tabla})")]
        if "municipio_id" in cols:
            con.execute(f"UPDATE {tabla} SET municipio_id = ? WHERE municipio_id IS NULL", (clave,))
    con.commit()
    return clave


def descargar_catalogo() -> list[Path]:
    extraer.RAW.mkdir(parents=True, exist_ok=True)
    rutas = []
    for n in range(1, 33):
        ent = f"{n:02d}"
        destino = extraer.RAW / f"catalogo_inegi_{ent}.xlsx"
        if not destino.exists():
            url = URL_CATALOGO.format(ent=ent)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (auditor-atlixco)"})
            with urllib.request.urlopen(req, timeout=300) as r:
                datos = r.read()
            if not datos.startswith(b"PK"):
                raise ValueError(f"El catálogo de la entidad {ent} no devolvió un XLSX")
            destino.write_bytes(datos)
        rutas.append(destino)
    return rutas


def leer_xlsx(ruta: Path) -> list[dict]:
    """Lee la hoja 1 de la exportación oficial (XLSX con cadenas compartidas), sin dependencias nuevas."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(ruta) as z:
        compartidas = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")):
                compartidas.append("".join(t.text or "" for t in si.iter(ns + "t")))
        hoja = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    filas = []
    for fila in hoja.iter(ns + "row"):
        celdas = {}
        for c in fila.iter(ns + "c"):
            col = re.match(r"[A-Z]+", c.get("r", "A")).group(0)
            idx = 0
            for ch in col:
                idx = idx * 26 + ord(ch) - 64
            v = c.find(ns + "v")
            if c.get("t") == "s" and v is not None:
                valor = compartidas[int(v.text)]
            elif c.get("t") == "inlineStr":
                valor = "".join(t.text or "" for t in c.iter(ns + "t"))
            else:
                valor = v.text if v is not None else ""
            celdas[idx - 1] = valor or ""
        if celdas:
            filas.append([celdas.get(i, "") for i in range(max(celdas) + 1)])
    encabezado = next(i for i, f in enumerate(filas) if "CVEGEO" in f)
    cols = filas[encabezado]
    return [dict(zip(cols, f)) for f in filas[encabezado + 1:] if len(f) > 10 and f[cols.index("CVEGEO")]]


def cargar_catalogo(con, rutas: list[Path]) -> tuple[int, int]:
    con.execute("DELETE FROM localidades")
    total_loc = 0
    municipios = {}
    for ruta in rutas:
        filas = leer_xlsx(ruta)
        con.executemany(
            "INSERT OR IGNORE INTO localidades (clave_geo, clave_mun, nom_loc, nom_mun, nom_ent, nombre_norm, mun_norm) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(f["CVEGEO"], f["CVE_ENT"] + f["CVE_MUN"], f["NOM_LOC"], f["NOM_MUN"], f["NOM_ENT"],
              sin_acentos(f["NOM_LOC"]), sin_acentos(f["NOM_MUN"])) for f in filas])
        for f in filas:
            municipios[f["CVE_ENT"] + f["CVE_MUN"]] = (f["NOM_ENT"], f["NOM_MUN"])
        total_loc += len(filas)
        print(f"  {ruta.name}: {len(filas)} localidades")
    con.executemany(
        "INSERT INTO municipios (clave_inegi, estado, nombre, estado_indexacion) VALUES (?, ?, ?, 'sin_revisar') "
        "ON CONFLICT(clave_inegi) DO UPDATE SET estado = excluded.estado, nombre = excluded.nombre",
        [(c, e, n) for c, (e, n) in sorted(municipios.items())])
    con.commit()
    return total_loc, len(municipios)


def buscar_localidades(con, texto: str, limite: int = 20) -> list[dict]:
    q = sin_acentos(texto).strip()
    if len(q) < 3:
        return []
    con.row_factory = sqlite3.Row
    return [dict(f) for f in con.execute(
        """SELECT l.clave_geo, l.nom_loc, l.nom_mun, l.nom_ent, l.clave_mun, m.estado_indexacion
           FROM localidades l JOIN municipios m ON m.clave_inegi = l.clave_mun
           WHERE l.nombre_norm LIKE ? OR l.mun_norm LIKE ?
           ORDER BY (l.nombre_norm LIKE ?) DESC, l.nom_loc LIMIT ?""",
        (f"%{q}%", f"%{q}%", f"{q}%", limite))]


def main():
    rutas = descargar_catalogo()
    manifiesto_ruta = extraer.RAW / "manifiesto.json"
    manifiesto = json.loads(manifiesto_ruta.read_text()) if manifiesto_ruta.exists() else []
    conocidos = {m["archivo"] for m in manifiesto}
    for ruta in rutas:
        if ruta.name not in conocidos:
            manifiesto.append({"archivo": ruta.name,
                               "url": URL_CATALOGO.format(ent=ruta.name[-7:-5]),
                               "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest(),
                               "descargado": _ahora()})
    manifiesto_ruta.write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False))
    with conectar() as con:
        n_loc, n_mun = cargar_catalogo(con, rutas)
        clave = sembrar_atlixco(con)
    print(f"Catálogo INEGI: {n_loc} localidades, {n_mun} municipios.")
    print(f"Atlixco verificado en el catálogo: clave INEGI {clave}, estado_indexacion = indexado.")


if __name__ == "__main__":
    main()
