"""Genera auditor/static/mapa-mexico.svg desde Natural Earth (dominio público).

Uso único, fuera de la app (la app nunca descarga el mapa al navegar):
    .venv/bin/python scripts/generar_mapa.py

Descarga ne_10m_admin_1_states_provinces (estados), filtra México, simplifica
cada anillo con Douglas-Peucker y proyecta (equirectangular corregida por
coseno) a un viewBox fijo. Cada estado queda como una línea:
<path data-estado="Puebla" d="M…L…Z"><title>Puebla</title></path>
y la raíz guarda data-proy="lon0,lat1,escala,cos,ox,oy" para que web.py
ubique las cabeceras municipales con la misma proyección.
"""
import io
import math
import struct
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip"
DESTINO = Path(__file__).resolve().parent.parent / "auditor" / "static" / "mapa-mexico.svg"
ANCHO, ALTO, TOL = 720, 460, 0.045  # tolerancia de simplificación en grados
NOMBRES = {"Distrito Federal": "Ciudad de México"}


def leer_dbf(datos: bytes) -> list[dict]:
    nrec, hlen = struct.unpack_from("<IH", datos, 4)
    campos, off = [], 32
    while datos[off] != 0x0D:
        campos.append((datos[off:off + 11].split(b"\x00")[0].decode(), datos[off + 16]))
        off += 32
    filas, rlen = [], 1 + sum(l for _, l in campos)
    for i in range(nrec):
        reg, vals, p = datos[hlen + i * rlen: hlen + (i + 1) * rlen], {}, 1
        for nombre, largo in campos:
            vals[nombre] = reg[p:p + largo].decode("utf-8", "replace").strip("\x00 ").strip()
            p += largo
        filas.append(vals)
    return filas


def leer_shp(datos: bytes) -> list[list[list[tuple]]]:
    poligonos, off = [], 100
    while off < len(datos):
        largo = struct.unpack_from(">i", datos, off + 4)[0] * 2
        cuerpo = datos[off + 8: off + 8 + largo]
        off += 8 + largo
        if struct.unpack_from("<i", cuerpo, 0)[0] != 5:  # solo polígonos
            continue
        npartes, npuntos = struct.unpack_from("<ii", cuerpo, 36)
        cortes = struct.unpack_from(f"<{npartes}i", cuerpo, 44)
        pts = struct.unpack_from(f"<{npuntos * 2}d", cuerpo, 44 + 4 * npartes)
        puntos = [(pts[i], pts[i + 1]) for i in range(0, len(pts), 2)]
        anillos, limites = [], list(cortes) + [npuntos]
        for a, b in zip(limites, limites[1:]):
            anillos.append(puntos[a:b])
        poligonos.append(anillos)
    return poligonos


def _dist(p, a, b) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    t = 0 if dx == dy == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def simplificar(anillo: list[tuple], tol: float = TOL) -> list[tuple]:
    if len(anillo) < 4:
        return anillo
    queda = [False] * len(anillo)
    queda[0] = queda[-1] = True
    pila = [(0, len(anillo) - 1)]
    while pila:
        a, b = pila.pop()
        dmax, imax = tol, -1
        for i in range(a + 1, b):
            d = _dist(anillo[i], anillo[a], anillo[b])
            if d > dmax:
                dmax, imax = d, i
        if imax > 0:
            queda[imax] = True
            pila += [(a, imax), (imax, b)]
    return [p for p, k in zip(anillo, queda) if k]


def main() -> None:
    with urllib.request.urlopen(URL, timeout=120) as r:  # script único: sí usa red, la app no
        z = zipfile.ZipFile(io.BytesIO(r.read()))
    nombres = z.namelist()
    filas = leer_dbf(z.read(next(n for n in nombres if n.endswith(".dbf"))))
    formas = leer_shp(z.read(next(n for n in nombres if n.endswith(".shp"))))
    estados = []
    for fila, anillos in zip(filas, formas):
        nombre = NOMBRES.get(fila.get("name", ""), fila.get("name", ""))
        if fila.get("iso_a2") == "MX" and nombre:
            estados.append((nombre, [simplificar(a) for a in anillos]))
    todos = [p for _, anillos in estados for a in anillos for p in a]
    lon0, lon1 = min(p[0] for p in todos), max(p[0] for p in todos)
    lat0, lat1 = min(p[1] for p in todos), max(p[1] for p in todos)
    coseno = math.cos(math.radians(23.5))
    escala = min(ANCHO / ((lon1 - lon0) * coseno), ALTO / (lat1 - lat0))
    ox, oy = (ANCHO - (lon1 - lon0) * coseno * escala) / 2, (ALTO - (lat1 - lat0) * escala) / 2

    def xy(lon: float, lat: float) -> tuple[float, float]:
        return ox + (lon - lon0) * coseno * escala, oy + (lat1 - lat) * escala

    lineas = []
    for nombre, anillos in sorted(estados):
        d = ""
        for anillo in anillos:
            pts = [xy(*p) for p in anillo]
            if len(pts) >= 3:
                d += "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z"
        lineas.append(f'<path data-estado="{nombre}" d="{d}"><title>{nombre}</title></path>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ANCHO} {ALTO}" '
           f'data-proy="{lon0:.4f},{lat1:.4f},{escala:.4f},{coseno:.6f},{ox:.2f},{oy:.2f}" '
           f'role="img" aria-label="Mapa de México por estado">\n' + "\n".join(lineas) + "\n</svg>\n")
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(svg, encoding="utf-8")
    print(f"{len(estados)} estados -> {DESTINO} ({DESTINO.stat().st_size / 1024:.1f} KB)")
    if DESTINO.stat().st_size > 80 * 1024:
        sys.exit("El SVG pasa de 80 KB: sube TOL en este script y vuelve a correrlo.")


if __name__ == "__main__":
    main()
