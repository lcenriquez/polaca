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


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            f()
            print("ok", nombre)
