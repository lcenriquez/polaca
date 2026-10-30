"""Cruza partidas del Presupuesto 2026 contra acuerdos_canonicos y genera hallazgos.

Uso: python auditor/cruzar.py

Un hallazgo es una discrepancia verificable: ambas fuentes hablan de lo mismo
(la partida aparece nombrada en el acuerdo, en los campos guardados en SQLite)
y difieren en un dato comparable (hoy, el monto; partidas no tiene fecha,
área ni proveedor). Sin dato comparable no hay hallazgo: se reporta la
cobertura y qué fuentes faltan para poder cruzar.

No se usa Muse para emparejar: la regla es determinística y las citas
(archivo, página y fragmento de cada fuente) salen de SQLite.

Con contratos (contratos.py) hay además, solo con citas verificadas (ok):
- monto_difiere_entre_fuentes: mismo número de contrato con montos distintos en
  dos documentos (o en un acuerdo de Cabildo que lo nombra).
- procedimiento_difiere: mismo contrato con procedimiento distinto en dos documentos.
- contratos_superan_capitulo: la suma de contratos de un capítulo supera lo
  presupuestado para ese capítulo en el mismo año y municipio.
- promesa_sin_registro (cruzar_pmd): meta medible del PMD sin acuerdo, partida ni
  contrato asociado en los documentos revisados. No es incumplimiento.
La concentración de contratos por proveedor es un dato descriptivo, no un hallazgo.
"""
import re
import sqlite3
from datetime import datetime, timezone

import contratos
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
    for tabla in ("hallazgos", "documentos", "acuerdos", "partidas"):  # municipios.py también las agrega
        if "municipio_id" not in {c[1] for c in con.execute(f"PRAGMA table_info({tabla})")}:
            con.execute(f"ALTER TABLE {tabla} ADD COLUMN municipio_id TEXT")
    contratos.conectar(con)  # contratos y metas_pmd en la misma base
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
            "fragmento_acuerdo": a["fragmento"], "municipio_id": p.get("municipio_id"),
        })
    return hallazgos + hallazgos_contratos(con)


def _contratos(con):
    return _filas(con, """SELECT c.*, d.archivo AS archivo FROM contratos c JOIN documentos d ON d.id = c.documento_id
                          WHERE c.verificacion = 'ok' ORDER BY c.id""")


def _monto(c: dict, otro: dict) -> tuple[float, float, str] | None:
    """Montos comparables: con IVA si ambos lo traen; si no, sin IVA. None si no hay par."""
    for campo, rotulo in (("monto_con_iva_mxn", "con IVA"), ("monto_sin_iva_mxn", "sin IVA"),
                          ("monto_planeado_mxn", "monto planeado")):
        if c.get(campo) is not None and otro.get(campo) is not None:
            return c[campo], otro[campo], rotulo
    return None


def _cita(prefijo: str, fila: dict) -> dict:
    return {f"archivo_{prefijo}": fila["archivo"], f"pagina_{prefijo}": fila["pagina"],
            f"fragmento_{prefijo}": fila["fragmento"]}


def _hallazgo(tipo, descripcion, a, b, municipio, partida_id=None, acuerdo_id=None) -> dict:
    """Fuente A va en las columnas *_presupuesto y fuente B en *_acuerdo (mismo esquema que el cruce original)."""
    h = {"tipo": tipo, "descripcion": descripcion, "partida_id": partida_id, "acuerdo_id": acuerdo_id,
         "municipio_id": municipio, "archivo_presupuesto": None, "pagina_presupuesto": None,
         "fragmento_presupuesto": None, "archivo_acuerdo": None, "pagina_acuerdo": None, "fragmento_acuerdo": None}
    if a:
        h.update(_cita("presupuesto", a))
    if b:
        h.update(_cita("acuerdo", b))
    return h


def _pesos(v: float) -> str:
    return f"${v:,.2f}"


def hallazgos_contratos(con) -> list[dict]:
    """Discrepancias aritméticas o documentales entre contratos y otras fuentes, con ambas citas."""
    filas = _contratos(con)
    hallazgos = []
    por_numero: dict[tuple, list[dict]] = {}
    for c in filas:
        if contratos.clave_numero(c["numero"]):
            por_numero.setdefault((c["municipio_id"], contratos.clave_numero(c["numero"])), []).append(c)
    for grupo in por_numero.values():
        for i, a in enumerate(grupo):
            for b in grupo[i + 1:]:
                if a["documento_id"] == b["documento_id"]:
                    continue  # misma fuente repetida: no es una segunda fuente
                par = _monto(a, b)
                if par and abs(par[0] - par[1]) >= 0.01:
                    hallazgos.append(_hallazgo(
                        "monto_difiere_entre_fuentes",
                        f"El {'proyecto' if par[2] == 'monto planeado' else 'contrato'} {a['numero']} aparece con "
                        f"{_pesos(par[0])} ({par[2]}) en {a['archivo']} y con {_pesos(par[1])} ({par[2]}) en "
                        f"{b['archivo']}. Verificar en ambas fuentes si se trata de una modificación u otra "
                        "versión del mismo registro.",
                        a, b, a["municipio_id"]))
                if a["procedimiento"] and b["procedimiento"] and a["procedimiento"] != b["procedimiento"]:
                    nombre = {"licitacion": "licitación", "invitacion": "invitación",
                              "adjudicacion_directa": "adjudicación directa"}
                    hallazgos.append(_hallazgo(
                        "procedimiento_difiere",
                        f"El contrato {a['numero']} aparece como {nombre[a['procedimiento']]} en {a['archivo']} "
                        f"y como {nombre[b['procedimiento']]} en {b['archivo']}. Verificar en ambas fuentes "
                        "cuál fue el procedimiento de contratación.",
                        a, b, a["municipio_id"]))
    # Contrato contra acuerdo de Cabildo que nombra su número.
    for a in _acuerdos(con):
        if a["monto_mxn"] is None or a.get("verificacion") != "ok":
            continue
        texto = re.sub(r"[^a-z0-9]", "", plano(f"{a['acuerdo']} {a['fragmento']}"))
        for c in filas:
            clave = contratos.clave_numero(c["numero"])
            if not clave or clave not in texto or c["municipio_id"] != a.get("municipio_id"):
                continue
            montos = [m for m in (c["monto_con_iva_mxn"], c["monto_sin_iva_mxn"], c["monto_planeado_mxn"])
                      if m is not None]
            if montos and all(abs(m - a["monto_mxn"]) >= 0.01 for m in montos):
                hallazgos.append(_hallazgo(
                    "monto_difiere_entre_fuentes",
                    f"El contrato {c['numero']} aparece con {_pesos(montos[0])} en {c['archivo']} y el acuerdo "
                    f"'{a['acuerdo']}' registra {_pesos(a['monto_mxn'])}. Verificar en ambas fuentes el alcance "
                    "de cada cifra.", c, a, c["municipio_id"], acuerdo_id=a["id"]))
    hallazgos += _superan_capitulo(con, filas)
    return hallazgos


def _anio(texto: str | None) -> str | None:
    m = re.search(r"20\d\d", texto or "")
    return m.group(0) if m else None


def _superan_capitulo(con, filas) -> list[dict]:
    """Suma de contratos de un capítulo y año contra la partida del presupuesto de ese capítulo y año."""
    sumas: dict[tuple, list[dict]] = {}
    for c in filas:
        monto = c["monto_con_iva_mxn"] if c["monto_con_iva_mxn"] is not None else c["monto_sin_iva_mxn"]
        if c["capitulo"] and monto is not None and _anio(c["fecha"]):
            sumas.setdefault((c["municipio_id"], c["capitulo"], _anio(c["fecha"])), []).append({**c, "monto": monto})
    hallazgos = []
    for p in _partidas(con):
        # ponytail: el año de la partida sale del nombre del archivo (…EGRESOS_2026.pdf); guardar ejercicio en partidas si hay varios por archivo.
        clave = (p.get("municipio_id"), p["capitulo"], _anio(p["archivo"]))
        grupo = sumas.get(clave)
        if p["monto_mxn"] is None or p["verificacion"] != "ok" or not grupo:
            continue
        total = sum(c["monto"] for c in grupo)
        if total - p["monto_mxn"] < 0.01:
            continue
        mayor = max(grupo, key=lambda c: c["monto"])
        numeros = ", ".join(c["numero"] or f"sin número (p. {c['pagina']})" for c in grupo)
        hallazgos.append(_hallazgo(
            "contratos_superan_capitulo",
            f"En {clave[2]}, la suma de {len(grupo)} contrato(s) del capítulo {p['capitulo']} ({numeros}) es "
            f"{_pesos(total)}, y el presupuesto registra {_pesos(p['monto_mxn'])} para '{p['nombre']}'. "
            f"Diferencia: {_pesos(total - p['monto_mxn'])}. Verificar si hubo ampliaciones presupuestales "
            "o si los contratos abarcan más de un ejercicio.",
            p, mayor, p.get("municipio_id"), partida_id=p["id"]))
    return hallazgos


def concentracion_proveedores(con) -> list[dict]:
    """Dato descriptivo, sin juicio: cuántos contratos y cuánto monto por proveedor en cada municipio."""
    filas = _filas(con, """SELECT municipio_id, proveedor, count(*) AS contratos,
                                  sum(coalesce(monto_con_iva_mxn, monto_sin_iva_mxn)) AS monto
                           FROM contratos WHERE verificacion = 'ok' AND proveedor IS NOT NULL
                           GROUP BY municipio_id, proveedor ORDER BY monto DESC""")
    totales: dict = {}
    for f in filas:
        totales[f["municipio_id"]] = totales.get(f["municipio_id"], 0) + (f["monto"] or 0)
    for f in filas:
        f["proporcion"] = (f["monto"] or 0) / totales[f["municipio_id"]] if totales[f["municipio_id"]] else None
    return filas


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
    if not con.execute("SELECT 1 FROM metas_pmd LIMIT 1").fetchone():
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
        "contratos": con.execute("SELECT count(*) FROM contratos").fetchone()[0],
        "contratos_verificados": con.execute("SELECT count(*) FROM contratos WHERE verificacion = 'ok'").fetchone()[0],
        "metas_pmd": con.execute("SELECT count(*) FROM metas_pmd").fetchone()[0],
        "fuentes_faltantes": faltan,
    }


def _raices(texto: str | None) -> set[str]:
    """Palabras recortadas a 5 letras: 'luminarias' y 'luminaria' cuentan como la misma."""
    from extraer import palabras
    return {p[:5] for p in palabras(texto) if len(p) >= 4}


def cruzar_pmd(con) -> list[dict]:
    """promesa_sin_registro: meta medible del PMD sin acuerdo, partida ni contrato que la nombre.

    La coincidencia es generosa (basta la mitad de las palabras del tema) para no
    reportar ausencias que sí están. Sin metas del PMD cargadas, no hay hallazgo."""
    metas = _filas(con, """SELECT m.*, d.archivo AS archivo FROM metas_pmd m JOIN documentos d ON d.id = m.documento_id
                           WHERE m.verificacion = 'ok' AND m.cantidad IS NOT NULL""")
    if not metas:
        return []
    otras = (_filas(con, "SELECT a.acuerdo || ' ' || a.fragmento AS texto, a.municipio_id, a.documento_id FROM acuerdos a")
             + _filas(con, "SELECT p.nombre AS texto, p.municipio_id, p.documento_id FROM partidas p")
             + _filas(con, "SELECT c.objeto || ' ' || coalesce(c.area_solicitante, '') AS texto, c.municipio_id, "
                           "c.documento_id FROM contratos c"))
    hallazgos = []
    for m in metas:
        tema = _raices(m["tema"])
        revisadas = [o for o in otras if o["municipio_id"] == m["municipio_id"]]
        if not tema or any(len(tema & _raices(o["texto"])) * 2 >= len(tema) for o in revisadas):
            continue
        n_docs = len({o["documento_id"] for o in revisadas})
        cifra = f"{m['cantidad']:,g}" + (f" {m['unidad']}" if m["unidad"] else "")
        hallazgos.append(_hallazgo(
            "promesa_sin_registro",
            f"El Plan Municipal de Desarrollo establece: «{m['meta']}» ({cifra}). No se encontró en los "
            f"{n_docs} documentos revisados un acuerdo, partida ni contrato asociado a «{m['tema']}». "
            "Puede estar en documentos que aún no se han revisado; esto no indica incumplimiento.",
            m, None, m["municipio_id"]))
    return hallazgos


def guardar(con, hallazgos: list[dict]):
    con.execute("DELETE FROM hallazgos")
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.executemany("""INSERT INTO hallazgos (tipo, descripcion, partida_id, acuerdo_id, archivo_presupuesto,
                       pagina_presupuesto, fragmento_presupuesto, archivo_acuerdo, pagina_acuerdo,
                       fragmento_acuerdo, municipio_id, creado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(h["tipo"], h["descripcion"], h["partida_id"], h["acuerdo_id"], h["archivo_presupuesto"],
                      h["pagina_presupuesto"], h["fragmento_presupuesto"], h["archivo_acuerdo"],
                      h["pagina_acuerdo"], h["fragmento_acuerdo"], h.get("municipio_id"), ahora) for h in hallazgos])
    con.commit()


def main():
    with conectar() as con:
        hallazgos = generar(con) + cruzar_pmd(con)
        guardar(con, hallazgos)
        c = cobertura(con)
        concentracion = concentracion_proveedores(con)
    print("Cobertura del cruce:")
    print(f"- Partidas: {c['partidas']} ({c['partidas_con_monto']} con monto, suma ${c['suma_partidas']:,.2f}, "
          f"{c['partidas_nombre_no_verificado']} con nombre no verificado)")
    print(f"- Acuerdos canónicos: {c['acuerdos_canonicos']} ({c['acuerdos_con_monto']} con monto, "
          f"{c['acuerdos_con_proveedor']} con proveedor)")
    print(f"- Pares comparables (misma partida nombrada y monto en ambas fuentes): {c['pares_comparables']}")
    print(f"- Contratos: {c['contratos']} ({c['contratos_verificados']} con cita verificada); metas del PMD: {c['metas_pmd']}")
    if concentracion:
        print("Contratos por proveedor (dato descriptivo):")
        for f in concentracion[:10]:
            parte = f" ({f['proporcion']:.0%} del monto registrado del municipio)" if f["proporcion"] is not None else ""
            print(f"  * {f['municipio_id']} · {f['proveedor']}: {f['contratos']} contrato(s), "
                  f"${f['monto'] or 0:,.2f}{parte}")
    if c["fuentes_faltantes"]:
        print("Fuentes que faltan para poder cruzar:")
        for f in c["fuentes_faltantes"]:
            print(f"  * {f}")
    for h in hallazgos:
        print(f"- [{h['tipo']}] {h['descripcion']}")
    print(f"{len(hallazgos)} hallazgos → tabla hallazgos")


if __name__ == "__main__":
    main()
