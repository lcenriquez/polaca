# Pendientes de código en `auditor/` para producción

Cambios que faltan **dentro de `auditor/`** antes de considerar la demo
un servicio público. Se harán después, cuando la sesión que estabiliza
`auditor/` termine (hoy ese directorio no se toca desde esta sesión).
El despliegue de Fly.io ya está preparado (`fly.toml`, `Dockerfile`)
asumiendo estos cambios.

## 1. Leer `DATA_DIR` para todo lo persistente

- [ ] La base SQLite, `datos/` y la caché se resuelven desde la variable
      de entorno `DATA_DIR` (en Fly vale `/data`, el volumen).
- [ ] Sin `DATA_DIR`, el comportamiento local actual no cambia
      (default: la carpeta `datos/` del repo).
- [ ] Ninguna ruta absoluta ni relativa al cwd debe quedar suelta:
      buscar todos los `Path("datos/...")` y constantes equivalentes.

## 2. Cabeceras de seguridad en todas las respuestas

- [ ] `Content-Security-Policy` sin recursos externos (todo inline o
      del mismo origen): `default-src 'self'` y lo mínimo que la UI
      necesite, sin CDN.
- [ ] `X-Content-Type-Options: nosniff`
- [ ] `Referrer-Policy: no-referrer` (o `same-origin` si algo lo exige)
- [ ] `frame-ancestors 'none'` en la CSP (nadie incrusta la consola).

## 3. Límite de 10 MB en subidas

- [ ] Rechazar con `413` cualquier subida mayor a 10 MB (evidencia y
      cualquier otro endpoint con `UploadFile`), contando el tamaño
      real leído, no solo el encabezado `Content-Length`.

## 4. Límite de solicitudes por IP

- [ ] Tope por IP en `/solicitar`, `/evidencia` y `/admin`
      (ventana corta, p. ej. decenas por minuto; `/admin` más estricto).
- [ ] Responder `429` al excederlo. Sin dependencias nuevas si se puede:
      contador en memoria basta para una sola máquina (ver ADR Fly).

## Fuera de alcance aquí

- Respaldos automáticos del volumen y monitoreo: se deciden cuando la
  demo pase a servicio continuo, no en este pase.
