# Frontend — POLACA

Next.js 16 (App Router), React 19 y TypeScript. Renderizado en servidor para las páginas públicas, que así tienen vista previa al compartirse en WhatsApp y Facebook.

- Arquitectura: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)
- Cómo levantarlo: [`../docs/SETUP.md`](../docs/SETUP.md)
- Diseño: [`../../design/`](../../design/)

## Estructura

```
src/
├── app/          # rutas de Next.js: páginas y layouts
├── components/   # componentes de UI reutilizables (PascalCase)
├── services/     # cliente HTTP del API
├── hooks/        # hooks de React (useX)
└── utils/        # funciones puras: formato de dinero, fechas
public/           # archivos estáticos: favicon, manifest de la PWA
```

En desarrollo, `next.config.ts` hace de proxy de `/api/*` hacia `API_INTERNAL_URL`, así que frontend y API comparten origen igual que en producción.

## Scripts

| Comando | Qué hace |
|---|---|
| `npm run dev` | Servidor de desarrollo en `:3000` |
| `npm test` | Vitest + Testing Library, con cobertura |
| `npm run build` | Build de producción |

> **Estado:** pre-MVP. El código se escribe a partir de la semana 3, cuando estén listos los wireframes.
