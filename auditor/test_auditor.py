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
    paginas = {6: extraer.normalizar("Clasificador 1000 Servicios Personales $100.00")}
    assert presupuesto.verificar_nombre("Servicios Personales", paginas, 6) == "ok"
    assert presupuesto.verificar_nombre("Participaciones y Aportaciones", paginas, 6) == "no_encontrado"
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        p = {"capitulo": "1000", "nombre": "Servicios Personales", "monto_mxn": 100.0,
             "pagina": 6, "fragmento": "$100.00", "verificacion": "ok", "verificacion_nombre": "ok"}
        with presupuesto.conectar() as con:
            presupuesto.guardar(con, "pres.pdf", 10, [p, {**p, "capitulo": "2000", "nombre": "Materiales"}], (5, 6))
            presupuesto.guardar(con, "pres.pdf", 10, [p], (5, 6))
            filas = con.execute("SELECT capitulo, monto_mxn, verificacion_nombre FROM partidas").fetchall()
            assert filas == [("1000", 100.0, "ok")], filas


def test_cruzar_sin_datos_comparables():
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
                   "pagina": 6, "fragmento": "$50.00", "verificacion": "ok", "verificacion_nombre": "ok"}
        with cruzar.conectar() as con:
            extraer.guardar(con, "g.pdf", 9, [acuerdo], (1, 9))
            presupuesto.guardar(con, "pres.pdf", 10, [partida], (5, 6))
            # Reglamento sin monto contra capítulo del presupuesto: no hay dato comparable, no hay hallazgo.
            assert cruzar.generar(con) == []
            c = cruzar.cobertura(con)
            assert (c["partidas"], c["acuerdos_canonicos"], c["acuerdos_con_monto"], c["pares_comparables"]) == (1, 1, 0, 0)
            assert any("Presupuesto de Egresos 2026" in f for f in c["fuentes_faltantes"])
            assert cruzar.cruzar_pmd(con) == []  # fuente no cargada: no inventa hallazgos


def test_cruzar_monto_difiere():
    import cruzar
    import presupuesto
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        acuerdo = {"acuerdo": "Se aprobó un pago de Servicios Personales", "tipo_sesion": None, "fecha_sesion": None,
                   "propuesto_por": [], "monto_mxn": 999.0, "proveedor": None, "resultado_votacion": None,
                   "pagina": 4, "fragmento": "pago de Servicios Personales por $999.00", "verificacion": "ok"}
        partida = {"capitulo": "1000", "nombre": "Servicios Personales", "monto_mxn": 100.0,
                   "pagina": 6, "fragmento": "$100.00", "verificacion": "ok", "verificacion_nombre": "ok"}
        with cruzar.conectar() as con:
            extraer.guardar(con, "g.pdf", 9, [acuerdo], (1, 9))
            presupuesto.guardar(con, "pres.pdf", 10, [partida], (5, 6))
            hallazgos = cruzar.generar(con)
            assert [h["tipo"] for h in hallazgos] == ["monto_difiere_entre_fuentes"], hallazgos
            h = hallazgos[0]
            assert (h["archivo_presupuesto"], h["pagina_presupuesto"], h["fragmento_presupuesto"]) == ("pres.pdf", 6, "$100.00")
            assert (h["archivo_acuerdo"], h["pagina_acuerdo"], h["fragmento_acuerdo"]) == ("g.pdf", 4, "pago de Servicios Personales por $999.00")
            acuerdo["monto_mxn"] = 100.0  # mismo monto en ambas fuentes: ya no difieren
            extraer.guardar(con, "g.pdf", 9, [acuerdo], (1, 9))
            assert cruzar.generar(con) == []


def test_evidencia():
    import evidencia
    from PIL import Image
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        # Foto con EXIF (marca y fecha): la copia guardada no debe conservar nada.
        foto = Path(d) / "foto.jpg"
        exif = Image.Exif()
        exif[271] = "camara-prueba"      # Make
        exif[306] = "2026:01:01 00:00:00"  # DateTime
        Image.new("RGB", (20, 10), (120, 120, 120)).save(foto, exif=exif)
        limpia = evidencia.guardar_sin_exif(foto, Path(d) / "limpia.jpg")
        with Image.open(limpia) as im:
            assert dict(im.getexif()) == {} and im.size == (20, 10)

        with evidencia.conectar() as con:
            # Una sugerencia no es una liga confirmada: acuerdo_id y partida_id quedan null.
            id_ = evidencia.guardar(con, "limpia.jpg", "pothole", {"texto": "", "objetos": []}, None, None,
                                    None, None,
                                    [{"tipo": "partida", "id": 1, "justificacion": "podría relacionarse",
                                      "archivo": "pres.pdf", "pagina": 6, "fragmento": "$100.00"}])
            fila = con.execute("SELECT acuerdo_id, partida_id, sugerencias FROM evidencias WHERE id = ?", (id_,)).fetchone()
            assert fila[0] is None and fila[1] is None
            assert json.loads(fila[2])[0]["justificacion"] == "podría relacionarse"
            # La liga confirmada por la persona sí se registra como tal.
            id2 = evidencia.guardar(con, "limpia.jpg", "pothole", {"texto": "", "objetos": []}, None, None,
                                    None, 1, [])
            assert con.execute("SELECT partida_id FROM evidencias WHERE id = ?", (id2,)).fetchone()[0] == 1


def test_web():
    import evidencia
    import presupuesto
    import web
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        evidencia.EVIDENCIA = Path(d) / "evidencia"
        (Path(d) / "manifiesto.json").write_text(json.dumps(
            [{"archivo": "g.pdf", "url": "https://ejemplo.gob.mx/g.pdf", "sha256": "abc123",
              "descargado": "2026-01-01T00:00:00+00:00"}]))
        (Path(d) / "g.pdf").write_bytes(b"%PDF-1.4 prueba")
        acuerdo = {"acuerdo": "Se aprobó el Bando de Policía y Gobierno", "tipo_sesion": "ordinaria",
                   "fecha_sesion": "2025-02-24",
                   "propuesto_por": [{"nombre": "Ariadna Ayala Camarillo", "cargo": "Presidenta Municipal"}],
                   "monto_mxn": None, "proveedor": None, "resultado_votacion": "aprobado",
                   "pagina": 4, "fragmento": "Bando de Policía", "verificacion": "ok"}
        partida = {"capitulo": "8000", "nombre": "Participaciones y Aportaciones", "monto_mxn": 100.0,
                   "pagina": 6, "fragmento": "$100.00", "verificacion": "ok", "verificacion_nombre": "no_encontrado"}
        with evidencia.conectar() as con:
            extraer.guardar(con, "g.pdf", 9, [acuerdo], (1, 9))
            presupuesto.guardar(con, "pres.pdf", 10, [partida], (5, 6))

        cliente = TestClient(web.app)
        for ruta in ["/", "/funcionarios", "/funcionarios/ariadna-ayala-camarillo", "/acuerdos", "/acuerdos/1",
                     "/presupuesto", "/hallazgos", "/evidencia"]:
            r = cliente.get(ruta)
            assert r.status_code == 200, (ruta, r.status_code)
            texto = r.text.lower()
            assert "corrupción" not in texto and "robo" not in texto, ruta
        assert "nombre no verificado" in cliente.get("/presupuesto").text
        assert "abc123" in cliente.get("/").text  # sha256 del manifiesto en la fuente
        assert cliente.get("/fuentes/g.pdf").status_code == 200
        assert cliente.get("/fuentes/manifiesto.json").status_code == 404  # solo PDF de datos/raw
        assert cliente.get("/fuentes/%2E%2E%2Fweb.py").status_code == 404  # nada fuera de datos/raw
        r = cliente.post("/evidencia", files={"foto": ("nota.txt", b"hola", "text/plain")}, data={"objeto": "bache"})
        assert r.status_code == 400, r.status_code  # solo JPEG/PNG: se rechaza sin llamar a la API


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            f()
            print("ok", nombre)
