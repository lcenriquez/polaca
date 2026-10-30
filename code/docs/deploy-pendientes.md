# Pendientes de código en `auditor/` para producción

Cambios que faltan **dentro de `auditor/`** antes de considerar la demo
un servicio público. Se harán después, cuando la sesión que estabiliza
`auditor/` termine (hoy ese directorio no se toca desde esta sesión).
El despliegue de Fly.io ya está preparado (`fly.toml`, `Dockerfile`)
asumiendo estos cambios.

## 1. Leer `DATA_DIR` para todo lo persistente

- [x] La base SQLite, `datos/` y la caché se resuelven desde la variable
      de entorno `DATA_DIR` (en Fly vale `/data`, el volumen).
- [x] Sin `DATA_DIR`, el comportamiento local actual no cambia
      (default: la carpeta `datos/` del repo).
- [x] Ninguna ruta absoluta ni relativa al cwd debe quedar suelta:
      buscar todos los `Path("datos/...")` y constantes equivalentes.

## 2. Cabeceras de seguridad en todas las respuestas

- [x] `Content-Security-Policy` sin recursos externos (todo inline o
      del mismo origen): `default-src 'self'` y lo mínimo que la UI
      necesite, sin CDN.
- [x] `X-Content-Type-Options: nosniff`
- [x] `Referrer-Policy: no-referrer` (o `same-origin` si algo lo exige)
- [x] `frame-ancestors 'none'` en la CSP (nadie incrusta la consola).

## 3. Límite de 10 MB en subidas

- [x] Rechazar con `413` cualquier subida mayor a 10 MB (evidencia y
      cualquier otro endpoint con `UploadFile`), contando el tamaño
      real leído, no solo el encabezado `Content-Length`.

## 4. Límite de solicitudes por IP

- [x] Tope por IP en `/solicitar`, `/evidencia` y `/admin`
      (ventana corta, p. ej. decenas por minuto; `/admin` más estricto).
- [x] Responder `429` al excederlo. Sin dependencias nuevas si se puede:
      contador en memoria basta para una sola máquina (ver ADR Fly).

## Hecho además (pase de octubre 2026)

- `/admin` solo existe si `ADMIN_TOKEN` tiene al menos 32 caracteres; si no, responde 404.
- `GET /salud` responde 200 sin tocar la base; el health check de `fly.toml` apunta ahí.
- `scripts/revisar_privacidad.py`: revisa la base a subir y sale con código 1 si
  encuentra correos no `.gob.mx` o teléfonos fuera de los campos de contacto institucional.

## Fuera de alcance aquí

- Respaldos automáticos del volumen y monitoreo: se deciden cuando la
  demo pase a servicio continuo, no en este pase.
