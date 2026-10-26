# POLACA

**Plataforma de transparencia y participación democrática.**

> La política no te ignora. ¿La ignoras tú?

POLACA reúne en un solo lugar quién gobierna tu municipio, qué reporta la ciudadanía, en qué se gasta el dinero público, qué opina la gente y qué puedes hacer al respecto. El piloto es **Atlixco, Puebla**, y la meta es cubrir todo México en sus tres órdenes de gobierno.

## Estado

🚧 **Pre-MVP.** Estamos definiendo la especificación, el diseño y la arquitectura. Todavía no hay código ejecutable.

## Funcionalidades del MVP

- 🔐 Cuentas con correo y contraseña
- 🏛️ Perfiles de los 23 funcionarios electos de Atlixco
- 📣 Denuncias ciudadanas moderadas
- 💰 Auditoría del gasto público con fuentes oficiales
- 📊 Encuesta pulso de aprobación e intención de voto (no representativa)
- 🧭 Rutas de acción: revocación de mandato, denuncia formal, prensa y solicitudes de información

## Estructura del repositorio

| Carpeta | Contenido |
|---|---|
| [`spec/`](spec/PLATFORM_SPECIFICATION.md) | Especificación funcional |
| [`design/`](design/DESIGN_BRIEF.md) | Brief, sistema de diseño, wireframes y mockups |
| [`code/`](code/README.md) | Código y documentación técnica (arquitectura, API, base de datos, setup y deploy) |
| [`.github/`](.github/) | Plantillas de issues y PR, y workflows de CI/CD |

## Hackathon Meta Global AI Developer (26 oct – 4 nov 2026)

### Lo que existía antes del 26 de octubre de 2026

Todo lo de `spec/`, `design/`, `code/` y `.github/`: especificación, brief de diseño y el andamiaje técnico (Next.js + Fastify + PostgreSQL) sin código ejecutable.

### Lo construido durante el hackathon (rama `hackathon-meta`)

**Auditor autónomo de Atlixco** en [`auditor/`](auditor/): lee documentos públicos del Ayuntamiento con **Muse Spark** (Meta Model API), extrae acuerdos de Cabildo en datos estructurados y guarda cada uno con su cita (archivo, página y fragmento textual).

| Archivo | Qué hace |
|---|---|
| `auditor/descargar.py` | Descarga las fuentes oficiales a `datos/raw/` con URL, fecha y sha256 |
| `auditor/llm.py` | Cliente de Meta Model API con caché en disco y registro de tokens y costo (`datos/costos.jsonl`) |
| `auditor/extraer.py` | Manda el PDF a Muse Spark en tramos de 20 páginas, con salida JSON por esquema, y coteja cada fragmento contra el texto de la página |
| `auditor/evaluar.py` | Compara la extracción contra `datos/eval/etiquetado.csv` (etiquetado a mano): recall de acuerdos y precisión por campo |
| `auditor/test_auditor.py` | Pruebas sin red ni costo |

Un mismo acuerdo suele aparecer varias veces (índice, dictamen y cierre). Cada aparición se guarda como mención con su cita y se agrupa, sin llamar a la API, en un acuerdo canónico (`grupo_id`, vista `acuerdos_canonicos`).

**Etiquetado para evaluar:** llena `datos/eval/etiquetado.csv`, una fila por acuerdo. Varias personas en `propuesto_por` y `cargo` van separadas por `;` y en el mismo orden; un campo vacío o `null` es null. Las filas con `es_ejemplo=1` se ignoran salvo con `--ejemplos`.

Reglas: los hallazgos son discrepancias verificables, no acusaciones; un dato que no está en la fuente es `null`; un fragmento que no aparece literalmente en la página citada queda marcado `no_encontrado`.

```bash
python3 -m venv .venv && .venv/bin/pip install -r auditor/requirements.txt
echo "META_API_KEY=..." > .env
cd auditor
../.venv/bin/python descargar.py
../.venv/bin/python extraer.py GACETA_AGOSTO-DICIEMBRE_2025.pdf --paginas 4-6   # prueba chica
../.venv/bin/python llm.py costos
../.venv/bin/python evaluar.py
../.venv/bin/python test_auditor.py
```

## Contribuir

Toda ayuda cuenta: código, diseño, datos, revisión jurídica o difusión. Lee [`CONTRIBUTING.md`](CONTRIBUTING.md) y el [Código de Conducta](CODE_OF_CONDUCT.md).

## Licencia

[GNU AGPL v3](LICENSE). Si modificas POLACA y la ofreces como servicio en red, debes publicar tu código fuente bajo la misma licencia.
