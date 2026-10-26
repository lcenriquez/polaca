"""Pruebas mínimas, sin red ni costo: python auditor/test_auditor.py"""
import json
import tempfile
from pathlib import Path

import extraer
import llm


def test_verificar():
    paginas = {10: extraer.normalizar("DADO EN SESIÓN DE CAB ILDO del\nmunicipio de Atlixco, Puebla ."),
               11: extraer.normalizar("texto de la página once"),
               12: ""}
    assert extraer.verificar("Dado en sesión de Cabildo", paginas, 10) == (10, "ok")
    assert extraer.verificar("Atlixco, Puebla.", paginas, 10) == (10, "ok")
    assert extraer.verificar("página once", paginas, 10) == (11, "ok")          # corrige la página
    assert extraer.verificar("Puebla. texto de", paginas, 10) == (10, "ok")     # cruza a la siguiente
    assert extraer.verificar("acuerdo inventado", paginas, 10) == (10, "no_encontrado")
    assert extraer.verificar("lo que sea", paginas, 12) == (12, "sin_texto")
    assert extraer.verificar("", paginas, 10) == (10, "no_encontrado")


def test_costo():
    uso = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000,
           "prompt_tokens_details": {"cached_tokens": 500_000}}
    assert round(llm.costo_usd("muse-spark-1.3-contributor", uso), 4) == round(0.05 + 0.001 + 0.20, 4)


def test_cache_no_llama_api():
    with tempfile.TemporaryDirectory() as d:
        llm.CACHE = Path(d)
        kwargs = {"model": "x", "messages": []}
        clave = llm.hashlib.sha256(json.dumps(kwargs, sort_keys=True).encode()).hexdigest()
        (Path(d) / f"{clave}.json").write_text('{"guardado": true}')
        llm._cliente = "no-debe-usarse"
        assert llm.llamar("prueba", **kwargs) == {"guardado": True}


def test_guardar_reemplaza_rango():
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        a = {"acuerdo": "x", "tipo_sesion": None, "fecha_sesion": None, "propuesto_por": [], "monto_mxn": None,
             "proveedor": None, "resultado_votacion": None, "pagina": 5, "fragmento": "f", "verificacion": "ok"}
        with extraer.conectar() as con:
            extraer.guardar(con, "doc.pdf", 9, [a, a], (1, 9))
            extraer.guardar(con, "doc.pdf", 9, [a], (1, 9))
            assert con.execute("SELECT count(*) FROM acuerdos").fetchone()[0] == 1


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            f()
            print("ok", nombre)
