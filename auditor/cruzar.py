"""Cruza partidas del Presupuesto 2026 contra acuerdos_canonicos y genera hallazgos.

Uso: python auditor/cruzar.py

Un hallazgo es una discrepancia verificable entre las fuentes cargadas, con
descripción neutral y cita de ambas fuentes (archivo, página y fragmento).
Sin llamada a la API: la coincidencia textual reusa parecido() de extraer.py.

Reglas actuales:
- partida_sin_acuerdo_textual: partida con monto > 0 sin acuerdo canónico con
  coincidencia textual >= UMBRAL; se cita el acuerdo más cercano como referencia.
- acuerdo_supera_total_presupuestado: acuerdo canónico con monto mayor que la
  suma de las partidas; se cita la partida de mayor monto como referencia.

Punto de entrada para el Plan Municipal de Desarrollo 2024-2027: cruzar_pmd().
Esa fuente aún no está en datos/raw/, así que no genera ningún hallazgo.
"""
import sqlite3
from datetime import datetime, timezone

import presupuesto
from extraer import parecido

UMBRAL = 0.5  # ponytail: heurística de palabras de extraer.parecido; subir a cruce con Muse si da falsos positivos.
PMD_ARCHIVO = "PLAN_MUNICIPAL_DE_DESARROLLO_2024-2027.pdf"


def conectar() -> sqlite3.Connection:
    con = presupuesto.conectar()
    con.execute("""
        CREATE TABLE IF NOT EXISTS hallazgos (
            id INTEGER PRIMARY KEY,
            tipo TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            partida_id INTEGER REFERENCES partidas(id),
            acuerdo_id INTEGER REFERENCES acuerdos(id),
            archivo_presupuesto TEXT, pagina_presupuesto INTEGER, fragmento_presupuesto TEXT,
            archivo_acuerdo TEXT, pagina_acuerdo INTEGER, fragmento_acuerdo TEXT,
            creado TEXT NOT NULL
        )""")
    con.commit()
    return con


def _filas(con, sql):
    con.row_factory = sqlite3.Row
    return [dict(f) for f in con.execute(sql)]


def generar(con) -> list[dict]:
    """Devuelve los hallazgos (sin guardarlos) a partir de partidas y acuerdos_canonicos."""
    partidas = _filas(con, """SELECT p.*, d.archivo AS archivo FROM partidas p
                              JOIN documentos d ON d.id = p.documento_id ORDER BY p.monto_mxn DESC""")
    acuerdos = _filas(con, """SELECT a.*, d.archivo AS archivo FROM acuerdos_canonicos a
                              JOIN documentos d ON d.id = a.documento_id""")
    if not partidas or not acuerdos:
        return []
    total = sum(p["monto_mxn"] or 0 for p in partidas)
    mayor = partidas[0]
    hallazgos = []

    def cita(f, prefijo):
        return {f"archivo_{prefijo}": f["archivo"], f"pagina_{prefijo}": f["pagina"],
                f"fragmento_{prefijo}": f["fragmento"]}

    for p in partidas:
        if not p["monto_mxn"]:
            continue
        sim, cercano = max(((parecido(p["nombre"], a["acuerdo"]), a) for a in acuerdos), key=lambda x: x[0])
        if sim >= UMBRAL:
            continue
        hallazgos.append({
            "tipo": "partida_sin_acuerdo_textual",
            "descripcion": (f"La partida {p['capitulo'] or 'sin capítulo'} '{p['nombre']}' por ${p['monto_mxn']:,.2f} "
                            f"no tiene un acuerdo canónico con coincidencia textual de al menos {UMBRAL:.0%} "
                            f"entre los acuerdos registrados; el más cercano es '{cercano['acuerdo']}' ({sim:.0%}). "
                            "Esto solo indica ausencia de coincidencia textual en las fuentes cargadas."),
            "partida_id": p["id"], "acuerdo_id": cercano["id"],
            **cita(p, "presupuesto"), **cita(cercano, "acuerdo"),
        })
    for a in acuerdos:
        if a["monto_mxn"] is not None and total and a["monto_mxn"] > total:
            hallazgos.append({
                "tipo": "acuerdo_supera_total_presupuestado",
                "descripcion": (f"El acuerdo '{a['acuerdo']}' registra un monto de ${a['monto_mxn']:,.2f}, "
                                f"mayor que la suma de las partidas del Presupuesto 2026 (${total:,.2f}). "
                                "Verificar el alcance y el ejercicio fiscal de ambos datos en las fuentes citadas."),
                "partida_id": mayor["id"], "acuerdo_id": a["id"],
                **cita(mayor, "presupuesto"), **cita(a, "acuerdo"),
            })
    return hallazgos


def cruzar_pmd(con) -> list[dict]:
    """Cruce contra el Plan Municipal de Desarrollo 2024-2027 (pendiente: la fuente no está cargada)."""
    # Sin el PMD en datos/raw/ ni en documentos no hay dato que citar: no se inventa ningún hallazgo.
    # Cuando exista, extraer sus ejes/metas a una tabla propia y repetir el patrón de generar().
    cargado = con.execute("SELECT 1 FROM documentos WHERE archivo = ?", (PMD_ARCHIVO,)).fetchone()
    if not cargado:
        print(f"PMD 2024-2027 ({PMD_ARCHIVO}) aún no está en las fuentes; se omite su cruce.")
        return []
    print(f"PMD 2024-2027 detectado ({PMD_ARCHIVO}); falta implementar su extracción antes de cruzarlo.")
    return []


def guardar(con, hallazgos: list[dict]):
    con.execute("DELETE FROM hallazgos")
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.executemany("""INSERT INTO hallazgos (tipo, descripcion, partida_id, acuerdo_id, archivo_presupuesto,
                       pagina_presupuesto, fragmento_presupuesto, archivo_acuerdo, pagina_acuerdo,
                       fragmento_acuerdo, creado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(h["tipo"], h["descripcion"], h["partida_id"], h["acuerdo_id"], h["archivo_presupuesto"],
                      h["pagina_presupuesto"], h["fragmento_presupuesto"], h["archivo_acuerdo"],
                      h["pagina_acuerdo"], h["fragmento_acuerdo"], ahora) for h in hallazgos])
    con.commit()


def main():
    with conectar() as con:
        hallazgos = generar(con)
        guardar(con, hallazgos)
        cruzar_pmd(con)
    for h in hallazgos:
        print(f"- [{h['tipo']}] {h['descripcion']}")
    print(f"{len(hallazgos)} hallazgos → tabla hallazgos")


if __name__ == "__main__":
    main()
