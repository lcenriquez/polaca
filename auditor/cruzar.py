"""Cruza partidas del Presupuesto 2026 contra acuerdos_canonicos y genera hallazgos.

Uso: python auditor/cruzar.py

Un hallazgo es una discrepancia verificable: ambas fuentes hablan de lo mismo
(la partida aparece nombrada en el acuerdo, en los campos guardados en SQLite)
y difieren en un dato comparable (hoy, el monto; partidas no tiene fecha,
área ni proveedor). Sin dato comparable no hay hallazgo: se reporta la
cobertura y qué fuentes faltan para poder cruzar.

No se usa Muse para emparejar: la regla es determinística y las citas
(archivo, página y fragmento de cada fuente) salen de SQLite.

Punto de entrada para el Plan Municipal de Desarrollo 2024-2027: cruzar_pmd().
Esa fuente aún no está en datos/raw/, así que no genera ningún hallazgo.
"""
import re
import sqlite3
from datetime import datetime, timezone

import presupuesto
from extraer import plano

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


def _partidas(con):
    return _filas(con, """SELECT p.*, d.archivo AS archivo FROM partidas p
                          JOIN documentos d ON d.id = p.documento_id ORDER BY p.monto_mxn DESC""")


def _acuerdos(con):
    return _filas(con, """SELECT a.*, d.archivo AS archivo FROM acuerdos_canonicos a
                          JOIN documentos d ON d.id = a.documento_id""")


def _menciona(acuerdo: dict, partida: dict) -> bool:
    """¿El acuerdo nombra esta partida (nombre completo o 'capítulo NNNN') en el texto guardado en SQLite?"""
    texto = plano(f"{acuerdo['acuerdo']} {acuerdo['fragmento']}")
    if plano(partida["nombre"]) in texto:
        return True
    return bool(partida["capitulo"] and re.search(rf"capitulo\s*{partida['capitulo']}\b", texto))


def _pares(partidas, acuerdos) -> list[tuple[dict, dict]]:
    """Pares comparables: misma partida nombrada y monto registrado en ambas fuentes."""
    return [(p, a) for a in acuerdos if a["monto_mxn"] is not None
            for p in partidas if p["monto_mxn"] is not None and _menciona(a, p)]


def generar(con) -> list[dict]:
    """Hallazgos: pares comparables cuyo monto difiere entre fuentes. Nada comparable → lista vacía."""
    hallazgos = []
    for p, a in _pares(_partidas(con), _acuerdos(con)):
        if abs(a["monto_mxn"] - p["monto_mxn"]) < 0.01:
            continue
        hallazgos.append({
            "tipo": "monto_difiere_entre_fuentes",
            "descripcion": (f"Para la partida {p['capitulo'] or 'sin capítulo'} '{p['nombre']}', el acuerdo "
                            f"'{a['acuerdo']}' registra ${a['monto_mxn']:,.2f} y la partida del Presupuesto 2026 "
                            f"registra ${p['monto_mxn']:,.2f}. Verificar el alcance y el ejercicio fiscal "
                            "de ambos datos en las fuentes citadas."),
            "partida_id": p["id"], "acuerdo_id": a["id"],
            "archivo_presupuesto": p["archivo"], "pagina_presupuesto": p["pagina"],
            "fragmento_presupuesto": p["fragmento"],
            "archivo_acuerdo": a["archivo"], "pagina_acuerdo": a["pagina"],
            "fragmento_acuerdo": a["fragmento"],
        })
    return hallazgos


def cobertura(con) -> dict:
    """Qué hay para cruzar y qué fuentes faltan. Sin datos comparables, esto es el resultado."""
    partidas, acuerdos = _partidas(con), _acuerdos(con)
    nombres_no_verificados = [p for p in partidas if p.get("verificacion_nombre") != "ok"]
    faltan = []
    if not any(a["monto_mxn"] is not None for a in acuerdos):
        faltan.append("Gacetas o actas con acuerdos que registren monto u obra: ningún acuerdo canónico "
                      "tiene monto_mxn, así que no hay cifra comparable contra las partidas.")
    if not any("presupuesto" in plano(a["acuerdo"]) for a in acuerdos):
        faltan.append("El acuerdo de Cabildo que aprobó el Presupuesto de Egresos 2026 (acta o gaceta de "
                      "esa sesión), para contrastar lo aprobado contra la versión ciudadana publicada.")
    if nombres_no_verificados:
        caps = ", ".join(p["capitulo"] or "sin capítulo" for p in nombres_no_verificados)
        faltan.append(f"Texto verificable para el nombre de {len(nombres_no_verificados)} partida(s) "
                      f"(capítulos {caps}): en la infografía no aparecen en el texto extraído de la página, "
                      "así que quedan como nombre no verificado hasta tener OCR o una versión con texto.")
    if not con.execute("SELECT 1 FROM documentos WHERE archivo = ?", (PMD_ARCHIVO,)).fetchone():
        faltan.append(f"El Plan Municipal de Desarrollo 2024-2027 ({PMD_ARCHIVO}), para cruzar sus ejes "
                      "y áreas contra los capítulos del presupuesto.")
    return {
        "partidas": len(partidas),
        "partidas_con_monto": sum(p["monto_mxn"] is not None for p in partidas),
        "suma_partidas": sum(p["monto_mxn"] or 0 for p in partidas),
        "partidas_nombre_no_verificado": len(nombres_no_verificados),
        "acuerdos_canonicos": len(acuerdos),
        "acuerdos_con_monto": sum(a["monto_mxn"] is not None for a in acuerdos),
        "acuerdos_con_proveedor": sum(a["proveedor"] is not None for a in acuerdos),
        "pares_comparables": len(_pares(partidas, acuerdos)),
        "fuentes_faltantes": faltan,
    }


def cruzar_pmd(con) -> list[dict]:
    """Cruce contra el Plan Municipal de Desarrollo 2024-2027 (pendiente: la fuente no está cargada)."""
    # Sin el PMD en datos/raw/ ni en documentos no hay dato que citar: no se inventa ningún hallazgo.
    # Cuando exista, extraer sus ejes/metas a una tabla propia y repetir el patrón de generar().
    if not con.execute("SELECT 1 FROM documentos WHERE archivo = ?", (PMD_ARCHIVO,)).fetchone():
        return []
    return []  # Detectado, pero falta implementar su extracción antes de cruzarlo.


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
        c = cobertura(con)
        cruzar_pmd(con)
    print("Cobertura del cruce:")
    print(f"- Partidas: {c['partidas']} ({c['partidas_con_monto']} con monto, suma ${c['suma_partidas']:,.2f}, "
          f"{c['partidas_nombre_no_verificado']} con nombre no verificado)")
    print(f"- Acuerdos canónicos: {c['acuerdos_canonicos']} ({c['acuerdos_con_monto']} con monto, "
          f"{c['acuerdos_con_proveedor']} con proveedor)")
    print(f"- Pares comparables (misma partida nombrada y monto en ambas fuentes): {c['pares_comparables']}")
    if c["fuentes_faltantes"]:
        print("Fuentes que faltan para poder cruzar:")
        for f in c["fuentes_faltantes"]:
            print(f"  * {f}")
    for h in hallazgos:
        print(f"- [{h['tipo']}] {h['descripcion']}")
    print(f"{len(hallazgos)} hallazgos → tabla hallazgos")


if __name__ == "__main__":
    main()
