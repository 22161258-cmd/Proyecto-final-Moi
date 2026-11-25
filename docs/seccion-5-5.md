# 5.5. Implementación de la metodología (backend y frontend)

La implementación convierte el modelo dimensional y los indicadores definidos previamente en un flujo reproducible de preparación de datos y una interfaz interactiva. El backend se desarrolla con Python y PostgreSQL. El frontend utiliza Plotly Dash para presentar tarjetas KPI, comparativos temporales y desgloses por zona y categoría hotelera. La organización del trabajo sigue el enfoque incremental de Scrum seleccionado para el proyecto: los scripts de carga, los indicadores y las vistas pueden revisarse como incrementos independientes.

El prototipo contempla información a nivel hotel-día y separa la ocupación de la procedencia de los turistas. Esta separación conserva la granularidad correcta: las habitaciones disponibles y ocupadas se registran una vez por hotel y día, mientras que las personas hospedadas se detallan por origen. El conjunto incluido para ejecutar la demostración es sintético y reproducible; no debe interpretarse como una medición oficial de Oaxaca.

## 5.5.1. Proceso ETL (códigos Python)

El proceso ETL se implementa en `etl/etl.py` y se divide en extracción, transformación y carga:

1. **Extracción.** Se leen `hoteles.csv`, `ocupacion_diaria.csv` y `turistas_origen.csv` desde `data/raw/`. Los archivos contienen el catálogo hotelero, las medidas diarias de operación y los turistas agrupados por origen, respectivamente.
2. **Transformación.** Se revisan las columnas obligatorias, se normalizan las fechas, se convierten las medidas a tipos numéricos, se eliminan filas incompletas y duplicados según la granularidad de cada tabla y se comprueban claves de hotel, rangos y relaciones entre habitaciones, reservaciones y cancelaciones. Se crea `id_fecha` con formato AAAAMMDD y se deriva la dimensión de tiempo.
3. **Carga.** Se generan cuatro archivos para inspección y consumo del dashboard: `dim_hotel.csv`, `dim_tiempo.csv`, `fact_ocupacion_diaria.csv` y `fact_turistas.csv` en `data/processed/`. Si se configura `DATABASE_URL`, las mismas tablas se cargan en PostgreSQL después de crear el esquema con `sql/schema.sql`. La carga completa reemplaza el contenido anterior para que la ejecución sea repetible y no duplique filas.

Las validaciones detienen la ejecución cuando faltan columnas, aparecen hoteles sin dimensión, la ocupación excede las habitaciones disponibles, una cancelación supera las reservaciones o una medida de conteo no es un entero no negativo. Así se evita presentar datos inconsistentes como si fueran resultados válidos. Las filas que no tienen fecha o medidas requeridas se descartan durante la limpieza.

El generador `scripts/generate_demo_data.py` crea un ejemplo sintético determinista de siete establecimientos ficticios para los años 2024 a 2026. Puede utilizarse para observar el flujo completo antes de disponer de información autorizada. Para iniciar el prototipo se ejecuta:

```powershell
python scripts/generate_demo_data.py
python etl/etl.py
python app.py
```

El dashboard se abre en `http://127.0.0.1:8050`. La conexión a PostgreSQL es opcional en modo CSV; para utilizarla se crea la base, se ejecuta `sql/schema.sql` y se configura `DATABASE_URL` en el archivo local `.env`.

## 5.5.2. Visualización efectiva (KPIs y dashboard)

El tablero integra ocho indicadores en tarjetas que responden a los filtros de año, zona turística y categoría del hotel:

| KPI | Cálculo aplicado | Uso en la lectura |
|---|---|---|
| Ocupación hotelera (%) | Habitaciones ocupadas ÷ habitaciones disponibles × 100 | Resume la demanda de hospedaje del periodo. |
| Tarifa promedio diaria (ADR) | Ingreso por hospedaje ÷ habitaciones ocupadas | Compara el ingreso obtenido por noche ocupada. |
| RevPAR | Ingreso por hospedaje ÷ habitaciones disponibles | Integra tarifa y ocupación en un indicador de rendimiento por habitación disponible. |
| Tasa de cancelación (%) | Cancelaciones ÷ reservaciones × 100 | Ayuda a localizar periodos con mayor pérdida de reservas. |
| Turistas hospedados | Suma de turistas hospedados | Muestra el volumen de visitantes alojados. |
| Ingreso por hospedaje | Suma del ingreso de hospedaje en MXN | Expone la derrama directa registrada por alojamiento. |
| Noches de habitación ocupadas | Suma de habitaciones ocupadas por día | Mide el volumen de uso acumulado en el periodo. |
| Brecha contra la meta (puntos porcentuales) | Ocupación observada − meta de ocupación ponderada | Señala si la demanda está por debajo o por encima del objetivo. |

ADR, RevPAR, ocupación y cancelaciones se calculan como razones entre sumas del periodo filtrado; no se promedian porcentajes diarios. La meta se pondera por habitaciones disponibles. Esta agregación evita que un hotel pequeño o un día con poca disponibilidad tenga el mismo peso que un hotel con mayor capacidad.

La narrativa visual tiene tres momentos, de acuerdo con el storytelling planteado en el documento:

- **Panorama:** ocho tarjetas KPI y una gráfica de líneas con ocupación mensual del año seleccionado, el mismo periodo del año anterior y la meta.
- **Problema detectado:** barras horizontales para comparar ocupación por zona; mapa de calor zona-mes para localizar estacionalidad; y dispersión de ADR contra ocupación por hotel para reconocer establecimientos con combinaciones distintas de tarifa y demanda.
- **Acción recomendada:** un panel de lectura identifica si la ocupación filtrada está por debajo de la meta, indica la zona con menor ocupación y presenta una acción de revisión o promoción focalizada. La recomendación es una regla descriptiva del prototipo, no una predicción automatizada.

Los filtros son compartidos por los indicadores y las vistas de detalle. El control anual mantiene disponible el año previo para la comparación interanual. Los gráficos incluyen unidades, leyendas y etiquetas que facilitan interpretar valores. Cuando no existen datos para una selección, la interfaz muestra un estado sin resultados en lugar de inventar cifras.

**Consideración para la versión final:** reemplazar los archivos sintéticos con fuentes oficiales o registros hoteleros autorizados, documentar su fecha de corte y método de obtención, y validar con los usuarios las metas y la interpretación de cada indicador. El alcance permanece descriptivo y de actualización por lote; no incluye predicción ni reservaciones en tiempo real.
