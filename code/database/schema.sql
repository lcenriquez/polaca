-- POLACA — esquema de referencia (PostgreSQL 16+)
-- Las migraciones en ./migrations son la fuente de verdad; este archivo es la
-- foto completa del esquema. Documentación: ../docs/DATABASE.md

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Búsqueda de texto en español que ignora acentos.
CREATE TEXT SEARCH CONFIGURATION es (COPY = spanish);
ALTER TEXT SEARCH CONFIGURATION es
  ALTER MAPPING FOR hword, hword_part, word WITH unaccent, spanish_stem;

-- ─── Tipos ───────────────────────────────────────────────────────────────

CREATE TYPE rol_usuario       AS ENUM ('ciudadano', 'moderador', 'admin');
CREATE TYPE rango_edad        AS ENUM ('18_24', '25_34', '35_44', '45_54', '55_64', '65_mas');
CREATE TYPE tipo_token        AS ENUM ('verificacion', 'recuperacion');
CREATE TYPE nivel_gobierno    AS ENUM ('municipal', 'estatal', 'federal');
CREATE TYPE estado_denuncia   AS ENUM ('pendiente', 'cambios_solicitados', 'rechazada', 'publicada',
                                       'en_seguimiento', 'resuelta', 'sin_respuesta', 'oculta');
CREATE TYPE mostrar_autor     AS ENUM ('colonia', 'anonimo');
CREATE TYPE motivo_rechazo    AS ENUM ('datos_personales', 'acusacion_sin_evidencia', 'odio', 'propaganda',
                                       'spam', 'duplicada', 'fuera_de_alcance', 'otro');
CREATE TYPE motivo_reporte    AS ENUM ('datos_personales', 'falso', 'odio', 'propaganda', 'spam', 'otro');
CREATE TYPE estado_revision   AS ENUM ('pendiente', 'aprobada', 'rechazada');
CREATE TYPE estado_reporte    AS ENUM ('abierto', 'descartado', 'atendido');
CREATE TYPE tipo_procedimiento AS ENUM ('licitacion_publica', 'invitacion_restringida', 'adjudicacion_directa', 'otro');
CREATE TYPE tipo_importacion  AS ENUM ('presupuesto', 'contratos');
CREATE TYPE estado_importacion AS ENUM ('procesando', 'completada', 'fallida');
CREATE TYPE tipo_pregunta     AS ENUM ('intencion', 'aprobacion');

-- ─── Territorio ──────────────────────────────────────────────────────────

CREATE TABLE entidades (
  id           smallint PRIMARY KEY,               -- clave INEGI de la entidad
  nombre       text NOT NULL
);

CREATE TABLE municipios (
  id           serial PRIMARY KEY,
  entidad_id   smallint NOT NULL REFERENCES entidades,
  clave_inegi  char(5) NOT NULL UNIQUE,            -- entidad (2) + municipio (3)
  nombre       text NOT NULL,
  slug         text NOT NULL UNIQUE
);

CREATE TABLE colonias (
  id            serial PRIMARY KEY,
  municipio_id  int NOT NULL REFERENCES municipios,
  nombre        text NOT NULL,
  codigo_postal char(5),
  UNIQUE (municipio_id, nombre, codigo_postal)
);

-- ─── Usuarios y sesiones ────────────────────────────────────────────────

CREATE TABLE usuarios (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email               citext UNIQUE,                -- NULL cuando la cuenta se elimina
  password_hash       text,
  rol                 rol_usuario NOT NULL DEFAULT 'ciudadano',
  email_verificado_en timestamptz,
  colonia_id          int REFERENCES colonias,
  rango_edad          rango_edad,
  terminos_version    text NOT NULL,                -- versión del aviso/términos aceptados
  terminos_aceptados_en timestamptz NOT NULL,
  bloqueado_en        timestamptz,
  eliminado_en        timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CHECK ((eliminado_en IS NULL) = (email IS NOT NULL AND password_hash IS NOT NULL))
);

CREATE TABLE sesiones (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario_id    uuid NOT NULL REFERENCES usuarios ON DELETE CASCADE,
  token_hash    bytea NOT NULL UNIQUE,              -- sha256 del token de la cookie
  ip            inet,
  user_agent    text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  ultimo_uso_en timestamptz NOT NULL DEFAULT now(),
  expira_en     timestamptz NOT NULL
);
CREATE INDEX ON sesiones (usuario_id);
CREATE INDEX ON sesiones (expira_en);

CREATE TABLE tokens_email (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario_id  uuid NOT NULL REFERENCES usuarios ON DELETE CASCADE,
  tipo        tipo_token NOT NULL,
  token_hash  bytea NOT NULL UNIQUE,
  expira_en   timestamptz NOT NULL,
  usado_en    timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- ─── Procedencia ────────────────────────────────────────────────────────

CREATE TABLE fuentes (
  id            serial PRIMARY KEY,
  url           text NOT NULL,
  titulo        text NOT NULL,
  institucion   text NOT NULL,                      -- p. ej. "IEE Puebla", "PNT", "ASEP"
  consultado_en date NOT NULL,
  sha256        char(64),                           -- hash del archivo original, si lo hay
  archivo_key   text,                               -- copia del original en el almacenamiento
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- ─── Funcionarios ───────────────────────────────────────────────────────

CREATE TABLE partidos (
  id        serial PRIMARY KEY,
  siglas    text NOT NULL UNIQUE,
  nombre    text NOT NULL,
  color_hex char(7)                                 -- solo para la etiqueta del partido
);

CREATE TABLE cargos (
  id      serial PRIMARY KEY,
  nombre  text NOT NULL UNIQUE,                     -- "Presidente/a municipal", "Regidor/a", …
  nivel   nivel_gobierno NOT NULL,
  orden   smallint NOT NULL DEFAULT 0
);

CREATE TABLE funcionarios (
  id              serial PRIMARY KEY,
  slug            text NOT NULL UNIQUE,
  nombre          text NOT NULL,
  cargo_id        int NOT NULL REFERENCES cargos,
  entidad_id      smallint NOT NULL REFERENCES entidades,
  distrito        text,                             -- para legisladores
  partido_id      int REFERENCES partidos,          -- partido que lo postuló
  coalicion       text,
  periodo_inicio  date NOT NULL,
  periodo_fin     date NOT NULL,
  foto_key        text,
  foto_credito    text,
  semblanza       text,
  comisiones      text[] NOT NULL DEFAULT '{}',
  enlaces         jsonb NOT NULL DEFAULT '[]',      -- [{ "etiqueta": "...", "url": "..." }]
  activo          boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (periodo_fin > periodo_inicio)
);

-- Municipios que gobierna o representa (un diputado de distrito cubre varios).
CREATE TABLE funcionarios_municipios (
  funcionario_id int NOT NULL REFERENCES funcionarios ON DELETE CASCADE,
  municipio_id   int NOT NULL REFERENCES municipios,
  PRIMARY KEY (funcionario_id, municipio_id)
);
CREATE INDEX ON funcionarios_municipios (municipio_id);

CREATE TABLE funcionarios_fuentes (
  funcionario_id int NOT NULL REFERENCES funcionarios ON DELETE CASCADE,
  fuente_id      int NOT NULL REFERENCES fuentes,
  campo          text NOT NULL,                     -- qué dato respalda: "cargo", "partido", "foto", …
  PRIMARY KEY (funcionario_id, fuente_id, campo)
);

-- ─── Denuncias ──────────────────────────────────────────────────────────

CREATE TABLE categorias_denuncia (
  id      serial PRIMARY KEY,
  slug    text NOT NULL UNIQUE,
  nombre  text NOT NULL,
  orden   smallint NOT NULL DEFAULT 0
);

CREATE TABLE denuncias (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  autor_id        uuid REFERENCES usuarios ON DELETE SET NULL,
  municipio_id    int NOT NULL REFERENCES municipios,
  colonia_id      int REFERENCES colonias,
  categoria_id    int NOT NULL REFERENCES categorias_denuncia,
  funcionario_id  int REFERENCES funcionarios,
  dependencia     text,
  titulo          text NOT NULL CHECK (char_length(titulo) BETWEEN 10 AND 120),
  descripcion     text NOT NULL CHECK (char_length(descripcion) BETWEEN 30 AND 5000),
  fecha_hecho     date,
  lat             numeric(6,3) CHECK (lat BETWEEN -90 AND 90),     -- redondeado a ~110 m
  lng             numeric(6,3) CHECK (lng BETWEEN -180 AND 180),
  mostrar_como    mostrar_autor NOT NULL DEFAULT 'colonia',
  estado          estado_denuncia NOT NULL DEFAULT 'pendiente',
  apoyos_count    int NOT NULL DEFAULT 0,
  publicada_en    timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  busqueda        tsvector GENERATED ALWAYS AS
                    (to_tsvector('es', titulo || ' ' || descripcion)) STORED,
  CHECK ((lat IS NULL) = (lng IS NULL))
);
CREATE INDEX ON denuncias (municipio_id, estado, publicada_en DESC);
CREATE INDEX ON denuncias (funcionario_id) WHERE funcionario_id IS NOT NULL;
CREATE INDEX ON denuncias (autor_id);
CREATE INDEX ON denuncias (lat, lng) WHERE lat IS NOT NULL;
CREATE INDEX ON denuncias USING gin (busqueda);

CREATE TABLE fotos (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  denuncia_id  uuid REFERENCES denuncias ON DELETE CASCADE,  -- NULL hasta adjuntarse
  subido_por   uuid REFERENCES usuarios ON DELETE SET NULL,
  storage_key  text NOT NULL UNIQUE,
  ancho        int NOT NULL,
  alto         int NOT NULL,
  bytes        int NOT NULL CHECK (bytes <= 5 * 1024 * 1024),
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON fotos (denuncia_id);

CREATE TABLE apoyos (
  denuncia_id uuid NOT NULL REFERENCES denuncias ON DELETE CASCADE,
  usuario_id  uuid NOT NULL REFERENCES usuarios ON DELETE CASCADE,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (denuncia_id, usuario_id)
);

CREATE TABLE reportes (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  denuncia_id  uuid NOT NULL REFERENCES denuncias ON DELETE CASCADE,
  usuario_id   uuid REFERENCES usuarios ON DELETE SET NULL,
  motivo       motivo_reporte NOT NULL,
  comentario   text CHECK (char_length(comentario) <= 1000),
  estado       estado_reporte NOT NULL DEFAULT 'abierto',
  resuelto_por uuid REFERENCES usuarios,
  resuelto_en  timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (denuncia_id, usuario_id)
);
CREATE INDEX ON reportes (estado) WHERE estado = 'abierto';

-- Historial de moderación y de cambios de estado.
CREATE TABLE moderacion_eventos (
  id               bigserial PRIMARY KEY,
  denuncia_id      uuid NOT NULL REFERENCES denuncias ON DELETE CASCADE,
  moderador_id     uuid REFERENCES usuarios,
  estado_anterior  estado_denuncia NOT NULL,
  estado_nuevo     estado_denuncia NOT NULL,
  motivo           motivo_rechazo,
  nota             text,                            -- visible para el autor
  evidencia_url    text,
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON moderacion_eventos (denuncia_id);

-- Derecho de réplica de funcionarios.
CREATE TABLE replicas (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  funcionario_id   int NOT NULL REFERENCES funcionarios,
  denuncia_id      uuid REFERENCES denuncias ON DELETE CASCADE,
  remitente_nombre text NOT NULL,
  remitente_cargo  text NOT NULL,
  correo_contacto  citext NOT NULL,                 -- privado, nunca se publica
  texto            text NOT NULL CHECK (char_length(texto) BETWEEN 30 AND 5000),
  estado           estado_revision NOT NULL DEFAULT 'pendiente',
  revisado_por     uuid REFERENCES usuarios,
  publicada_en     timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON replicas (funcionario_id);
CREATE INDEX ON replicas (denuncia_id);

-- ─── Gasto público ──────────────────────────────────────────────────────

-- Clasificador por Objeto del Gasto (CONAC): capítulo → concepto → partida.
CREATE TABLE clasificador_gasto (
  clave        varchar(5) PRIMARY KEY,              -- "3000", "3100", "31101"
  nombre       text NOT NULL,
  padre        varchar(5) REFERENCES clasificador_gasto
);

CREATE TABLE importaciones_gasto (
  id            serial PRIMARY KEY,
  municipio_id  int NOT NULL REFERENCES municipios,
  fuente_id     int NOT NULL REFERENCES fuentes,
  ejercicio     smallint NOT NULL CHECK (ejercicio BETWEEN 2000 AND 2100),
  tipo          tipo_importacion NOT NULL,
  estado        estado_importacion NOT NULL DEFAULT 'procesando',
  filas_ok      int NOT NULL DEFAULT 0,
  filas_error   int NOT NULL DEFAULT 0,
  errores       jsonb NOT NULL DEFAULT '[]',        -- [{ "fila": 12, "error": "..." }]
  importado_por uuid REFERENCES usuarios,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE presupuesto (
  id             bigserial PRIMARY KEY,
  importacion_id int NOT NULL REFERENCES importaciones_gasto ON DELETE CASCADE,
  municipio_id   int NOT NULL REFERENCES municipios,
  ejercicio      smallint NOT NULL,
  clave_cog      varchar(5) NOT NULL REFERENCES clasificador_gasto,
  aprobado       numeric(16,2) NOT NULL,
  modificado     numeric(16,2),
  ejercido       numeric(16,2),
  UNIQUE (importacion_id, clave_cog)
);
CREATE INDEX ON presupuesto (municipio_id, ejercicio);

CREATE TABLE proveedores (
  id      serial PRIMARY KEY,
  rfc     varchar(13) UNIQUE,
  nombre  text NOT NULL
);
CREATE INDEX ON proveedores USING gin (nombre gin_trgm_ops);

CREATE TABLE contratos (
  id             bigserial PRIMARY KEY,
  importacion_id int NOT NULL REFERENCES importaciones_gasto ON DELETE CASCADE,
  municipio_id   int NOT NULL REFERENCES municipios,
  ejercicio      smallint NOT NULL,
  numero         text,
  proveedor_id   int REFERENCES proveedores,
  objeto         text NOT NULL,
  procedimiento  tipo_procedimiento NOT NULL,
  monto          numeric(16,2) NOT NULL CHECK (monto >= 0),   -- MXN con IVA
  fecha          date,
  clave_cog      varchar(5) REFERENCES clasificador_gasto,
  dependencia    text,
  documento_url  text,
  busqueda       tsvector GENERATED ALWAYS AS (to_tsvector('es', objeto)) STORED
);
CREATE INDEX ON contratos (municipio_id, ejercicio);
CREATE INDEX ON contratos (proveedor_id);
CREATE INDEX ON contratos USING gin (busqueda);

CREATE TABLE reglas_alerta (
  slug         text PRIMARY KEY,                    -- coincide con la función en backend/src/services/alertas
  nombre       text NOT NULL,
  descripcion  text NOT NULL,                       -- explicación pública
  parametros   jsonb NOT NULL DEFAULT '{}',         -- p. ej. { "umbral_mxn": 500000 }
  activa       boolean NOT NULL DEFAULT true
);

CREATE TABLE alertas_gasto (
  id              bigserial PRIMARY KEY,
  regla_slug      text NOT NULL REFERENCES reglas_alerta,
  municipio_id    int NOT NULL REFERENCES municipios,
  ejercicio       smallint NOT NULL,
  contrato_id     bigint REFERENCES contratos ON DELETE CASCADE,
  presupuesto_id  bigint REFERENCES presupuesto ON DELETE CASCADE,
  proveedor_id    int REFERENCES proveedores,
  detalle         jsonb NOT NULL,                   -- valores que dispararon la regla
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON alertas_gasto (municipio_id, ejercicio);

-- ─── Encuesta pulso ─────────────────────────────────────────────────────

CREATE TABLE encuestas (
  id            serial PRIMARY KEY,
  municipio_id  int NOT NULL REFERENCES municipios,
  titulo        text NOT NULL,                      -- "Pulso octubre 2026"
  abre_en       timestamptz NOT NULL,
  cierra_en     timestamptz NOT NULL,
  minimo_publicacion int NOT NULL DEFAULT 50,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CHECK (cierra_en > abre_en)
);

CREATE TABLE preguntas (
  id              serial PRIMARY KEY,
  encuesta_id     int NOT NULL REFERENCES encuestas ON DELETE CASCADE,
  tipo            tipo_pregunta NOT NULL,
  funcionario_id  int REFERENCES funcionarios,      -- para preguntas de aprobación
  texto           text NOT NULL,
  orden           smallint NOT NULL DEFAULT 0,
  CHECK ((tipo = 'aprobacion') = (funcionario_id IS NOT NULL))
);

CREATE TABLE opciones (
  id              serial PRIMARY KEY,
  pregunta_id     int NOT NULL REFERENCES preguntas ON DELETE CASCADE,
  etiqueta        text NOT NULL,                    -- "Ninguno", "No sé", nombre o partido
  funcionario_id  int REFERENCES funcionarios,
  partido_id      int REFERENCES partidos,
  orden           smallint NOT NULL DEFAULT 0
);

-- Votos seudonimizados: votante = HMAC(VOTE_SECRET, usuario_id || pregunta_id).
CREATE TABLE votos (
  pregunta_id  int NOT NULL REFERENCES preguntas ON DELETE CASCADE,
  votante      bytea NOT NULL,
  opcion_id    int NOT NULL REFERENCES opciones,
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (pregunta_id, votante)
);
CREATE INDEX ON votos (pregunta_id, opcion_id);

-- Periodos en que la encuesta de intención de voto se cierra y oculta.
CREATE TABLE vedas (
  id           serial PRIMARY KEY,
  entidad_id   smallint REFERENCES entidades,       -- NULL = nacional
  descripcion  text NOT NULL,
  inicia_en    timestamptz NOT NULL,
  termina_en   timestamptz NOT NULL,
  CHECK (termina_en > inicia_en)
);

-- ─── Rutas de acción ────────────────────────────────────────────────────

CREATE TABLE rutas_accion (
  id            serial PRIMARY KEY,
  slug          text NOT NULL UNIQUE,
  titulo        text NOT NULL,
  resumen       text NOT NULL,
  contenido_md  text NOT NULL,
  revisado_por  text,                               -- nombre de quien hizo la revisión jurídica
  revisado_en   date,
  publicada     boolean NOT NULL DEFAULT false,
  orden         smallint NOT NULL DEFAULT 0,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CHECK (NOT publicada OR (revisado_por IS NOT NULL AND revisado_en IS NOT NULL))
);

-- ─── Auditoría ──────────────────────────────────────────────────────────

CREATE TABLE auditoria (
  id          bigserial PRIMARY KEY,
  actor_id    uuid REFERENCES usuarios,
  accion      text NOT NULL,                        -- "funcionario.actualizar", "usuario.bloquear", …
  entidad     text NOT NULL,
  entidad_id  text NOT NULL,
  cambios     jsonb,                                -- { "campo": [antes, después] }
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON auditoria (entidad, entidad_id);
