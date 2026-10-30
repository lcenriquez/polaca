"""Evidencia ciudadana: segmenta un objeto en una foto con SAM 3.1 y la registra.

Uso:
    python auditor/evidencia.py FOTO "pothole" [--acuerdo ID | --partida ID]

La foto se guarda sin metadatos EXIF (incluido GPS) en datos/evidencia/. La
liga a un acuerdo o partida solo la confirma la persona, con --acuerdo o
--partida; sin eso, Muse Spark (MODELO_PRIVADO, porque la foto puede traer
datos personales) sugiere hasta 3 candidatos de SQLite y quedan guardados
como sugerencias con su justificación y su cita, nunca como liga confirmada.

La foto es evidencia de un estado observado, no una acusación.
SAM 3.1 se llama por Responses API vía llm.llamar_responses() (misma caché y
registro de costos; $2.50 por cada 1,000 imágenes). Su salida en output_text
se parsea con el paquete oficial meta-sam-parser.
"""
import argparse
import base64
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

import llm
import extraer
import presupuesto

EVIDENCIA = extraer.DATA_DIR / "evidencia"

ESQUEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sugerencias"],
    "properties": {
        "sugerencias": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["tipo", "id", "justificacion"],
                "properties": {
                    "tipo": {"type": "string", "enum": ["acuerdo", "partida"]},
                    "id": {"type": "integer", "description": "Id del acuerdo canónico o de la partida, tal como viene en la lista."},
                    "justificacion": {"type": "string",
                                      "description": "Por qué podría relacionarse, citando el fragmento del candidato."},
                },
            },
        }
    },
}

INSTRUCCIONES = """Eres un asistente que sugiere posibles relaciones entre evidencia ciudadana y registros públicos del Ayuntamiento de Atlixco, Puebla.

Te dan el objeto observado en una foto (una descripción breve), el resultado de segmentación, y una lista de acuerdos de Cabildo y partidas del Presupuesto 2026, cada uno con su id y un fragmento textual.

Reglas estrictas:
- Sugiere hasta 3 candidatos que podrían relacionarse con el estado observado. Nada más que sugerencias: la relación la confirma una persona.
- Usa solo los ids de la lista. Si ninguno podría relacionarse, devuelve una lista vacía.
- Cada "justificacion" debe mencionar y citar entre comillas el fragmento del candidato tal como viene en la lista.
- Lenguaje neutral y descriptivo: la foto muestra un estado observado; no afirmes causas ni responsabilidades."""


def conectar() -> sqlite3.Connection:
    con = presupuesto.conectar()
    con.execute("""
        CREATE TABLE IF NOT EXISTS evidencias (
            id INTEGER PRIMARY KEY,
            archivo TEXT NOT NULL,          -- foto guardada, sin EXIF
            objeto TEXT NOT NULL,           -- texto usado como prompt de SAM
            sam_resultado TEXT NOT NULL,    -- JSON: cajas, confianzas y texto crudo de SAM
            mascara TEXT,                   -- ruta de la máscara combinada (PNG)
            superpuesta TEXT,               -- ruta de la imagen con la segmentación encima (PNG)
            acuerdo_id INTEGER REFERENCES acuerdos(id),   -- solo si la persona lo confirma con --acuerdo
            partida_id INTEGER REFERENCES partidas(id),   -- solo si la persona lo confirma con --partida
            sugerencias TEXT NOT NULL,      -- JSON: [{tipo, id, justificacion, archivo, pagina, fragmento}]
            fecha TEXT NOT NULL
        )""")
    con.commit()
    return con


def guardar_sin_exif(origen: Path, destino: Path) -> Path:
    """Guarda una copia sin ningún metadato EXIF (incluido GPS), aplicando antes la orientación EXIF."""
    with Image.open(origen) as im:
        im = ImageOps.exif_transpose(im)  # endereza según EXIF y ya no lo conserva
        limpia = Image.new(im.mode, im.size)
        limpia.paste(im)
    if limpia.mode not in ("RGB", "L"):
        limpia = limpia.convert("RGB")
    destino.parent.mkdir(parents=True, exist_ok=True)
    limpia.save(destino)
    return destino


def _texto_respuesta(resp: dict) -> str:
    return "".join(parte.get("text", "")
                   for salida in resp.get("output", [])
                   for parte in salida.get("content", [])
                   if parte.get("type") == "output_text")


def segmentar(ruta: Path, objeto: str) -> dict:
    """Llama a SAM 3.1 y parsea su output_text con meta-sam-parser. Devuelve texto y objetos con su máscara."""
    from meta_sam_parser import CompletedOutcome, SegmentationBoxRecord, SegmentationMaskRecord, image_segmentation_format

    datos = base64.b64encode(ruta.read_bytes()).decode()
    resp = llm.llamar_responses(
        f"sam:{objeto}",
        model="sam-3.1",
        metadata={"include_confidence": "true"},
        input=[{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": objeto},
            {"type": "input_image", "image_url": f"data:image/jpeg;base64,{datos}"},
        ]}],
    )
    texto = _texto_respuesta(resp)
    parser = image_segmentation_format().create_parser()
    parser.push(texto)
    resultado = parser.finish(CompletedOutcome()).result
    cajas = {r.object_id: r for r in resultado.records if isinstance(r, SegmentationBoxRecord)}
    objetos = [{"id": r.object_id, "registro_mascara": r,
                "caja": [cajas[r.object_id].left, cajas[r.object_id].top,
                         cajas[r.object_id].right, cajas[r.object_id].bottom] if r.object_id in cajas else None,
                "confianza": r.confidence}
               for r in resultado.records if isinstance(r, SegmentationMaskRecord)]
    return {"texto": texto, "objetos": objetos}


def resumen_sam(seg: dict) -> dict:
    """Versión JSON-guardable del resultado de SAM (sin los objetos de máscara del parser)."""
    return {"texto": seg["texto"],
            "objetos": [{"id": o["id"], "caja": o["caja"], "confianza": o["confianza"],
                         "mascara": {"ancho": o["registro_mascara"].mask.width,
                                     "alto": o["registro_mascara"].mask.height,
                                     "codificacion": o["registro_mascara"].mask.encoding}}
                        for o in seg["objetos"]]}


def guardar_salidas(ruta: Path, seg: dict, base: Path) -> tuple[Path | None, Path | None]:
    """Guarda la máscara combinada y la imagen con la segmentación superpuesta. (None, None) si SAM no encontró nada."""
    if not seg["objetos"]:
        return None, None
    from meta_sam_parser import decode_mask_to_raster

    with Image.open(ruta) as im:
        original = im.convert("RGB")
    mascara = Image.new("L", original.size, 0)
    for o in seg["objetos"]:
        r = o["registro_mascara"]
        raster = decode_mask_to_raster(r.mask)
        pieza = Image.frombytes("L", (r.mask.width, r.mask.height), bytes(255 * b for b in raster))
        mascara.paste(pieza, (int(r.bounds.left), int(r.bounds.top)))
    ruta_mascara = base.with_name(base.name + "_mascara.png")
    mascara.save(ruta_mascara)

    roja = Image.new("RGB", original.size, (255, 0, 0))
    superpuesta = Image.composite(roja, original, mascara.point(lambda v: v * 120 // 255))
    trazo = ImageDraw.Draw(superpuesta)
    for o in seg["objetos"]:
        if o["caja"]:
            trazo.rectangle(o["caja"], outline=(255, 255, 0), width=3)
    ruta_superpuesta = base.with_name(base.name + "_segmentada.png")
    superpuesta.save(ruta_superpuesta)
    return ruta_mascara, ruta_superpuesta


def _candidatos(con) -> tuple[list[dict], list[dict]]:
    con.row_factory = sqlite3.Row
    acuerdos = [dict(f) for f in con.execute(
        "SELECT a.id, a.acuerdo, a.fragmento, a.pagina, d.archivo FROM acuerdos_canonicos a "
        "JOIN documentos d ON d.id = a.documento_id")]
    partidas = [dict(f) for f in con.execute(
        "SELECT p.id, p.capitulo, p.nombre, p.monto_mxn, p.fragmento, p.pagina, d.archivo FROM partidas p "
        "JOIN documentos d ON d.id = p.documento_id")]
    return acuerdos, partidas


def sugerir(con, objeto: str, seg: dict) -> list[dict]:
    """Hasta 3 sugerencias de Muse (MODELO_PRIVADO), validadas contra SQLite y con la cita de SQLite."""
    acuerdos, partidas = _candidatos(con)
    if not acuerdos and not partidas:
        return []
    lista = "\n".join(
        [f"acuerdo id={a['id']}: {a['acuerdo']} | fragmento: \"{a['fragmento']}\"" for a in acuerdos]
        + [f"partida id={p['id']}: capítulo {p['capitulo']} {p['nombre']} ${p['monto_mxn']:,.2f} | fragmento: \"{p['fragmento']}\""
           for p in partidas])
    resumen = {"texto": seg["texto"][:500], "objetos": len(seg["objetos"]),
               "cajas": [o["caja"] for o in seg["objetos"]]}
    resp = llm.llamar(
        f"evidencia-sugerencias:{objeto}",
        model=llm.MODELO_PRIVADO,
        reasoning_effort="medium",
        messages=[
            {"role": "system", "content": INSTRUCCIONES},
            {"role": "user", "content": f"Objeto observado: {objeto}\nSegmentación SAM: {json.dumps(resumen, ensure_ascii=False)}\n\nCandidatos:\n{lista}"},
        ],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "sugerencias", "strict": True, "schema": ESQUEMA}},
    )
    propuestas = json.loads(resp["choices"][0]["message"]["content"])["sugerencias"][:3]
    por_clave = {("acuerdo", a["id"]): a for a in acuerdos} | {("partida", p["id"]): p for p in partidas}
    sugerencias = []
    for s in propuestas:  # la cita final sale de SQLite, no del modelo
        fila = por_clave.get((s["tipo"], s["id"]))
        if fila:
            sugerencias.append({"tipo": s["tipo"], "id": s["id"], "justificacion": s["justificacion"],
                                "archivo": fila["archivo"], "pagina": fila["pagina"], "fragmento": fila["fragmento"]})
    return sugerencias


def guardar(con, archivo: str, objeto: str, sam_resultado: dict, mascara: str | None, superpuesta: str | None,
            acuerdo_id: int | None, partida_id: int | None, sugerencias: list[dict]) -> int:
    cur = con.execute("""INSERT INTO evidencias (archivo, objeto, sam_resultado, mascara, superpuesta,
                         acuerdo_id, partida_id, sugerencias, fecha) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                      (archivo, objeto, json.dumps(sam_resultado, ensure_ascii=False), mascara, superpuesta,
                       acuerdo_id, partida_id, json.dumps(sugerencias, ensure_ascii=False),
                       datetime.now(timezone.utc).isoformat(timespec="seconds")))
    con.commit()
    return cur.lastrowid


def main():
    p = argparse.ArgumentParser()
    p.add_argument("foto", help="ruta de la foto")
    p.add_argument("objeto", help="descripción breve del objeto a segmentar, p. ej. \"pothole\"")
    liga = p.add_mutually_exclusive_group()
    liga.add_argument("--acuerdo", type=int, help="id de acuerdo canónico confirmado por la persona")
    liga.add_argument("--partida", type=int, help="id de partida confirmada por la persona")
    args = p.parse_args()

    foto = Path(args.foto)
    with conectar() as con:
        # La liga confirmada se valida antes de gastar en API.
        if args.acuerdo and not con.execute("SELECT 1 FROM acuerdos_canonicos WHERE id = ?", (args.acuerdo,)).fetchone():
            raise SystemExit(f"No existe el acuerdo canónico id={args.acuerdo} en acuerdos_canonicos.")
        if args.partida and not con.execute("SELECT 1 FROM partidas WHERE id = ?", (args.partida,)).fetchone():
            raise SystemExit(f"No existe la partida id={args.partida} en partidas.")

        sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        base = EVIDENCIA / f"{sello}_{foto.stem}"
        limpia = guardar_sin_exif(foto, base.with_name(base.name + "_limpia.jpg"))
        seg = segmentar(limpia, args.objeto)
        ruta_mascara, ruta_superpuesta = guardar_salidas(limpia, seg, base)
        sugerencias = [] if (args.acuerdo or args.partida) else sugerir(con, args.objeto, seg)
        id_ = guardar(con, str(limpia.relative_to(extraer.DATA_DIR)), args.objeto, resumen_sam(seg),
                      str(ruta_mascara.relative_to(extraer.DATA_DIR)) if ruta_mascara else None,
                      str(ruta_superpuesta.relative_to(extraer.DATA_DIR)) if ruta_superpuesta else None,
                      args.acuerdo, args.partida, sugerencias)

    print(f"Evidencia {id_}: '{args.objeto}' — {len(seg['objetos'])} objeto(s) segmentado(s).")
    print(f"  foto sin EXIF: {limpia}")
    if ruta_superpuesta:
        print(f"  segmentación superpuesta: {ruta_superpuesta}")
        print(f"  máscara: {ruta_mascara}")
    else:
        print("  SAM no encontró el objeto en la foto.")
    if args.acuerdo or args.partida:
        print(f"  liga confirmada por la persona: {'acuerdo' if args.acuerdo else 'partida'} id={args.acuerdo or args.partida}")
    for s in sugerencias:
        print(f"  sugerencia (sin confirmar): {s['tipo']} id={s['id']} — {s['justificacion']} "
              f"[{s['archivo']}, p.{s['pagina']}: \"{s['fragmento'][:80]}...\"]")
    print("Gasto acumulado:", llm.resumen_costos())


if __name__ == "__main__":
    main()
