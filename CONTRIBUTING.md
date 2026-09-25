# Cómo contribuir a POLACA

¡Gracias por tu interés! POLACA es un proyecto abierto y cualquier persona puede aportar. Al participar aceptas el [Código de Conducta](CODE_OF_CONDUCT.md).

## Formas de contribuir

| Tipo | Dónde empezar |
|---|---|
| Código | [`code/docs/CONTRIBUTING_CODE.md`](code/docs/CONTRIBUTING_CODE.md) |
| Diseño | [`design/DESIGN_BRIEF.md`](design/DESIGN_BRIEF.md) |
| Datos (funcionarios, gasto) | Abre un issue con la fuente oficial del dato |
| Revisión jurídica (rutas de acción, avisos) | Abre un issue con la etiqueta `legal` |
| Reportar errores o proponer funciones | Usa las [plantillas de issues](.github/ISSUE_TEMPLATE/) |

## Flujo de trabajo

1. Busca o abre un issue antes de empezar un cambio grande, para acordar el enfoque.
2. Haz fork del repo y crea una rama con el prefijo del tipo de cambio: `feat/…`, `fix/…`, `docs/…` o `design/…`.
3. Usa commits en formato [Conventional Commits](https://www.conventionalcommits.org/es/), con la descripción **en español**:

   ```
   feat: agregar filtro por colonia en denuncias
   fix: corregir conteo de apoyos duplicados
   docs: documentar endpoint de encuesta
   ```

   Tipos permitidos: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci` y `perf`.
4. Abre un PR usando la plantilla y enlaza el issue (`Cierra #123`).
5. Al menos una persona mantenedora revisa y aprueba el PR antes de fusionarlo.

## Reglas de contenido

- **Neutralidad.** Ningún cambio puede favorecer o atacar a un partido o a una persona.
- **Datos con fuente.** Todo dato de un funcionario o del gasto público debe incluir la URL de la fuente oficial.
- **Privacidad.** Nunca subas datos personales reales a issues, PRs, seeds ni pruebas. Usa datos ficticios.

## Seguridad

Si encuentras una vulnerabilidad, **no abras un issue público**. Repórtala en privado desde la pestaña *Security → Report a vulnerability* del repositorio.

## Licencia

Al contribuir, aceptas que tu aporte se publique bajo la licencia [AGPL v3](LICENSE) del proyecto.
