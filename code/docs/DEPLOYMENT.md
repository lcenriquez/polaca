# Deployment — POLACA

La razón de cada decisión está en [ARCHITECTURE.md](ARCHITECTURE.md#hosting).

## Resumen

| | Staging | Producción |
|---|---|---|
| Disparador | Push a `main` (automático) | Manual: `workflow_dispatch` con una etiqueta `vX.Y.Z` |
| URL | `staging.<dominio>` | `<dominio>` |
| Servidor | El mismo VPS, proyecto Compose `polaca-staging` | VPS, proyecto Compose `polaca` |
| Base de datos | `polaca_staging`, con seeds de desarrollo | `polaca` |
| Correo | Mailpit (no se envía nada real) | Amazon SES |
| Archivos | Bucket R2 `polaca-staging` | Bucket R2 `polaca` |

Mientras el tráfico sea bajo, staging y producción comparten el VPS. Si staging llega a afectar a producción, staging se mueve a otro servidor.

## Infraestructura (una sola vez)

1. **VPS:** Hetzner Cloud en US East, con Ubuntu 24.04 LTS, 4 vCPU y 8 GB.
   - Crear un usuario `deploy` sin contraseña y con acceso solo por llave SSH.
   - Abrir en el firewall únicamente los puertos 22, 80 y 443. Los puertos 80 y 443 solo deben aceptar las IP de Cloudflare.
   - Instalar Docker Engine y el plugin de Compose.
   - Activar `unattended-upgrades` para las actualizaciones de seguridad.
2. **Cloudflare:**
   - DNS del dominio con proxy activado (nube naranja).
   - SSL en modo *Full (strict)*.
   - Crear los buckets R2 `polaca`, `polaca-staging` y `polaca-backups`. Los dos primeros con acceso público de lectura, a través de un subdominio de archivos; `polaca-backups` privado.
3. **Amazon SES:**
   - Verificar el dominio con DKIM, SPF y DMARC.
   - Pedir la salida del *sandbox*.
4. **En el VPS**, en `/srv/polaca/`:
   - `compose.prod.yml` y `compose.staging.yml`: se generan a partir de la plantilla del repositorio cuando exista el código.
   - `Caddyfile`
   - `.env.production` y `.env.staging`, con permisos `600` y propiedad del usuario `deploy`.

## Cómo es un deploy

El workflow [`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml) hace esto:

1. Construye las imágenes `ghcr.io/lcenriquez/polaca-backend:<sha>` y `polaca-frontend:<sha>` y las publica en GitHub Container Registry.
2. Se conecta por SSH al VPS como `deploy`.
3. Descarga las imágenes nuevas: `docker compose pull`.
4. Corre las migraciones en un contenedor de un solo uso: `docker compose run --rm backend npm run migrate`. Si fallan, el deploy se detiene y la versión anterior sigue sirviendo.
5. Arranca los servicios con la versión nueva: `docker compose up -d --remove-orphans`.
6. Verifica la salud: `curl -f $HEALTH_URL` hasta 10 veces en un minuto. Si falla, regresa a la última etiqueta que pasó la verificación (guardada en `/srv/polaca/.tag-<proyecto>`).

Las migraciones tienen que ser compatibles con la versión anterior del backend (ver [DATABASE.md](DATABASE.md#migraciones)), porque durante unos segundos conviven la base migrada y el código viejo.

### Producción

1. Revisa los commits desde la última etiqueta (`git log vA.B.C..main --oneline`).
2. Crea y sube la etiqueta:

   ```bash
   git tag v0.3.0 && git push origin v0.3.0
   ```
3. En GitHub, ve a **Actions → Deploy → Run workflow**, elige el entorno `production` y escribe la etiqueta. El entorno `production` exige que lo apruebe una persona mantenedora (GitHub Environments).

### Revertir una versión

Vuelve a correr el workflow con la etiqueta anterior. Si la versión incluía una migración, revísala antes: las migraciones compatibles hacia atrás no necesitan revertirse.

## Variables de entorno

### Backend

| Variable | Ejemplo o formato | Notas |
|---|---|---|
| `NODE_ENV` | `production` | |
| `PORT` | `4000` | |
| `LOG_LEVEL` | `info` | |
| `APP_URL` | `https://<dominio>` | Se usa en la verificación de `Origin` y en los enlaces de los correos |
| `TRUST_PROXY` | `true` | Para leer la IP real a través de Caddy y Cloudflare |
| `API_DOCS` | `false` | Swagger UI en producción |
| `DATABASE_URL` | `postgres://polaca:***@db:5432/polaca` | |
| `VOTE_SECRET` | 64 caracteres hex | **Secreto.** No debe cambiar mientras haya una encuesta abierta. Respáldalo. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` | Credenciales SMTP de SES | **Secreto** |
| `MAIL_FROM` | `POLACA <no-responder@<dominio>>` | |
| `STORAGE_DRIVER` | `s3` | |
| `S3_ENDPOINT` | `https://<account>.r2.cloudflarestorage.com` | |
| `S3_BUCKET` | `polaca` | |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | | **Secreto**; token de R2 limitado al bucket |
| `S3_PUBLIC_URL` | `https://archivos.<dominio>` | |

### Frontend

| Variable | Ejemplo |
|---|---|
| `API_INTERNAL_URL` | `http://backend:4000` (red interna de Compose) |
| `NEXT_PUBLIC_SITE_URL` | `https://<dominio>` |

### GitHub (Settings → Environments → `staging` / `production`)

| Secreto | Uso |
|---|---|
| `DEPLOY_HOST` | IP o nombre del VPS |
| `DEPLOY_SSH_KEY` | Llave privada del usuario `deploy` |
| `DEPLOY_KNOWN_HOSTS` | Salida de `ssh-keyscan <host>` |
| `HEALTH_URL` (variable, no secreto) | `https://staging.<dominio>/api/health` o `https://<dominio>/api/health` |

Los secretos de la aplicación viven **solo** en los archivos `.env.*` del VPS, no en GitHub.

## Respaldos

| Qué | Cómo | Cada cuánto | Retención |
|---|---|---|---|
| PostgreSQL | `pg_dump -Fc`, cifrado con `age`, subido a R2 `polaca-backups` | Diario, 03:00 hora de CDMX (cron en el VPS) | 7 diarios, 4 semanales, 12 mensuales |
| Archivos (fotos, originales de gasto) | Ya viven en R2, con versionado activado en el bucket | — | 30 días de versiones |
| Secretos (`.env.production`, llave `age`) | Gestor de contraseñas del equipo núcleo, con dos personas con acceso | Cada vez que cambian | — |

**Prueba de restauración cada mes:** se restaura el último respaldo en staging y se verifica que `GET /api/health` y el conteo de denuncias coincidan. Un respaldo que nunca se ha restaurado no cuenta como respaldo.

Objetivos:

- **RPO** de 24 h: como máximo se pierde un día de datos.
- **RTO** de 4 h: el servicio vuelve en menos de cuatro horas.

Si hace falta un RPO menor, se pasa a PostgreSQL administrado con PITR (etapa 2 de escalabilidad).

## Monitoreo

- **Disponibilidad:** un monitor externo gratuito (Better Stack o UptimeRobot) consulta `/api/health` cada minuto y avisa por correo o Telegram.
- **Logs:** JSON de pino en la salida estándar. Se consultan con `docker compose logs`; la rotación la hace el log driver `local` de Docker.
- **Recursos:** alertas de CPU y disco del panel de Hetzner.
