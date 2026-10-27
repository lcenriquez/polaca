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
        for ruta in ["/", "/donde", "/representantes", "/temas", "/gastos", "/funcionarios",
                     "/funcionarios/ariadna-ayala-camarillo", "/acuerdos", "/acuerdos/1",
                     "/presupuesto", "/hallazgos", "/evidencia"]:
            r = cliente.get(ruta)
            assert r.status_code == 200, (ruta, r.status_code)
            texto = r.text.lower()
            assert "corrupción" not in texto and "robo" not in texto, ruta
        assert "nombre no verificado" in cliente.get("/presupuesto").text
        assert "abc123" in cliente.get("/donde").text  # sha256 del manifiesto, en detalles técnicos
        assert cliente.get("/fuentes/g.pdf").status_code == 200
        assert cliente.get("/fuentes/manifiesto.json").status_code == 404  # solo PDF de datos/raw
        assert cliente.get("/fuentes/%2E%2E%2Fweb.py").status_code == 404  # nada fuera de datos/raw
        r = cliente.post("/evidencia", files={"foto": ("nota.txt", b"hola", "text/plain")}, data={"objeto": "bache"})
        assert r.status_code == 400, r.status_code  # solo JPEG/PNG: se rechaza sin llamar a la API


def test_explicar_web():
    import explicar
    import web
    from fastapi.testclient import TestClient
    assert web.en_palabras(244_276_746.96) == "244 millones de pesos"
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        acuerdo = {"acuerdo": "Se aprobó el Bando de Policía y Gobierno", "tipo_sesion": "ordinaria",
                   "fecha_sesion": "2025-02-24", "propuesto_por": [], "monto_mxn": None, "proveedor": None,
                   "resultado_votacion": "aprobado", "pagina": 4, "fragmento": "Bando de Policía", "verificacion": "ok"}
        with explicar.conectar() as con:
            extraer.guardar(con, "g.pdf", 9, [acuerdo], (1, 9))
            explicar.guardar_glosario(con, [
                {"termino": "Cabildo", "definicion": "Reunión del Ayuntamiento.", "archivo": "g.pdf",
                 "pagina": 4, "fragmento": "Bando de Policía", "verificacion": "ok"},
                {"termino": "Capítulo del gasto", "definicion": "Grupo de gastos por tipo.", "archivo": None,
                 "pagina": None, "fragmento": None, "verificacion": "sin_fuente"}])
            # Invariante: cada término tiene cita completa o la marca de sin fuente local.
            for t in con.execute("SELECT * FROM glosario"):
                assert (t[2] and t[3] and t[4]) or t[5] == "sin_fuente", t
            explicar.guardar_resumenes(con, [
                {"tipo": "acuerdo", "id": 1, "resumen": "Se aprobó el Bando de Policía.",
                 "archivo": "g.pdf", "pagina": 4, "fragmento": "Bando de Policía"}])
            for r in con.execute("SELECT archivo, pagina, fragmento FROM resumenes"):
                assert all(r), r  # cada resumen lleva su cita
            explicar.guardar_rutas(con, [
                {"clave": "solicitud-pnt", "titulo": "Pedir información", "pasos": ["Entra a la plataforma."],
                 "plantilla": "Solicito conocer {tema}.", "fundamento_archivo": "g.pdf", "fundamento_pagina": 4,
                 "fundamento_fragmento": "Bando de Policía", "fundamento_url": "https://ejemplo.gob.mx",
                 "verificacion": "ok"}])
        cliente = TestClient(web.app)
        acuerdos = cliente.get("/acuerdos").text
        assert "¿Qué es esto?" in acuerdos and "sin fuente local" not in acuerdos  # Cabildo tiene fuente
        detalle = cliente.get("/acuerdos/1").text
        assert "En palabras simples" in detalle and "¿Qué puedes hacer?" in detalle and "Solicito conocer" in detalle
        presupuesto_html = cliente.get("/presupuesto").text
        assert "sin fuente local" in presupuesto_html  # Capítulo del gasto, marcado, no como dato oficial
        inicio = cliente.get("/").text
        assert "Escuchar esta página" in inicio and "POLACA" in inicio  # marca nueva; el menú de accesibilidad va en el encabezado
        assert "¿Quién gobierna donde vives?" in inicio and "Atlixco a la vista" not in inicio
        for ruta in ["/", "/acuerdos", "/acuerdos/1", "/presupuesto"]:
            texto = cliente.get(ruta).text.lower()
            assert "corrupción" not in texto and "robo" not in texto, ruta


def test_gobierno():
    import gobierno
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        (Path(d) / "x.html").write_text("<html><head><style>a{}</style><script>var x=1;</script></head>"
                                        "<body><p>Hola <b>mundo</b></p></body></html>")
        assert gobierno.texto_html("x.html") == "Hola\nmundo"
        filas = [{"nombre": "Persona", "cargo": "Regiduría de Salud", "comision": "Salud", "archivo": "x.html",
                  "pagina": 1, "fragmento": "Hola mundo", "verificacion": "ok"},
                 {"nombre": "Otra", "cargo": "Regiduría de Turismo", "comision": "Turismo", "archivo": "x.html",
                  "pagina": 1, "fragmento": "no está", "verificacion": "no_encontrado"}]
        with gobierno.conectar() as con:
            ok = gobierno._guardar(con, "funcionarios",
                                   ["nombre", "cargo", "comision", "archivo", "pagina", "fragmento", "verificacion"], filas)
            assert [f["nombre"] for f in ok] == ["Persona"]  # solo con cita verificada se muestra
            assert con.execute("SELECT count(*) FROM funcionarios WHERE verificacion = 'ok'").fetchone()[0] == 1


def test_recorrido():
    import gobierno
    import presupuesto
    import web
    from fastapi.testclient import TestClient
    partidas = [{"id": 1, "nombre": "A", "monto_mxn": 333.0}, {"id": 2, "nombre": "B", "monto_mxn": 333.0},
                {"id": 3, "nombre": "C", "monto_mxn": 334.0}]
    assert sum(web.monedas_100(partidas).values()) == 100  # la cuadrícula suma siempre 100
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        cols_f = ["nombre", "cargo", "comision", "archivo", "pagina", "fragmento", "verificacion"]
        base = {"archivo": "g.html", "pagina": 1, "verificacion": "ok"}
        with gobierno.conectar() as con:
            gobierno._guardar(con, "funcionarios", cols_f, [
                {**base, "nombre": "Ana Presidenta", "cargo": "Presidenta Municipal", "comision": None, "fragmento": "Ana Presidenta"},
                {**base, "nombre": "Beto Síndico", "cargo": "Sindicatura Municipal", "comision": None, "fragmento": "Beto Síndico"},
                {**base, "nombre": "Cora Regidora", "cargo": "Regiduría de Desarrollo Urbano, Obras y Servicios Públicos",
                 "comision": "Desarrollo Urbano, Obras y Servicios Públicos", "fragmento": "Cora Regidora"}])
            gobierno._guardar(con, "juntas_auxiliares", ["nombre", "presidente", "localidades", "archivo", "pagina", "fragmento", "verificacion"], [
                {**base, "nombre": "Metepec", "presidente": "Dario Auxiliar", "localidades": "[]", "fragmento": "Dario Auxiliar Metepec"}])
            gobierno._guardar(con, "funciones_cargo", ["cargo", "funcion", "archivo", "pagina", "fragmento", "verificacion"], [
                {**base, "cargo": c, "funcion": f"Función de {c}.", "fragmento": f"Función de {c}."}
                for c in ["Presidente Municipal", "Regidores", "Síndico", "Presidente Auxiliar", "Inspector de sección"]])
            gobierno._guardar(con, "comisiones", ["nombre", "temas", "archivo", "pagina", "fragmento", "verificacion"], [
                {**base, "nombre": "De Desarrollo Urbano, Obras y Servicios Públicos", "temas": "Obras y servicios",
                 "fragmento": "De Desarrollo Urbano"}])
            gobierno._guardar(con, "contacto_institucional",
                              ["oficina", "telefono", "direccion", "horario", "archivo", "pagina", "fragmento", "verificacion"], [
                {**base, "oficina": "PRESIDENCIA MUNICIPAL", "telefono": "2440000000", "direccion": None,
                 "horario": None, "fragmento": "PRESIDENCIA MUNICIPAL 2440000000"}])
            presupuesto.guardar(con, "pres.pdf", 10, [
                {"capitulo": "6000", "nombre": "Inversión Pública", "monto_mxn": 100.0, "pagina": 6,
                 "fragmento": "$100.00", "verificacion": "ok", "verificacion_nombre": "ok"}], (5, 6))
        cliente = TestClient(web.app)
        import re

        def visible(html_texto):
            return re.sub(r"<details.*?</details>", "", html_texto, flags=re.S)
        for ruta in ["/", "/donde", "/representantes?junta=1", "/temas", "/temas/baches",
                     "/revisar", "/revisar/3", "/gastos", "/actua"]:
            r = cliente.get(ruta)
            assert r.status_code == 200, (ruta, r.status_code)
            assert "corrupción" not in r.text.lower() and "robo" not in r.text.lower(), ruta
            v = visible(r.text)
            assert "sha-256" not in v.lower() and ".pdf" not in v.lower(), ruta  # lo técnico va en detalles
            for svg in re.findall(r"<svg[^>]*>", r.text):
                assert 'aria-label="' in svg or 'aria-hidden="true"' in svg, (ruta, svg)  # todo gráfico con texto alternativo
        rep = cliente.get("/representantes?junta=1").text
        # Del más cercano al más lejano: presidente auxiliar, regidora, presidenta.
        assert rep.index("Dario Auxiliar") < rep.index("Cora Regidora") < rep.index("Ana Presidenta")
        assert "Persona Inventada" not in rep  # nadie aparece si no está en la base con cita
        detalle = cliente.get("/temas/baches").text
        assert "De Desarrollo Urbano, Obras y Servicios Públicos" in detalle  # comisión con cita
        assert "Orientación general" in cliente.get("/temas/agua").text  # marcado cuando no es dato oficial
        assert "100 monedas" in cliente.get("/gastos").text


def test_monedas():
    """Las 100 monedas de /gastos suman exactamente 100, también en la página pintada."""
    import re
    import presupuesto
    import web
    from fastapi.testclient import TestClient
    # Repartos con residuos empujados: la suma debe ser 100 siempre.
    casos = [
        [{"id": i, "monto_mxn": m} for i, m in enumerate([1.0, 1.0, 1.0], 1)],
        [{"id": i, "monto_mxn": m} for i, m in enumerate([333.33, 333.33, 333.34], 1)],
        [{"id": i, "monto_mxn": m} for i, m in enumerate([10.0] * 7, 1)],
        [{"id": i, "monto_mxn": m} for i, m in enumerate([244_276_746.96, 150_000_000.0, 90_000_000.5, 1.0], 1)],
        [{"id": 1, "monto_mxn": 42.0}],
    ]
    for partidas in casos:
        monedas = web.monedas_100(partidas)
        assert sum(monedas.values()) == 100, monedas
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        with presupuesto.conectar() as con:
            presupuesto.guardar(con, "pres.pdf", 10, [
                {"capitulo": c, "nombre": n, "monto_mxn": m, "pagina": 6, "fragmento": "$1.00",
                 "verificacion": "ok", "verificacion_nombre": "ok"}
                for c, n, m in [("1000", "Servicios Personales", 333.33),
                                ("6000", "Inversión Pública", 333.33),
                                ("8000", "Participaciones y Aportaciones", 333.34)]], (5, 6))
        texto = TestClient(web.app).get("/gastos").text
        monedas_pintadas = len(re.findall(r'<i style="background:', texto))
        assert monedas_pintadas == 100, monedas_pintadas  # la cuadrícula pinta exactamente 100 monedas


def test_responsive_y_temas():
    """Escritorio sin contenedor principal < 640 px; claro y oscuro definen las mismas variables."""
    import re
    import web
    css = web.CSS
    escritorio = css.split("@media (min-width: 768px)", 1)[1]
    assert "max-width: 1120px" in escritorio  # el contenido crece en tablet y escritorio
    assert "nav.bottom { display: none; }" in escritorio  # arriba manda el menú, no la barra inferior
    assert "repeat(4,minmax(0,1fr))" in escritorio  # regidores: 4 columnas en escritorio, sin desbordar

    def variables(bloque):
        return set(re.findall(r"(--[a-z0-9-]+)\s*:", bloque))
    claro = variables(css.split(":root {", 1)[1].split("}", 1)[0])
    oscuro_media = variables(css.split(':root:not([data-theme="light"]) {', 1)[1].split("}", 1)[0])
    oscuro_forzado = variables(css.split(':root[data-theme="dark"] {', 1)[1].split("}", 1)[0])
    assert claro == oscuro_media == oscuro_forzado, (claro ^ oscuro_media, claro ^ oscuro_forzado)
    assert "data-theme" in web.pagina("x", "y").body.decode()  # el selector de tema llega a la página


def test_tarjeta_png_y_ceros():
    """La tarjeta PNG mide 1080x1350 y lleva la fuente; el 0 va con el número de documentos."""
    import io as _io
    import gobierno
    import web
    from fastapi.testclient import TestClient
    from PIL import Image
    png = web._tarjeta_png("0 diferencias encontradas", "Ana Presidenta", "Presidenta Municipal",
                           "g.pdf, página 4")
    with Image.open(_io.BytesIO(png)) as im:
        assert im.format == "PNG" and im.size == (1080, 1350), im.size
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        cols_f = ["nombre", "cargo", "comision", "archivo", "pagina", "fragmento", "verificacion"]
        base = {"archivo": "g.html", "pagina": 1, "verificacion": "ok"}
        acuerdo = {"acuerdo": "Se aprobó el Bando de Policía y Gobierno", "tipo_sesion": None, "fecha_sesion": None,
                   "propuesto_por": [], "monto_mxn": None, "proveedor": None, "resultado_votacion": None,
                   "pagina": 4, "fragmento": "Bando de Policía", "verificacion": "ok"}
        with gobierno.conectar() as con:
            extraer.guardar(con, "g.pdf", 9, [acuerdo], (1, 9))  # 1 documento en la tabla documentos
            gobierno._guardar(con, "funcionarios", cols_f, [
                {**base, "nombre": "Ana Presidenta", "cargo": "Presidenta Municipal", "comision": None,
                 "fragmento": "Ana Presidenta"}])
        cliente = TestClient(web.app)
        ficha = cliente.get("/revisar/1").text
        assert "en los 1 documentos revisados hasta hoy" in ficha  # ningún 0 aparece solo
        assert "Ayúdanos a revisar más" in ficha and "Compartir" in ficha and "wa.me" in ficha
        r = cliente.get("/compartir/funcionario/1.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        with Image.open(_io.BytesIO(r.content)) as im:
            assert im.size == (1080, 1350), im.size
        assert cliente.get("/compartir/funcionario/99.png").status_code == 404
        assert cliente.get("/compartir/hallazgo/99.png").status_code == 404


def test_buscador_nacional():
    """El buscador encuentra localidades con y sin acentos y distingue municipios ya revisados."""
    import municipios
    import web
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        with municipios.conectar() as con:
            con.executemany("INSERT INTO municipios VALUES (?, ?, ?, ?)",
                            [("15054", "México", "Metepec", "sin_revisar"),
                             ("21019", "Puebla", "Atlixco", "indexado")])
            con.executemany("INSERT INTO localidades VALUES (?, ?, ?, ?, ?, ?, ?)",
                            [("150540001", "15054", "Metepec", "Metepec", "México",
                              municipios.sin_acentos("Metepec"), municipios.sin_acentos("Metepec")),
                             ("210190001", "21019", "Atlixco de las Flores", "Atlixco", "Puebla",
                              municipios.sin_acentos("Atlixco de las Flores"), municipios.sin_acentos("Atlixco"))])
            con.commit()
            for texto in ("metepec", "Métepec", "METEPEC"):
                encontrados = municipios.buscar_localidades(con, texto)
                assert encontrados and encontrados[0]["clave_mun"] == "15054", texto
            assert municipios.buscar_localidades(con, "atlixco")[0]["estado_indexacion"] == "indexado"
            assert municipios.buscar_localidades(con, "ab") == []  # muy corto: no busca
        cliente = TestClient(web.app)
        r = cliente.get("/donde", params={"q": "metepec"})
        assert r.status_code == 200 and "/municipio/15054" in r.text
        r = cliente.get("/donde", params={"q": "Atlixco"})
        assert "/representantes?m=21019" in r.text and "Revisado" in r.text
        r = cliente.get("/municipio/15054")
        assert "Aún no revisamos Metepec" in r.text and "Todavía sin revisar" in r.text
        assert "Pídele a Muse que lo revise" in r.text
        assert cliente.get("/municipio/99999").status_code == 404


def test_marca_polaca_y_conteo_real():
    """Ninguna página dice 'Atlixco a la vista' y el inicio cuenta los municipios de la tabla, no un ejemplo."""
    import gobierno
    import municipios
    import web
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        with municipios.conectar() as con:
            con.executemany("INSERT INTO municipios VALUES (?, ?, ?, ?)",
                            [("15054", "México", "Metepec", "sin_revisar"),
                             ("21019", "Puebla", "Atlixco", "indexado")])
            con.commit()
        with gobierno.conectar() as con:
            gobierno._guardar(con, "funcionarios",
                              ["nombre", "cargo", "comision", "archivo", "pagina", "fragmento", "verificacion"],
                              [{"nombre": "Ana Presidenta", "cargo": "Presidenta Municipal", "comision": None,
                                "archivo": "g.html", "pagina": 1, "fragmento": "Ana Presidenta", "verificacion": "ok"}])
        cliente = TestClient(web.app)
        inicio = cliente.get("/").text
        assert "POLACA" in inicio and "La política no te ignora" in inicio
        assert "de 2 municipios revisados" in inicio  # 2 en la tabla, 1 indexado: conteo real, no el del mockup
        for ruta in ["/", "/donde", "/representantes", "/temas", "/gastos", "/actua",
                     "/municipio/15054", "/indexando/15054", "/revisar/1", "/acuerdos", "/presupuesto"]:
            r = cliente.get(ruta)
            assert r.status_code == 200, ruta
            assert "Atlixco a la vista" not in r.text, ruta
            assert "POLACA" in r.text, ruta


def test_grid_columnas_siempre_con_minmax():
    """Ninguna columna grid usa fr sin minmax(0, …): el contenido largo no debe desbordar la página."""
    import re
    import web
    for decl in re.findall(r"grid-template-columns:\s*([^;]+);", web.CSS):
        resto = re.sub(r"minmax\(\s*0\s*,\s*[\d.]+fr\s*\)", "", decl)
        assert "fr" not in resto, decl
    assert "40px minmax(0,1fr)" in web.CSS  # los eventos en vivo, con URLs largas


def test_solicitar_en_indexando_no_duplica():
    """Si Muse ya está revisando, pedir de nuevo no crea otra solicitud ni pisa el estado."""
    import municipios
    import web
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        with municipios.conectar() as con:
            con.execute("INSERT INTO municipios VALUES ('15054', 'México', 'Metepec', 'indexando')")
            con.commit()
        cliente = TestClient(web.app, follow_redirects=False)
        r = cliente.post("/solicitar/15054")
        assert r.status_code == 303 and r.headers["location"] == "/indexando/15054"
        with municipios.conectar() as con:
            assert con.execute("SELECT count(*) FROM solicitudes").fetchone()[0] == 0
            assert con.execute("SELECT estado_indexacion FROM municipios WHERE clave_inegi = '15054'").fetchone()[0] == "indexando"
        pagina_mun = cliente.get("/municipio/15054").text
        assert "Ya estamos revisando Metepec" in pagina_mun and "Ver la revisión en vivo" in pagina_mun
        assert 'action="/solicitar' not in pagina_mun  # sin formulario mientras Muse trabaja


def test_solicitudes_pendientes_no_se_duplican():
    """Máximo una solicitud pendiente por municipio: ni doble envío ni inserción directa la duplican."""
    import sqlite3
    import municipios
    import web
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        with municipios.conectar() as con:
            con.execute("INSERT INTO municipios VALUES ('15054', 'México', 'Metepec', 'sin_revisar')")
            con.commit()
            con.execute("INSERT INTO solicitudes (clave_inegi, estado, creada) VALUES ('15054', 'pendiente', '2026-01-01')")
            con.commit()
            try:
                con.execute("INSERT INTO solicitudes (clave_inegi, estado, creada) VALUES ('15054', 'pendiente', '2026-01-01')")
                raise AssertionError("la segunda pendiente debió chocar con el índice único")
            except sqlite3.IntegrityError:
                con.rollback()
        cliente = TestClient(web.app)
        cliente.post("/solicitar/15054")
        cliente.post("/solicitar/15054")  # doble envío del formulario
        with municipios.conectar() as con:
            assert con.execute("SELECT count(*) FROM solicitudes WHERE estado = 'pendiente'").fetchone()[0] == 1


def test_municipio_ya_aprobado_no_repite_peticion():
    """Un municipio ya aprobado una vez (revisión detenida) no genera otra petición desde el botón."""
    import municipios
    import web
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        with municipios.conectar() as con:
            con.execute("INSERT INTO municipios VALUES ('15054', 'México', 'Metepec', 'error')")
            con.execute("INSERT INTO solicitudes (clave_inegi, estado, creada) VALUES ('15054', 'aprobada', '2026-01-01')")
            con.commit()
        cliente = TestClient(web.app, follow_redirects=False)
        r = cliente.post("/solicitar/15054")
        assert r.status_code == 303 and r.headers["location"] == "/indexando/15054"
        with municipios.conectar() as con:
            assert con.execute("SELECT count(*) FROM solicitudes").fetchone()[0] == 1  # ninguna nueva
            assert con.execute("SELECT estado_indexacion FROM municipios WHERE clave_inegi = '15054'").fetchone()[0] == "error"
        pagina_mun = cliente.get("/municipio/15054").text
        assert "La revisión se detuvo" in pagina_mun and "Ver lo que pasó" in pagina_mun
        assert 'action="/solicitar' not in pagina_mun  # sin botón para repetir la misma petición


def test_solicitud_sin_aprobacion_no_dispara_agente():
    """Sin token no hay /admin; rechazar nunca lanza el agente; aprobar lo lanza una sola vez."""
    import os
    import municipios
    import web
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory() as d:
        extraer.DB = Path(d) / "t.db"
        extraer.RAW = Path(d)
        (Path(d) / "manifiesto.json").write_text("[]")
        with municipios.conectar() as con:
            con.execute("INSERT INTO municipios VALUES ('15054', 'México', 'Metepec', 'sin_revisar')")
            con.commit()
        lanzadas = []
        original = web._lanzar_indexador
        web._lanzar_indexador = lanzadas.append
        os.environ["ADMIN_TOKEN"] = "token-de-prueba"
        try:
            cliente = TestClient(web.app, raise_server_exceptions=False)
            r = cliente.post("/solicitar/15054", follow_redirects=False)
            assert r.status_code == 303 and lanzadas == []  # pedir no dispara nada
            assert "token" in cliente.get("/admin").text.lower()  # sin token: formulario, no la lista
            assert cliente.post("/admin/decision", data={"token": "malo", "solicitud": 1,
                                                         "decision": "aprobar"}).status_code == 403
            assert lanzadas == []
            with municipios.conectar() as con:
                sid = con.execute("SELECT id FROM solicitudes WHERE estado = 'pendiente'").fetchone()[0]
            cliente.post("/admin/decision", data={"token": "token-de-prueba", "solicitud": sid,
                                                  "decision": "rechazar"})
            assert lanzadas == []  # rechazar tampoco
            cliente.post("/solicitar/15054", follow_redirects=False)
            with municipios.conectar() as con:
                sid = con.execute("SELECT id FROM solicitudes WHERE estado = 'pendiente'").fetchone()[0]
            cliente.post("/admin/decision", data={"token": "token-de-prueba", "solicitud": sid,
                                                  "decision": "aprobar"})
            assert lanzadas == ["15054"]  # solo la aprobación humana lo dispara
            with municipios.conectar() as con:
                assert con.execute("SELECT estado_indexacion FROM municipios WHERE clave_inegi = '15054'"
                                   ).fetchone()[0] == "indexando"
                assert con.execute("SELECT count(*) FROM eventos_indexacion WHERE clave_inegi = '15054'"
                                   ).fetchone()[0] == 1
            assert cliente.get("/indexando/15054").status_code == 200
        finally:
            web._lanzar_indexador = original
            os.environ.pop("ADMIN_TOKEN", None)


def test_indexador_filtros_y_topes():
    """El agente descarta dominios que no son .gob.mx y se detiene al llegar al tope de gasto."""
    import indexar
    assert indexar.es_gob_mx("https://cuetzalan.gob.mx/gaceta.pdf")
    assert indexar.es_gob_mx("https://transparencia.atlixco.gob.mx/x")
    assert indexar.es_gob_mx("http://gob.mx/")
    assert not indexar.es_gob_mx("https://dawhois.com/domain/cuetzalan.gob.mx.html")
    assert not indexar.es_gob_mx("https://gob.mx.ejemplo.com/")
    assert not indexar.es_gob_mx("https://www.gob.mx@ejemplo.com/")
    assert not indexar.es_gob_mx("sin-url")
    resp = {"output": [
        {"type": "web_search_call", "results": [
            {"url": "https://dawhois.com/domain/cuetzalan.gob.mx.html", "title": "whois"},
            {"url": "https://cuetzalan.gob.mx/Gaceta/gaceta_2026.pdf", "title": "Gaceta municipal"}]},
        {"type": "message", "content": [{"text": "ver https://ejemplo.com/gaceta.pdf", "annotations": []}]}]}
    candidatas = indexar.urls_de_respuesta(resp)
    assert indexar.elegir(candidatas, ["gaceta"], pdf=True) == "https://cuetzalan.gob.mx/Gaceta/gaceta_2026.pdf"
    assert indexar.elegir(candidatas, ["presupuesto"], pdf=True) is None  # sin fuente, no inventa
    # Confusión de municipios: la candidata que menciona al municipio va primero y la
    # lista conserva a las demás para reintentar si el documento resulta de otro lugar.
    confusas = [("https://zihuatanejo.gob.mx/gaceta/GACETA_MUNICIPAL.pdf", "Gaceta municipal extraordinaria"),
                ("https://cuernavaca.gob.mx/gaceta/gaceta_cuernavaca.pdf", "Gaceta del Ayuntamiento de Cuernavaca")]
    orden = indexar.elegir_candidatas(confusas, ["gaceta"], pdf=True, nombre="Cuernavaca")
    assert orden[0].startswith("https://cuernavaca.gob.mx") and len(orden) == 2
    assert indexar.elegir(confusas, ["gaceta"], pdf=True, nombre="Cuernavaca") == orden[0]
    # El dominio propio gana aunque otra candidata repita más palabras clave en su texto.
    mezcladas = [("https://www.tepalcingomorelos.gob.mx/presupuesto-egresos.pdf",
                  "Presupuesto de egresos presupuesto egresos aprobado"),
                 ("https://transparenciacuernavaca.gob.mx/docs/presupuesto.pdf", "Presupuesto")]
    assert indexar.elegir(mezcladas, ["presupuesto", "egresos"], pdf=True,
                          nombre="Cuernavaca").startswith("https://transparenciacuernavaca.gob.mx")
    # Un .gob.mx de otro municipio no cuenta: el documento debe mencionar al municipio pedido.
    assert indexar.menciona_municipio("MUNICIPIO DE CUETZALAN DEL PROGRESO, Estado de Puebla", "Cuetzalan del Progreso")
    assert not indexar.menciona_municipio("MUNICIPIO DE PROGRESO, Estado de Yucatán", "Cuetzalan del Progreso")
    with tempfile.TemporaryDirectory() as d:
        llm.LOG_COSTOS = Path(d) / "costos.jsonl"
        inicio = "2026-10-27T00:00:00+00:00"
        llm.LOG_COSTOS.write_text('{"ts": "2026-10-27T01:00:00+00:00", "usd": 0.40}\n')
        indexar.verificar_topes(inicio)  # bajo el tope: no lanza
        llm.LOG_COSTOS.write_text('{"ts": "2026-10-27T01:00:00+00:00", "usd": 1.50}\n')
        try:
            indexar.verificar_topes(inicio)
            raise AssertionError("debió detenerse al llegar al tope por municipio")
        except indexar.TopeAlcanzado:
            pass


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            f()
            print("ok", nombre)
