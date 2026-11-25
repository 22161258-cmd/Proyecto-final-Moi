# Dashboard de Ocupación Hotelera y Derrama Turística en Oaxaca

Prototipo académico descrito en la Sección 5.5. Integra un ETL en Python, un modelo dimensional para PostgreSQL y un dashboard interactivo en Plotly Dash.

> **Datos de demostración:** los archivos incluidos se generan de forma sintética y no representan cifras oficiales ni hoteles reales. Sustituye los CSV de `data/raw/` por datos autorizados antes de usar el dashboard para decisiones reales.

## Requisitos

- Python 3.10 o superior
- PostgreSQL 14 o superior (opcional para ejecutar el dashboard con CSV)

## Inicio rápido

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/generate_demo_data.py
python etl/etl.py
python app.py
```

Abre `http://127.0.0.1:8050`. El dashboard usa por defecto los CSV transformados y puede ejecutar sin PostgreSQL.

## PostgreSQL

1. Crea una base de datos y ejecuta `sql/schema.sql` en ella.
2. Copia `.env.example` a `.env` y configura `DATABASE_URL`.
3. Vuelve a ejecutar `python etl/etl.py`; el proceso carga las dimensiones y hechos en PostgreSQL.
4. Configura `DASHBOARD_SOURCE=postgres` para que el dashboard consulte la base. Si la conexión falla, muestra un mensaje claro; para usar CSV, configura `DASHBOARD_SOURCE=csv`.

## Estructura

```text
app.py                 Dashboard y siete KPIs
etl/etl.py             Extracción, limpieza, transformación y carga
scripts/generate_demo_data.py  Generador reproducible de datos sintéticos
sql/schema.sql         Dimensiones, hechos y consulta de indicadores
docs/seccion-5-5.md    Texto listo para incorporar al reporte
data/raw/              Archivos de entrada (se generan localmente)
data/processed/        Archivos transformados (se generan localmente)
```

## Alcance y limitaciones

El prototipo es descriptivo, consulta información agregada por hotel y día y no realiza predicciones ni procesa reservaciones en tiempo real, en línea con el alcance del documento. La tasa de ocupación, ADR, RevPAR y cancelación se calculan con razones de sumas para evitar promediar porcentajes diarios. Los datos sintéticos sirven únicamente para probar el flujo y la interfaz.
