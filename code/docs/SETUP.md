# Cómo levantar el proyecto localmente

> **Estado pre-MVP:** el código de la aplicación todavía no existe. Estos son los pasos acordados y funcionarán en cuanto se escriba el código (a partir de la semana 3). La base de datos (`docker compose` y `schema.sql`) ya se puede usar hoy.

## Prerrequisitos

- **Node.js 24 LTS** (mínimo 22). Recomendado: [`fnm`](https://github.com/Schniz/fnm) o `nvm`.
- **Docker** con Docker Compose, para PostgreSQL y el buzón de correo de pruebas.
- **Git**

No hace falta instalar PostgreSQL en tu máquina.

## 1. Clonar e iniciar los servicios

```bash
git clone https://github.com/lcenriquez/polaca.git
cd polaca/code
docker compose up -d
```

Esto levanta:

- **PostgreSQL 18** en `localhost:5432` (usuario, contraseña y base: `polaca`).
- **Mailpit** en `localhost:1025` (SMTP). Los correos de verificación y recuperación se ven en <http://localhost:8025>.

## 2. Backend

```bash
cd backend
npm install
cp .env.example .env
npm run migrate      # crea las tablas
npm run seed:dev     # catálogos y datos ficticios
npm run dev          # API en http://localhost:4000
```

Comprueba que funciona: <http://localhost:4000/api/health> y <http://localhost:4000/api/docs>.

## 3. Frontend

En otra terminal:

```bash
cd code/frontend
npm install
cp .env.example .env.local
npm run dev          # http://localhost:3000
```

## Usuarios de prueba

Los crea `npm run seed:dev`. Las contraseñas están en [`code/database/seeds/03_desarrollo.sql`](../database/seeds/).

| Correo | Rol |
|---|---|
| `admin@polaca.test` | admin |
| `mod@polaca.test` | moderador |
| `ciudadano@polaca.test` | ciudadano (verificado) |

## Pruebas

```bash
cd code/backend && npm test     # usa DATABASE_URL; crea y limpia sus propios datos
cd code/frontend && npm test
```

Las pruebas del backend corren contra el PostgreSQL de `docker compose`, **no** contra mocks.

## Base de datos

```bash
npm run migrate:create -- agregar-campo-x   # nueva migración SQL en code/database/migrations
npm run migrate                             # aplicarla
npm run db:dump                             # regenerar code/database/schema.sql
```

Para empezar de cero:

```bash
docker compose down -v && docker compose up -d
```

Detalles en [DATABASE.md](DATABASE.md).

## Problemas comunes

| Síntoma | Solución |
|---|---|
| `ECONNREFUSED 127.0.0.1:5432` | El contenedor no está listo: `docker compose ps` y espera a que diga `healthy`. |
| El puerto 5432 está ocupado | Tienes un PostgreSQL local. Detenlo o cambia el puerto en `docker-compose.yml` y en `DATABASE_URL`. |
| No llegan los correos | Revisa <http://localhost:8025>; en desarrollo ningún correo sale a internet. |
| `argon2` o `sharp` fallan al instalar | Usa Node 22 o superior y borra `node_modules` antes de reinstalar. |
