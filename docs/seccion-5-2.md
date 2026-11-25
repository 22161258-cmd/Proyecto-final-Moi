# 5.2. Selección de la metodología de desarrollo de software

## 5.2.1. Análisis comparativo de metodologías

El desarrollo de una solución de inteligencia de negocios y analítica turística requiere coordinar tareas interdependientes de extracción de fuentes oficiales heterogéneas, modelado dimensional en base de datos, construcción de reglas de validación y diseño de visualizaciones ejecutivas. Con el fin de elegir el marco de trabajo más adecuado para el proyecto, se evaluaron tres metodologías ampliamente utilizadas en ingeniería de software: **Scrum**, **Cascada (Waterfall)** y **Kanban**.

- **Cascada (Waterfall):** Organiza el desarrollo en fases secuenciales rígidas (requisitos, diseño, implementación, verificación y despliegue). Resulta útil cuando las especificaciones y los formatos de entrada son completamente estables desde el inicio, pero presenta alta fricción cuando los boletines oficiales o la estructura de datos exigen ajustes iterativos tras inspeccionar las fuentes reales.
- **Kanban:** Privilegia el flujo continuo de tareas y la limitación del trabajo en progreso (*Work In Progress*, WIP) sin iteraciones de duración fija. Aunque favorece la visibilidad del avance operativo, carece por sí solo de hitos formales de revisión por incremento y de una cadencia estructurada para alinear entregables académicos y técnicos acoplados.
- **Scrum:** Estructura el trabajo en iteraciones cortas denominadas *Sprints* con objetivos concretos, roles definidos, un *Product Backlog* priorizado y criterios de aceptación explícitos por incremento. Permite validar tempranamente los datos reales extraídos, ajustar el modelo dimensional antes de construir el tablero y realizar auditorías continuas de calidad.

### Matriz de decisión comparativa

Cada criterio se evaluó en una escala de **1 (bajo)** a **5 (alto)** considerando las necesidades reales de un proyecto de analítica de datos turísticos con múltiples componentes técnicos:

| Criterio de evaluación | Peso | Cascada | Kanban | Scrum | Justificación aplicada al proyecto |
|---|---|---|---|---|---|
| Adaptabilidad ante hallazgos en fuentes oficiales (PDF/tablas) | 25% | 2 | 4 | **5** | La estructura real de los boletines de SECTUR/DATATUR suele requerir ajustes iterativos en el parseo y en el esquema dimensional. |
| Entrega incremental verificable (ETL -> BD -> Dashboard -> Pruebas) | 25% | 1 | 3 | **5** | Permite entregar módulos funcionales probados al cierre de cada Sprint sin esperar al final del proyecto. |
| Claridad de roles y coordinación paralela | 20% | 3 | 3 | **5** | Facilita dividir responsabilidades claras entre ingeniería de datos, frontend analítico, documentación y auditoría de calidad. |
| Control de calidad y validación temprana | 15% | 2 | 3 | **5** | Cada incremento se somete a criterios de aceptación y pruebas antes de integrarse al siguiente componente. |
| Trazabilidad académica y gestión de alcance acotado | 15% | 4 | 3 | **4** | La estructura de Sprints y Backlog documenta de manera ordenada el avance por etapas dentro del calendario académico. |
| **Puntuación ponderada total (máx. 5.00)** | **100%** | **2.25** | **3.25** | **4.85** | **Scrum obtiene la mayor puntuación ponderada.** |

Con base en la matriz de decisión (**4.85 / 5.00**), se selecciona **Scrum** como metodología de desarrollo de software del proyecto.

## 5.2.2. Definición de roles bajo Scrum

Para ejecutar el proyecto de manera ordenada y sin traslapes de responsabilidad, los roles de Scrum se organizan de la siguiente manera:

| Rol Scrum | Responsabilidad principal en el proyecto |
|---|---|
| **Product Owner (PO)** | Define la visión del producto analítico, prioriza el *Product Backlog*, establece las reglas de negocio de los KPIs turísticos (razón de sumas, comparativo interanual) y valida la fidelidad con las fuentes oficiales. |
| **Scrum Master / Coordinación** | Asegura la aplicación del flujo Scrum, coordina dependencias entre datos, base de datos, dashboard y documentación, y resuelve bloqueos técnicos del entorno. |
| **Equipo de Desarrollo — Datos y ETL (`data-etl`)** | Configura el entorno Python, implementa la descarga reproducible de fuentes oficiales, diseña el modelo dimensional en PostgreSQL (`sql/schema.sql`) y construye el pipeline ETL (`etl/etl.py`). |
| **Equipo de Desarrollo — Frontend Analítico (`dashboard`)** | Implementa la interfaz interactiva en Plotly Dash (`app.py`), las tarjetas KPI, los gráficos de narrativa visual, filtros, exportación CSV y manejo de errores. |
| **Equipo de Desarrollo — Documentación (`docs`)** | Redacta y mantiene la documentación técnica y académica (secciones 5.1 a 5.5, reporte unificado y `README.md`) garantizando consistencia con el código real. |
| **Aseguramiento de Calidad y Auditoría (`auditor`)** | Diseña y ejecuta la suite de pruebas automatizadas (`tests/` con `pytest`), verifica la ausencia de datos sintéticos en producción y audita la coherencia integral del repositorio. |

## 5.2.3. Product Backlog

El *Product Backlog* agrupa los requerimientos funcionales y no funcionales en historias de usuario priorizadas:

| ID | Épica / Módulo | Historia de usuario / Requerimiento | Prioridad | Sprint |
|---|---|---|---|---|
| PB-01 | Datos y fuentes | Como analista, necesito descargar y registrar boletines oficiales reales de SECTUR Oaxaca y DATATUR para garantizar trazabilidad sin datos ficticios. | Alta | Sprint 1 |
| PB-02 | Modelado de datos | Como ingeniero de datos, necesito un esquema dimensional en PostgreSQL con dimensiones, tablas de hechos, restricciones `CHECK` y vistas sin duplicación de cuartos. | Alta | Sprint 1 |
| PB-03 | Pipeline ETL | Como operador técnico, necesito un script ETL idempotente en Python que valide tipos, rangos y llaves foráneas, genere CSV limpios y cargue PostgreSQL con bitácora. | Alta | Sprint 2 |
| PB-04 | Capa analítica y KPIs | Como tomador de decisiones, necesito al menos siete KPIs calculados como razón de sumas con variación interanual (YoY) para evitar sesgos de promedio simple. | Alta | Sprint 3 |
| PB-05 | Visualización Dash | Como usuario final, necesito un dashboard interactivo con filtros por año y destino, gráficas de estacionalidad, desglose nacional/extranjero y descarga CSV. | Alta | Sprint 3 |
| PB-06 | Resiliencia operativa | Como administrador, necesito operación dual (PostgreSQL o respaldo CSV) y mensajes claros ante filtros vacíos o fallas de conexión. | Media | Sprint 3 |
| PB-07 | Pruebas automatizadas | Como auditor, necesito una suite `pytest` que valide el ETL, los archivos procesados, las fórmulas KPI, los callbacks de Dash y el estado HTTP 200 del servidor. | Alta | Sprint 4 |
| PB-08 | Documentación | Como equipo académico, necesito documentar el planteamiento, metodología, modelo, implementación ETL, KPIs y guía de ejecución alineados al código real. | Alta | Sprint 4 |

## 5.2.4. Estructura de Sprints

El desarrollo se planificó en **cuatro Sprints** incrementales:

1. **Sprint 1 — Fuentes oficiales y modelo dimensional:**
   - Relevamiento y verificación de publicaciones oficiales de SECTUR Oaxaca y DATATUR.
   - Definición del planteamiento del problema (Sección 5.1) y selección metodológica (Sección 5.2).
   - Diseño del modelo estrella/constelación en `sql/schema.sql`, definiendo granularidad, llaves primarias/foráneas y restricciones de integridad.
2. **Sprint 2 — Pipeline ETL y PostgreSQL:**
   - Configuración del entorno virtual en Windows (`py -m venv .venv`) e instalación de dependencias.
   - Implementación del script de adquisición oficial en `scripts/` y del flujo de extracción, validación, limpieza y carga en `etl/etl.py`.
   - Generación de archivos procesados en `data/processed/`, registro de metadatos de corte y carga idempotente hacia PostgreSQL con bitácora en `etl_run_log`.
3. **Sprint 3 — KPIs y Dashboard interactivo en Plotly Dash:**
   - Implementación de `app.py` con lectura dual desde PostgreSQL o CSV procesados.
   - Construcción de las tarjetas KPI (con fórmula de razón de sumas y variación interanual), gráficos comparativos por destino, estacionalidad mensual y composición de turistas por origen, además de exportación CSV.
4. **Sprint 4 — Pruebas, auditoría y documentación final:**
   - Construcción y ejecución de la suite automatizada en `tests/` mediante `pytest`.
   - Verificación funcional del servidor Dash (`HTTP 200`) y auditoría de consistencia entre datos reales, código SQL/Python y documentación.
   - Redacción y consolidación de las secciones 5.3, 5.5, reporte unificado (`docs/reporte-completo.md`) y actualización de `README.md`.

## 5.2.5. Criterios de aceptación y Definición de Terminado (DoD)

Un incremento se considera **Terminado (Done)** únicamente cuando cumple con todos los criterios siguientes:

- **Fidelidad de datos:** Cero registros sintéticos o fabricados en el flujo principal; toda cifra en `data/processed/` proviene de fuentes oficiales documentadas con URL y fecha de corte.
- **Integridad estructural:** El archivo `sql/schema.sql` se ejecuta sin errores en PostgreSQL, aplica restricciones `CHECK` y llaves foráneas válidas, y sus vistas (`vw_kpis_mensuales` y `vw_kpis_anuales_yoy`) agregan correctamente sin multiplicar filas al cruzar hechos.
- **Reproducibilidad:** El entorno `.venv`, el script ETL y el dashboard se ejecutan de forma limpia y repetible en Windows sin duplicar registros en la base de datos ni en los CSV.
- **Calidad funcional y visual:** El dashboard presenta al menos 7 KPIs reales con unidades explícitas, responde a filtros sin lanzar excepciones (incluidos estados vacíos) y permite descargar los datos filtrados.
- **Verificación automatizada:** La suite `pytest` pasa al 100% tras los últimos cambios y el servidor responde con código HTTP 200.
- **Alineación documental:** Los nombres de archivos, tablas, columnas, fórmulas, comandos y cifras descritos en `docs/` y `README.md` coinciden exactamente con el código fuente y los datos reales del repositorio.
