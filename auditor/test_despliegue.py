"""Pruebas sin red del pase a producción (docs/deploy-pendientes.md): python auditor/test_despliegue.py"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

AUDITOR = Path(__file__).resolve().parent


def _rutas(data_dir: str | None) -> list[str]:
    env = {**os.environ, "PYTHONPATH": str(AUDITOR)}
    if data_dir:
        env["DATA_DIR"] = data_dir
    else:
        env.pop("DATA_DIR", None)
    codigo = ("import extraer, llm, evidencia, descargar\n"
              "print(extraer.DB)\nprint(extraer.RAW)\nprint(llm.CACHE)\n"
              "print(llm.LOG_COSTOS)\nprint(evidencia.EVIDENCIA)\nprint(descargar.RAW)\n")
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, env=env, cwd=AUDITOR)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


def test_data_dir_env():
    """Con DATA_DIR, base/caché/costos/subidas/raw salen de ahí; sin ella, de datos/ del repo."""
    with tempfile.TemporaryDirectory() as d:
        assert _rutas(d) == [f"{d}/auditor.db", f"{d}/raw", f"{d}/cache",
                             f"{d}/costos.jsonl", f"{d}/evidencia", f"{d}/raw"]
    local = _rutas(None)
    assert local[0].endswith("datos/auditor.db") and local[2].endswith("datos/cache")
    assert local[3].endswith("datos/costos.jsonl") and local[4].endswith("datos/evidencia")


def _cliente(d: str):
    """TestClient con la base en un tmp (mismo patrón que test_auditor.test_web)."""
    import extraer
    import cruzar
    import evidencia
    extraer.DB = Path(d) / "t.db"
    extraer.RAW = Path(d)
    evidencia.EVIDENCIA = Path(d) / "evidencia"
    with cruzar.conectar():
        pass
    import web
    from fastapi.testclient import TestClient
    return TestClient(web.app, follow_redirects=False)


def test_cabeceras_seguridad():
    with tempfile.TemporaryDirectory() as d:
        r = _cliente(d).get("/")
        assert r.status_code == 200
        csp = r.headers["content-security-policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert "http" not in csp  # ningún host externo
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
        r404 = _cliente(d).get("/no-existe")
        assert r404.headers["x-content-type-options"] == "nosniff"  # también en errores


def test_limites_por_ip():
    import web
    with tempfile.TemporaryDirectory() as d:
        cliente = _cliente(d)
        web._hits.clear()
        tope = web._LIMITES["solicitar"]
        web._LIMITES["solicitar"] = 3
        try:
            for _ in range(3):
                assert cliente.post("/solicitar/99999").status_code == 404  # pasa el límite, no el municipio
            r = cliente.post("/solicitar/99999")
            assert r.status_code == 429 and "Espera un minuto" in r.text
            # Otra ruta no comparte contador:
            assert cliente.get("/donde", params={"q": "x"}).status_code == 200
            # La búsqueda también tiene tope:
            web._LIMITES["buscar"] = 2
            cliente.get("/donde", params={"q": "x"})
            cliente.get("/donde", params={"q": "x"})
            assert cliente.get("/donde", params={"q": "x"}).status_code == 429
            # Sin q no es búsqueda: no cuenta.
            assert cliente.get("/donde").status_code == 200
        finally:
            web._LIMITES["solicitar"] = tope
            web._LIMITES["buscar"] = 60
            web._hits.clear()


def test_subida_maximo_10mb():
    import web
    with tempfile.TemporaryDirectory() as d:
        cliente = _cliente(d)
        web._hits.clear()
        grande = b"\xff\xd8\xff" + b"x" * (10 * 1024 * 1024)
        r = cliente.post("/evidencia", files={"foto": ("grande.jpg", grande, "image/jpeg")},
                         data={"objeto": "bache"})
        assert r.status_code == 413 and "10 MB" in r.text  # se rechaza antes de llamar a la API
        # Una foto chica no-JPEG/PNG sigue rechazada por tipo, no por tamaño:
        r = cliente.post("/evidencia", files={"foto": ("nota.txt", b"hola", "text/plain")},
                         data={"objeto": "bache"})
        assert r.status_code == 400


def test_salud():
    with tempfile.TemporaryDirectory() as d:
        r = _cliente(d).get("/salud")
        assert r.status_code == 200 and r.json() == {"estado": "ok"}
        assert r.headers["x-content-type-options"] == "nosniff"


def test_admin_requiere_token_largo():
    import web
    previo = os.environ.get("ADMIN_TOKEN")
    with tempfile.TemporaryDirectory() as d:
        cliente = _cliente(d)
        try:
            os.environ.pop("ADMIN_TOKEN", None)
            assert cliente.get("/admin").status_code == 404  # sin token configurado, /admin no existe
            assert cliente.post("/admin/decision", data={"token": "x", "solicitud": 1,
                                                         "decision": "rechazar"}).status_code == 404
            os.environ["ADMIN_TOKEN"] = "corto"
            assert cliente.get("/admin").status_code == 404  # menos de 32 caracteres: igual
            os.environ["ADMIN_TOKEN"] = "t" * 32
            web._hits.clear()
            r = cliente.get("/admin")
            assert r.status_code == 200 and "token" in r.text.lower()  # activo: pide el token
            assert cliente.post("/admin/decision", data={"token": "malo", "solicitud": 1,
                                                         "decision": "rechazar"}).status_code == 403
        finally:
            if previo is None:
                os.environ.pop("ADMIN_TOKEN", None)
            else:
                os.environ["ADMIN_TOKEN"] = previo


def test_revisar_privacidad():
    """El script de privacidad sale 1 con datos personales y 0 con contacto solo institucional."""
    import sqlite3
    script = Path(__file__).resolve().parent.parent / "scripts" / "revisar_privacidad.py"
    with tempfile.TemporaryDirectory() as d:
        ruta = Path(d) / "t.db"
        con = sqlite3.connect(ruta)
        con.executescript("""
            CREATE TABLE acuerdos (fragmento TEXT);
            CREATE TABLE funcionarios (correo TEXT, telefono TEXT);
            CREATE TABLE contacto_institucional (telefono TEXT);
            CREATE TABLE documentos (sha256 TEXT);
            INSERT INTO funcionarios VALUES ('oficina@cuernavaca.gob.mx', '777 000 0000');
            INSERT INTO contacto_institucional VALUES ('244 000 0000');
            INSERT INTO documentos VALUES ('a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2');
        """)
        con.commit()
        con.close()
        r = subprocess.run([sys.executable, str(script), str(ruta)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout  # gob.mx, contacto institucional y un hash: no es hallazgo
        con = sqlite3.connect(ruta)
        con.execute("INSERT INTO acuerdos VALUES ('escriban a juan.perez@gmail.com o al 55 1234 5678')")
        con.commit()
        con.close()
        r = subprocess.run([sys.executable, str(script), str(ruta)], capture_output=True, text=True)
        assert r.returncode == 1 and r.stdout.count("REVISAR:") == 2, r.stdout
        assert "juan.perez" not in r.stdout and "1234" not in r.stdout  # salida enmascarada


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            f()
            print("ok", nombre)
