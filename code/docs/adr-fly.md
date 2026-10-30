# ADR: despliegue de la demo en Fly.io

- Estado: sustituido por Render (Fly pide tarjeta; no se usa) — ver deploy-render.md
- Fecha: 2026-10-29

## Decisión

La demo se despliega en Fly.io: una sola máquina siempre encendida en la
región `qro` (Querétaro), con un volumen persistente montado en `/data`
donde vive SQLite (`DATA_DIR=/data`). Configuración en `fly.toml`,
imagen en `Dockerfile`, guía en [deploy-fly.md](deploy-fly.md).

## Por qué Fly.io

- Región `qro`: la más cercana a las personas usuarias en México; menos
  latencia que un proveedor con solo regiones en EE. UU.
- Volumen persistente simple: SQLite no necesita un servicio de base de
  datos aparte para la demo (sin costo ni operación extra).
- Máquina siempre encendida con `min_machines_running = 1` y sin
  auto-stop: el agente corre en segundo plano y no puede despertar
  bajo demanda; además SQLite exige una sola escritora.
- Secretos fuera del repo con `fly secrets set`; la imagen no contiene
  datos ni secretos.

## Costo estimado mensual

1 máquina pequeña encendida 24/7 + volumen de 1 GB, precios de lista
aproximados (verificar en fly.io/pricing antes de comprometer gasto):

| Concepto | Estimado |
|---|---|
| Máquina `shared-cpu-1x`, 512 MB RAM, siempre encendida | ~US$4/mes |
| Volumen 1 GB | ~US$0.15/mes |
| Transferencia y extras menores | ~US$0–2/mes |
| **Total** | **~US$4–6/mes** |

## Límites (por qué es solo demo)

- **Una sola máquina y una sola escritora SQLite**: no escala horizontal;
  dos máquinas escribiendo el mismo volumen corromperían la base.
- **Volumen atado a la región/máquina**: sin réplica ni respaldo
  automático; una falla del volumen pierde la base (hay que respaldar
  `auditor.db` a mano).
- **1 GB crece rápido**: hoy `auditor.db` + `raw/` ocupan ~111 MB, pero
  cada indexación suma; vigilar el uso y ampliar el volumen a tiempo.
- **Sin cambios de código de producción todavía**: faltan `DATA_DIR`
  aplicado en todo el código, cabeceras de seguridad y límites de
  subida/peticiones — ver [deploy-pendientes.md](deploy-pendientes.md).
  Hasta entonces, la demo no debe exponerse como servicio público
  definitivo.
- **Cold paths**: si alguien activa auto-stop por error, el agente en
  segundo plano se detiene y las solicitudes se pierden.
