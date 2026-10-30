"""Pruebas sin red ni costo de contratos y sus hallazgos: python auditor/test_contratos.py"""
import json
import tempfile
from pathlib import Path

import extraer


def _base(d):
    extraer.DB = Path(d) / "t.db"
    extraer.RAW = Path(d)
    (Path(d) / "manifiesto.json").write_text("[]")
    import cruzar
    return cruzar.conectar()


def _contrato(**kw):
    c = {"numero": "AC/SADMON/DGRM/DA/LP/010/2026", "objeto": "Adquisición de patrullas", "proveedor": None,
         "monto_con_iva_mxn": None, "monto_sin_iva_mxn": None, "fecha": "2026-08-31", "procedimiento": "licitacion",
         "area_solicitante": "Secretaría de Protección", "partida_presupuestal": None, "pagina": 1,
         "fragmento": "LP/010/2026", "verificacion": "ok"}
    return {**c, **kw}


def _tipos(con, tipo):
    import cruzar
    return [h for h in cruzar.generar(con) + cruzar.cruzar_pmd(con) if h["tipo"] == tipo]


def test_utilidades():
    import contratos
    assert contratos.capitulo("5411") == "5000" and contratos.capitulo("6000") == "6000"
    assert contratos.capitulo("Servicios") is None and contratos.capitulo(None) is None
    assert contratos.clave_numero("AC/SADMON/LP-010/2026") == contratos.clave_numero("ac sadmon lp 010 2026")
    assert contratos.clave_numero("A-2") is None  # clave corta: coincidiría por casualidad


def test_extraer_tramo_verifica_fragmento():
    """Muse simulado: el fragmento literal queda ok; el armado con celdas juntas, no_encontrado."""
    import contratos
    import llm
    from pypdf import PdfWriter
    with tempfile.TemporaryDirectory() as d:
        w = PdfWriter()
        w.add_blank_page(100, 100)
        ruta = Path(d) / "x.pdf"
        w.write(ruta)
        from pypdf import PdfReader
        reader = PdfReader(ruta)
        reader.pages[0].extract_text = lambda: "LICITACIÓN AC/SADMON/LP/010/2026 Adquisición de patrullas"
        reader.pages[0].extract_text = lambda: ("LICITACIÓN AC/SADMON/LP/010/2026 Adquisición de patrullas "
                                                "$ 1,425,464.92")
        filas = [_contrato(fragmento="AC/SADMON/LP/010/2026"), _contrato(fragmento="Objeto de la licitación pública"),
                 _contrato(fragmento="AC/SADMON/LP/010/2026", monto_planeado_mxn=1425464.92),
                 _contrato(fragmento="AC/SADMON/LP/010/2026", monto_con_iva_mxn=999.0)]  # monto que no está impreso
        original = llm.llamar
        llm.llamar = lambda *a, **k: {"choices": [{"message": {"content": json.dumps({"contratos": filas})}}]}
        try:
            salida = contratos.extraer_tramo("x.pdf", reader, 1, 1)
        finally:
            llm.llamar = original
        assert [f["verificacion"] for f in salida] == ["ok", "no_encontrado", "ok", "no_encontrado"]


def test_monto_difiere_entre_fuentes():
    import contratos
    with tempfile.TemporaryDirectory() as d:
        with _base(d) as con:
            contratos.guardar(con, "convocatoria.pdf", 1, [_contrato(monto_con_iva_mxn=1_000_000.0)], (1, 1), "17007")
            contratos.guardar(con, "fallo.pdf", 1, [_contrato(numero="AC SADMON DGRM DA LP 010 2026",
                                                              monto_con_iva_mxn=1_250_000.0, fragmento="$1,250,000.00")],
                              (1, 1), "17007")
            [h] = _tipos(con, "monto_difiere_entre_fuentes")
            assert "$1,000,000.00" in h["descripcion"] and "$1,250,000.00" in h["descripcion"]
            assert (h["archivo_presupuesto"], h["fragmento_presupuesto"]) == ("convocatoria.pdf", "LP/010/2026")
            assert (h["archivo_acuerdo"], h["fragmento_acuerdo"]) == ("fallo.pdf", "$1,250,000.00")
            # Mismo monto: no aplica.
            contratos.guardar(con, "fallo.pdf", 1, [_contrato(monto_con_iva_mxn=1_000_000.0)], (1, 1), "17007")
            assert _tipos(con, "monto_difiere_entre_fuentes") == []
            # Uno con IVA y otro sin IVA: no son comparables, no aplica.
            contratos.guardar(con, "fallo.pdf", 1, [_contrato(monto_sin_iva_mxn=862_068.97)], (1, 1), "17007")
            assert _tipos(con, "monto_difiere_entre_fuentes") == []
            # Fragmento no verificado: no aplica.
            contratos.guardar(con, "fallo.pdf", 1, [_contrato(monto_con_iva_mxn=9.0, verificacion="no_encontrado")],
                              (1, 1), "17007")
            assert _tipos(con, "monto_difiere_entre_fuentes") == []
            # Proyecto de obra (MIDS) con el mismo folio y monto planeado distinto en dos reportes: aplica.
            contratos.guardar(con, "mids2023.pdf", 1, [_contrato(numero="36503", monto_planeado_mxn=1_000.0)], (1, 1), "21019")
            contratos.guardar(con, "mids2024.pdf", 1, [_contrato(numero="36503", monto_planeado_mxn=1_200.0)], (1, 1), "21019")
            [h] = _tipos(con, "monto_difiere_entre_fuentes")
            assert h["descripcion"].startswith("El proyecto 36503") and "(monto planeado)" in h["descripcion"]
            contratos.guardar(con, "mids2024.pdf", 1, [_contrato(numero="36503", monto_planeado_mxn=1_000.0)], (1, 1), "21019")
            assert _tipos(con, "monto_difiere_entre_fuentes") == []
            # Otro municipio con el mismo número: no aplica.
            contratos.guardar(con, "fallo.pdf", 1, [_contrato(monto_con_iva_mxn=9.0)], (1, 1), "21019")
            assert _tipos(con, "monto_difiere_entre_fuentes") == []


def test_monto_difiere_contra_acuerdo():
    import contratos
    with tempfile.TemporaryDirectory() as d:
        with _base(d) as con:
            contratos.guardar(con, "contratos.pdf", 1, [_contrato(monto_con_iva_mxn=500.0)], (1, 1), "17007")
            acuerdo = {"acuerdo": "Se autoriza el contrato AC/SADMON/DGRM/DA/LP/010/2026", "tipo_sesion": None,
                       "fecha_sesion": None, "propuesto_por": [], "monto_mxn": 800.0, "proveedor": None,
                       "resultado_votacion": None, "pagina": 3, "fragmento": "por $800.00", "verificacion": "ok"}
            extraer.guardar(con, "gaceta.pdf", 9, [acuerdo], (1, 9))
            con.execute("UPDATE acuerdos SET municipio_id = '17007'")
            [h] = _tipos(con, "monto_difiere_entre_fuentes")
            assert h["acuerdo_id"] and h["archivo_acuerdo"] == "gaceta.pdf" and "$800.00" in h["descripcion"]
            con.execute("UPDATE acuerdos SET monto_mxn = 500.0")
            assert _tipos(con, "monto_difiere_entre_fuentes") == []


def test_procedimiento_difiere():
    import contratos
    with tempfile.TemporaryDirectory() as d:
        with _base(d) as con:
            contratos.guardar(con, "a.pdf", 1, [_contrato()], (1, 1), "17007")
            contratos.guardar(con, "b.pdf", 1, [_contrato(procedimiento="adjudicacion_directa")], (1, 1), "17007")
            [h] = _tipos(con, "procedimiento_difiere")
            assert "como licitación en a.pdf" in h["descripcion"] and "como adjudicación directa en b.pdf" in h["descripcion"]
            assert h["archivo_presupuesto"] == "a.pdf" and h["archivo_acuerdo"] == "b.pdf"
            # Mismo procedimiento, o uno sin dato: no aplica.
            contratos.guardar(con, "b.pdf", 1, [_contrato()], (1, 1), "17007")
            assert _tipos(con, "procedimiento_difiere") == []
            contratos.guardar(con, "b.pdf", 1, [_contrato(procedimiento=None)], (1, 1), "17007")
            assert _tipos(con, "procedimiento_difiere") == []
            # Repetido dentro del MISMO documento: no es una segunda fuente.
            contratos.guardar(con, "a.pdf", 1, [_contrato(), _contrato(procedimiento="adjudicacion_directa")],
                              (1, 1), "17007")
            assert _tipos(con, "procedimiento_difiere") == []


def test_contratos_superan_capitulo():
    import contratos
    import presupuesto
    with tempfile.TemporaryDirectory() as d:
        with _base(d) as con:
            partida = {"capitulo": "5000", "nombre": "Bienes Muebles", "monto_mxn": 1_000.0, "pagina": 6,
                       "fragmento": "$1,000.00", "verificacion": "ok", "verificacion_nombre": "ok"}
            presupuesto.guardar(con, "PRESUPUESTO_EGRESOS_2026.pdf", 10, [partida], (1, 10))
            filas = [_contrato(numero="LP-0001-2026", partida_presupuestal="5411", monto_con_iva_mxn=700.0),
                     _contrato(numero="LP-0002-2026", partida_presupuestal="5151", monto_con_iva_mxn=600.0)]
            contratos.guardar(con, "contratos.pdf", 1, filas, (1, 1), None)
            [h] = _tipos(con, "contratos_superan_capitulo")
            assert "$1,300.00" in h["descripcion"] and "Diferencia: $300.00" in h["descripcion"]
            assert h["archivo_presupuesto"] == "PRESUPUESTO_EGRESOS_2026.pdf" and h["archivo_acuerdo"] == "contratos.pdf"
            # Suma dentro de lo presupuestado: no aplica.
            filas[1]["monto_con_iva_mxn"] = 300.0
            contratos.guardar(con, "contratos.pdf", 1, filas, (1, 1), None)
            assert _tipos(con, "contratos_superan_capitulo") == []
            # Otro año u otro capítulo: no se suman contra 2026 / 5000.
            filas[1].update(monto_con_iva_mxn=600.0, fecha="2025-03-01")
            contratos.guardar(con, "contratos.pdf", 1, filas, (1, 1), None)
            assert _tipos(con, "contratos_superan_capitulo") == []
            filas[1].update(fecha="2026-03-01", partida_presupuestal="6141")
            contratos.guardar(con, "contratos.pdf", 1, filas, (1, 1), None)
            assert _tipos(con, "contratos_superan_capitulo") == []


def test_promesa_sin_registro():
    import contratos
    with tempfile.TemporaryDirectory() as d:
        with _base(d) as con:
            meta = {"meta": "Instalar 5,000 luminarias LED", "tema": "luminarias LED", "cantidad": 5000.0,
                    "unidad": "luminarias", "pagina": 40, "fragmento": "5,000 luminarias", "verificacion": "ok"}
            contratos.guardar(con, "PMD.pdf", 120, [meta], (1, 120), "21019", pmd=True)
            [h] = _tipos(con, "promesa_sin_registro")
            assert "No se encontró en los" in h["descripcion"] and "no indica incumplimiento" in h["descripcion"]
            assert h["archivo_presupuesto"] == "PMD.pdf" and h["pagina_presupuesto"] == 40
            # Un contrato del mismo municipio que la nombra (aun en singular): no aplica.
            contratos.guardar(con, "c.pdf", 1, [_contrato(objeto="Suministro de luminaria LED")], (1, 1), "21019")
            assert _tipos(con, "promesa_sin_registro") == []
            # Si el contrato es de otro municipio, la meta sigue sin registro.
            contratos.guardar(con, "c.pdf", 1, [_contrato(objeto="Suministro de luminaria LED")], (1, 1), "17007")
            assert len(_tipos(con, "promesa_sin_registro")) == 1
            # Meta con cita no verificada: no aplica.
            contratos.guardar(con, "PMD.pdf", 120, [{**meta, "verificacion": "no_encontrado"}], (1, 120), "21019", pmd=True)
            assert _tipos(con, "promesa_sin_registro") == []


def test_concentracion_es_descriptiva():
    """Muchos contratos a un proveedor no generan hallazgo: solo un dato descriptivo."""
    import contratos
    import cruzar
    with tempfile.TemporaryDirectory() as d:
        with _base(d) as con:
            filas = [_contrato(numero=f"LP-000{i}-2026", proveedor="Proveedor Uno", monto_con_iva_mxn=100.0)
                     for i in range(4)] + [_contrato(numero="LP-0009-2026", proveedor="Proveedor Dos", monto_con_iva_mxn=100.0)]
            contratos.guardar(con, "c.pdf", 1, filas, (1, 1), "17007")
            assert cruzar.generar(con) + cruzar.cruzar_pmd(con) == []
            [uno, dos] = cruzar.concentracion_proveedores(con)
            assert (uno["proveedor"], uno["contratos"], uno["proporcion"]) == ("Proveedor Uno", 4, 0.8)
            assert dos["proporcion"] == 0.2


def test_lenguaje_neutral():
    import re
    textos = Path(__file__).with_name("contratos.py").read_text() + Path(__file__).with_name("cruzar.py").read_text()
    assert not re.search(r"corrupci|irregular|desv[ií]o", textos, re.I)


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            f()
            print("ok", nombre)
