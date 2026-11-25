# 5.1. Planteamiento del problema

## 5.1.1. Contexto turístico del estado de Oaxaca

El sector turístico constituye uno de los principales motores económicos, sociales y culturales del estado de Oaxaca. Su oferta combina patrimonio histórico y arquitectónico, gastronomía, tradiciones indígenas y destinos de sol y playa de proyección nacional e internacional. Sin embargo, el desempeño turístico estatal presenta una marcada heterogeneidad territorial y temporal que condiciona la planeación de la capacidad hotelera, la promoción institucional y la distribución de la derrama económica.

En términos geográficos, la demanda de hospedaje y el gasto turístico se concentran históricamente en tres grandes polos turísticos monitoreados de forma sistemática por las autoridades estatales y federales: **Ciudad de Oaxaca** (Valles Centrales, turismo cultural y de negocios), **Bahías de Huatulco** (turismo de playa planeado y de mayor estancia) y **Puerto Escondido** (turismo de playa, surf y naturaleza). En contraste, los otros seis segmentos territoriales registrados en los indicadores oficiales —**Tuxtepec**, **Istmo de Tehuantepec**, **Mixteca**, **Juquila**, **Ventanilla Puerto Ángel** y **Resto del Estado**— exhiben volúmenes diferenciados de infraestructura hotelera, llegada de turistas y derrama económica.

## 5.1.2. Problemática identificada

A partir del análisis del ecosistema de información turística disponible para Oaxaca, se identifican cuatro problemáticas centrales que limitan la toma de decisiones oportuna y basada en evidencia:

1. **Concentración desigual entre destinos:** La actividad hotelera y la llegada de visitantes exhiben una fuerte polarización hacia los tres centros turísticos consolidados. Sin comparativos claros de cuartos disponibles, cuartos ocupados, porcentaje de ocupación y derrama económica por destino, resulta complejo dimensionar las brechas de desempeño y orientar estrategias de promoción diferenciadas.
2. **Fuerte estacionalidad de la demanda:** La ocupación hotelera en Oaxaca responde de manera pronunciada a ciclos vacacionales y festividades emblemáticas —como la Guelaguetza (julio), Día de Muertos (finales de octubre e inicios de noviembre), Semana Santa y el periodo decembrino—, mientras que en meses de temporada baja (por ejemplo, septiembre u otros meses valle) la demanda desciende de forma significativa. Esta variabilidad dificulta evaluar si los cambios mensuales obedecen a variaciones estacionales esperadas o a caídas interanuales reales.
3. **Dispersión y formato estático de los datos oficiales:** La información pública emitida por la Secretaría de Turismo del Estado de Oaxaca (**SECTUR Oaxaca**) y el Sistema Nacional de Información Estadística del Sector Turismo de México (**DATATUR** de SECTUR Federal) se difunde principalmente a través de boletines en formato PDF (mensuales, trimestrales o anuales) y reportes tabulares independientes. Esta fragmentación impide realizar cruces históricos ágiles, comparativos interanuales (*Year-over-Year*, YoY), análisis por procedencia del turista (nacional frente a extranjero) o consultas interactivas filtradas por periodo y destino.
4. **Riesgo de errores de agregación y lectura en indicadores:** Cuando las series estadísticas se analizan manualmente en hojas de cálculo, es frecuente promediar porcentajes de ocupación de distintos meses o destinos de distinto tamaño. Este error metodológico distorsiona la realidad operativa, ya que asigna el mismo peso a destinos o periodos con distinta oferta de cuartos disponibles; los indicadores compuestos deben calcularse como razones de sumas ponderadas por capacidad y demanda real.

## 5.1.3. Pregunta de investigación

> ¿Cómo diseñar e implementar una arquitectura analítica reproducible —compuesta por un proceso ETL en Python, un modelo dimensional en PostgreSQL y un dashboard interactivo en Plotly Dash— que consolide los registros oficiales de ocupación hotelera, llegada de turistas y derrama económica en Oaxaca para apoyar la toma de decisiones basada en evidencia?

## 5.1.4. Objetivos

### Objetivo general
Desarrollar una plataforma analítica descriptiva e interactiva que extraiga, valide, modele y visualice los indicadores oficiales de ocupación hotelera, flujo de turistas por origen y derrama económica de los principales destinos turísticos de Oaxaca, permitiendo identificar brechas territoriales, patrones de estacionalidad y variaciones interanuales.

### Objetivos específicos
1. **Recopilar y documentar fuentes oficiales verificables** de SECTUR Oaxaca y DATATUR, manteniendo trazabilidad explícita de URLs, periodicidad, metodología de integración y fecha de corte.
2. **Diseñar un modelo dimensional en PostgreSQL** bajo esquema estrella/constelación que separe la granularidad de los hechos de actividad hotelera respecto al desglose por origen del turista (nacional y extranjero), garantizando integridad referencial y evitando duplicaciones al consultar vistas agregadas.
3. **Construir un proceso ETL automatizado e idempotente en Python** capaz de limpiar, validar rangos, verificar llaves foráneas, generar archivos procesados en CSV y cargar los datos en PostgreSQL con bitácora de ejecución.
4. **Implementar un dashboard interactivo en Plotly Dash** con al menos siete KPIs clave calculados mediante razones de sumas, comparativos contra el año anterior, análisis por destino y origen de visitantes, filtros dinámicos, descarga de datos filtrados y soporte dual (PostgreSQL o respaldo en CSV).
5. **Asegurar la calidad técnica y documental** mediante pruebas automatizadas (`pytest`), verificación del servidor web y alineación estricta entre el código, los datos reales y la documentación del proyecto.

## 5.1.5. Alcance y limitaciones

- **Alcance analítico:** El sistema es de carácter **descriptivo y diagnóstico**. Permite explorar series históricas oficiales mediante tarjetas de indicadores, series temporales interanuales, comparativos entre destinos, mapas de calor de estacionalidad y composición de turistas por origen, así como exportar los subconjuntos filtrados en formato CSV.
- **Granularidad oficial:** La resolución temporal y geográfica del tablero se ajusta estrictamente a la granularidad disponible en las publicaciones oficiales de SECTUR Oaxaca y DATATUR, sin fabricar registros sintéticos para rellenar periodos o destinos no publicados.
- **Actualización por lote (*batch*):** La ingesta y actualización de la información se realiza mediante ejecución controlada de los scripts de descarga y ETL, no mediante conexión transaccional en tiempo real.
- **Exclusiones:** El proyecto no implementa modelos predictivos (*forecasting*), fijación dinámica de precios (*revenue management* automatizado) ni gestión operativa de reservaciones de establecimientos individuales.
