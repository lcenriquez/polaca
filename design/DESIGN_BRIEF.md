# Brief de diseño — POLACA

> **La política no te ignora. ¿La ignoras tú?**

Antes de empezar, lee la especificación completa en [`spec/PLATFORM_SPECIFICATION.md`](../spec/PLATFORM_SPECIFICATION.md).

## Misión

Diseñar una interfaz **profesional, accesible y educativa** para que cualquier persona de Atlixco (y después de todo México) entienda quién la gobierna, qué pasa con el dinero público y qué puede hacer al respecto.

## Público

- **Ciudadanía general, de 18 a 65 años.** Usa el teléfono como dispositivo principal y a veces tiene datos móviles limitados. Su nivel de alfabetización digital es variado.
- **Periodistas y organizaciones civiles.** Buscan datos con fuente y quieren descargarlos.
- **Moderadores y administradores.** Voluntarios que revisan denuncias desde un panel.

## Tono

- Claro, directo y cercano, sin jerga legal ni burocrática. Se trata de tú a la persona usuaria.
- Serio y confiable, sin ser solemne; sin sensacionalismo ni alarmismo.
- **No partidista.** Nada en el diseño debe sugerir afinidad con un partido.

## Restricciones

| Tema | Regla |
|---|---|
| Colores | Evitar que el color principal coincida con el de algún partido (guinda, azul PAN, verde o rojo PRI, naranja MC, amarillo PRD, verde PVEM). Los colores de partido solo aparecen como etiqueta pequeña y neutra junto al nombre del partido, nunca como tema. |
| Contraste | WCAG 2.1 AA: 4.5:1 para texto normal y 3:1 para texto grande y componentes. |
| Móvil primero | Diseñar primero a 360 px de ancho y escalar hacia arriba. |
| Peso | Pocas imágenes decorativas; iconos en SVG; como máximo dos familias tipográficas, de preferencia con licencia libre (Google Fonts u OFL). |
| Accesibilidad | Objetivos táctiles de 44 px o más, foco visible, sin depender solo del color, y soporte para lectores de pantalla. |
| Fuentes de datos | Cada cifra o dato de un funcionario muestra de dónde viene (enlace y fecha). Diseñar un componente reutilizable de "fuente". |
| Encuesta | Toda pantalla con resultados muestra la leyenda "Sondeo en línea no representativo". |

## Entregables

1. **10 wireframes** (baja fidelidad):
   1. Inicio
   2. Lista de funcionarios
   3. Perfil de funcionario
   4. Lista y mapa de denuncias
   5. Detalle de denuncia
   6. Crear denuncia (flujo de varios pasos)
   7. Gasto público
   8. Encuesta pulso (votar y ver resultados)
   9. Ruta de acción
   10. Registro e inicio de sesión
2. **5 mockups de alta fidelidad:**
   1. Inicio
   2. Perfil de funcionario
   3. Crear denuncia
   4. Gasto público
   5. Encuesta pulso
3. **Sistema de diseño** en `design/DESIGN_SYSTEM.md` (por crear):
   - Paleta propuesta, validada en WCAG AA y con modo oscuro.
   - Tipografía propuesta.
   - Espaciado y cuadrícula.
   - Componentes: botones, formularios, tarjetas de funcionario y de denuncia, badges de estado, componente de fuente, gráficas y avisos.
4. **Decisiones justificadas** en `design/DESIGN_DECISIONS.md` (por crear).
5. **De 3 a 4 flujos de usuario** en [`user_flows/`](user_flows/):
   1. Registrarse y verificar el correo.
   2. Crear una denuncia hasta su publicación, incluida la moderación.
   3. De un perfil de funcionario a una ruta de acción.
   4. Votar en la encuesta pulso.
6. Archivo de **Figma público** (o enlace compartido), con los PNG exportados en [`wireframes/`](wireframes/) y [`mockups/`](mockups/).

## Formato de entrega

- Rama `design/<tema>` (por ejemplo `design/wireframes-principales`) y PR con commits en formato Conventional Commits (ver [`CONTRIBUTING.md`](../CONTRIBUTING.md)).
- PNG exportados a 1x y 2x, con nombres en kebab-case (por ejemplo `perfil-funcionario-movil.png`).
- Todo el contenido de diseño se publica bajo la misma licencia del proyecto.
