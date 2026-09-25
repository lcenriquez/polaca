# Código — POLACA

Guía técnica para desarrolladores. La funcionalidad se define en [`spec/PLATFORM_SPECIFICATION.md`](../spec/PLATFORM_SPECIFICATION.md).

## Stack

| Capa | Tecnología |
|---|---|
| Frontend | Next.js 16 · React 19 · TypeScript |
| Backend | Node.js 24 · Fastify 5 · TypeScript · Kysely |
| Base de datos | PostgreSQL 16 o superior |
| Pruebas | Vitest · React Testing Library (cobertura de 70 % o más) |
| CI/CD | GitHub Actions → GHCR → VPS con Docker Compose |
| Infraestructura | Hetzner · Cloudflare (CDN y R2) · Amazon SES |

## Documentación

| Documento | Contenido |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Stack, arquitectura, decisiones, escalabilidad y seguridad |
| [API.md](docs/API.md) | Endpoints |
| [DATABASE.md](docs/DATABASE.md) | Modelo de datos, migraciones y seeds |
| [SETUP.md](docs/SETUP.md) | Cómo levantar el proyecto localmente |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Staging, producción, variables y respaldos |
| [CONTRIBUTING_CODE.md](docs/CONTRIBUTING_CODE.md) | Convenciones de código y de PR |

## Estructura

```
code/
├── docs/                 # documentación técnica
├── frontend/             # Next.js
├── backend/              # Fastify
├── database/
│   ├── schema.sql        # esquema completo de referencia
│   ├── migrations/       # migraciones SQL (node-pg-migrate)
│   └── seeds/            # catálogos y datos ficticios
└── docker-compose.yml    # PostgreSQL y Mailpit para desarrollo
```

Los workflows de CI/CD están en [`/.github/workflows/`](../.github/workflows/), en la raíz, porque GitHub solo los ejecuta desde ahí.

## Inicio rápido

```bash
cd code && docker compose up -d
cd backend && npm install && cp .env.example .env && npm run migrate && npm run seed:dev && npm run dev
# en otra terminal
cd code/frontend && npm install && cp .env.example .env.local && npm run dev
```

Guía completa en [SETUP.md](docs/SETUP.md).
