"""Dashboard interactivo de ocupación hotelera y derrama turística en Oaxaca.

Consume datos oficiales de SECTUR Oaxaca / DATATUR (SIITE) en modo dual:
CSV (`data/processed/*.csv`) o PostgreSQL (`vw_kpis_mensuales`) vía `.env`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, dash_table, dcc, html, no_update
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
PROCESSED = ROOT / "data" / "processed"

MONTHS: dict[int, str] = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}
MONTH_SHORT: dict[int, str] = {
    1: "Ene",
    2: "Feb",
    3: "Mar",
    4: "Abr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dic",
}
MONTH_ORDER = list(MONTHS.values())

COLORS = {
    "petroleo": "#172d3b",
    "ink": "#13222d",
    "muted": "#667584",
    "line": "#e2e8ee",
    "teal": "#127c78",
    "orange": "#d27845",
    "blue": "#4979b8",
}

METRIC_CONFIG = {
    "ocupacion": {
        "label": "Ocupación hotelera (%)",
        "col": "ocupacion_pct",
        "suffix": "%",
        "format": ".1f",
    },
    "derrama": {
        "label": "Derrama económica (MDP)",
        "col": "derrama_mdp",
        "suffix": " MDP",
        "format": ",.1f",
    },
    "turistas": {
        "label": "Llegada de turistas",
        "col": "llegada_turistas",
        "suffix": "",
        "format": ",.0f",
    },
}

SUMMARY_COLUMNS = [
    {"name": "Destino turístico", "id": "nombre_destino"},
    {"name": "Región", "id": "region"},
    {"name": "Tipo de destino", "id": "tipo_destino"},
    {"name": "Ocupación (%)", "id": "ocupacion_pct_fmt"},
    {"name": "Derrama (MDP)", "id": "derrama_mdp_fmt"},
    {"name": "Llegada de turistas", "id": "llegada_turistas_fmt"},
    {"name": "% Extranjero", "id": "pct_extranjeros_fmt"},
    {"name": "Derrama / turista", "id": "derrama_por_turista_fmt"},
    {"name": "Derrama / cuarto disp.", "id": "derrama_por_cuarto_fmt"},
    {"name": "Cuartos disponibles", "id": "cuartos_disponibles_fmt"},
    {"name": "Cuartos ocupados", "id": "cuartos_ocupados_fmt"},
    {"name": "Estadía (noches)", "id": "estadia_promedio_fmt"},
]


def load_metadata() -> dict:
    """Carga metadatos oficiales de fuentes y fecha de corte."""
    meta_path = PROCESSED / "metadata_fuentes.json"
    if meta_path.exists():
        with meta_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return {
        "fuente_oficial": "SECTUR Oaxaca - Boletines de Indicadores de la Actividad Turística (DATATUR / SIITE)",
        "portal_url": "https://www.oaxaca.gob.mx/sectur/informacion-de-interes/estadisticas/",
        "fecha_corte": "Consultar data/processed/metadata_fuentes.json",
        "nota_cobertura": "",
    }


def load_csv_data() -> pd.DataFrame:
    """Carga y une el modelo dimensional desde data/processed/*.csv."""
    required = [
        PROCESSED / name
        for name in (
            "dim_tiempo.csv",
            "dim_destino.csv",
            "fact_actividad_turistica.csv",
            "fact_turistas_origen.csv",
        )
    ]
    missing = [p.name for p in required if not p.exists()]
    if missing:
        raise RuntimeError(
            "Faltan archivos procesados en data/processed/: "
            + ", ".join(missing)
            + ". Ejecuta primero scripts/fetch_oaxaca_data.py y etl/etl.py."
        )

    times, destinations, activity, origin = [pd.read_csv(p) for p in required]
    origin_pivot = (
        origin.pivot_table(
            index=["id_fecha", "id_destino"],
            columns="tipo_turista",
            values="turistas",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    if "Nacional" not in origin_pivot.columns:
        origin_pivot["Nacional"] = 0
    if "Extranjero" not in origin_pivot.columns:
        origin_pivot["Extranjero"] = 0
    origin_pivot = origin_pivot.rename(
        columns={"Nacional": "turistas_nacionales", "Extranjero": "turistas_extranjeros"}
    )

    data = activity.merge(destinations, on="id_destino", validate="many_to_one")
    data = data.merge(times, on="id_fecha", validate="many_to_one")
    data = data.merge(
        origin_pivot[["id_fecha", "id_destino", "turistas_nacionales", "turistas_extranjeros"]],
        on=["id_fecha", "id_destino"],
        how="left",
        validate="one_to_one",
    )
    data["fecha"] = pd.to_datetime(data["fecha"])
    data["turistas_nacionales"] = data["turistas_nacionales"].fillna(0).astype(int)
    data["turistas_extranjeros"] = data["turistas_extranjeros"].fillna(0).astype(int)
    return data


def load_postgres_data() -> pd.DataFrame:
    """Carga el modelo consolidado desde PostgreSQL (vista vw_kpis_mensuales)."""
    from sqlalchemy import create_engine, text

    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DASHBOARD_SOURCE=postgres requiere DATABASE_URL en el entorno.")

    query = text(
        """
        SELECT
            id_fecha, fecha, anio, mes, nombre_mes, trimestre,
            id_destino, nombre_destino, region, tipo_destino,
            cuartos_disponibles, cuartos_ocupados, ocupacion_pct_oficial,
            derrama_economica_mxn, llegada_turistas, estadia_promedio,
            gasto_promedio_mxn, meta_ocupacion_pct, tipo_cifra,
            turistas_nacionales, turistas_extranjeros
        FROM vw_kpis_mensuales
        """
    )
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            data = pd.read_sql(query, connection)
    finally:
        engine.dispose()

    data["fecha"] = pd.to_datetime(data["fecha"])
    data["turistas_nacionales"] = data["turistas_nacionales"].fillna(0).astype(int)
    data["turistas_extranjeros"] = data["turistas_extranjeros"].fillna(0).astype(int)
    return data


def load_data() -> pd.DataFrame:
    """Selecciona la fuente de datos activa según DASHBOARD_SOURCE."""
    if os.getenv("DASHBOARD_SOURCE", "csv").strip().lower() == "postgres":
        return load_postgres_data()
    return load_csv_data()


METADATA = load_metadata()
DATA = load_data()
YEARS = sorted(DATA["anio"].dropna().astype(int).unique().tolist())
REGIONS = sorted(DATA["region"].dropna().unique().tolist())
DEST_TYPES = sorted(DATA["tipo_destino"].dropna().unique().tolist())
DESTINATIONS = sorted(DATA["nombre_destino"].dropna().unique().tolist())
MAX_YEAR = max(YEARS) if YEARS else 2026
MONTH_LABELS = (
    DATA[["mes", "nombre_mes"]].drop_duplicates().set_index("mes")["nombre_mes"].to_dict()
    if not DATA.empty
    else MONTHS
)
YEAR_TIPO_MAP = (
    DATA.groupby("anio")["tipo_cifra"].first().to_dict() if not DATA.empty else {}
)


def filter_data(
    df: pd.DataFrame,
    region: str | None = "Todas",
    dest_type: str | None = "Todos",
    destination: str | None = "Todos",
) -> pd.DataFrame:
    """Aplica filtros dimensionales manteniendo el historial multi-año para YoY."""
    filtered = df
    if region and region != "Todas":
        filtered = filtered[filtered["region"] == region]
    if dest_type and dest_type != "Todos":
        filtered = filtered[filtered["tipo_destino"] == dest_type]
    if destination and destination != "Todos":
        filtered = filtered[filtered["nombre_destino"] == destination]
    return filtered.copy()


def compute_kpis(df: pd.DataFrame) -> dict[str, float | None]:
    """Calcula KPIs agregados estrictamente como razón de sumas."""
    available = float(df["cuartos_disponibles"].sum())
    occupied = float(df["cuartos_ocupados"].sum())
    derrama_mxn = float(df["derrama_economica_mxn"].sum())
    tourists = float(df["llegada_turistas"].sum())
    nac = float(df["turistas_nacionales"].sum())
    ext = float(df["turistas_extranjeros"].sum())

    ocupacion_pct = (100.0 * occupied / available) if available > 0 else 0.0
    derrama_mdp = derrama_mxn / 1_000_000.0
    pct_extranjeros = (100.0 * ext / tourists) if tourists > 0 else 0.0
    derrama_por_turista = (derrama_mxn / tourists) if tourists > 0 else 0.0
    derrama_por_cuarto = (derrama_mxn / available) if available > 0 else 0.0
    estadia_prom = (
        float((df["estadia_promedio"] * df["llegada_turistas"]).sum()) / tourists
        if tourists > 0
        else 0.0
    )

    meta_valid = df["meta_ocupacion_pct"].notna()
    meta_avail = float(df.loc[meta_valid, "cuartos_disponibles"].sum())
    meta_pct = (
        float((df.loc[meta_valid, "cuartos_disponibles"] * df.loc[meta_valid, "meta_ocupacion_pct"]).sum())
        / meta_avail
        if meta_avail > 0
        else None
    )
    brecha_meta_pp = (ocupacion_pct - meta_pct) if meta_pct is not None else None

    return {
        "cuartos_disponibles": available,
        "cuartos_ocupados": occupied,
        "ocupacion_pct": ocupacion_pct,
        "derrama_mxn": derrama_mxn,
        "derrama_mdp": derrama_mdp,
        "llegada_turistas": tourists,
        "turistas_nacionales": nac,
        "turistas_extranjeros": ext,
        "pct_extranjeros": pct_extranjeros,
        "derrama_por_turista": derrama_por_turista,
        "derrama_por_cuarto": derrama_por_cuarto,
        "estadia_promedio": estadia_prom,
        "meta_ocupacion_pct": meta_pct,
        "brecha_meta_pp": brecha_meta_pp,
    }


def format_period_range(months: list[int], year: int) -> str:
    """Construye etiqueta legible para el conjunto de meses comparable."""
    if not months:
        return str(year)
    if len(months) == 12:
        return str(year)
    if len(months) == 1:
        return f"{MONTH_SHORT.get(months[0], months[0])} {year}"
    return f"{MONTH_SHORT.get(min(months), min(months))}–{MONTH_SHORT.get(max(months), max(months))} {year}"


def yoy_delta(
    cur_val: float,
    prev_val: float | None,
    prev_label: str,
    mode: str = "pct",
) -> tuple[str, str]:
    """Devuelve (texto_badge, clase_css) para la variación interanual YoY."""
    if prev_val is None:
        return "Sin base año anterior", "neutral"

    if mode == "pp":
        diff = cur_val - prev_val
        cls = "positive" if diff > 0.05 else ("negative" if diff < -0.05 else "neutral")
        return f"{diff:+.1f} pp vs {prev_label}", cls

    if mode == "nights":
        diff = cur_val - prev_val
        cls = "positive" if diff > 0.01 else ("negative" if diff < -0.01 else "neutral")
        return f"{diff:+.2f} n vs {prev_label}", cls

    if prev_val <= 0:
        return f"Sin base en {prev_label}", "neutral"
    pct = 100.0 * (cur_val - prev_val) / prev_val
    cls = "positive" if pct > 0.05 else ("negative" if pct < -0.05 else "neutral")
    return f"{pct:+.1f}% vs {prev_label}", cls


def money_mxn(value: float) -> str:
    return f"${value:,.0f} MXN"


def money_mdp(value_mdp: float, value_mxn: float) -> str:
    if abs(value_mdp) >= 1.0 or value_mdp == 0:
        return f"${value_mdp:,.1f} MDP"
    return money_mxn(value_mxn)


def kpi_card(
    label: str,
    value: str,
    note: str,
    badge_text: str = "—",
    badge_cls: str = "neutral",
    accent: str = COLORS["petroleo"],
) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div(label, className="kpi-label"),
                    html.Span(badge_text, className=f"yoy-badge {badge_cls}"),
                ],
                className="kpi-top",
            ),
            html.Div(value, className="kpi-value", style={"color": accent}),
            html.Div(note, className="kpi-note"),
        ],
        className="kpi-card",
    )


def empty_figure(message: str = "Sin registros para los filtros seleccionados") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font={"color": COLORS["muted"], "size": 14},
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(
        template="plotly_white",
        margin={"l": 16, "r": 16, "t": 12, "b": 12},
        height=330,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return fig


def build_destination_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega la vista filtrada por destino usando razón de sumas."""
    if df.empty:
        return pd.DataFrame()

    weighted_stay = df.assign(_stay_tur=df["estadia_promedio"] * df["llegada_turistas"])
    grouped = weighted_stay.groupby(
        ["id_destino", "nombre_destino", "region", "tipo_destino"], as_index=False
    ).agg(
        cuartos_disponibles=("cuartos_disponibles", "sum"),
        cuartos_ocupados=("cuartos_ocupados", "sum"),
        derrama_economica_mxn=("derrama_economica_mxn", "sum"),
        llegada_turistas=("llegada_turistas", "sum"),
        turistas_nacionales=("turistas_nacionales", "sum"),
        turistas_extranjeros=("turistas_extranjeros", "sum"),
        _stay_tur=("_stay_tur", "sum"),
    )
    grouped["ocupacion_pct"] = (
        100.0 * grouped["cuartos_ocupados"] / grouped["cuartos_disponibles"].where(grouped["cuartos_disponibles"] > 0)
    ).fillna(0.0)
    grouped["derrama_mdp"] = grouped["derrama_economica_mxn"] / 1_000_000.0
    grouped["pct_extranjeros"] = (
        100.0 * grouped["turistas_extranjeros"] / grouped["llegada_turistas"].where(grouped["llegada_turistas"] > 0)
    ).fillna(0.0)
    grouped["derrama_por_turista"] = (
        grouped["derrama_economica_mxn"] / grouped["llegada_turistas"].where(grouped["llegada_turistas"] > 0)
    ).fillna(0.0)
    grouped["derrama_por_cuarto"] = (
        grouped["derrama_economica_mxn"] / grouped["cuartos_disponibles"].where(grouped["cuartos_disponibles"] > 0)
    ).fillna(0.0)
    grouped["estadia_promedio"] = (
        grouped["_stay_tur"] / grouped["llegada_turistas"].where(grouped["llegada_turistas"] > 0)
    ).fillna(0.0)
    return grouped.drop(columns=["_stay_tur"]).sort_values("derrama_economica_mxn", ascending=False)


def format_summary_records(summary_df: pd.DataFrame) -> list[dict]:
    """Formatea filas para la tabla interactiva de Dash."""
    if summary_df.empty:
        return []
    out = summary_df.copy()
    out["ocupacion_pct_fmt"] = out["ocupacion_pct"].map(lambda x: f"{x:.1f}%")
    out["derrama_mdp_fmt"] = out["derrama_mdp"].map(lambda x: f"${x:,.1f} MDP")
    out["llegada_turistas_fmt"] = out["llegada_turistas"].map(lambda x: f"{x:,.0f}")
    out["pct_extranjeros_fmt"] = out["pct_extranjeros"].map(lambda x: f"{x:.1f}%")
    out["derrama_por_turista_fmt"] = out["derrama_por_turista"].map(lambda x: f"${x:,.0f}")
    out["derrama_por_cuarto_fmt"] = out["derrama_por_cuarto"].map(lambda x: f"${x:,.0f}")
    out["cuartos_disponibles_fmt"] = out["cuartos_disponibles"].map(lambda x: f"{x:,.0f}")
    out["cuartos_ocupados_fmt"] = out["cuartos_ocupados"].map(lambda x: f"{x:,.0f}")
    out["estadia_promedio_fmt"] = out["estadia_promedio"].map(lambda x: f"{x:.2f}")
    return out.to_dict("records")


def build_trend_chart(base_df: pd.DataFrame, year: int, metric: str) -> go.Figure:
    """Serie temporal mensual comparando año seleccionado vs año anterior."""
    trend_source = base_df[base_df["anio"].isin([year - 1, year])].copy()
    if trend_source.empty:
        return empty_figure()

    monthly = trend_source.groupby(["anio", "mes"], as_index=False).agg(
        cuartos_ocupados=("cuartos_ocupados", "sum"),
        cuartos_disponibles=("cuartos_disponibles", "sum"),
        derrama_economica_mxn=("derrama_economica_mxn", "sum"),
        llegada_turistas=("llegada_turistas", "sum"),
    )
    monthly["ocupacion_pct"] = (
        100.0 * monthly["cuartos_ocupados"] / monthly["cuartos_disponibles"].where(monthly["cuartos_disponibles"] > 0)
    ).fillna(0.0)
    monthly["derrama_mdp"] = monthly["derrama_economica_mxn"] / 1_000_000.0
    monthly["Periodo"] = monthly["anio"].astype(int).astype(str)
    monthly["Mes"] = monthly["mes"].map(MONTH_LABELS)
    monthly = monthly.sort_values(["anio", "mes"])

    cfg = METRIC_CONFIG.get(metric, METRIC_CONFIG["ocupacion"])
    y_col = cfg["col"]
    color_map = {str(year): COLORS["teal"], str(year - 1): COLORS["orange"]}

    fig = px.line(
        monthly,
        x="Mes",
        y=y_col,
        color="Periodo",
        markers=True,
        category_orders={"Mes": MONTH_ORDER},
        color_discrete_map=color_map,
        labels={y_col: cfg["label"], "Periodo": "Año"},
    )
    for trace in fig.data:
        if trace.name == str(year - 1):
            trace.update(line={"dash": "dot", "width": 2.4})
        else:
            trace.update(line={"width": 3})

    if metric == "ocupacion" and trend_source["meta_ocupacion_pct"].notna().any():
        cur_meta = trend_source[(trend_source["anio"] == year) & trend_source["meta_ocupacion_pct"].notna()].copy()
        if not cur_meta.empty:
            cur_meta["_meta_rooms"] = cur_meta["cuartos_disponibles"] * cur_meta["meta_ocupacion_pct"]
            meta_m = cur_meta.groupby("mes", as_index=False).agg(
                _meta_rooms=("_meta_rooms", "sum"),
                cuartos_disponibles=("cuartos_disponibles", "sum"),
            )
            meta_m["Meta"] = meta_m["_meta_rooms"] / meta_m["cuartos_disponibles"]
            meta_m["Mes"] = meta_m["mes"].map(MONTH_LABELS)
            meta_m = meta_m.sort_values("mes")
            fig.add_trace(
                go.Scatter(
                    x=meta_m["Mes"],
                    y=meta_m["Meta"],
                    name="Meta oficial",
                    mode="lines",
                    line={"color": "#7d8b99", "dash": "dash", "width": 2},
                )
            )

    fig.update_layout(
        template="plotly_white",
        margin={"l": 18, "r": 16, "t": 18, "b": 18},
        height=350,
        legend={"orientation": "h", "y": 1.13, "title_text": ""},
        hovermode="x unified",
        font={"color": COLORS["ink"]},
    )
    fig.update_yaxes(
        ticksuffix=cfg["suffix"],
        gridcolor=COLORS["line"],
        rangemode="tozero",
    )
    return fig


def build_destination_chart(summary_df: pd.DataFrame, metric: str, overall_kpis: dict) -> go.Figure:
    """Barras horizontales comparativas por destino turístico."""
    if summary_df.empty:
        return empty_figure()

    cfg = METRIC_CONFIG.get(metric, METRIC_CONFIG["ocupacion"])
    y_col = cfg["col"]
    plot_df = summary_df.sort_values(y_col, ascending=True).copy()

    if metric == "ocupacion":
        plot_df["label_txt"] = plot_df[y_col].map(lambda v: f"{v:.1f}%")
    elif metric == "derrama":
        plot_df["label_txt"] = plot_df[y_col].map(lambda v: f"${v:,.0f} MDP")
    else:
        plot_df["label_txt"] = plot_df[y_col].map(lambda v: f"{v:,.0f}")

    fig = px.bar(
        plot_df,
        x=y_col,
        y="nombre_destino",
        orientation="h",
        text="label_txt",
        color=y_col,
        color_continuous_scale=["#e7a57c", "#7fc3b3", "#127c78"],
        custom_data=["region", "ocupacion_pct", "derrama_mdp", "llegada_turistas"],
        labels={"nombre_destino": "Destino", y_col: cfg["label"]},
    )
    fig.update_traces(
        textposition="outside",
        cliponaxis=False,
        hovertemplate=(
            "<b>%{y}</b> (%{customdata[0]})<br>"
            "Ocupación: %{customdata[1]:.1f}%<br>"
            "Derrama: $%{customdata[2]:,.1f} MDP<br>"
            "Turistas: %{customdata[3]:,.0f}<extra></extra>"
        ),
    )

    if metric == "ocupacion":
        fig.add_vline(
            x=overall_kpis["ocupacion_pct"],
            line_dash="dash",
            line_color=COLORS["petroleo"],
            annotation_text=f"Prom. {overall_kpis['ocupacion_pct']:.1f}%",
            annotation_position="top",
        )
        x_max = max(100.0, float(plot_df[y_col].max()) * 1.15)
        fig.update_xaxes(range=[0, x_max], ticksuffix="%", gridcolor=COLORS["line"])
    else:
        x_max = float(plot_df[y_col].max()) * 1.22 if plot_df[y_col].max() > 0 else 10
        fig.update_xaxes(range=[0, x_max], gridcolor=COLORS["line"])

    fig.update_layout(
        template="plotly_white",
        margin={"l": 10, "r": 26, "t": 28, "b": 18},
        height=355,
        coloraxis_showscale=False,
        font={"color": COLORS["ink"]},
    )
    fig.update_yaxes(title_text="")
    return fig


def build_heatmap_chart(current: pd.DataFrame) -> go.Figure:
    """Mapa de calor Destino × Mes para detectar estacionalidad (Guelaguetza, Muertos, etc.)."""
    if current.empty:
        return empty_figure()

    heat = current.groupby(["nombre_destino", "mes"], as_index=False).agg(
        cuartos_ocupados=("cuartos_ocupados", "sum"),
        cuartos_disponibles=("cuartos_disponibles", "sum"),
    )
    heat["Ocupación"] = (
        100.0 * heat["cuartos_ocupados"] / heat["cuartos_disponibles"].where(heat["cuartos_disponibles"] > 0)
    ).fillna(0.0)

    order_dest = (
        heat.groupby("nombre_destino")["Ocupación"].mean().sort_values(ascending=True).index.tolist()
    )
    months_present = sorted(heat["mes"].unique().tolist())
    matrix = (
        heat.pivot(index="nombre_destino", columns="mes", values="Ocupación")
        .reindex(index=order_dest, columns=months_present)
    )

    fig = px.imshow(
        matrix,
        aspect="auto",
        color_continuous_scale=["#f6dfd0", "#e79b72", "#59a99d", "#127c78"],
        labels={"x": "Mes", "y": "Destino", "color": "Ocupación (%)"},
        x=[MONTH_SHORT[m] for m in matrix.columns],
        zmin=0,
        zmax=max(85.0, float(matrix.max().max()) if not matrix.isna().all().all() else 85.0),
        text_auto=".0f",
    )
    fig.update_layout(
        template="plotly_white",
        margin={"l": 10, "r": 16, "t": 22, "b": 38},
        height=360,
        font={"color": COLORS["ink"]},
    )
    fig.update_yaxes(title_text="")
    return fig


def build_origin_chart(current: pd.DataFrame, summary_df: pd.DataFrame) -> tuple[go.Figure, str]:
    """Gráfica de composición Turismo Nacional vs. Extranjero."""
    if current.empty or summary_df.empty:
        return empty_figure(), "Sin datos para composición por origen."

    if len(summary_df) == 1:
        dest_name = summary_df.iloc[0]["nombre_destino"]
        monthly_orig = current.groupby("mes", as_index=False).agg(
            turistas_nacionales=("turistas_nacionales", "sum"),
            turistas_extranjeros=("turistas_extranjeros", "sum"),
        ).sort_values("mes")
        monthly_orig["Mes"] = monthly_orig["mes"].map(MONTH_SHORT)
        melted = monthly_orig.melt(
            id_vars=["mes", "Mes"],
            value_vars=["turistas_nacionales", "turistas_extranjeros"],
            var_name="Origen",
            value_name="Turistas",
        )
        melted["Origen"] = melted["Origen"].map(
            {"turistas_nacionales": "Nacional", "turistas_extranjeros": "Extranjero"}
        )
        fig = px.bar(
            melted,
            x="Mes",
            y="Turistas",
            color="Origen",
            barmode="stack",
            color_discrete_map={"Nacional": COLORS["teal"], "Extranjero": COLORS["orange"]},
            labels={"Turistas": "Llegada de turistas", "Mes": "Mes"},
        )
        subtitle = f"Desglose mensual Nacional vs. Extranjero en {dest_name}."
    else:
        ordered = summary_df.sort_values("llegada_turistas", ascending=True).copy()
        melted = ordered.melt(
            id_vars=["nombre_destino", "pct_extranjeros"],
            value_vars=["turistas_nacionales", "turistas_extranjeros"],
            var_name="Origen",
            value_name="Turistas",
        )
        melted["Origen"] = melted["Origen"].map(
            {"turistas_nacionales": "Nacional", "turistas_extranjeros": "Extranjero"}
        )
        fig = px.bar(
            melted,
            x="Turistas",
            y="nombre_destino",
            color="Origen",
            orientation="h",
            barmode="stack",
            color_discrete_map={"Nacional": COLORS["teal"], "Extranjero": COLORS["orange"]},
            custom_data=["pct_extranjeros"],
            labels={"Turistas": "Llegada de turistas", "nombre_destino": "Destino"},
        )
        fig.update_traces(
            hovertemplate=(
                "<b>%{y}</b><br>%{fullData.name}: %{x:,.0f} turistas"
                "<br>Participación extranjera del destino: %{customdata[0]:.1f}%<extra></extra>"
            )
        )
        fig.update_yaxes(title_text="")
        subtitle = "Distribución de llegadas por origen (Nacional vs. Extranjero) según fact_turistas_origen."

    fig.update_layout(
        template="plotly_white",
        margin={"l": 12, "r": 16, "t": 22, "b": 22},
        height=360,
        legend={"orientation": "h", "y": 1.12, "title_text": ""},
        font={"color": COLORS["ink"]},
    )
    fig.update_xaxes(gridcolor=COLORS["line"])
    fig.update_yaxes(gridcolor=COLORS["line"])
    return fig, subtitle


def build_scatter_chart(summary_df: pd.DataFrame) -> go.Figure:
    """Dispersión Derrama económica vs. Ocupación hotelera por destino."""
    if summary_df.empty:
        return empty_figure()

    fig = px.scatter(
        summary_df,
        x="ocupacion_pct",
        y="derrama_mdp",
        size="llegada_turistas",
        size_max=46,
        color="region",
        hover_name="nombre_destino",
        text="nombre_destino" if len(summary_df) <= 9 else None,
        custom_data=[
            "tipo_destino",
            "llegada_turistas",
            "derrama_por_turista",
            "estadia_promedio",
            "pct_extranjeros",
        ],
        labels={
            "ocupacion_pct": "Ocupación hotelera (%)",
            "derrama_mdp": "Derrama económica (MDP)",
            "region": "Región",
        },
        color_discrete_sequence=[
            COLORS["teal"],
            COLORS["orange"],
            COLORS["blue"],
            COLORS["petroleo"],
            "#6c8f4e",
            "#9b6b9e",
            "#c28d2c",
        ],
    )
    fig.update_traces(
        textposition="top center",
        textfont={"size": 10, "color": COLORS["ink"]},
        hovertemplate=(
            "<b>%{hovertext}</b><br>"
            "Tipo: %{customdata[0]}<br>"
            "Ocupación: %{x:.1f}%<br>"
            "Derrama: $%{y:,.1f} MDP<br>"
            "Turistas: %{customdata[1]:,.0f}<br>"
            "Derrama / turista: $%{customdata[2]:,.0f} MXN<br>"
            "Estadía prom.: %{customdata[3]:.2f} noches<br>"
            "Turismo extranjero: %{customdata[4]:.1f}%<extra></extra>"
        ),
    )
    fig.update_layout(
        template="plotly_white",
        margin={"l": 18, "r": 18, "t": 28, "b": 22},
        height=370,
        legend={"orientation": "h", "y": 1.14, "title_text": ""},
        font={"color": COLORS["ink"]},
    )
    fig.update_xaxes(ticksuffix="%", gridcolor=COLORS["line"], rangemode="tozero")
    fig.update_yaxes(gridcolor=COLORS["line"], rangemode="tozero")
    return fig


def build_insight_copy(
    current: pd.DataFrame,
    summary_df: pd.DataFrame,
    cur_kpis: dict,
    prev_kpis: dict | None,
    prev_label: str,
    year: int,
) -> tuple[str, str, str]:
    """Genera diagnóstico y recomendación accionable con base en los datos reales filtrados."""
    if current.empty or summary_df.empty:
        return (
            "No hay registros para esta combinación",
            "Los filtros seleccionados no coinciden con ningún destino o periodo disponible.",
            "Restablece Región, Tipo de destino o Destino turístico a 'Todos' para recuperar resultados.",
        )

    occ = cur_kpis["ocupacion_pct"]
    derrama_mdp = cur_kpis["derrama_mdp"]

    if prev_kpis is not None:
        occ_diff = occ - prev_kpis["ocupacion_pct"]
        derr_yoy = (
            100.0 * (derrama_mdp - prev_kpis["derrama_mdp"]) / prev_kpis["derrama_mdp"]
            if prev_kpis["derrama_mdp"] > 0
            else 0.0
        )
        yoy_sentence = (
            f"Respecto a {prev_label}, la ocupación varió {occ_diff:+.1f} pp "
            f"y la derrama económica {derr_yoy:+.1f}%."
        )
    elif year - 1 == 2023:
        yoy_sentence = (
            "No existe base comparable para 2023 en los datos oficiales "
            "(2023 fue publicado como imágenes sin capa de texto)."
        )
    else:
        yoy_sentence = (
            f"No hay boletín cargado para {year - 1}, por lo que no se calcula variación YoY."
        )

    monthly_occ = current.groupby("mes", as_index=False).agg(
        occ=("cuartos_ocupados", "sum"), disp=("cuartos_disponibles", "sum")
    )
    monthly_occ["pct"] = 100.0 * monthly_occ["occ"] / monthly_occ["disp"].where(monthly_occ["disp"] > 0)
    peak_row = monthly_occ.sort_values("pct", ascending=False).iloc[0]
    low_row = monthly_occ.sort_values("pct", ascending=True).iloc[0]
    peak_month = MONTHS.get(int(peak_row["mes"]), str(peak_row["mes"]))
    low_month = MONTHS.get(int(low_row["mes"]), str(low_row["mes"]))

    if len(summary_df) > 1:
        occ_sorted = summary_df.sort_values("ocupacion_pct", ascending=False)
        leader = occ_sorted.iloc[0]
        laggard = occ_sorted.iloc[-1]
        derr_leader = summary_df.iloc[0]
        share_top_derr = 100.0 * derr_leader["derrama_economica_mxn"] / cur_kpis["derrama_mxn"] if cur_kpis["derrama_mxn"] > 0 else 0.0
        gap_pp = leader["ocupacion_pct"] - laggard["ocupacion_pct"]

        title = f"{leader['nombre_destino']} lidera en ocupación ({leader['ocupacion_pct']:.1f}%)"
        copy = (
            f"En el corte filtrado ({year}), la brecha entre {leader['nombre_destino']} "
            f"y {laggard['nombre_destino']} ({laggard['ocupacion_pct']:.1f}%) alcanza {gap_pp:.1f} pp. "
            f"{derr_leader['nombre_destino']} concentra {share_top_derr:.1f}% de la derrama "
            f"(${derr_leader['derrama_mdp']:,.1f} MDP). {yoy_sentence}"
        )
        action = (
            f"Acción recomendada: aprovechar el pico estacional de {peak_month} ({peak_row['pct']:.1f}%) "
            f"para impulsar paquetes multidestino hacia {laggard['nombre_destino']} y reforzar "
            f"promoción en {low_month} ({low_row['pct']:.1f}%), especialmente para turismo extranjero "
            f"(actualmente {cur_kpis['pct_extranjeros']:.1f}% del total)."
        )
    else:
        dest = summary_df.iloc[0]
        title = f"{dest['nombre_destino']}: pico en {peak_month} ({peak_row['pct']:.1f}%)"
        copy = (
            f"Registra ocupación agregada de {occ:.1f}%, derrama de ${derrama_mdp:,.1f} MDP "
            f"y {dest['pct_extranjeros']:.1f}% de turismo extranjero. {yoy_sentence}"
        )
        action = (
            f"Acción recomendada: proteger tarifa y capacidad en {peak_month} ({peak_row['pct']:.1f}%) "
            f"y diseñar campañas de temporada baja para elevar la ocupación de {low_month} "
            f"({low_row['pct']:.1f}%) y extender la estadía actual ({cur_kpis['estadia_promedio']:.2f} noches)."
        )

    return title, copy, action


def build_kpi_cards(cur: dict, prev: dict | None, prev_label: str, tipo_cifra_label: str) -> list[html.Div]:
    """Construye las 9 tarjetas KPI reales con badges YoY."""
    occ_badge, occ_cls = yoy_delta(cur["ocupacion_pct"], prev["ocupacion_pct"] if prev else None, prev_label, mode="pp")
    derr_badge, derr_cls = yoy_delta(cur["derrama_mxn"], prev["derrama_mxn"] if prev else None, prev_label, mode="pct")
    tur_badge, tur_cls = yoy_delta(cur["llegada_turistas"], prev["llegada_turistas"] if prev else None, prev_label, mode="pct")
    ext_badge, ext_cls = yoy_delta(cur["pct_extranjeros"], prev["pct_extranjeros"] if prev else None, prev_label, mode="pp")
    dpt_badge, dpt_cls = yoy_delta(cur["derrama_por_turista"], prev["derrama_por_turista"] if prev else None, prev_label, mode="pct")
    dpc_badge, dpc_cls = yoy_delta(cur["derrama_por_cuarto"], prev["derrama_por_cuarto"] if prev else None, prev_label, mode="pct")
    disp_badge, disp_cls = yoy_delta(cur["cuartos_disponibles"], prev["cuartos_disponibles"] if prev else None, prev_label, mode="pct")
    ocup_badge, ocup_cls = yoy_delta(cur["cuartos_ocupados"], prev["cuartos_ocupados"] if prev else None, prev_label, mode="pct")
    est_badge, est_cls = yoy_delta(cur["estadia_promedio"], prev["estadia_promedio"] if prev else None, prev_label, mode="nights")

    occ_note = (
        f"Meta ponderada: {cur['meta_ocupacion_pct']:.1f}% ({cur['brecha_meta_pp']:+.1f} pp)"
        if cur["meta_ocupacion_pct"] is not None and cur["brecha_meta_pp"] is not None
        else f"Razón de sumas · Cifra {tipo_cifra_label}"
    )

    return [
        kpi_card("Ocupación hotelera", f"{cur['ocupacion_pct']:.1f}%", occ_note, occ_badge, occ_cls, COLORS["teal"]),
        kpi_card("Derrama económica total", money_mdp(cur["derrama_mdp"], cur["derrama_mxn"]), f"{money_mxn(cur['derrama_mxn'])} · {tipo_cifra_label}", derr_badge, derr_cls, COLORS["petroleo"]),
        kpi_card("Llegada de turistas", f"{cur['llegada_turistas']:,.0f}", "Total acumulado en el periodo", tur_badge, tur_cls, COLORS["blue"]),
        kpi_card("Participación turismo extranjero", f"{cur['pct_extranjeros']:.1f}%", f"Nac: {cur['turistas_nacionales']:,.0f} · Ext: {cur['turistas_extranjeros']:,.0f}", ext_badge, ext_cls, COLORS["orange"]),
        kpi_card("Derrama promedio por turista", money_mxn(cur["derrama_por_turista"]), "Derrama total ÷ llegada de turistas", dpt_badge, dpt_cls, COLORS["teal"]),
        kpi_card("Derrama / cuarto disponible", money_mxn(cur["derrama_por_cuarto"]), "RevPAR turístico estimado (Derrama ÷ disp.)", dpc_badge, dpc_cls, COLORS["blue"]),
        kpi_card("Cuartos disponibles (oferta)", f"{cur['cuartos_disponibles']:,.0f}", "Cuartos-noche ofertados del periodo", disp_badge, disp_cls, COLORS["petroleo"]),
        kpi_card("Cuartos ocupados", f"{cur['cuartos_ocupados']:,.0f}", "Cuartos-noche ocupados del periodo", ocup_badge, ocup_cls, COLORS["teal"]),
        kpi_card("Estadía promedio ponderada", f"{cur['estadia_promedio']:.2f} noches", "Ponderada por llegada de turistas", est_badge, est_cls, COLORS["orange"]),
    ]


app = Dash(__name__, title="Oaxaca | Observatorio Turístico Oficial")
app.index_string = (
    "<!DOCTYPE html><html lang='es'><head>{%metas%}<title>{%title%}</title>{%favicon%}{%css%}</head>"
    "<body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>"
)

FUENTE_OFICIAL = METADATA.get(
    "fuente_oficial",
    "SECTUR Oaxaca - Boletines de Indicadores de la Actividad Turística (DATATUR / SIITE)",
)
FECHA_CORTE = METADATA.get("fecha_corte", "Agosto 2026")
PORTAL_URL = METADATA.get(
    "portal_url",
    "https://www.oaxaca.gob.mx/sectur/informacion-de-interes/estadisticas/",
)
NOTA_COBERTURA = METADATA.get("nota_cobertura", "")

app.layout = html.Div(
    [
        html.Header(
            [
                html.Div(
                    [
                        html.Div("OBSERVATORIO TURÍSTICO · ESTADO DE OAXACA", className="eyebrow"),
                        html.H1("Ocupación hotelera y derrama turística"),
                        html.P(
                            "Monitoreo oficial de los 9 destinos turísticos de Oaxaca con variación interanual, "
                            "estacionalidad mensual y composición nacional vs. extranjera."
                        ),
                        html.Div(
                            [
                                html.Span(f"FUENTE OFICIAL · {FUENTE_OFICIAL}", className="official-tag"),
                                html.Span(f"Corte: {FECHA_CORTE}", className="cutoff-tag"),
                            ],
                            className="source-badges",
                        ),
                    ],
                    className="hero-copy",
                ),
                html.Div(
                    [
                        html.Div("LECTURA DEL TABLERO", className="eyebrow"),
                        html.Div(
                            [
                                html.Span("01", className="step"),
                                html.Span("Panorama"),
                                html.Span("02", className="step"),
                                html.Span("Brecha y Acción"),
                                html.Span("03", className="step"),
                                html.Span("Detalle y Composición"),
                            ],
                            className="storyline",
                        ),
                        html.P(
                            "Todos los porcentajes e indicadores agregados se calculan como razón de sumas "
                            "y comparan meses equivalentes contra el año anterior."
                        ),
                        html.Div(
                            NOTA_COBERTURA
                            or "Fuente de datos configurable vía DASHBOARD_SOURCE (csv | postgres).",
                            className="hero-foot",
                        ),
                    ],
                    className="hero-note",
                ),
            ],
            className="hero",
        ),
        html.Main(
            [
                html.Section(
                    [
                        html.Div(
                            [
                                html.Label("Año", htmlFor="year-filter"),
                                dcc.Dropdown(
                                    id="year-filter",
                                    options=[
                                        {
                                            "label": f"{y} ({YEAR_TIPO_MAP.get(y, 'Oficial')})",
                                            "value": y,
                                        }
                                        for y in YEARS
                                    ],
                                    value=MAX_YEAR,
                                    clearable=False,
                                ),
                            ],
                            className="filter",
                        ),
                        html.Div(
                            [
                                html.Label("Región", htmlFor="region-filter"),
                                dcc.Dropdown(
                                    id="region-filter",
                                    options=[{"label": "Todas las regiones", "value": "Todas"}]
                                    + [{"label": r, "value": r} for r in REGIONS],
                                    value="Todas",
                                    clearable=False,
                                ),
                            ],
                            className="filter",
                        ),
                        html.Div(
                            [
                                html.Label("Tipo de destino", htmlFor="dest-type-filter"),
                                dcc.Dropdown(
                                    id="dest-type-filter",
                                    options=[{"label": "Todos los tipos", "value": "Todos"}]
                                    + [{"label": t, "value": t} for t in DEST_TYPES],
                                    value="Todos",
                                    clearable=False,
                                ),
                            ],
                            className="filter",
                        ),
                        html.Div(
                            [
                                html.Label("Destino turístico", htmlFor="destination-filter"),
                                dcc.Dropdown(
                                    id="destination-filter",
                                    options=[{"label": "Todos los destinos", "value": "Todos"}]
                                    + [{"label": d, "value": d} for d in DESTINATIONS],
                                    value="Todos",
                                    clearable=False,
                                ),
                            ],
                            className="filter",
                        ),
                        html.Div(
                            [
                                html.Label("Métrica principal", htmlFor="metric-selector"),
                                dcc.Dropdown(
                                    id="metric-selector",
                                    options=[
                                        {"label": v["label"], "value": k}
                                        for k, v in METRIC_CONFIG.items()
                                    ],
                                    value="ocupacion",
                                    clearable=False,
                                ),
                            ],
                            className="filter",
                        ),
                    ],
                    className="filter-bar",
                ),
                html.Div(id="kpi-grid", className="kpi-grid"),
                html.Section(
                    [
                        html.Div(
                            [
                                html.Div("01 / PANORAMA", className="eyebrow"),
                                html.H2("Trayectoria mensual frente al año anterior"),
                                html.P(
                                    "Compara la evolución mes a mes de ocupación hotelera, derrama económica "
                                    "o llegada de turistas contra el año inmediato anterior."
                                ),
                            ],
                            className="section-heading",
                        ),
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.H3("Serie temporal mensual", className="panel-title"),
                                        html.P(
                                            "Línea continua: año seleccionado · Línea punteada: año anterior.",
                                            className="panel-subtitle",
                                        ),
                                        dcc.Graph(id="trend-chart", config={"displayModeBar": False}),
                                    ],
                                    className="panel",
                                )
                            ]
                        ),
                    ],
                    className="content-section",
                ),
                html.Section(
                    [
                        html.Div(
                            [
                                html.Div("02 / BRECHA Y ACCIÓN", className="eyebrow"),
                                html.H2("Desempeño por destino y prioridades de acción"),
                                html.P(
                                    "Identifica la concentración turística, el destino líder, el destino rezagado "
                                    "y las palancas de acción según los filtros activos."
                                ),
                            ],
                            className="section-heading",
                        ),
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.H3(
                                            "Comparativa por destino turístico",
                                            className="panel-title",
                                        ),
                                        html.P(
                                            "Ordenado según la métrica principal seleccionada.",
                                            className="panel-subtitle",
                                        ),
                                        dcc.Graph(
                                            id="destination-chart", config={"displayModeBar": False}
                                        ),
                                    ],
                                    className="panel",
                                ),
                                html.Div(
                                    [
                                        html.Div("DIAGNÓSTICO AUTOMÁTICO", className="eyebrow"),
                                        html.H3(id="insight-title"),
                                        html.P(id="insight-copy"),
                                        html.Div(id="insight-action", className="action-callout"),
                                    ],
                                    className="insight-panel",
                                ),
                            ],
                            className="overview-grid",
                        ),
                    ],
                    className="content-section",
                ),
                html.Section(
                    [
                        html.Div(
                            [
                                html.Div("03 / DETALLE Y COMPOSICIÓN", className="eyebrow"),
                                html.H2("Estacionalidad, origen del turista y rentabilidad por destino"),
                                html.P(
                                    "Cruza estacionalidad mensual (Guelaguetza, Semana Santa, Día de Muertos, diciembre), "
                                    "composición nacional vs. extranjera y relación derrama–ocupación."
                                ),
                            ],
                            className="section-heading",
                        ),
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.H3(
                                            "Estacionalidad de ocupación (Destino × Mes)",
                                            className="panel-title",
                                        ),
                                        html.P(
                                            "Porcentaje de ocupación hotelera mensual por destino.",
                                            className="panel-subtitle",
                                        ),
                                        dcc.Graph(
                                            id="heatmap-chart", config={"displayModeBar": False}
                                        ),
                                    ],
                                    className="panel",
                                ),
                                html.Div(
                                    [
                                        html.H3(
                                            "Composición: Turismo Nacional vs. Extranjero",
                                            className="panel-title",
                                        ),
                                        html.P(
                                            id="origin-subtitle",
                                            className="panel-subtitle",
                                        ),
                                        dcc.Graph(
                                            id="origin-chart", config={"displayModeBar": False}
                                        ),
                                    ],
                                    className="panel",
                                ),
                                html.Div(
                                    [
                                        html.H3(
                                            "Derrama económica vs. Ocupación hotelera",
                                            className="panel-title",
                                        ),
                                        html.P(
                                            "El tamaño de cada burbuja representa la llegada total de turistas.",
                                            className="panel-subtitle",
                                        ),
                                        dcc.Graph(
                                            id="scatter-chart", config={"displayModeBar": False}
                                        ),
                                    ],
                                    className="panel panel-wide",
                                ),
                                html.Div(
                                    [
                                        html.Div(
                                            [
                                                html.Div(
                                                    [
                                                        html.H3(
                                                            "Tabla resumen por destino (vista filtrada)",
                                                            className="panel-title",
                                                        ),
                                                        html.P(
                                                            "Todos los indicadores se calculan como razón de sumas para el corte activo.",
                                                            className="panel-subtitle",
                                                        ),
                                                    ]
                                                ),
                                                html.Div(
                                                    [
                                                        html.Button(
                                                            "Descargar CSV filtrado",
                                                            id="download-csv-btn",
                                                            n_clicks=0,
                                                            className="btn-download",
                                                        ),
                                                        dcc.Download(id="download-csv"),
                                                    ]
                                                ),
                                            ],
                                            className="table-header",
                                        ),
                                        dash_table.DataTable(
                                            id="summary-table",
                                            columns=SUMMARY_COLUMNS,
                                            data=[],
                                            sort_action="native",
                                            page_size=12,
                                            style_table={"overflowX": "auto"},
                                            style_cell={
                                                "textAlign": "left",
                                                "padding": "9px 11px",
                                                "fontFamily": "'DM Sans', Arial, sans-serif",
                                                "fontSize": "12px",
                                                "borderBottom": f"1px solid {COLORS['line']}",
                                                "color": COLORS["ink"],
                                            },
                                            style_header={
                                                "backgroundColor": "#f2f6f8",
                                                "fontWeight": "700",
                                                "color": COLORS["petroleo"],
                                                "borderBottom": f"2px solid {COLORS['teal']}",
                                            },
                                            style_data_conditional=[
                                                {
                                                    "if": {"row_index": "odd"},
                                                    "backgroundColor": "#fafcfd",
                                                }
                                            ],
                                        ),
                                    ],
                                    className="panel panel-wide",
                                ),
                            ],
                            className="chart-grid",
                        ),
                    ],
                    className="content-section",
                ),
                html.Footer(
                    [
                        html.Span(
                            [
                                "Fuente oficial: ",
                                html.A(FUENTE_OFICIAL, href=PORTAL_URL, target="_blank"),
                                f" · Corte: {FECHA_CORTE}.",
                            ]
                        ),
                        html.Span(
                            NOTA_COBERTURA
                            or "Modo de carga configurable por .env (DASHBOARD_SOURCE=csv | postgres)."
                        ),
                    ],
                    className="footer",
                ),
            ],
            className="main-content",
        ),
    ],
    className="page",
)


@app.callback(
    Output("kpi-grid", "children"),
    Output("trend-chart", "figure"),
    Output("destination-chart", "figure"),
    Output("heatmap-chart", "figure"),
    Output("origin-chart", "figure"),
    Output("origin-subtitle", "children"),
    Output("scatter-chart", "figure"),
    Output("insight-title", "children"),
    Output("insight-copy", "children"),
    Output("insight-action", "children"),
    Output("summary-table", "data"),
    Input("year-filter", "value"),
    Input("region-filter", "value"),
    Input("dest-type-filter", "value"),
    Input("destination-filter", "value"),
    Input("metric-selector", "value"),
)
def update_dashboard(
    year: int | None,
    region: str | None,
    dest_type: str | None,
    destination: str | None,
    metric: str | None,
):
    selected_year = int(year) if year is not None else MAX_YEAR
    selected_metric = metric if metric in METRIC_CONFIG else "ocupacion"

    base = filter_data(DATA, region=region, dest_type=dest_type, destination=destination)
    current = base[base["anio"] == selected_year]

    if current.empty:
        empty_cards = [
            kpi_card(title, "—", "Sin datos para el filtro", "Sin datos", "neutral", COLORS["muted"])
            for title in [
                "Ocupación hotelera",
                "Derrama económica total",
                "Llegada de turistas",
                "Participación turismo extranjero",
                "Derrama promedio por turista",
                "Derrama / cuarto disponible",
                "Cuartos disponibles (oferta)",
                "Cuartos ocupados",
                "Estadía promedio ponderada",
            ]
        ]
        blank = empty_figure()
        return (
            empty_cards,
            blank,
            blank,
            blank,
            blank,
            "Sin registros para los filtros seleccionados.",
            blank,
            "No hay datos para esta combinación",
            "Los filtros aplicados no devuelven registros disponibles.",
            "Amplía Región, Tipo de destino o Destino turístico para recuperar resultados.",
            [],
        )

    cur_months = sorted(current["mes"].dropna().astype(int).unique().tolist())
    prev = base[(base["anio"] == (selected_year - 1)) & (base["mes"].isin(cur_months))]

    cur_kpis = compute_kpis(current)
    prev_kpis = compute_kpis(prev) if not prev.empty else None
    prev_label = format_period_range(cur_months, selected_year - 1)
    tipo_cifra_vals = current["tipo_cifra"].dropna().unique().tolist()
    tipo_cifra_label = "/".join(tipo_cifra_vals) if tipo_cifra_vals else "Oficial"

    cards = build_kpi_cards(cur_kpis, prev_kpis, prev_label, tipo_cifra_label)
    summary_df = build_destination_summary(current)

    trend_fig = build_trend_chart(base, selected_year, selected_metric)
    dest_fig = build_destination_chart(summary_df, selected_metric, cur_kpis)
    heat_fig = build_heatmap_chart(current)
    origin_fig, origin_sub = build_origin_chart(current, summary_df)
    scatter_fig = build_scatter_chart(summary_df)
    insight_title, insight_copy, insight_action = build_insight_copy(
        current, summary_df, cur_kpis, prev_kpis, prev_label, selected_year
    )
    table_records = format_summary_records(summary_df)

    return (
        cards,
        trend_fig,
        dest_fig,
        heat_fig,
        origin_fig,
        origin_sub,
        scatter_fig,
        insight_title,
        insight_copy,
        insight_action,
        table_records,
    )


@app.callback(
    Output("download-csv", "data"),
    Input("download-csv-btn", "n_clicks"),
    State("year-filter", "value"),
    State("region-filter", "value"),
    State("dest-type-filter", "value"),
    State("destination-filter", "value"),
    prevent_initial_call=True,
)
def download_filtered_csv(
    n_clicks: int,
    year: int | None,
    region: str | None,
    dest_type: str | None,
    destination: str | None,
):
    if not n_clicks:
        return no_update

    selected_year = int(year) if year is not None else MAX_YEAR
    base = filter_data(DATA, region=region, dest_type=dest_type, destination=destination)
    current = base[base["anio"] == selected_year]
    summary_df = build_destination_summary(current)
    if summary_df.empty:
        return no_update

    export_df = summary_df[
        [
            "nombre_destino",
            "region",
            "tipo_destino",
            "ocupacion_pct",
            "derrama_mdp",
            "derrama_economica_mxn",
            "llegada_turistas",
            "turistas_nacionales",
            "turistas_extranjeros",
            "pct_extranjeros",
            "derrama_por_turista",
            "derrama_por_cuarto",
            "cuartos_disponibles",
            "cuartos_ocupados",
            "estadia_promedio",
        ]
    ].rename(
        columns={
            "nombre_destino": "Destino turistico",
            "region": "Region",
            "tipo_destino": "Tipo de destino",
            "ocupacion_pct": "Ocupacion (%)",
            "derrama_mdp": "Derrama economica (MDP)",
            "derrama_economica_mxn": "Derrama economica (MXN)",
            "llegada_turistas": "Llegada de turistas",
            "turistas_nacionales": "Turistas nacionales",
            "turistas_extranjeros": "Turistas extranjeros",
            "pct_extranjeros": "Participacion extranjeros (%)",
            "derrama_por_turista": "Derrama promedio por turista (MXN)",
            "derrama_por_cuarto": "Derrama por cuarto disponible (MXN)",
            "cuartos_disponibles": "Cuartos disponibles",
            "cuartos_ocupados": "Cuartos ocupados",
            "estadia_promedio": "Estadia promedio ponderada (noches)",
        }
    )
    return dcc.send_data_frame(
        export_df.to_csv,
        f"oaxaca_turismo_{selected_year}_resumen.csv",
        index=False,
        encoding="utf-8-sig",
    )


if __name__ == "__main__":
    app.run(
        debug=os.getenv("DASH_DEBUG", "false").lower() == "true",
        host="127.0.0.1",
        port=int(os.getenv("PORT", "8050")),
    )
