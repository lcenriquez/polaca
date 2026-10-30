# POLACA — reglas permanentes

## 1. Prioridad
- Este repo sigue las convenciones de `~/Developer/CLAUDE.md`: Conventional Commits en inglés y un commit por cambio acotado.
- Lo que ese archivo dice de la arquitectura y los repos `sos.*` no aplica aquí; la fuente de verdad de POLACA es `spec/` y `design/`.

## 2. Forma de trabajar
- No termines tu turno al anunciar el siguiente paso; ejecútalo y sigue hasta completar la tarea, incluidas las pruebas y el commit.
- Solo detente para pedir una decisión que no puedas tomar tú, o si algo requiere aprobación humana.
- Para no saturar el contexto, no leas `auditor/web.py` completo: usa grep y lee solo las secciones necesarias.

## 3. Git
- Conventional Commits en inglés, en la rama `hackathon-meta`.
- Nunca uses `git stash`, `git add -A` ni `git push`.
- Haz commit solo de los archivos que tú modificaste (`git add <ruta>` o `git add -p`), porque puede haber otra sesión trabajando en paralelo.

## 4. Seguridad
- Nunca leas, muestres ni edites `.env`.
- Los secretos solo vienen de variables de entorno.
- No levantes servidores (Luis ya tiene uno con `--reload`).
- No corras el agente indexador sin que te lo pidan.

## 5. Aprobación humana
- Las solicitudes de indexación solo las aprueba una persona en `/admin`. Nunca las apruebes tú, ni en pruebas; en pruebas usa una base temporal.

## 6. Datos y ética
- Los hallazgos son discrepancias verificables, nunca acusaciones. Prohibido usar «corrupción», «robo», «desvío», «irregularidad» y similares.
- Si un dato no está en la fuente, es `null`.
- Cada dato guarda archivo, página y fragmento verificados.
- Solo contactos institucionales; nunca correos ni teléfonos personales.

## 7. API de Meta
- Toda llamada pasa por `auditor/llm.py`, con caché y registro de costos.
- Usa `MODELO_PUBLICO` (Contributor) para documentos públicos y `MODELO_PRIVADO` (Standard) para fotos ciudadanas.
- Prueba siempre con 2 o 3 páginas antes de un lote.
- Respeta los topes de gasto que indique cada tarea.

## 8. Pruebas
- Pruebas sin red en `auditor/test_auditor.py` y `auditor/test_contratos.py`. Todo cambio deja su prueba y corre la suite completa antes del commit.

## 9. Interfaz
- Mobile first y adaptable a escritorio, sin scroll horizontal; usa `minmax(0, …)` en las cuadrículas.
- Lo más gráfico posible, en lenguaje claro para personas con poca escolaridad.
- Nunca una sección vacía ni un «0» solo: siempre una acción sugerida.
- Nada fijo de un solo municipio (por ejemplo, «Atlixco» escrito en el código); todo sale del municipio elegido.
- Referencia visual: `design/mockups/polaca-nacional.html`.

## 10. Autoría
- El código de este repo se desarrolla con Muse (Meta) vía Claude Code. No agregues líneas `Co-Authored-By` de Claude.
