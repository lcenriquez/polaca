"""Cliente de Meta Model API (compatible con OpenAI) con caché en disco y registro de costos.

Toda llamada a Muse Spark pasa por `llamar()`: si el mismo request ya se hizo,
se devuelve la respuesta guardada y no se paga de nuevo.
"""
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "datos" / "cache"
LOG_COSTOS = RAIZ / "datos" / "costos.jsonl"

# Documentos públicos → Contributor (Meta puede entrenar con ellos, 12x más barato).
# Fotos ciudadanas → Standard (no se usan para entrenar).
MODELO_PUBLICO = os.environ.get("MUSE_MODEL_PUBLICO", "muse-spark-1.3-contributor")
MODELO_PRIVADO = os.environ.get("MUSE_MODEL_PRIVADO", "muse-spark-1.3")

# USD por millón de tokens: (entrada, entrada en caché, salida).
# Fuente: https://dev.meta.ai/docs/pricing-rate-limits (consultado 2026-10-26)
PRECIOS = {
    "muse-spark-1.3": (1.25, 0.15, 4.25),
    "muse-spark-1.3-contributor": (0.10, 0.002, 0.20),
}


def _cargar_env():
    env = RAIZ / ".env"
    if env.exists():
        for linea in env.read_text().splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                k, v = linea.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_cargar_env()  # al importar: web.py necesita ADMIN_TOKEN sin esperar a la primera llamada a la API


def costo_usd(modelo: str, uso: dict) -> float:
    entrada, en_cache, salida = PRECIOS[modelo]
    cacheados = (uso.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    return (
        (uso["prompt_tokens"] - cacheados) * entrada
        + cacheados * en_cache
        + uso["completion_tokens"] * salida
    ) / 1e6


_cliente = None


def llamar(etiqueta: str, **kwargs) -> dict:
    """Ejecuta chat.completions.create(**kwargs) con caché. Devuelve la respuesta como dict."""
    clave = hashlib.sha256(json.dumps(kwargs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    archivo = CACHE / f"{clave}.json"
    if archivo.exists():
        return json.loads(archivo.read_text())

    global _cliente
    if _cliente is None:
        _cargar_env()
        _cliente = OpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["META_API_KEY"], max_retries=3)
    inicio = time.monotonic()
    resp = _cliente.chat.completions.create(**kwargs).model_dump()
    CACHE.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps(resp, ensure_ascii=False))

    uso = resp["usage"]
    registro = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "etiqueta": etiqueta,
        "modelo": kwargs["model"],
        "prompt_tokens": uso["prompt_tokens"],
        "completion_tokens": uso["completion_tokens"],
        "cached_tokens": (uso.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
        "usd": round(costo_usd(kwargs["model"], uso), 6),
        "segundos": round(time.monotonic() - inicio, 1),
        "cache": clave[:12],
    }
    with LOG_COSTOS.open("a") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return resp


# USD por imagen, según https://dev.meta.ai/docs/pricing-rate-limits (sam-3.1: $2.50 / 1,000 imágenes).
PRECIOS_IMAGEN = {"sam-3.1": 2.50 / 1_000}


def llamar_responses(etiqueta: str, imagenes: int = 1, **kwargs) -> dict:
    """Responses API (p. ej. SAM 3.1, que no usa chat.completions) con la misma caché y registro que llamar().

    El costo es plano por imagen, no por tokens.
    """
    clave = hashlib.sha256(json.dumps(kwargs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    archivo = CACHE / f"{clave}.json"
    if archivo.exists():
        return json.loads(archivo.read_text())

    global _cliente
    if _cliente is None:
        _cargar_env()
        _cliente = OpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["META_API_KEY"], max_retries=3)
    inicio = time.monotonic()
    resp = _cliente.responses.create(**kwargs).model_dump()
    CACHE.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps(resp, ensure_ascii=False))

    registro = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "etiqueta": etiqueta,
        "modelo": kwargs["model"],
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
        "imagenes": imagenes,
        "usd": round(PRECIOS_IMAGEN[kwargs["model"]] * imagenes, 6),
        "segundos": round(time.monotonic() - inicio, 1),
        "cache": clave[:12],
    }
    with LOG_COSTOS.open("a") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return resp


def llamar_responses_texto(etiqueta: str, **kwargs) -> dict:
    """Responses API para texto (p. ej. búsqueda web con tools=[{"type": "web_search"}]).

    Misma caché y registro de costos que llamar(); el costo se calcula por tokens
    con PRECIOS, igual que en chat completions. La búsqueda web solo existe en
    Responses/Messages, no en Chat Completions (dev.meta.ai/docs/search-grounding).
    """
    clave = hashlib.sha256(json.dumps(kwargs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    archivo = CACHE / f"{clave}.json"
    if archivo.exists():
        return json.loads(archivo.read_text())

    global _cliente
    if _cliente is None:
        _cargar_env()
        _cliente = OpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["META_API_KEY"], max_retries=3)
    inicio = time.monotonic()
    resp = _cliente.responses.create(**kwargs).model_dump()
    CACHE.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps(resp, ensure_ascii=False))

    uso = resp.get("usage") or {}
    uso_norm = {"prompt_tokens": uso.get("input_tokens", 0),
                "completion_tokens": uso.get("output_tokens", 0),
                "prompt_tokens_details": {"cached_tokens": (uso.get("input_tokens_details") or {}).get("cached_tokens", 0)}}
    registro = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "etiqueta": etiqueta,
        "modelo": kwargs["model"],
        "prompt_tokens": uso_norm["prompt_tokens"],
        "completion_tokens": uso_norm["completion_tokens"],
        "cached_tokens": uso_norm["prompt_tokens_details"]["cached_tokens"],
        "usd": round(costo_usd(kwargs["model"], uso_norm), 6),
        "segundos": round(time.monotonic() - inicio, 1),
        "cache": clave[:12],
    }
    with LOG_COSTOS.open("a") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return resp


def resumen_costos() -> dict:
    if not LOG_COSTOS.exists():
        return {"llamadas": 0, "usd": 0.0}
    filas = [json.loads(l) for l in LOG_COSTOS.read_text().splitlines() if l.strip()]
    return {
        "llamadas": len(filas),
        "prompt_tokens": sum(f["prompt_tokens"] for f in filas),
        "completion_tokens": sum(f["completion_tokens"] for f in filas),
        "usd": round(sum(f["usd"] for f in filas), 4),
    }


if __name__ == "__main__":
    if sys.argv[1:] == ["costos"]:
        print(json.dumps(resumen_costos(), indent=2))
