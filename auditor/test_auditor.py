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


def test_agrupar():
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        base = {"tipo_sesion": None, "propuesto_por": [], "monto_mxn": None, "proveedor": None,
                "resultado_votacion": None, "fragmento": "f", "verificacion": "ok"}
        menciones = [
            ("Se aprobó el Reglamento de Mercados, Tianguis, Centrales de Abasto o de Acopio y Comercio en Vía Pública",
             "2025-02-24", 4),
            ("Se aprueba el reglamento que regula los mercados, tianguis, centrales de abasto y de acopio",
             "2025-02-24", 134),
            ("Se aprobó el Reglamento de Mercados, Tianguis, Centrales de Abasto o de Acopio", "2024-01-01", 9),
            ("Se aprueba la modificación de la Estructura Orgánica de la Secretaría del Ayuntamiento", None, 5),
            ("Se aprueba la modificación de la Estructura Orgánica de la Contraloría Municipal del Ayuntamiento", None, 11),
        ]
        acuerdos = [{**base, "acuerdo": t, "fecha_sesion": f, "pagina": p} for t, f, p in menciones]
        acuerdos[1]["verificacion"] = "sin_texto"
        with extraer.conectar() as con:
            extraer.guardar(con, "doc.pdf", 200, acuerdos, (1, 200))
            grupos = [g for (g,) in con.execute("SELECT grupo_id FROM acuerdos ORDER BY id")]
            assert grupos == [1, 1, 3, 4, 5], grupos  # otra fecha y otra dependencia no se agrupan
            assert con.execute("SELECT id, menciones FROM acuerdos_canonicos WHERE id = 1").fetchone() == (1, 2)


def test_evaluar():
    import evaluar
    assert evaluar.traslapan(extraer.normalizar("se apruebe el Reglamento de Espectáculos del Municipio, Puebla."),
                             extraer.normalizar("Espectáculos del Municipio, Puebla. (Aprobado en la Sesión)"))
    assert not evaluar.traslapan("fragmentouno" * 3, "otracosadistinta" * 3)
    assert evaluar.traslapan("", "") and not evaluar.traslapan("algo", "")

    ex = {"id": 1, "grupo_id": 1, "archivo": "g.pdf", "pagina": 4, "acuerdo": "Se aprobó el Bando de Policía y Gobierno",
          "tipo_sesion": "extraordinaria", "fecha_sesion": "2025-02-24", "monto_mxn": None, "proveedor": None,
          "resultado_votacion": "aprobado", "fragmento": "el Bando de Policía y Gobierno del Municipio",
          "propuesto_por": json.dumps([{"nombre": "Iván Cortés Ambrosio", "cargo": "Síndico Municipal"},
                                       {"nombre": "Ariadna Ayala Camarillo", "cargo": "Presidenta Municipal"}])}
    otro = {**ex, "id": 2, "grupo_id": 2, "acuerdo": "Reglamento de Espectáculos", "pagina": 5}
    et = {"archivo": "g.pdf", "pagina": "5", "acuerdo": "Aprobación del Bando de Policía y Gobierno",
          "tipo_sesion": "Extraordinaria", "fecha_sesion": "2025-02-24", "monto_mxn": "", "proveedor": "null",
          "resultado_votacion": "unanimidad", "fragmento": "Bando de Policía y Gobierno",
          "propuesto_por": "ariadna ayala camarillo; IVAN CORTES AMBROSIO", "cargo": "Presidenta Municipal"}
    perdida = {**et, "pagina": "40"}
    r = evaluar.evaluar([et, perdida], [ex, otro])
    assert (r["emparejadas"], r["recall"], r["precision_acuerdos"]) == (1, 0.5, 0.5)
    bien = {c: b for c, (b, _) in r["campos"].items()}
    assert bien == {"pagina": 0, "tipo_sesion": 1, "fecha_sesion": 1, "propuesto_por": 1, "cargo": 0,
                    "monto_mxn": 1, "proveedor": 1, "resultado_votacion": 0, "fragmento": 1}, bien


def test_presupuesto_guardar():
    import presupuesto
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        p = {"capitulo": "1000", "nombre": "Servicios Personales", "monto_mxn": 100.0,
             "pagina": 6, "fragmento": "$100.00", "verificacion": "ok"}
        with presupuesto.conectar() as con:
            presupuesto.guardar(con, "pres.pdf", 10, [p, {**p, "capitulo": "2000", "nombre": "Materiales"}], (5, 6))
            presupuesto.guardar(con, "pres.pdf", 10, [p], (5, 6))
            filas = con.execute("SELECT capitulo, monto_mxn FROM partidas").fetchall()
            assert filas == [("1000", 100.0)], filas


def test_cruzar():
    import cruzar
    import presupuesto
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        acuerdo = {"acuerdo": "Se aprobó el Bando de Policía y Gobierno", "tipo_sesion": None, "fecha_sesion": None,
                   "propuesto_por": [], "monto_mxn": None, "proveedor": None, "resultado_votacion": None,
                   "pagina": 4, "fragmento": "Bando de Policía", "verificacion": "ok"}
        partida = {"capitulo": "6000", "nombre": "Inversión Pública", "monto_mxn": 50.0,
                   "pagina": 6, "fragmento": "$50.00", "verificacion": "ok"}
        with cruzar.conectar() as con:
            extraer.guardar(con, "g.pdf", 9, [acuerdo], (1, 9))
            presupuesto.guardar(con, "pres.pdf", 10, [partida], (5, 6))
            hallazgos = cruzar.generar(con)
            assert len(hallazgos) == 1 and hallazgos[0]["tipo"] == "partida_sin_acuerdo_textual", hallazgos
            h = hallazgos[0]
            assert (h["archivo_presupuesto"], h["pagina_presupuesto"], h["fragmento_presupuesto"]) == ("pres.pdf", 6, "$50.00")
            assert (h["archivo_acuerdo"], h["pagina_acuerdo"], h["fragmento_acuerdo"]) == ("g.pdf", 4, "Bando de Policía")
            assert "corrupción" not in h["descripcion"].lower() and "robo" not in h["descripcion"].lower()
            assert cruzar.cruzar_pmd(con) == []  # fuente no cargada: no inventa hallazgos


def test_cruzar_acuerdo_supera_total():
    import cruzar
    import presupuesto
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        acuerdo = {"acuerdo": "Se aprobó un pago de Servicios Personales", "tipo_sesion": None, "fecha_sesion": None,
                   "propuesto_por": [], "monto_mxn": 999.0, "proveedor": None, "resultado_votacion": None,
                   "pagina": 4, "fragmento": "Servicios Personales", "verificacion": "ok"}
        partida = {"capitulo": "1000", "nombre": "Servicios Personales", "monto_mxn": 100.0,
                   "pagina": 6, "fragmento": "$100.00", "verificacion": "ok"}
        with cruzar.conectar() as con:
            extraer.guardar(con, "g.pdf", 9, [acuerdo], (1, 9))
            presupuesto.guardar(con, "pres.pdf", 10, [partida], (5, 6))
            hallazgos = cruzar.generar(con)
            assert [h["tipo"] for h in hallazgos] == ["acuerdo_supera_total_presupuestado"], hallazgos


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            f()
            print("ok", nombre)
