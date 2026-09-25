# API — POLACA

API REST en JSON, servida en `/api` desde el mismo origen que el frontend. Cuando exista el backend, el **contrato ejecutable** será la especificación OpenAPI que genera Fastify en `GET /api/docs`. Este documento es la referencia para diseñar e implementar, y se actualiza en el mismo PR que cambie un endpoint.

## Convenciones

- **Autenticación:** cookie de sesión `polaca_session` (`HttpOnly`, `Secure`, `SameSite=Lax`). No hay tokens Bearer.
- **Acceso** (columna "Acceso" en cada tabla):

  | Valor | Significado |
  |---|---|
  | 🌐 | Público |
  | 🔑 | Con sesión |
  | ✅ | Con sesión y correo verificado |
  | 🛡️ | Moderador o administrador |
  | 👑 | Solo administrador |
- **CSRF:** toda petición `POST`, `PATCH`, `PUT` o `DELETE` debe traer un encabezado `Origin` que coincida con `APP_URL`; si no, responde `403`.
- **Formato:** `Content-Type: application/json`, excepto las subidas de archivos (`multipart/form-data`).
- **Nombres:** los campos JSON van en `snake_case` y en español, igual que la base de datos.
- **Fechas:** ISO 8601 en UTC (`2026-10-01T18:00:00Z`).
- **Dinero:** montos como **string** decimal (`"1250000.00"`) para no perder precisión.
- **Paginación:** `?page=1&limit=20` (el máximo de `limit` es 100). Las respuestas paginadas tienen esta forma:

  ```json
  { "data": [ ... ], "page": 1, "limit": 20, "total": 134 }
  ```
- **Errores:** siempre con esta forma:

  ```json
  { "error": { "code": "email_not_verified", "message": "Verifica tu correo para continuar.", "details": {} } }
  ```

| HTTP | Cuándo |
|---|---|
| 400 | Validación (`details` trae los campos con error) |
| 401 | Sin sesión o sesión expirada |
| 403 | Sin permiso, correo sin verificar u `Origin` inválido |
| 404 | No existe, o existe pero no es visible para quien la pide |
| 409 | Conflicto de estado (p. ej. votar en una encuesta cerrada) |
| 413 | Archivo demasiado grande |
| 429 | Límite de peticiones; trae el encabezado `Retry-After` |

- **Caché:** los `GET` públicos responden `Cache-Control: public, s-maxage=60` y Cloudflare los cachea. Las respuestas que dependen de la sesión responden `private, no-store`.

---

## Autenticación

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| POST | `/api/auth/register` | 🌐 | Crear una cuenta |
| POST | `/api/auth/verify-email` | 🌐 | Confirmar el correo |
| POST | `/api/auth/resend-verification` | 🌐 | Reenviar la verificación |
| POST | `/api/auth/login` | 🌐 | Iniciar sesión |
| POST | `/api/auth/logout` | 🔑 | Cerrar sesión |
| POST | `/api/auth/password/forgot` | 🌐 | Pedir la recuperación de contraseña |
| POST | `/api/auth/password/reset` | 🌐 | Poner una contraseña nueva |

### POST /api/auth/register

- **Parámetros:**
  - `email`
  - `password` (mínimo 10 caracteres y que no esté en la lista de contraseñas comunes)
  - `accept_terms` (debe ser `true`)
  - `terminos_version`
- **Respuesta:** `202 { "message": "Revisa tu correo para activar tu cuenta." }`
- **Errores:**
  - `400`: correo inválido, contraseña débil o términos no aceptados.
  - `429`: demasiados intentos.
- **Nota:** **no** se responde `409` si el correo ya existe. En ese caso se envía un correo al dueño de esa cuenta ("ya tienes cuenta; ¿olvidaste tu contraseña?"), para no revelar quién está registrado en la plataforma. Tampoco se inicia sesión hasta que se verifique el correo.

### POST /api/auth/verify-email

- **Parámetros:** `token` (viene en el enlace del correo)
- **Respuesta:** `200 { "user": User }` y crea la sesión (cookie)
- **Errores:** `400 token_invalid` si el token no existe, ya expiró o ya se usó.

### POST /api/auth/resend-verification

- **Parámetros:** `email`
- **Respuesta:** siempre `202`
- **Errores:** `429`

### POST /api/auth/login

- **Parámetros:** `email`, `password`
- **Respuesta:** `200 { "user": User }` y crea la sesión (cookie)
- **Errores:**
  - `401 invalid_credentials`: el mensaje es el mismo si el correo no existe o si la contraseña está mal.
  - `403 email_not_verified`
  - `403 account_blocked`
  - `429`

### POST /api/auth/logout

- **Respuesta:** `204`. Borra la sesión actual y la cookie.

### POST /api/auth/password/forgot

- **Parámetros:** `email`
- **Respuesta:** siempre `202`
- **Errores:** `429`

### POST /api/auth/password/reset

- **Parámetros:** `token`, `password`
- **Respuesta:** `204`. Revoca **todas** las sesiones del usuario.
- **Errores:** `400 token_invalid`, `400` si la contraseña es débil.

### Objeto `User`

```json
{
  "id": "0b9c…",
  "email": "ana@example.com",
  "rol": "ciudadano",
  "email_verificado": true,
  "colonia": { "id": 12, "nombre": "Centro" },
  "rango_edad": "25_34",
  "created_at": "2026-10-01T18:00:00Z"
}
```

## Mi cuenta

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| GET | `/api/me` | 🔑 | Usuario actual (`401` si no hay sesión) |
| PATCH | `/api/me` | 🔑 | Actualizar `colonia_id` y `rango_edad` (se pueden poner en `null`) |
| POST | `/api/me/password` | 🔑 | `{ current_password, new_password }` → `204`; revoca las demás sesiones |
| GET | `/api/me/export` | 🔑 | Descarga en JSON de todos mis datos (derecho ARCO de acceso) |
| DELETE | `/api/me` | 🔑 | `{ password }` → `204`. Anonimiza la cuenta (ver DATABASE.md). |
| GET | `/api/me/denuncias` | 🔑 | Mis denuncias en cualquier estado, con las notas de moderación |

## Territorio y catálogos

| Método | Ruta | Acceso | Respuesta |
|---|---|---|---|
| GET | `/api/municipios` | 🌐 | `[{ id, slug, nombre, entidad }]` |
| GET | `/api/municipios/:slug/colonias` | 🌐 | `[{ id, nombre, codigo_postal }]` |
| GET | `/api/partidos` | 🌐 | `[{ id, siglas, nombre, color_hex }]` |
| GET | `/api/categorias` | 🌐 | `[{ id, slug, nombre }]` |

## Funcionarios

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| GET | `/api/funcionarios` | 🌐 | Lista. Filtros: `municipio` (slug, obligatorio), `cargo`, `partido`, `nivel`, `activo` (por defecto `true`) |
| GET | `/api/funcionarios/:slug` | 🌐 | Perfil |
| POST | `/api/admin/funcionarios` | 👑 | Crear |
| PATCH | `/api/admin/funcionarios/:id` | 👑 | Editar; registra el cambio en la auditoría |
| PUT | `/api/admin/funcionarios/:id/foto` | 👑 | `multipart`: `foto` y `foto_credito` |
| PUT | `/api/admin/funcionarios/:id/fuentes` | 👑 | `[{ fuente_id \| fuente: {…}, campo }]` (reemplaza las existentes) |

### GET /api/funcionarios/:slug

```json
{
  "id": 7,
  "slug": "nombre-apellido",
  "nombre": "Nombre Apellido",
  "cargo": { "nombre": "Regidor/a", "nivel": "municipal" },
  "partido": { "siglas": "XYZ", "nombre": "…", "color_hex": "#…" },
  "coalicion": null,
  "periodo": { "inicio": "2024-10-15", "fin": "2027-10-14" },
  "foto_url": "https://…", "foto_credito": "…",
  "semblanza": "…", "comisiones": ["Hacienda"],
  "enlaces": [{ "etiqueta": "Perfil oficial", "url": "https://…" }],
  "fuentes": [{ "campo": "cargo", "url": "https://…", "institucion": "IEE Puebla", "consultado_en": "2026-09-20" }],
  "stats": {
    "denuncias_publicadas": 14,
    "aprobacion": { "encuesta_id": 3, "aprueba_pct": 41.2, "respuestas": 212 }
  },
  "replicas_count": 1
}
```

`stats.aprobacion` es `null` si la última encuesta cerrada no llegó al mínimo de respuestas.

## Denuncias

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| GET | `/api/denuncias` | 🌐 | Lista de denuncias publicadas |
| GET | `/api/denuncias/:id` | 🌐 | Detalle (`404` si no está publicada, salvo para su autor o un moderador) |
| POST | `/api/uploads/fotos` | ✅ | Subir una foto antes de crear la denuncia |
| POST | `/api/denuncias` | ✅ | Crear una denuncia |
| PATCH | `/api/denuncias/:id` | ✅ | El autor la corrige cuando está en `cambios_solicitados`; vuelve a `pendiente` |
| POST | `/api/denuncias/:id/apoyos` | ✅ | Apoyar → `201`, o `200` si ya la había apoyado |
| DELETE | `/api/denuncias/:id/apoyos` | ✅ | Quitar el apoyo → `204` |
| POST | `/api/denuncias/:id/reportes` | ✅ | `{ motivo, comentario? }` → `201`; `409` si ya la había reportado |
| POST | `/api/replicas` | 🌐 | Un funcionario envía su derecho de réplica |

### GET /api/denuncias

Filtros:

| Parámetro | Descripción |
|---|---|
| `municipio` | Slug, obligatorio |
| `categoria` | Slug de la categoría |
| `estado` | `publicada`, `en_seguimiento`, `resuelta` o `sin_respuesta` |
| `colonia` | ID de la colonia |
| `funcionario` | Slug del funcionario |
| `q` | Texto libre |
| `bbox` | `lng_min,lat_min,lng_max,lat_max`, para el mapa |
| `orden` | `recientes` (por defecto) o `apoyos` |
| `page`, `limit` | Paginación |

Cada elemento de la lista:

```json
{
  "id": "…", "titulo": "…", "extracto": "primeros 200 caracteres…",
  "categoria": { "slug": "baches", "nombre": "Baches y vialidades" },
  "estado": "publicada", "colonia": "Centro",
  "ubicacion": { "lat": 18.908, "lng": -98.436 },
  "autor": "Ciudadano/a de Centro",
  "apoyos": 23, "fotos": 2, "publicada_en": "…",
  "funcionario": { "slug": "…", "nombre": "…" }
}
```

El detalle agrega:

- `descripcion`, `fecha_hecho` y `dependencia`.
- `fotos: [{ url, ancho, alto }]`.
- `historial`: los eventos públicos de moderación (cambios de estado con su nota).
- `replicas`: las réplicas aprobadas.
- `yo_apoyo`: booleano, solo si hay sesión.
- `ruta_sugerida`: `{ slug, titulo }`.

`autor` es `"Anónimo"` o `"Ciudadano/a de <colonia>"`. **Nunca** incluye el id ni el correo del autor.

### POST /api/uploads/fotos

- **Parámetros:** `multipart` con el campo `foto` (JPEG, PNG o WebP de hasta 5 MB)
- **Respuesta:** `201 { "id": "…", "url": "…", "ancho": 1600, "alto": 1200 }`
- **Errores:** `400` si el tipo no es válido, `413`, `429`
- **Nota:** la imagen se re-codifica y pierde sus metadatos EXIF. Si no se adjunta a una denuncia en 24 h, se borra.

### POST /api/denuncias

- **Parámetros:**

  ```json
  {
    "municipio": "atlixco",
    "categoria_id": 2,
    "titulo": "Bache profundo frente a la escuela",
    "descripcion": "…",
    "colonia_id": 12,
    "ubicacion": { "lat": 18.90812, "lng": -98.43577 },
    "fecha_hecho": "2026-09-20",
    "funcionario_id": null,
    "dependencia": "Obras Públicas",
    "mostrar_como": "colonia",
    "foto_ids": ["…"]
  }
  ```

- **Respuesta:** `201 { "id": "…", "estado": "pendiente" }`
- **Errores:**
  - `400`: título de 10 a 120 caracteres, descripción de 30 a 5 000, máximo 3 fotos que deben ser del mismo usuario y no estar adjuntas a otra denuncia.
  - `403 email_not_verified`
  - `429`: más de 5 denuncias al día.
- **Nota:** el servidor redondea la ubicación a 3 decimales antes de guardarla.

### POST /api/replicas

- **Parámetros:** `funcionario_id`, `denuncia_id?`, `remitente_nombre`, `remitente_cargo`, `correo_contacto`, `texto`
- **Respuesta:** `202`. La réplica pasa a moderación, y el moderador verifica la identidad del remitente por el correo institucional o por teléfono antes de publicarla.
- **Errores:** `400`, `429` (3 por hora por IP)

## Moderación

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| GET | `/api/mod/denuncias` | 🛡️ | Cola de moderación. Filtros: `estado` (por defecto `pendiente`), `categoria`. Orden: la más antigua primero. Incluye los datos internos (autor, número de denuncias previas del autor). |
| POST | `/api/mod/denuncias/:id/decision` | 🛡️ | Decidir sobre una denuncia pendiente |
| POST | `/api/mod/denuncias/:id/estado` | 🛡️ | Cambiar el estado de una denuncia ya publicada |
| GET | `/api/mod/reportes` | 🛡️ | Reportes abiertos, agrupados por denuncia |
| POST | `/api/mod/reportes/:denuncia_id/resolver` | 🛡️ | `{ accion: "descartar" \| "ocultar", nota }`. Resuelve todos los reportes abiertos de esa denuncia. |
| GET | `/api/mod/replicas` | 🛡️ | Réplicas pendientes |
| POST | `/api/mod/replicas/:id/decision` | 🛡️ | `{ accion: "aprobar" \| "rechazar", nota? }` |

### POST /api/mod/denuncias/:id/decision

- **Parámetros:**

  ```json
  { "accion": "aprobar" | "rechazar" | "solicitar_cambios", "motivo": "datos_personales", "nota": "Quita el nombre del vecino." }
  ```

  `motivo` es obligatorio al rechazar. `nota` es obligatoria al rechazar o al solicitar cambios, y se le envía por correo al autor.
- **Respuesta:** `200 { "estado": "publicada" }`
- **Errores:** `409` si la denuncia ya no está `pendiente`, porque otro moderador ya la tomó.

### POST /api/mod/denuncias/:id/estado

- **Parámetros:** `{ "estado": "en_seguimiento" | "resuelta" | "sin_respuesta", "nota": "…", "evidencia_url": "…" }`
- **Errores:** `409` si la transición no es válida (ver la máquina de estados en DATABASE.md)

## Gasto público

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| GET | `/api/gasto/ejercicios?municipio=` | 🌐 | Ejercicios que tienen datos: `[{ ejercicio, tipos: ["presupuesto","contratos"], fuente }]` |
| GET | `/api/gasto/resumen?municipio=&ejercicio=` | 🌐 | Totales y desglose por capítulo |
| GET | `/api/gasto/contratos` | 🌐 | Filtros: `municipio`, `ejercicio`, `capitulo`, `procedimiento`, `proveedor`, `q`, `orden` (`monto` o `fecha`), paginación |
| GET | `/api/gasto/contratos.csv` | 🌐 | Mismos filtros, sin paginación, en CSV UTF-8 con BOM (para que Excel lo abra bien) |
| GET | `/api/gasto/proveedores?municipio=&ejercicio=&limit=10` | 🌐 | Principales proveedores: `[{ id, nombre, rfc, monto_total, contratos, pct_del_total }]` |
| GET | `/api/gasto/alertas?municipio=&ejercicio=` | 🌐 | Alertas con su regla y `detalle` |
| GET | `/api/gasto/reglas-alerta` | 🌐 | Reglas activas: `[{ slug, nombre, descripcion, parametros }]` |
| POST | `/api/admin/gasto/importaciones` | 👑 | Importar un archivo de gasto |
| GET | `/api/admin/gasto/importaciones/:id` | 👑 | Estado, `filas_ok`, `filas_error`, `errores[]` |

### GET /api/gasto/resumen

```json
{
  "ejercicio": 2025,
  "fuente": { "url": "https://…", "institucion": "…", "consultado_en": "2026-09-01", "sha256": "…" },
  "totales": { "aprobado": "412000000.00", "modificado": "430500000.00", "ejercido": "418200000.00" },
  "capitulos": [
    { "clave": "1000", "nombre": "Servicios personales", "aprobado": "…", "ejercido": "…", "variacion_pct": 3.4 }
  ],
  "alertas": 5
}
```

### POST /api/admin/gasto/importaciones

- **Parámetros:** `multipart` con estos campos:
  - `archivo`: CSV (UTF-8 o Latin-1) de hasta 20 MB. En el MVP, los XLSX se exportan a CSV antes de subirlos.
  - `municipio`, `ejercicio`.
  - `tipo`: `presupuesto` o `contratos`.
  - `fuente_url`, `fuente_titulo`, `fuente_institucion`, `consultado_en`.
- **Respuesta:** `202 { "importacion_id": 4 }`. La importación corre en segundo plano dentro del proceso: guarda el original en R2, calcula el `sha256`, normaliza los datos y evalúa las reglas de alerta.
- **Errores:** `400` si faltan columnas obligatorias; el formato esperado por tipo está en `backend/src/services/importadores/README.md`.

## Encuesta pulso

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| GET | `/api/encuestas/actual?municipio=` | 🌐 | Encuesta abierta con preguntas y opciones. Con sesión, agrega `mis_votos: { pregunta_id: opcion_id }`. Las preguntas de `intencion` se omiten durante una veda. Si no hay encuesta abierta, responde `404`. |
| POST | `/api/encuestas/:id/votos` | ✅ | Votar o cambiar el voto |
| GET | `/api/encuestas/:id/resultados` | 🌐 | Resultados |
| GET | `/api/encuestas?municipio=&estado=cerrada` | 🌐 | Historial de encuestas |
| POST | `/api/admin/encuestas` | 👑 | Crear una encuesta con sus preguntas y opciones ("Ninguno" y "No sé" se agregan solas) |
| PATCH | `/api/admin/encuestas/:id` | 👑 | Editar, solo antes de `abre_en` |
| GET, POST, DELETE | `/api/admin/vedas` | 👑 | Gestionar los periodos de veda |

### POST /api/encuestas/:id/votos

- **Parámetros:**

  ```json
  { "consentimiento_dato_sensible": true, "respuestas": [{ "pregunta_id": 1, "opcion_id": 4 }] }
  ```

- **Respuesta:** `204`. Es un `UPSERT` por pregunta: si ya había voto, se reemplaza.
- **Errores:**
  - `400`: falta el consentimiento, o la opción no pertenece a la pregunta.
  - `403 email_not_verified`
  - `409 encuesta_cerrada`
  - `409 veda_electoral`: la pregunta es de intención y hay una veda activa.

### GET /api/encuestas/:id/resultados

```json
{
  "encuesta": { "id": 3, "titulo": "Pulso septiembre 2026", "abre_en": "…", "cierra_en": "…" },
  "leyenda": "Sondeo en línea no probabilístico. No representa a la población de Atlixco.",
  "preguntas": [
    {
      "id": 1, "tipo": "intencion", "texto": "…", "respuestas": 212,
      "opciones": [{ "id": 4, "etiqueta": "…", "votos": 80, "pct": 37.7 }]
    },
    { "id": 2, "tipo": "aprobacion", "texto": "…", "respuestas": 31, "opciones": null, "motivo": "minimo_no_alcanzado" }
  ]
}
```

Durante una veda, las preguntas de `intencion` responden `"opciones": null, "motivo": "veda_electoral"`.

## Rutas de acción

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| GET | `/api/rutas` | 🌐 | `[{ slug, titulo, resumen }]`, solo las publicadas |
| GET | `/api/rutas/:slug` | 🌐 | `{ slug, titulo, resumen, contenido_md, revisado_por, revisado_en }` |
| GET | `/api/admin/rutas` | 👑 | Todas, incluidas las no publicadas |
| POST | `/api/admin/rutas` | 👑 | Crear |
| PATCH | `/api/admin/rutas/:id` | 👑 | Editar. `publicada: true` exige `revisado_por` y `revisado_en`; si faltan, responde `400`. |

## Administración

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| GET | `/api/admin/usuarios?q=&rol=&page=` | 👑 | Buscar usuarios por correo |
| PATCH | `/api/admin/usuarios/:id` | 👑 | `{ rol?, bloqueado? }`. Bloquear revoca las sesiones del usuario. |
| GET | `/api/admin/auditoria?entidad=&entidad_id=&actor=&page=` | 👑 | Bitácora de auditoría |
| POST | `/api/admin/fuentes` | 👑 | Registrar una fuente: `{ url, titulo, institucion, consultado_en }` |

## Sistema

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| GET | `/api/health` | 🌐 | `200 { "status": "ok", "db": "ok", "version": "1.2.0" }`; `503` si la base de datos no responde |
| GET | `/api/docs` | 🌐 | OpenAPI y Swagger UI (deshabilitado en producción si `API_DOCS=false`) |
