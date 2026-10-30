# Guía de despliegue de la demo en Render

Render despliega desde GitHub con el blueprint `render.yaml` de la raíz:
un servicio web Docker, plan free, rama `hackathon-meta`, sin disco
persistente. La imagen lleva los datos semilla (`datos/semilla/`): al
arrancar, si `DATA_DIR` (`/tmp/polaca`) no tiene `auditor.db`, la app
copia ahí la base y las fuentes; nunca sobrescribe una base existente.

## Pasos en render.com

1. **New → Blueprint** y elige el repo `lcenriquez/polaca`.
2. Confirma la rama `hackathon-meta`. Render lee `render.yaml` y propone
   el servicio `polaca` (Docker, plan free, health check `/salud`).
3. Cuando pida las variables marcadas `sync: false`, captura:
   - `META_API_KEY`: la clave de la API de Meta.
   - `ADMIN_TOKEN`: al menos 32 caracteres (con menos, `/admin` no existe).
4. **Apply**. El primer despliegue tarda unos minutos en construir la
   imagen; los siguientes son automáticos con cada push a la rama.

## Notas de operación

- **Arranque en frío:** en el plan free el servicio duerme tras ~15 min
  sin tráfico; la primera visita después tarda alrededor de 1 min.
- **Datos volátiles:** sin disco persistente, lo que se escriba en
  tiempo de ejecución (solicitudes nuevas, evidencia ciudadana) se
  pierde al reiniciar; el sitio vuelve a la copia semilla de la imagen.
  `/admin` muestra este aviso. Para actualizar los datos públicos, se
  regenera `datos/semilla/` y se vuelve a desplegar.
- **No se usa Fly.io** (`fly.toml` y `deploy-fly.md` quedan como
  referencia: Fly pide tarjeta) **ni Hugging Face Spaces** (su SDK
  Docker ya no es gratuito).
