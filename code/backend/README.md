# Backend — POLACA

API REST con Fastify 5, TypeScript, Kysely y PostgreSQL.

- Endpoints: [`../docs/API.md`](../docs/API.md)
- Arquitectura: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)
- Cómo levantarlo: [`../docs/SETUP.md`](../docs/SETUP.md)

## Estructura

```
src/
├── routes/       # declaración de rutas y esquemas (un archivo por recurso)
├── controllers/  # manejo de la petición y la respuesta
├── services/     # lógica de negocio: moderación, importadores, alertas, correo
├── models/       # tipos de Kysely y consultas
└── middleware/   # sesión, roles, Origin/CSRF, límite de peticiones
```

Las migraciones y los seeds viven en [`../database/`](../database/).

## Scripts

| Comando | Qué hace |
|---|---|
| `npm run dev` | Servidor en modo watch en `:4000` |
| `npm test` | Pruebas con cobertura (mínimo 70 %) |
| `npm run migrate` | Aplica las migraciones pendientes |
| `npm run seed` / `seed:dev` | Carga catálogos / catálogos y datos ficticios |
| `npm run db:dump` | Regenera `../database/schema.sql` |

> **Estado:** pre-MVP. Los scripts están definidos; el código fuente se escribe a partir de la semana 3 (ver el plan en la especificación).
