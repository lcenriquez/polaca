# Contribuir código — POLACA

Primero lee [`CONTRIBUTING.md`](../../CONTRIBUTING.md) en la raíz, que tiene el flujo general, las reglas de contenido y la licencia. Aquí están los detalles técnicos.

## Setup para contribuyentes

1. Haz fork del repo en GitHub.
2. Clona tu fork:

   ```bash
   git clone git@github.com:<tu-usuario>/polaca.git
   ```
3. Sigue [SETUP.md](SETUP.md).
4. Crea una rama:

   ```bash
   git checkout -b feat/filtro-colonia
   ```
5. Haz commits claros con [Conventional Commits](https://www.conventionalcommits.org/es/), con la descripción en español:

   ```bash
   git commit -m "feat: agregar filtro por colonia en denuncias"
   ```
6. Corre las pruebas: `npm test` en `frontend` y en `backend`. La cobertura mínima es de 70 % y la CI falla si baja.
7. Abre un PR hacia `main` usando la plantilla.

## Convenciones de código

### General

- TypeScript en modo `strict`. Evita `any`; si es inevitable, deja un comentario que explique por qué.
- Idioma:
  - **Dominio en español**: rutas, tablas, campos de la API y variables de negocio (`denuncia`, `funcionario`, `apoyosCount`).
  - Términos técnicos en inglés cuando son el estándar (`handler`, `middleware`, `hook`).
  - Comentarios y documentación en español.
- Mantén las funciones cortas y con una sola responsabilidad. Como guía, unas 20 líneas; no es un límite absoluto.
- Prefiere funciones puras. La lógica de negocio (reglas de alerta, transiciones de estado, redondeo de ubicación) va en funciones puras y probadas.
- Formato y estilo: ESLint (`npm run lint`). No discutas estilo en las revisiones: lo que no marca el linter, no bloquea un PR.
- Antes de agregar una dependencia nueva, justifícala en el PR. Si son menos de 20 líneas de código propio, no se agrega.

### Frontend

| Elemento | Convención |
|---|---|
| Variables y funciones | `camelCase` |
| Componentes y sus archivos | `PascalCase` (`TarjetaDenuncia.tsx`) |
| Hooks | `useX` (`useSesion.ts`) |
| Estilos | CSS Module junto al componente (`TarjetaDenuncia.module.css`), usando los tokens de `design/DESIGN_SYSTEM.md` |

- Los datos se leen en **server components** siempre que se pueda. Usa `"use client"` solo cuando haga falta interacción.
- **Accesibilidad:** HTML semántico, `label` en cada input, foco visible y contraste AA. Las pruebas de componentes consultan por rol (`getByRole`), no por clase.
- Pruebas: Vitest + React Testing Library, en `*.test.tsx` junto al componente.

### Backend

| Elemento | Convención |
|---|---|
| Variables y funciones | `camelCase` |
| Tipos | `PascalCase` |
| Tablas y columnas | `snake_case` |

- Una capa por responsabilidad: `routes` (esquemas) → `controllers` (HTTP) → `services` (negocio) → `models` (SQL). Los controllers no escriben SQL.
- Todo endpoint declara el esquema de su cuerpo, de su query y de su respuesta. La respuesta con esquema evita filtrar campos por accidente, como el correo del autor.
- **Errores:** lanza `AppError(code, status, message)`; el manejador global da el formato `{ error: { code, message, details } }`.
- **Transacciones:** toda operación que escriba en más de una tabla usa una transacción, por ejemplo apoyo + `apoyos_count`, o moderación + `moderacion_eventos`.
- **Documentación:** un comentario TSDoc en español en cada función exportada de `services/`.
- **Pruebas:**
  - Vitest, en `*.test.ts` junto al archivo que prueban.
  - Los servicios se prueban contra PostgreSQL real, y cada prueba corre dentro de una transacción que se revierte al terminar.
  - Los endpoints se prueban con `fastify.inject()`.

### Base de datos

- Todo cambio de esquema es una migración SQL nueva, junto con `schema.sql` regenerado (`npm run db:dump`) y la actualización de [DATABASE.md](DATABASE.md).
- Si el cambio toca un endpoint, actualiza [API.md](API.md) en el mismo PR.

## Qué revisamos en un PR

- [ ] Pasa la CI: lint, tipos, pruebas y cobertura del 70 % o más.
- [ ] Documentación actualizada: API.md, DATABASE.md, etc.
- [ ] No expone datos personales: correo, IP o ubicación exacta.
- [ ] Los endpoints nuevos tienen control de acceso y límite de peticiones cuando corresponde.
- [ ] Los cambios visibles incluyen una captura de pantalla, en móvil y en escritorio.
