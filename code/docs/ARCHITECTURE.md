# Arquitectura técnica — POLACA

Funcionalidades: [`spec/PLATFORM_SPECIFICATION.md`](../../spec/PLATFORM_SPECIFICATION.md). Este documento explica **cómo** se construye.

## Criterios de decisión

1. **Lo puede mantener una comunidad de voluntarios.** Tecnologías populares, bien documentadas y con un solo lenguaje en toda la base de código.
2. **Bajo costo.** El MVP debe operar con menos de 30 USD al mes.
3. **Autohospedable.** Cualquier organización debe poder levantar su propia instancia con `docker compose` (la AGPL lo favorece).
4. **Sin dependencia de un proveedor.** Nada que no se pueda reemplazar con un equivalente libre.

## Tech stack

### Frontend

- **Framework:** Next.js 16 (App Router) con React 19
- **Lenguaje:** TypeScript
- **Estilos:** CSS Modules con variables CSS (tokens del sistema de diseño). No usamos librerías de componentes.
- **Mapas:** Leaflet con teselas de OpenStreetMap
- **Razón:**
  - Los perfiles de funcionarios y las denuncias **se comparten en WhatsApp y Facebook**. Para que la vista previa (Open Graph) funcione, esas páginas tienen que renderizarse en el servidor; una SPA con Vite no lo logra sin un servidor adicional.
  - El SSR también mejora el SEO y el tiempo de carga en teléfonos de gama baja.
  - React tiene la mayor base de posibles colaboradores.
  - Se evitan librerías de componentes para cumplir el límite de < 200 KB de JS inicial y controlar la accesibilidad.

### Backend

- **Lenguaje:** Node.js 24 LTS con TypeScript
- **Framework:** Fastify 5
- **Acceso a datos:** Kysely (query builder tipado; SQL explícito, sin ORM)
- **Validación:** esquemas JSON de Fastify y Zod en la frontera de entrada
- **Razón:**
  - Un solo lenguaje en frontend y backend reduce la barrera de entrada para contribuir.
  - Fastify valida contra esquemas, genera OpenAPI (`@fastify/swagger`) y trae logging estructurado (pino) sin piezas extra.
  - Kysely evita la "magia" de un ORM: el SQL que se ejecuta es el SQL que se lee.

Descartado: **Python con FastAPI**. Hubiera servido para los importadores de gasto (pandas), pero obliga a mantener dos lenguajes. Los importadores del MVP son CSV y XLSX sencillos y se resuelven en Node.

### Base de datos

- **Principal:** PostgreSQL 16 o superior
- **Extensiones:** `citext`, `unaccent` y `pg_trgm`
- **Migraciones:** `node-pg-migrate` con archivos SQL planos en [`code/database/migrations/`](../database/migrations/)
- **Razón:**
  - Los datos son relacionales: funcionarios, denuncias, contratos, proveedores y votos.
  - PostgreSQL cubre desde el inicio la búsqueda de texto en español (`tsvector` con `unaccent`), la búsqueda difusa de proveedores (`pg_trgm`) y las restricciones de integridad, sin sumar Elasticsearch ni Redis.
  - Detalles en [DATABASE.md](DATABASE.md).

### Almacenamiento de archivos

- **Producción:** Cloudflare R2 (compatible con S3, sin costo de salida de datos)
- **Desarrollo:** disco local (`STORAGE_DRIVER=local`)
- **Uso:** fotos de denuncias, archivos originales de las importaciones de gasto y respaldos

### Autenticación

- **Método:** sesiones en el servidor con cookie `HttpOnly`, `Secure` y `SameSite=Lax`
- **Contraseñas:** hash con Argon2id
- **Razón:**
  - Un JWT no se puede revocar sin agregar una lista negra, y esta plataforma necesita cerrar sesiones de inmediato: bloqueo de usuarios, cambio de contraseña, eliminación de cuenta.
  - Las sesiones se guardan en PostgreSQL como un hash SHA-256 del token, así que si la base se filtra, los tokens no sirven.
  - Frontend y API viven en el **mismo origen** (`/api/*`), así que no hace falta CORS.
  - CSRF se mitiga con `SameSite=Lax` más la verificación del encabezado `Origin` en toda petición que modifica datos.

### Correo

- **SMTP genérico** (Nodemailer). En producción, Amazon SES; en desarrollo, Mailpit, que captura los correos en `localhost:8025`.

### Hosting

- **Cómputo:** un VPS (Hetzner Cloud, región US East; unos 8 USD al mes por 4 vCPU y 8 GB) con Docker Compose y Caddy (HTTPS automático)
- **Red:** Cloudflare (plan gratuito) delante: CDN, DNS y protección DDoS
- **Razón:**
  - Un sitio político en México **será blanco de ataques DDoS**, y Cloudflare los absorbe sin costo.
  - Un solo VPS con Compose es lo más barato y lo que cualquier colaborador puede replicar en su máquina.
  - US East queda a unos 60–70 ms del centro de México.
  - Detalles en [DEPLOYMENT.md](DEPLOYMENT.md).

### CI/CD

- **Plataforma:** GitHub Actions
- **Pruebas:** Vitest en frontend y backend; React Testing Library para componentes. El backend se prueba contra un PostgreSQL real (servicio de GitHub Actions), no contra mocks.
- **Cobertura:** mínimo del 70 % de líneas, forzado en CI
- **Calidad:** ESLint y `tsc --noEmit`
- **Despliegue:**
  - **Staging:** automático en cada push a `main`
  - **Producción:** manual (`workflow_dispatch`) con una etiqueta `vX.Y.Z`
- **Workflows:** [`.github/workflows/`](../../.github/workflows/). Van en la raíz del repositorio porque GitHub solo ejecuta los workflows que están ahí.

## Arquitectura general

```
                 ┌──────────────────────────────┐
  Navegador ───► │ Cloudflare (CDN, DNS, DDoS)  │
                 └──────────────┬───────────────┘
                                │ HTTPS
                 ┌──────────────▼───────────────┐   VPS · Docker Compose
                 │ Caddy (TLS, proxy inverso)   │
                 └───────┬──────────────┬───────┘
                   /*    │              │  /api/*
             ┌───────────▼───┐   ┌──────▼─────────┐
             │ frontend      │──►│ backend        │──► SMTP (Amazon SES)
             │ Next.js (SSR) │   │ Fastify        │──► Cloudflare R2 (fotos, archivos)
             └───────────────┘   └──────┬─────────┘
                                        │
                                 ┌──────▼─────────┐
                                 │ PostgreSQL     │──► respaldo diario a R2
                                 └────────────────┘
```

- Next.js renderiza en el servidor las páginas públicas llamando al backend por la red interna (`API_INTERNAL_URL`). En el navegador, las acciones del usuario van a `/api/*` en el mismo origen.
- El backend es **sin estado**: la sesión vive en PostgreSQL. Por eso se puede escalar horizontalmente.
- Los importadores de gasto corren dentro del backend como tareas del administrador; no hay un worker aparte en el MVP.

### Estructura del código

```
code/
├── frontend/src/
│   ├── app/          # rutas de Next.js (páginas)
│   ├── components/   # componentes de UI reutilizables
│   ├── services/     # cliente HTTP del API
│   ├── hooks/
│   └── utils/
├── backend/src/
│   ├── routes/       # declaración de rutas y esquemas
│   ├── controllers/  # manejo de la petición y la respuesta
│   ├── services/     # lógica de negocio (moderación, importadores, alertas)
│   ├── models/       # tipos de Kysely y consultas
│   └── middleware/   # sesión, roles, límite de peticiones
├── database/
│   ├── schema.sql    # esquema completo de referencia
│   ├── migrations/   # única fuente de verdad de los cambios al esquema
│   └── seeds/        # catálogos y datos ficticios para desarrollo
└── docker-compose.yml  # PostgreSQL y Mailpit para desarrollo local
```

Las páginas del frontend viven en `src/app/`, que es la convención de Next.js, y no en `src/pages/`. Las migraciones y seeds viven solo en `code/database/` para no tener dos fuentes de verdad.

## Decisiones importantes

1. **Moderación antes de publicar.** Ninguna denuncia se publica sin revisión humana. Esto frena el crecimiento, pero reduce el riesgo de difamación, que es el riesgo existencial del proyecto.
2. **El registro no revela si un correo ya existe.** `POST /api/auth/register` siempre responde `202` y avisa por correo al dueño de la cuenta existente. Así nadie puede saber si una persona tiene cuenta en una plataforma de denuncias.
3. **Votos seudonimizados.** El voto guarda un `HMAC(VOTE_SECRET, usuario_id ‖ pregunta_id)` en lugar del `usuario_id`. Con eso se evitan duplicados y se permite cambiar el voto, pero una filtración de la base de datos por sí sola no revela cómo votó cada persona.
4. **Ubicación redondeada al guardar.** Las coordenadas de una denuncia se guardan con 3 decimales (unos 110 m). La ubicación exacta nunca llega a la base de datos.
5. **Procedencia obligatoria.** Todo dato importado (gasto) o capturado (funcionarios) apunta a una fila de `fuentes` con URL, fecha y hash del archivo original.
6. **Reglas de alerta en código abierto y documentadas.** Las alertas de gasto son funciones puras en `backend/src/services/alertas/`, con umbrales en la tabla `reglas_alerta` y descripción pública en `GET /api/gasto/reglas-alerta`.
7. **Un solo municipio en el MVP, modelo multi-municipio.** Todas las tablas de contenido llevan `municipio_id`, así que agregar otro municipio es cargar datos, no migrar el esquema.

## Escalabilidad (100 000 usuarios)

Con 100 000 usuarios registrados, los picos esperados son de unas 1 000 sesiones concurrentes y la carga es de mayoría lectura. El plan va por etapas y solo se avanza cuando una métrica lo pide:

| Etapa | Cuándo | Qué se hace |
|---|---|---|
| 0 (MVP) | Hasta ~10 000 usuarios | 1 VPS. Cloudflare cachea las respuestas públicas con `Cache-Control: s-maxage=60` (listas de funcionarios, gasto, resultados de encuesta). Contadores desnormalizados (`apoyos_count`). |
| 1 | CPU > 70 % sostenido | VPS más grande; varias réplicas de `backend` y `frontend` en Compose detrás de Caddy (posible porque no guardan estado) |
| 2 | La base de datos es el cuello de botella | PostgreSQL administrado con réplica de lectura; las consultas de gasto y resultados van a la réplica |
| 3 | Varios estados | Separar los importadores en un worker con cola (`pg-boss`, que usa PostgreSQL); rate limiting compartido en Redis |

El límite de peticiones del MVP vive en memoria (`@fastify/rate-limit`). Funciona con una sola instancia; en la etapa 1 se mueve a Redis.

## Seguridad

- **Transporte:** HTTPS obligatorio con HSTS; Cloudflare en modo *Full (strict)*.
- **Contraseñas:**
  - Hash con Argon2id (parámetros por defecto de OWASP).
  - Mínimo 10 caracteres.
  - Se rechazan contraseñas comunes usando una lista local: no se envía nada a servicios externos.
- **Sesiones:**
  - Token aleatorio de 32 bytes; en la base solo se guarda su hash.
  - Expiran a los 30 días, o a los 7 días sin actividad.
  - Se revocan todas al cambiar la contraseña.
- **Límite de peticiones:**
  - Login: 5 por minuto por IP y correo.
  - Registro y recuperación: 3 por hora por IP.
  - Creación de denuncias: 5 por día por usuario.
  - Votos: 30 por hora por usuario.
- **Autorización:** roles `ciudadano`, `moderador` y `admin` verificados en middleware. Cada acción de moderación o administración queda en la tabla `auditoria`.
- **Entradas:**
  - Todo cuerpo de petición se valida con un esquema.
  - Todo el SQL se parametriza a través de Kysely.
  - El Markdown de las rutas de acción se sanitiza al renderizarlo.
- **Archivos:**
  - Solo se aceptan JPEG, PNG y WebP, validados por su contenido y no por la extensión, de hasta 5 MB.
  - Se re-codifican con `sharp`, lo que también elimina los metadatos EXIF y el GPS.
  - Se sirven desde el dominio de R2, no desde el de la aplicación.
- **Encabezados:** `@fastify/helmet` con una CSP estricta.
- **Datos personales (LFPDPPP):**
  - Mínimos: correo, y colonia y rango de edad solo si la persona los da.
  - Aviso de privacidad y derechos ARCO: exportación (`GET /api/me/export`) y eliminación (`DELETE /api/me`).
  - La IP de las sesiones se borra cuando la sesión expira.
- **Secretos:** solo en variables de entorno o GitHub Secrets; nunca en el repositorio.
- **Dependencias:** Dependabot y `npm audit` en CI.
- **Reporte de vulnerabilidades:** reporte privado de GitHub (ver [CONTRIBUTING.md](../../CONTRIBUTING.md#seguridad)).
