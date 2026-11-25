# Dashboard de Ocupación Hotelera y Derrama Turística en Oaxaca

Plataforma analítica descriptiva basada en **datos oficiales de SECTUR Oaxaca / DATATUR (SIITE)**. Integra extracción reproducible de boletines PDF oficiales, un pipeline ETL en Python con validaciones de calidad, un modelo dimensional constelación en PostgreSQL y un dashboard interactivo en Plotly Dash con 9 KPIs reales y operación dual (`CSV` o `PostgreSQL`).

## Fuentes oficiales y cobertura

- **Fuente principal:** Secretaría de Turismo del Estado de Oaxaca (SECTUR Oaxaca) — [Estadísticas Turísticas](https://www.oaxaca.gob.mx/sectur/informacion-de-interes/estadisticas/) / DATATUR (SIITE).
- **Fecha de corte más reciente:** **Agosto 2026** (cifras preliminares enero–agosto 2026; cierres anuales definitivos para **2022**, **2024** y **2025**).
- **Cobertura:** **44 meses** y **9 destinos oficiales** (`Ciudad de Oaxaca`, `Bahías de Huatulco`, `Puerto Escondido`, `Tuxtepec`, `Istmo de Tehuantepec`, `Mixteca`, `Juquila`, `Ventanilla Puerto Ángel` y `Resto del Estado`), detallados en [`data/raw/FUENTES_OFICIALES.md`](data/raw/FUENTES_OFICIALES.md) y [`data/processed/metadata_fuentes.json`](data/processed/metadata_fuentes.json).
- **Nota metodológica:** El boletín anual 2023 publicado por SECTUR Oaxaca se distribuyó como imágenes rasterizadas sin capa de texto extraíble, por lo que no se incluye en el parseo automático sin OCR para preservar la trazabilidad exacta.

## Requisitos

- **Python 3.10 o superior** (probado en Windows con **Python 3.14.3** usando `py`)
- **PostgreSQL 14 o superior** (opcional; por defecto el dashboard lee `data/processed/*.csv`)

## Inicio rápido en Windows

> En Windows, utiliza `py` para crear el entorno virtual si el alias `python` apunta a Microsoft Store.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\fetch_oaxaca_data.py --skip-download
.\.venv\Scripts\python.exe etl\etl.py
.\.venv\Scripts\python.exe app.py
```

- Para volver a descargar los boletines PDF desde el portal oficial de SECTUR Oaxaca, omite `--skip-download`:
  ```powershell
  .\.venv\Scripts\python.exe scripts\fetch_oaxaca_data.py
  ```
- Abre `http://127.0.0.1:8050` en tu navegador. Por defecto (`DASHBOARD_SOURCE=csv`), el dashboard funciona sin requerir servidor PostgreSQL activo.

## Configuración de PostgreSQL (modo dual)

1. Crea una base de datos vacía en PostgreSQL (por ejemplo, `oaxaca_turismo`) y ejecuta [`sql/schema.sql`](sql/schema.sql) para crear tablas, restricciones `CHECK`, índices y vistas (`vw_kpis_mensuales` y `vw_kpis_anuales_yoy`).
2. Copia `.env.example` a `.env` y configura `DATABASE_URL`:
   ```env
   DATABASE_URL=postgresql+psycopg2://postgres:tu_password@localhost:5432/oaxaca_turismo
   DASHBOARD_SOURCE=postgres
   ```
3. Ejecuta el ETL para realizar la carga transaccional idempotente y registrar la corrida en `etl_run_log`:
   ```powershell
   .\.venv\Scripts\python.exe etl\etl.py
   ```
4. Inicia el tablero con `.\.venv\Scripts\python.exe app.py`. Para volver al respaldo local en CSV, cambia `DASHBOARD_SOURCE=csv` en `.env`.

## Ejecución de pruebas automatizadas (`pytest`)

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

## Estructura del proyecto

```text
app.py                         Dashboard Plotly Dash (9 KPIs reales, storytelling y exportación CSV)
assets/style.css               Hoja de estilos del observatorio turístico
scripts/fetch_oaxaca_data.py   Descarga y parseo reproducible de boletines PDF de SECTUR Oaxaca
etl/etl.py                     Validación, transformación, metadatos y carga idempotente
sql/schema.sql                 Modelo dimensional constelación, etl_run_log y vistas YoY
tests/                         Suite de pruebas automatizadas (pytest)
data/raw/                      CSVs extraídos, boletines PDF en official/ y FUENTES_OFICIALES.md
data/processed/                Tablas dimensionales limpias (CSV) y metadata_fuentes.json
docs/                          Documentación académica y técnica (secciones 5.1, 5.2, 5.3, 5.5 y reporte completo)
requirements.txt               Dependencias del proyecto
.env.example                   Plantilla de configuración para PostgreSQL y DASHBOARD_SOURCE
```

## Alcance y cálculo de indicadores

El tablero es de naturaleza **descriptiva y diagnóstica**. Todas las tasas y promedios agregados (ocupación hotelera, participación extranjera, derrama por turista, derrama por cuarto disponible y estadía promedio) se calculan estrictamente como **razones de sumas** y ponderaciones por volumen real del periodo filtrado, nunca promediando porcentajes mensuales. Las variaciones interanuales (**YoY**) comparan únicamente meses equivalentes del año inmediato anterior.
