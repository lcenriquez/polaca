# Especificación de la plataforma — POLACA

> **La política no te ignora. ¿La ignoras tú?**

| | |
|---|---|
| Estado | Borrador v0.1 (MVP) |
| Licencia | AGPL v3 |
| Piloto | Atlixco, Puebla |
| Duración del MVP | 12 semanas |
| Visión | Todo México, tres órdenes de gobierno (municipal, estatal, federal) |

## 1. Problema

La información sobre quién gobierna, cómo gasta el dinero público y qué puede hacer la ciudadanía existe, pero está dispersa en portales difíciles de usar (Plataforma Nacional de Transparencia, datos.gob.mx, cuentas públicas, gacetas). Quien quiere quejarse de un bache, cuestionar un gasto o exigir cuentas a su regidor no sabe por dónde empezar.

## 2. Objetivo

Una plataforma pública, gratuita y no partidista que, para un municipio, reúna en un solo lugar:

1. **Quién gobierna**: perfil de cada funcionario electo.
2. **Qué reporta la ciudadanía**: denuncias ciudadanas moderadas.
3. **En qué se gasta**: gasto público con fuente verificable.
4. **Qué opina la gente**: encuesta pulso de aprobación e intención.
5. **Qué puedo hacer**: rutas de acción paso a paso.

### Principios

- **No partidista.** La plataforma no apoya ni ataca a ningún partido ni persona. Diseño, textos y algoritmos deben ser neutrales.
- **Todo dato tiene fuente.** Cada cifra y cada dato de un funcionario enlaza a su fuente oficial, con fecha de consulta.
- **Privacidad por defecto.** Recolectamos el mínimo de datos personales. Quien denuncia nunca queda expuesto públicamente.
- **Abierto.** Código AGPL v3; datos agregados publicables como datos abiertos.
- **Móvil primero.** La mayoría del público entra desde un teléfono y con conexión limitada.

## 3. Usuarios y roles

| Rol | Quién es | Puede |
|---|---|---|
| Visitante | Cualquiera sin cuenta | Ver funcionarios, denuncias publicadas, gasto, resultados de la encuesta y rutas de acción |
| Ciudadano | Cuenta con correo verificado | Todo lo anterior, más crear denuncias, apoyar denuncias, votar en la encuesta y reportar contenido |
| Moderador | Voluntario designado por el equipo | Aprobar, rechazar o editar denuncias; atender reportes; publicar réplicas |
| Administrador | Equipo núcleo | Todo lo anterior, más gestionar funcionarios, importar datos de gasto, gestionar usuarios y moderadores, y abrir o cerrar encuestas |

Los funcionarios no tienen cuenta propia en el MVP. Envían su **derecho de réplica** por un formulario de contacto y un moderador la publica (ver §4.3).

## 4. Funcionalidades del MVP

### 4.1 Autenticación (correo + contraseña)

- Registro con correo, contraseña y aceptación explícita del **aviso de privacidad** y los **términos de uso**.
- Verificación de correo obligatoria antes de denunciar, apoyar o votar.
- Inicio y cierre de sesión, y recuperación de contraseña por correo.
- Contraseña de mínimo 10 caracteres; se rechazan contraseñas filtradas conocidas (lista local; ver ARCHITECTURE).
- Límite de intentos para iniciar sesión, registrarse y recuperar la contraseña.
- Eliminación de cuenta a solicitud (derechos ARCO). Las denuncias quedan anonimizadas, no se borran.
- Datos de perfil opcionales: colonia o localidad (para estadísticas agregadas) y rango de edad. **No** se piden nombre real, CURP, INE ni teléfono.

### 4.2 Funcionarios electos

- Catálogo de los **23 funcionarios electos** que gobiernan o representan a Atlixco. El administrador confirma la lista exacta con fuentes oficiales (IEE Puebla, cabildo, Congreso) antes del lanzamiento.
- Perfil: nombre, cargo, partido o coalición por la que fue electo, periodo (inicio y fin), foto (de fuente oficial o con licencia libre), comisiones y enlaces oficiales.
- Dentro del perfil:
  - Denuncias publicadas relacionadas con el funcionario.
  - Resultados de la encuesta pulso sobre ese funcionario.
  - Gasto asociado a su área, cuando aplique.
  - Réplicas publicadas.
- Cada dato del perfil guarda su fuente (URL) y su fecha de verificación.
- Solo un administrador puede editar, y cada cambio queda en la bitácora de auditoría.

### 4.3 Denuncias ciudadanas

Reportes ciudadanos sobre **problemas públicos** (servicios, obras, seguridad, trámites, uso de recursos), no sobre la vida privada de las personas.

**Flujo:**

1. El ciudadano elige una categoría y escribe título y descripción. Opcionalmente agrega ubicación (punto en el mapa o colonia), fecha del hecho, hasta 3 fotos y el funcionario o dependencia relacionada.
2. La denuncia queda **pendiente de moderación**. Nada se publica sin revisión.
3. El moderador la **aprueba**, la **rechaza** (con motivo tomado de un catálogo) o **pide cambios**.
4. Ya publicada, otros ciudadanos pueden **apoyarla** ("a mí también me pasa", uno por cuenta) o **reportarla**.
5. Su estado puede avanzar: `publicada → en_seguimiento → resuelta` (o `sin_respuesta`). Los cambios de estado los hacen los moderadores con evidencia.

**Reglas:**

- Públicamente, el autor aparece siempre como "Ciudadano/a de <colonia>" o "Anónimo". Su correo nunca se expone.
- Al subir una foto se eliminan sus metadatos EXIF, incluida la ubicación GPS.
- La ubicación pública se redondea a unos 100 m.
- Se rechazan: datos personales de terceros (domicilios, teléfonos, rostros de particulares), acusaciones de delitos sin evidencia, discurso de odio, propaganda electoral y spam.
- **Derecho de réplica.** Cualquier funcionario mencionado puede enviar una réplica, que se publica junto a la denuncia.
- Categorías iniciales: alumbrado, baches y vialidades, agua y drenaje, basura, seguridad, obras públicas, trámites y servicios, uso de recursos, otro.

### 4.4 Auditoría del gasto público

- Importación de datos de gasto de fuentes oficiales: datos.gob.mx, la Plataforma Nacional de Transparencia (obligaciones de transparencia del municipio), cuentas públicas y los informes de la Auditoría Superior del Estado de Puebla.
- Cada registro guarda la fuente (URL), la fecha de descarga y el hash del archivo original, para que cualquiera pueda comprobarlo.
- Vistas:
  - Gasto por año y capítulo o partida.
  - Principales proveedores y contratos.
  - Comparativo entre presupuesto aprobado y ejercido.
- **Alertas automáticas** con reglas públicas y documentadas, por ejemplo: un contrato por adjudicación directa arriba de un umbral, un proveedor que concentra más del X % del gasto, o un sobreejercicio mayor al Y % del presupuesto aprobado. Una alerta es una **señal para revisar**, no una acusación, y así se indica en la interfaz.
- Descarga de los datos normalizados en CSV.
- Las importaciones las ejecuta un administrador. En el MVP no hay extracción automática programada.

### 4.5 Encuesta pulso

- Pregunta de intención: "Si hoy fueran las elecciones, ¿a quién votarías?", con opciones que el administrador configura para cada encuesta. Siempre incluye "Ninguno" y "No sé".
- Pregunta de aprobación por funcionario: "¿Apruebas o desapruebas su trabajo?".
- Un voto por cuenta verificada en cada ronda; se puede cambiar mientras la ronda esté abierta. Las rondas son mensuales.
- Los resultados muestran conteos y porcentajes, y no se publican hasta superar un mínimo de 50 respuestas.
- **Cumplimiento electoral.** Es un **sondeo de opinión en línea, no probabilístico y no representativo**, y debe decirlo en cada pantalla donde aparezcan resultados. Durante los periodos de veda que marca la ley electoral, la encuesta de intención de voto se **cierra y oculta** automáticamente. Las fechas de veda las captura el administrador.
- **Dato sensible.** La opinión política es un dato personal sensible según la LFPDPPP, así que votar exige consentimiento **expreso** (casilla específica, aparte del aviso general). El voto se guarda **seudonimizado**: sin el identificador del usuario, con un HMAC que solo sirve para evitar votos duplicados. Nunca se publican votos individuales, y los resultados no se desglosan por colonia ni por edad en el MVP.

### 4.6 Rutas de acción

Guías paso a paso y verificadas sobre qué puede hacer una persona:

| Ruta | Contenido |
|---|---|
| **Revocación de mandato** | Si la ley estatal lo permite para el cargo, con requisitos, plazos, firmas y autoridad responsable. Si no aplica, se explica por qué. |
| **Denuncia formal** | Ante quién presentarla (contraloría municipal, ASEP, fiscalía anticorrupción, órgano interno de control), qué pruebas llevar y plantillas de escrito. |
| **Prensa** | Cómo documentar un caso, a qué medios locales y nacionales acudir, y una plantilla de comunicado. |
| **Solicitud de información** | Cómo pedir información pública en la PNT, con plantilla y plazos de respuesta. |

- Cada ruta muestra su fecha de última revisión y quién la revisó. Antes de publicarse, una persona con formación jurídica debe validar el contenido.
- Desde una denuncia publicada se puede saltar a la ruta relevante.
- El contenido se guarda en la base de datos (Markdown) y lo edita un administrador.

## 5. Fuera del MVP

- Otros municipios, estados o el nivel federal. El modelo de datos sí los contempla desde el inicio (ver `code/docs/DATABASE.md`).
- Cuentas verificadas para funcionarios.
- Aplicaciones móviles nativas (el MVP es una web responsiva e instalable como PWA).
- Inicio de sesión con redes sociales.
- Notificaciones push.
- Importación automática programada de datos de gasto.
- Seguimiento de votaciones de cabildo y asistencia.

## 6. Requisitos no funcionales

| Área | Requisito |
|---|---|
| Rendimiento | Páginas públicas con LCP < 2.5 s en una red 4G media; menos de 200 KB de JS inicial |
| Accesibilidad | WCAG 2.1 AA |
| Idioma | Español (México) |
| Privacidad | Cumplimiento de la LFPDPPP; aviso de privacidad y derechos ARCO |
| Seguridad | OWASP ASVS nivel 1 como base; HTTPS obligatorio |
| Disponibilidad | 99 % mensual en el MVP |
| Escala objetivo | 100 000 usuarios registrados; picos de 1 000 usuarios concurrentes |
| Transparencia | Código abierto; reglas de moderación y de alertas públicas |

## 7. Métricas de éxito del MVP (semana 12)

- 1 000 cuentas verificadas en Atlixco.
- 100 denuncias publicadas, con tiempo medio de moderación menor a 48 h.
- Los 23 perfiles de funcionarios completos y con fuente.
- Gasto de al menos 2 ejercicios fiscales importado.
- 3 rondas mensuales de la encuesta pulso con 50 o más respuestas cada una.

## 8. Plan de 12 semanas

| Semana | Entregable |
|---|---|
| 1–2 | Documentación técnica, diseño (wireframes, sistema de diseño), CI y esqueleto del proyecto |
| 3 | Autenticación completa: registro, verificación, sesión, recuperación y límite de intentos |
| 4 | Funcionarios: modelo, API, páginas públicas y panel de administración; carga de los 23 perfiles |
| 5–6 | Denuncias: creación, subida de fotos, moderación, apoyos y reportes |
| 7–8 | Gasto: importador, normalización, vistas, alertas y descarga en CSV |
| 9 | Encuesta pulso: rondas, votación, resultados y veda |
| 10 | Rutas de acción, aviso de privacidad y términos, y revisión jurídica del contenido |
| 11 | Accesibilidad, rendimiento, pruebas de seguridad y carga; corrección de errores |
| 12 | Lanzamiento en producción en Atlixco; monitoreo |

## 9. Riesgos

| Riesgo | Mitigación |
|---|---|
| Difamación o responsabilidad legal por denuncias | Moderación previa, reglas publicadas, derecho de réplica y revisión jurídica |
| Percepción de sesgo partidista | Neutralidad en diseño y textos, reglas públicas y código abierto |
| Manipulación de la encuesta con cuentas falsas | Correo verificado, límites de uso, detección de patrones y aviso de "no representativo" |
| Incumplimiento electoral de la encuesta | Leyenda metodológica y cierre automático en veda |
| Datos de gasto incompletos o en formatos malos | Importadores por fuente, registro de procedencia y reporte público de huecos |
| Exposición de denunciantes | Anonimato público, EXIF eliminado, ubicación redondeada y mínimos datos personales |
