"""Descarga las fuentes públicas a datos/raw/ y registra URL, fecha y sha256."""
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RAW = Path(os.environ.get("DATA_DIR", RAIZ / "datos")) / "raw"  # en Fly: el volumen /data

FUENTES = [
    "https://transparencia.atlixco.gob.mx/Admin24-27/2025/Gaceta/GACETA_AGOSTO-DICIEMBRE_2025.pdf",
    "https://transparencia.atlixco.gob.mx/Admin24-27/2026/Armonizacion_Contable/Informacion_Anual/VERSION_CIUDADANA_PRESUPUESTO_EGRESOS_2026.pdf",
    "https://ojp.puebla.gob.mx/media/k2/attachments/Reglamento_Interior_de_Cabildo_del_Municipio_de_Atlixco_T2_08072025.pdf",
    "https://transparencia.atlixco.gob.mx/Atlixco/gaceta/2015/9C.3-011215.pdf",
    "https://transparencia.atlixco.gob.mx/Atlixco/gaceta/2022/GACETA_JULIO_2022.pdf",
    # Etapa de gobierno cercano: directorio, juntas, contacto oficial y la ley que define cada cargo.
    "https://atlixco.gob.mx/Pages/Ayuntamiento/Cabildo.aspx",
    "https://atlixco.gob.mx/Pages/Ayuntamiento/Juntas_Auxiliares.aspx",
    "https://atlixco.gob.mx/Pages/Ayuntamiento/Contacto.aspx",
    "https://ojp.puebla.gob.mx/media/k2/attachments/Ley_Organica_Municipal_TEV_08062026.pdf",
]


def descargar(url: str) -> dict:
    nombre = url.rsplit("/", 1)[-1]
    if nombre.endswith(".aspx"):  # las páginas del portal se guardan como HTML
        nombre = nombre[:-5] + ".html"
    destino = RAW / nombre
    if not destino.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (auditor-atlixco)"})
        with urllib.request.urlopen(req, timeout=120) as r:
            datos = r.read()
        if not datos.startswith(b"%PDF") and b"<html" not in datos[:1000].lower():
            raise ValueError(f"{url} no devolvió un PDF ni una página HTML")
        destino.write_bytes(datos)
    return {
        "archivo": nombre,
        "url": url,
        "sha256": hashlib.sha256(destino.read_bytes()).hexdigest(),
        "bytes": destino.stat().st_size,
        "descargado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    manifiesto = RAW / "manifiesto.json"
    previo = {m["archivo"]: m for m in json.loads(manifiesto.read_text())} if manifiesto.exists() else {}
    for url in FUENTES:
        try:
            m = descargar(url)
            m["descargado"] = previo.get(m["archivo"], m)["descargado"]
            previo[m["archivo"]] = m
            print(f"ok  {m['archivo']} ({m['bytes'] // 1024} KB)")
        except Exception as e:
            print(f"ERR {url}: {e}", file=sys.stderr)
    manifiesto.write_text(json.dumps(list(previo.values()), indent=2, ensure_ascii=False))
