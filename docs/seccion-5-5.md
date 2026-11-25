# 5.5. Implementación de la metodología (backend y frontend)

La implementación materializa el enfoque incremental de Scrum, el modelo dimensional constelación en PostgreSQL y la capa de visualización analítica en una solución reproducible basada en datos oficiales reales del estado de Oaxaca. El **backend** se integra por la adquisición automatizada de boletines PDF de **SECTUR Oaxaca / DATATUR (SIITE)** (`scripts/fetch_oaxaca_data.py`), el pipeline de validación, transformación y carga idempotente (`etl/etl.py`) y el esquema relacional (`sql/schema.sql`). El **frontend** se implementa en **Plotly Dash** (`app.py` y `assets/style.css`), operando de manera dual sobre `data/processed/*.csv` o directamente sobre la vista SQL `vw_kpis_mensuales` en PostgreSQL.

La arquitectura preserva la separación de granularidad del modelo dimensional: `fact_actividad_turistica` registra la operación mensual por destino (396 filas correspondientes a 9 destinos × 44 meses: 2022, 2024, 2025 y enero–agosto de 2026), mientras que `fact_turistas_origen` desglosa la llegada mensual entre turismo `Nacional` y `Extranjero` (792 filas), evitando duplicar cuartos disponibles, cuartos ocupados o derrama económica al realizar agregaciones.

---

## 5.5.1. Proceso ETL (códigos Python)

El flujo de datos se divide en una etapa previa de adquisición documental (`scripts/fetch_oaxaca_data.py`) y las tres fases clásicas del ETL implementadas en `etl/etl.py`:

### Etapa previa: Extracción reproducible desde boletines oficiales PDF
El script `scripts/fetch_oaxaca_data.py` descarga desde el portal oficial de SECTUR Oaxaca los boletines PDF de *Indicadores de la Actividad Turística* correspondientes a los cierres anuales 2022, 2024 y 2025 y al corte preliminar enero–agosto 2026 (almacenados en `data/raw/official/`). Mediante `pdfplumber`, extrae tanto el inventario de hospedaje (hoteles y cuartos registrados por destino) como las tablas mensuales de los 9 destinos oficiales, verificando que la suma `Nacional + Extranjero` coincida exactamente con el total de turistas y contra la fila `Total` oficial de cada tabla:

```python
# Fragmento real de scripts/fetch_oaxaca_data.py
dias_mes = calendar.monthrange(anio, mes)[1]
cuartos_disp = cuartos_inv * dias_mes
cuartos_ocup = int(round(cuartos_disp * (occ_pct / 100.0)))
fecha_str = f"{anio:04d}-{mes:02d}-01"
```

Los datos extraídos se guardan en `data/raw/` (`destinos.csv`, `actividad_turistica_mensual.csv`, `turistas_origen_mensual.csv`, `sources_metadata.json`) junto con la documentación trazable en `data/raw/FUENTES_OFICIALES.md`.

### 1. Extracción en `etl/etl.py`
La función `read_inputs()` lee los tres CSV generados en `data/raw/` y verifica de inmediato la presencia de todas las columnas requeridas mediante `require_columns()`, registrando el conteo en bitácora estructurada:

```python
# Fragmento real de etl/etl.py
def read_inputs(raw_dir: Path = RAW) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    destinos = pd.read_csv(raw_dir / "destinos.csv")
    actividad = pd.read_csv(raw_dir / "actividad_turistica_mensual.csv")
    origen = pd.read_csv(raw_dir / "turistas_origen_mensual.csv")

    require_columns(destinos, REQUIRED_DEST_COLS, "destinos.csv")
    require_columns(actividad, REQUIRED_ACT_COLS, "actividad_turistica_mensual.csv")
    require_columns(origen, REQUIRED_ORIG_COLS, "turistas_origen_mensual.csv")
    return destinos, actividad, origen
```

### 2. Transformación y validaciones de calidad
La función `transform()` aplica reglas estrictas de limpieza, integridad referencial y consistencia de negocio antes de emitir los archivos analíticos:

- **Validación de cadenas y enteros:** `_ensure_nonempty_strings()` verifica explícitamente `isna()` y cadenas vacías antes de normalizar texto (evitando que valores nulos se conviertan en `"nan"`), y `_ensure_integers()` rechaza decimales o nulos en conteos de hoteles, cuartos y turistas.
- **Deduplicación e integridad referencial:** Se eliminan posibles duplicados por llave natural (`id_destino`, `(fecha, id_destino)`, `(fecha, id_destino, tipo_turista)`) y se comprueba que no existan llaves huérfanas respecto a `dim_destino`.
- **Reglas de negocio y conciliación cruzada:** Se exige `0 <= cuartos_ocupados <= cuartos_disponibles`, `0 <= ocupacion_pct_oficial <= 100`, `estadia_promedio > 0`, valores monetarios no negativos, `tipo_cifra` en `{'Cierre', 'Preliminar'}` y conciliación exacta entre `llegada_turistas` y la suma `Nacional + Extranjero`:

```python
# Fragmento real de etl/etl.py: validación de rangos y conciliación origen vs total
invalid_act = (
    (act["cuartos_disponibles"] <= 0)
    | (act["cuartos_ocupados"] < 0)
    | (act["cuartos_ocupados"] > act["cuartos_disponibles"])
    | (~act["ocupacion_pct_oficial"].between(0, 100))
    | (act["derrama_economica_mxn"] < 0)
    | (act["llegada_turistas"] < 0)
    | (act["estadia_promedio"] <= 0)
    | (act["gasto_promedio_mxn"] < 0)
    | (~act["tipo_cifra"].isin(["Cierre", "Preliminar"]))
)
...
orig_sum = orig.groupby(["fecha", "id_destino"], as_index=False)["turistas"].sum()
reconcile = act[["fecha", "id_destino", "llegada_turistas"]].merge(
    orig_sum, on=["fecha", "id_destino"], how="left"
)
mismatch = reconcile[reconcile["llegada_turistas"] != reconcile["turistas"].astype(int)]
if not mismatch.empty:
    raise ValueError(
        f"Inconsistencia entre llegada_turistas y suma Nacional+Extranjero en {len(mismatch)} registros."
    )
```

- **Derivación de `dim_tiempo`:** Se genera `id_fecha` en formato entero `AAAAMMDD` junto con `anio`, `mes`, `nombre_mes` (en español) y `trimestre`, y se calcula el diccionario `quality` con conteos y totales de control.

### 3. Carga idempotente (CSV y PostgreSQL)
La función `write_outputs()` genera en `data/processed/` los archivos `dim_tiempo.csv` (44 filas), `dim_destino.csv` (9 filas), `fact_actividad_turistica.csv` (396 filas), `fact_turistas_origen.csv` (792 filas) y `metadata_fuentes.json`.

Cuando la variable `DATABASE_URL` está configurada en `.env`, `load_postgres()` ejecuta una carga atómica e idempotente dentro de `engine.begin()`: trunca las tablas en cascada, inserta dimensiones y hechos por lotes (`chunksize=500`) y registra el resultado (`SUCCESS` o `FAILED`) en `etl_run_log`:

```python
# Fragmento real de etl/etl.py: carga transaccional idempotente
with engine.begin() as conn:
    conn.execute(
        text("TRUNCATE fact_turistas_origen, fact_actividad_turistica, dim_destino, dim_tiempo CASCADE")
    )
    dim_tiempo_db = dim_tiempo.copy()
    dim_tiempo_db["fecha"] = pd.to_datetime(dim_tiempo_db["fecha"]).dt.date
    dim_tiempo_db.to_sql("dim_tiempo", conn, if_exists="append", index=False, method="multi", chunksize=500)
    dest_df.to_sql("dim_destino", conn, if_exists="append", index=False, method="multi", chunksize=500)
    fact_actividad.to_sql("fact_actividad_turistica", conn, if_exists="append", index=False, method="multi", chunksize=500)
    fact_origen.to_sql("fact_turistas_origen", conn, if_exists="append", index=False, method="multi", chunksize=500)
```

Para ejecutar el flujo completo en Windows usando el entorno virtual del proyecto:

```powershell
.\.venv\Scripts\python.exe scripts\fetch_oaxaca_data.py
.\.venv\Scripts\python.exe etl\etl.py
.\.venv\Scripts\python.exe app.py
```

---

## 5.5.2. Visualización efectiva (KPIs y dashboard)

El dashboard implementado en `app.py` (servido en `http://127.0.0.1:8050`) incorpora cinco filtros globales compartidos (`year-filter`, `region-filter`, `dest-type-filter`, `destination-filter` y `metric-selector`) e integra **nueve indicadores clave (KPIs)** calculados estrictamente mediante **razones de sumas** en `compute_kpis()`, acompañados de insignias de variación interanual (**YoY**) comparadas contra los mismos meses disponibles de `anio - 1` (`format_period_range` + `yoy_delta`).

### Catálogo de KPIs integrados en el dashboard

| # | KPI en tarjeta | Fórmula (razón de sumas) | Variación YoY | Significado de negocio |
|---|---|---|---|---|
| 1 | **Ocupación hotelera** | `100 × Σ cuartos_ocupados ÷ Σ cuartos_disponibles` | Puntos porcentuales (`pp`) | Mide el aprovechamiento real de la capacidad hotelera ponderada por cuartos-noche ofertados. |
| 2 | **Derrama económica total** | `Σ derrama_economica_mxn` (mostrada en MDP y MXN) | Porcentual (`%`) | Cuantifica el ingreso turístico total generado en el periodo y destinos filtrados. |
| 3 | **Llegada de turistas** | `Σ llegada_turistas` | Porcentual (`%`) | Mide el volumen acumulado de visitantes hospedados. |
| 4 | **Participación turismo extranjero** | `100 × Σ turistas_extranjeros ÷ Σ llegada_turistas` | Puntos porcentuales (`pp`) | Evalúa la internacionalización de la demanda (mostrando el desglose Nac vs. Ext). |
| 5 | **Derrama promedio por turista** | `Σ derrama_economica_mxn ÷ Σ llegada_turistas` | Porcentual (`%`) | Estima el gasto promedio captado por visitante en MXN. |
| 6 | **Derrama / cuarto disponible** | `Σ derrama_economica_mxn ÷ Σ cuartos_disponibles` | Porcentual (`%`) | Funciona como indicador de rendimiento por capacidad disponible (RevPAR turístico estimado en MXN). |
| 7 | **Cuartos disponibles (oferta)** | `Σ cuartos_disponibles` | Porcentual (`%`) | Refleja la capacidad instalada mensual-anual ofertada (`cuartos_registrados × días del mes`). |
| 8 | **Cuartos ocupados** | `Σ cuartos_ocupados` | Porcentual (`%`) | Mide la demanda física absoluta de cuartos-noche ocupados. |
| 9 | **Estadía promedio ponderada** | `Σ (estadia_promedio × llegada_turistas) ÷ Σ llegada_turistas` | Diferencia en noches (`n`) | Indica la permanencia media ponderada por volumen real de visitantes. |

*(Nota: si el archivo de origen contiene valores no nulos en `meta_ocupacion_pct`, la tarjeta de ocupación y la gráfica temporal muestran automáticamente la meta ponderada y su brecha en puntos porcentuales; en las publicaciones oficiales actuales dicho campo permanece nulo para no inventar metas).*

### Narrativa visual (*Storytelling* en 3 momentos)

El tablero organiza la lectura ejecutiva en tres secciones progresivas:

1. **`01 / PANORAMA` — Tarjetas KPI y serie temporal mensual (`trend-chart`):** Presenta los 9 KPIs con sus insignias YoY y una gráfica de líneas mensuales que contrasta el año seleccionado (línea continua) contra el año inmediato anterior (línea punteada) para ocupación, derrama o llegada de turistas. Cuando el año seleccionado carece de base previa comparable (como 2022 o 2024), informa explícitamente la ausencia de año anterior en las insignias y en el diagnóstico (precisando en 2024 que el boletín 2023 fue publicado por SECTUR como imágenes rasterizadas sin capa de texto).
2. **`02 / BRECHA Y ACCIÓN` — Comparativa por destino (`destination-chart`) y panel de diagnóstico (`insight-panel`):** Combina barras horizontales ordenadas por destino (con línea de promedio ponderado en ocupación) junto con un panel dinámico (`build_insight_copy()`) que identifica al destino líder y al rezagado, calcula la brecha en puntos porcentuales (ej. en el cierre 2025, **Bahías de Huatulco** alcanza `60.7%` de ocupación y `$10,267.0 MDP`, mientras **Ciudad de Oaxaca** capta `1,324,332` turistas y `16.0%` de turismo extranjero, frente a `18.6%` y `$159.0 MDP` en **Mixteca**), señala el pico y valle estacional y emite una recomendación descriptiva accionable.
3. **`03 / DETALLE Y COMPOSICIÓN` — Estacionalidad, origen, dispersión y tabla exportable:**
   - **Mapa de calor Destino × Mes (`heatmap-chart`):** Localiza picos estacionales (Guelaguetza en julio, Semana Santa, Día de Muertos y diciembre) y meses valle por cada uno de los 9 destinos.
   - **Composición Nacional vs. Extranjero (`origin-chart`):** Aprovecha `fact_turistas_origen` con barras apiladas por destino (o desglose mensual cuando se filtra un único destino).
   - **Dispersión Derrama vs. Ocupación (`scatter-chart`):** Relaciona porcentaje de ocupación, derrama económica en MDP y volumen de turistas (tamaño de burbuja) coloreado por región.
   - **Tabla resumen y descarga CSV (`summary-table` y `download-csv-btn`):** Resume los 9 indicadores por destino y permite exportar la vista filtrada en `oaxaca_turismo_{anio}_resumen.csv` (UTF-8 con BOM). Si una combinación de filtros no arroja filas, el callback `update_dashboard` devuelve tarjetas neutras y figuras vacías informativas sin generar excepciones.

### Fuentes oficiales y fecha de corte

- **Fuente principal:** Secretaría de Turismo del Estado de Oaxaca (**SECTUR Oaxaca**), portal de estadísticas ([oaxaca.gob.mx/sectur/informacion-de-interes/estadisticas/](https://www.oaxaca.gob.mx/sectur/informacion-de-interes/estadisticas/)), en coordinación con **DATATUR (SECTUR Federal)** y **SIITE**.
- **Boletines integrados (`data/raw/official/`):**
  - Cierre anual 2022 (`2023_05_1.-Indicadores-de-la-Actividad-Turistica-2022-2.pdf`): `5,099,619` turistas, `$16,194 MDP`, `38.5%` ocupación.
  - Cierre anual 2024 (`2025_04_1.-Indicadores-de-la-Actividad-Turistica-2024-cierre-web.pdf`): `6,063,761` turistas, `$22,765 MDP`, `44.0%` ocupación.
  - Cierre anual 2025 (`2026_04_1.-Indicadores-de-la-Actividad-Turistica-2025.pdf.pdf`): `6,289,000` turistas, `$23,347 MDP`, `42.5%` ocupación.
  - Corte preliminar enero–agosto 2026 (`2026_09_1.-Indicadores-de-la-Actividad-Turistica-2026-Enero_-agosto.pdf`): `4,312,798` turistas, `$16,970 MDP`, `45.3%` ocupación.
- **Fecha de corte más reciente:** **Agosto 2026** (cifras preliminares enero–agosto 2026; cierres anuales definitivos para 2022, 2024 y 2025; total acumulado de `21,765,178` turistas y `$79,276 MDP` en los 44 meses procesados).
