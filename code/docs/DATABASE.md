# Base de datos — POLACA

PostgreSQL 16 o superior. El DDL completo está en [`code/database/schema.sql`](../database/schema.sql), validado contra PostgreSQL 18. Este documento explica el modelo; en caso de diferencia, manda el SQL.

## Convenciones

- Nombres de tablas y columnas en español, en `snake_case` y plural (`denuncias`, `funcionarios`).
- Llaves primarias:
  - `uuid` en entidades creadas por usuarios y que aparecen en URLs (`usuarios`, `denuncias`), para que no se puedan enumerar.
  - `serial` o `bigserial` en catálogos y datos importados.
- Fechas en `timestamptz`, siempre en UTC. La zona `America/Mexico_City` se aplica solo al mostrarlas.
- Dinero en `numeric(16,2)`, en MXN. Nunca `float`.
- Estados y catálogos cerrados como `ENUM` de PostgreSQL. Los catálogos que edita un administrador son tablas.
- Todas las tablas de contenido llevan `municipio_id` (o se relacionan a un municipio), porque el modelo es multi-municipio desde el inicio.

## Extensiones

| Extensión | Uso |
|---|---|
| `citext` | Correos sin distinguir mayúsculas y minúsculas |
| `unaccent` | Configuración de búsqueda `es` que ignora acentos ("policia" encuentra "policía") |
| `pg_trgm` | Búsqueda difusa de proveedores ("Constructora XYZ SA de CV" ≈ "CONSTRUCTORA X.Y.Z.") |

## Diagrama de relaciones

```
entidades ─< municipios ─< colonias
                 │
                 ├──< funcionarios_municipios >── funcionarios >── cargos
                 │                                    │  └──> partidos
                 │                                    └──< funcionarios_fuentes >── fuentes
                 │
                 ├──< denuncias >── categorias_denuncia
                 │       ├──< fotos
                 │       ├──< apoyos >── usuarios
                 │       ├──< reportes
                 │       ├──< moderacion_eventos
                 │       └──< replicas >── funcionarios
                 │
                 ├──< importaciones_gasto >── fuentes
                 │       ├──< presupuesto >── clasificador_gasto
                 │       └──< contratos >── proveedores
                 ├──< alertas_gasto >── reglas_alerta
                 │
                 └──< encuestas ─< preguntas ─< opciones
                                        └──< votos

usuarios ─< sesiones
usuarios ─< tokens_email
vedas · rutas_accion · auditoria        (independientes)
```

## Tablas

### Territorio

| Tabla | Descripción |
|---|---|
| `entidades` | Estados. `id` es la clave INEGI (Puebla = 21). |
| `municipios` | `clave_inegi` de 5 dígitos y `slug` para URLs (`atlixco`). |
| `colonias` | Catálogo para ubicar denuncias y el perfil opcional del usuario. |

### Usuarios y sesiones

**`usuarios`**

| Columna | Tipo | Notas |
|---|---|---|
| `id` | uuid PK | |
| `email` | citext UNIQUE | `NULL` cuando la cuenta se elimina |
| `password_hash` | text | Argon2id; `NULL` cuando la cuenta se elimina |
| `rol` | `ciudadano` \| `moderador` \| `admin` | |
| `email_verificado_en` | timestamptz | `NULL` = no puede denunciar, apoyar ni votar |
| `colonia_id`, `rango_edad` | | Opcionales; solo para estadísticas agregadas |
| `terminos_version`, `terminos_aceptados_en` | | Prueba del consentimiento |
| `bloqueado_en`, `eliminado_en` | timestamptz | |

**Eliminar una cuenta** (derechos ARCO) no borra la fila:

1. Se ponen en `NULL` el `email`, el `password_hash` y los datos opcionales, y se marca `eliminado_en`.
2. Se borran sus sesiones.
3. Las denuncias quedan publicadas, pero ya no se pueden ligar a nadie.

Un `CHECK` impide que quede una cuenta "eliminada" que todavía tenga correo.

**`sesiones`:** `token_hash` es el SHA-256 del token de la cookie. `expira_en` marca el límite absoluto de 30 días; la inactividad se controla con `ultimo_uso_en`. Un job diario borra las sesiones expiradas, y con ellas la IP.

**`tokens_email`:** tokens de verificación de correo (expiran en 24 h) y de recuperación de contraseña (1 h). Son de un solo uso (`usado_en`).

### Procedencia

**`fuentes`:** cada fuente oficial tiene URL, título, institución, fecha de consulta y, cuando hay un archivo, su `sha256` y una copia en el almacenamiento (`archivo_key`). Tanto `funcionarios_fuentes` como `importaciones_gasto` apuntan aquí.

### Funcionarios

| Tabla | Descripción |
|---|---|
| `partidos` | Siglas, nombre y color (solo para la etiqueta del partido) |
| `cargos` | Cargo y nivel (`municipal`, `estatal`, `federal`) |
| `funcionarios` | Nombre, cargo, entidad, distrito (legisladores), partido y coalición que lo postularon, periodo, foto con crédito, semblanza, comisiones y enlaces |
| `funcionarios_municipios` | Municipios que gobierna o representa. Un diputado de distrito cubre varios municipios, por eso es N:M. Los "23 de Atlixco" son `WHERE municipio_id = <atlixco>`. |
| `funcionarios_fuentes` | Qué fuente respalda cada dato (`campo`: `cargo`, `partido`, `foto`, …) |

### Denuncias

**`denuncias`**

| Columna | Notas |
|---|---|
| `id` | uuid |
| `autor_id` | `SET NULL` si el usuario se elimina |
| `municipio_id`, `colonia_id`, `categoria_id`, `funcionario_id`, `dependencia` | |
| `titulo` | 10 a 120 caracteres |
| `descripcion` | 30 a 5 000 caracteres |
| `lat`, `lng` | `numeric(6,3)`: el backend redondea a 3 decimales (unos 110 m) **antes** de guardar |
| `mostrar_como` | `colonia` o `anonimo` |
| `estado` | Ver la máquina de estados abajo |
| `apoyos_count` | Contador desnormalizado; se actualiza en la misma transacción que `apoyos` |
| `busqueda` | `tsvector` generado (configuración `es`) con índice GIN |

Máquina de estados:

```
                ┌──────── cambios_solicitados ◄──┐
                ▼                                │
  pendiente ──► (moderador) ──┬──► publicada ──► en_seguimiento ──► resuelta
                              │        │                       └──► sin_respuesta
                              └──► rechazada
  publicada | en_seguimiento ──► oculta   (por reportes atendidos)
```

Cada transición inserta una fila en `moderacion_eventos` con estado anterior, estado nuevo, motivo (`motivo_rechazo`), nota para el autor y evidencia.

| Tabla | Descripción |
|---|---|
| `fotos` | Hasta 3 por denuncia (la regla se aplica en el backend). Se suben antes de crear la denuncia con `denuncia_id = NULL`; un job borra las huérfanas de más de 24 h. |
| `apoyos` | PK `(denuncia_id, usuario_id)`: un apoyo por persona. |
| `reportes` | `UNIQUE (denuncia_id, usuario_id)`: un reporte por persona y denuncia. |
| `replicas` | Réplica de un funcionario. `correo_contacto` es privado. Se publica solo con estado `aprobada`. |

### Gasto público

| Tabla | Descripción |
|---|---|
| `clasificador_gasto` | Clasificador por Objeto del Gasto del CONAC, jerárquico: capítulo `3000` → concepto `3100` → partida `31101` |
| `importaciones_gasto` | Una carga de archivo: fuente, ejercicio, tipo (`presupuesto` o `contratos`), estado, filas buenas y con error, detalle de errores |
| `presupuesto` | Aprobado, modificado y ejercido por clave del clasificador y ejercicio |
| `proveedores` | RFC (único cuando existe) y nombre con índice de trigramas para deduplicar |
| `contratos` | Número, proveedor, objeto, procedimiento, monto, fecha, partida, dependencia y enlace al documento |
| `reglas_alerta` | Catálogo público de reglas y sus parámetros. El `slug` coincide con la función en `backend/src/services/alertas/`. |
| `alertas_gasto` | Resultado de evaluar las reglas después de cada importación, con los valores que la dispararon en `detalle` |

**Reimportar** un ejercicio crea una importación nueva. Las consultas públicas usan la **última importación `completada`** por municipio, ejercicio y tipo. Las anteriores se conservan para poder auditar los cambios.

Reglas iniciales (los parámetros se ajustan en la tabla):

| `slug` | Se dispara cuando |
|---|---|
| `adjudicacion_directa_alta` | Un contrato por adjudicación directa supera `umbral_mxn` |
| `concentracion_proveedor` | Un proveedor recibe más del `porcentaje` del monto contratado del ejercicio |
| `sobreejercicio` | Lo ejercido en un capítulo supera lo aprobado en más del `porcentaje` |
| `contratos_fraccionados` | El mismo proveedor tiene `n` o más adjudicaciones directas en `dias` días que juntas superan `umbral_mxn` |

### Encuesta pulso

| Tabla | Descripción |
|---|---|
| `encuestas` | Una ronda (mensual) por municipio, con apertura, cierre y el mínimo de respuestas para publicar resultados (50) |
| `preguntas` | `intencion` o `aprobacion`. Un `CHECK` exige `funcionario_id` solo en las de aprobación. |
| `opciones` | Etiqueta más un vínculo opcional a funcionario o partido. Siempre incluye "Ninguno" y "No sé". |
| `votos` | PK `(pregunta_id, votante)`, donde `votante = HMAC-SHA256(VOTE_SECRET, usuario_id ‖ pregunta_id)`. **No guarda `usuario_id`.** Cambiar el voto es un `UPSERT`. |
| `vedas` | Periodos en que las preguntas de `intencion` se cierran y sus resultados se ocultan. `entidad_id NULL` significa veda federal. |

Si se pierde `VOTE_SECRET`, las rondas abiertas ya no pueden evitar votos duplicados. Por eso se respalda junto con los demás secretos.

### Rutas de acción y auditoría

- **`rutas_accion`:** contenido en Markdown. Un `CHECK` impide publicar una ruta sin `revisado_por` y `revisado_en`.
- **`auditoria`:** toda acción de un moderador o administrador, con quién la hizo, qué cambió (`cambios` como `{campo: [antes, después]}`) y cuándo. Nunca se borra.

## Migraciones

- Herramienta: [`node-pg-migrate`](https://salsita.github.io/node-pg-migrate/) con migraciones en **SQL plano** en `code/database/migrations/`.
- Nombre de archivo: `<timestamp>_<descripcion-en-kebab>.sql`, por ejemplo `20261001120000_esquema-inicial.sql`.
- La primera migración será el contenido de `schema.sql`.
- Después de cada migración nueva se regenera `schema.sql` con `npm run db:dump` (`pg_dump --schema-only`) y se commitea junto con la migración.
- Las migraciones deben ser **compatibles hacia atrás** con la versión anterior del backend, porque el deploy migra antes de reiniciar. Para renombrar una columna: primero se agrega la nueva, luego se despliega, luego se elimina la vieja.
- Nunca se edita una migración que ya se aplicó en staging o en producción.

```bash
cd code/backend
npm run migrate            # aplica las pendientes
npm run migrate:create -- nombre-del-cambio
npm run migrate:down       # revierte la última (solo en desarrollo)
```

## Seeds

En `code/database/seeds/`, en orden:

| Archivo | Contenido | Entornos |
|---|---|---|
| `01_catalogos.sql` | Entidad Puebla, municipio Atlixco, colonias (catálogo de SEPOMEX), cargos, categorías de denuncia, capítulos y conceptos del clasificador CONAC, reglas de alerta | Todos |
| `02_partidos.sql` | Partidos con registro vigente según INE e IEE Puebla | Todos |
| `03_desarrollo.sql` | Usuarios de prueba (`admin@polaca.test`, `mod@polaca.test`, `ciudadano@polaca.test`), funcionarios **ficticios**, denuncias, un ejercicio de gasto inventado y una encuesta abierta | Solo desarrollo y staging |

**Los datos de funcionarios reales no van en seeds.** Se capturan en producción desde el panel de administración, con su fuente, para que cada dato quede en la bitácora de auditoría.

```bash
npm run seed               # aplica 01 y 02
npm run seed:dev           # aplica 01, 02 y 03
```

## Respaldos

Ver [DEPLOYMENT.md](DEPLOYMENT.md#respaldos).
