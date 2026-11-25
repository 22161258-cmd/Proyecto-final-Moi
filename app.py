"""Dashboard interactivo de ocupación hotelera y turismo para Oaxaca."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
PROCESSED = ROOT / "data" / "processed"
MONTHS = {1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"}
MONTH_ORDER = list(MONTHS.values())
COLORS = {"ink": "#18212f", "muted": "#6d7a8b", "line": "#e6ebf1", "teal": "#127c78", "orange": "#d27845", "blue": "#4979b8"}


def load_csv_data() -> pd.DataFrame:
    required = [PROCESSED / name for name in ("dim_hotel.csv", "dim_tiempo.csv", "fact_ocupacion_diaria.csv", "fact_turistas.csv")]
    missing = [p.name for p in required if not p.exists()]
    if missing:
        raise RuntimeError("Faltan datos transformados: " + ", ".join(missing) + ". Ejecuta primero scripts/generate_demo_data.py y etl/etl.py.")
    hotels, times, occupancy, tourists = [pd.read_csv(p) for p in required]
    times["fecha"] = pd.to_datetime(times["id_fecha"].astype(str), format="%Y%m%d")
    tourist_totals = tourists.groupby(["id_fecha", "id_hotel"], as_index=False)["turistas_hospedados"].sum()
    data = occupancy.merge(hotels, on="id_hotel", validate="many_to_one")
    data = data.merge(times[["id_fecha", "fecha", "anio", "mes", "nombre_mes"]], on="id_fecha", validate="many_to_one")
    data = data.merge(tourist_totals, on=["id_fecha", "id_hotel"], how="left", validate="one_to_one")
    data["turistas_hospedados"] = data["turistas_hospedados"].fillna(0)
    return data


def load_postgres_data() -> pd.DataFrame:
    from sqlalchemy import create_engine, text

    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DASHBOARD_SOURCE=postgres requiere DATABASE_URL en el entorno.")
    query = text("""
        SELECT f.id_fecha, t.fecha, t.anio, t.mes, t.nombre_mes, f.id_hotel,
               h.nombre_hotel, h.zona_turistica, h.categoria_hotel, h.num_habitaciones,
               f.habitaciones_disponibles, f.habitaciones_ocupadas, f.ingreso_hospedaje,
               f.reservaciones, f.cancelaciones, f.meta_ocupacion_pct,
               COALESCE(x.turistas_hospedados, 0) AS turistas_hospedados
        FROM fact_ocupacion_diaria f
        JOIN dim_tiempo t USING (id_fecha)
        JOIN dim_hotel h USING (id_hotel)
        LEFT JOIN (
            SELECT id_fecha, id_hotel, SUM(turistas_hospedados) AS turistas_hospedados
            FROM fact_turistas GROUP BY id_fecha, id_hotel
        ) x USING (id_fecha, id_hotel)
    """)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            data = pd.read_sql(query, connection)
    finally:
        engine.dispose()
    data["fecha"] = pd.to_datetime(data["fecha"])
    return data


def load_data() -> pd.DataFrame:
    if os.getenv("DASHBOARD_SOURCE", "csv").strip().lower() == "postgres":
        return load_postgres_data()
    return load_csv_data()


DATA = load_data()
YEARS = sorted(DATA["anio"].dropna().astype(int).unique().tolist())
ZONES = sorted(DATA["zona_turistica"].dropna().unique().tolist())
MAX_YEAR = max(YEARS)
MONTH_LABELS = DATA[["mes", "nombre_mes"]].drop_duplicates().set_index("mes")["nombre_mes"].to_dict()


def money(value: float) -> str:
    return f"${value:,.0f} MXN"


def card(label: str, value: str, note: str, accent: str = COLORS["teal"]) -> html.Div:
    return html.Div([
        html.Div(label, className="kpi-label"),
        html.Div(value, className="kpi-value", style={"color": accent}),
        html.Div(note, className="kpi-note"),
    ], className="kpi-card")


def empty_figure(message: str = "Sin registros para los filtros seleccionados") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font={"color": COLORS["muted"], "size": 14})
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(template="plotly_white", margin={"l": 15, "r": 15, "t": 12, "b": 12}, height=320)
    return fig


app = Dash(__name__, title="Oaxaca | Ocupación y derrama turística")
app.layout = html.Div([
    html.Header([
        html.Div([html.Div("OBSERVATORIO TURÍSTICO · OAXACA", className="eyebrow"),
                  html.H1("Ocupación hotelera y derrama turística"),
                  html.P("Una lectura rápida para anticipar brechas, comparar temporadas y enfocar acciones."),
                  html.Div("PROTOTIPO ACADÉMICO · DATOS SINTÉTICOS", className="demo-tag")], className="hero-copy"),
        html.Div([html.Div("LECTURA DEL TABLERO", className="eyebrow"),
                  html.Div([html.Span("01", className="step"), html.Span("Panorama"), html.Span("02", className="step"), html.Span("Brecha"), html.Span("03", className="step"), html.Span("Acción")], className="storyline"),
                  html.P("Compara los resultados con la meta y con el mismo periodo del año anterior."),
                  html.Div("Actualización demostrativa · 2024–2026", className="hero-foot")], className="hero-note"),
    ], className="hero"),
    html.Main([
        html.Section([
            html.Div([html.Label("Año", htmlFor="year-filter"), dcc.Dropdown(id="year-filter", options=[{"label": str(y), "value": y} for y in YEARS], value=MAX_YEAR, clearable=False)], className="filter"),
            html.Div([html.Label("Zona turística", htmlFor="zone-filter"), dcc.Dropdown(id="zone-filter", options=[{"label":"Todas las zonas","value":"Todas"}] + [{"label":z,"value":z} for z in ZONES], value="Todas", clearable=False)], className="filter"),
            html.Div([html.Label("Categoría hotelera", htmlFor="category-filter"), dcc.Dropdown(id="category-filter", options=[{"label":"Todas las categorías","value":"Todas"}] + [{"label":f"{c} estrellas","value":c} for c in sorted(DATA["categoria_hotel"].unique())], value="Todas", clearable=False)], className="filter"),
            html.Div("Los indicadores se recalculan con los filtros seleccionados.", className="filter-hint"),
        ], className="filter-bar"),
        html.Div(id="kpi-grid", className="kpi-grid"),
        html.Section([
            html.Div([html.Div("01 / PANORAMA", className="eyebrow"), html.H2("La ocupación frente a la meta"), html.P("Compara cada mes con el mismo mes del año anterior.")], className="section-heading"),
            html.Div([html.Div([dcc.Graph(id="trend-chart", config={"displayModeBar":False})], className="panel panel-wide"),
                      html.Div([html.Div("BRECHA ACTUAL", className="eyebrow"), html.H3(id="insight-title"), html.P(id="insight-copy"), html.Div(id="insight-action", className="action-callout")], className="insight-panel")], className="overview-grid"),
        ], className="content-section"),
        html.Section([
            html.Div([html.Div("02 / DETALLE", className="eyebrow"), html.H2("Dónde se concentra la oportunidad"), html.P("Cruza zona, mes y desempeño de cada hotel para detectar patrones.")], className="section-heading"),
            html.Div([html.Div([dcc.Graph(id="zone-chart", config={"displayModeBar":False})], className="panel"),
                      html.Div([dcc.Graph(id="heatmap-chart", config={"displayModeBar":False})], className="panel"),
                      html.Div([dcc.Graph(id="scatter-chart", config={"displayModeBar":False})], className="panel panel-wide")], className="chart-grid"),
        ], className="content-section"),
        html.Footer([html.Span("Fuente: conjunto sintético reproducible incluido en el prototipo."), html.Span("Los resultados no son estadísticas oficiales ni corresponden a establecimientos reales.")], className="footer"),
    ], className="main-content"),
], className="page")


@app.callback(
    Output("kpi-grid", "children"), Output("trend-chart", "figure"),
    Output("zone-chart", "figure"), Output("heatmap-chart", "figure"),
    Output("scatter-chart", "figure"), Output("insight-title", "children"),
    Output("insight-copy", "children"), Output("insight-action", "children"),
    Input("year-filter", "value"), Input("zone-filter", "value"), Input("category-filter", "value"),
)
def update_dashboard(year: int, zone: str, category: int | str):
    base = DATA.copy()
    if zone != "Todas":
        base = base[base["zona_turistica"] == zone]
    if category != "Todas":
        base = base[base["categoria_hotel"] == category]
    current = base[base["anio"] == year]
    if current.empty:
        cards = [card(label, "—", "Sin datos para el filtro", COLORS["muted"]) for label in ["Ocupación", "ADR", "RevPAR", "Cancelaciones", "Turistas hospedados", "Ingreso hospedaje", "Noches ocupadas", "Brecha contra meta"]]
        blank = empty_figure()
        return cards, blank, blank, blank, blank, "No hay datos para esta selección", "Prueba otra combinación de filtros.", "Amplía la zona o la categoría para recuperar resultados."

    available = current["habitaciones_disponibles"].sum()
    occupied = current["habitaciones_ocupadas"].sum()
    revenue = current["ingreso_hospedaje"].sum()
    reservations = current["reservaciones"].sum()
    cancellations = current["cancelaciones"].sum()
    occupancy_pct = 100 * occupied / available if available else 0
    adr = revenue / occupied if occupied else 0
    revpar = revenue / available if available else 0
    cancel_pct = 100 * cancellations / reservations if reservations else 0
    target = (current["habitaciones_disponibles"] * current["meta_ocupacion_pct"]).sum() / available if available else 0
    gap = occupancy_pct - target
    tourists = current["turistas_hospedados"].sum()
    cards = [
        card("Ocupación hotelera", f"{occupancy_pct:.1f}%", f"Meta ponderada: {target:.1f}%", COLORS["teal"] if gap >= 0 else COLORS["orange"]),
        card("Tarifa promedio diaria · ADR", money(adr), "Ingreso ÷ noches ocupadas", COLORS["blue"]),
        card("Ingreso por habitación · RevPAR", money(revpar), "Ingreso ÷ noches disponibles", COLORS["blue"]),
        card("Tasa de cancelación", f"{cancel_pct:.1f}%", f"{cancellations:,.0f} de {reservations:,.0f} reservaciones", COLORS["orange"]),
        card("Turistas hospedados", f"{tourists:,.0f}", "Suma del periodo seleccionado"),
        card("Ingreso por hospedaje", money(revenue), "MXN · suma del periodo"),
        card("Noches de habitación ocupadas", f"{occupied:,.0f}", "Habitaciones ocupadas por día", COLORS["blue"]),
        card("Brecha contra la meta", f"{gap:+.1f} pp", "Ocupación menos meta", COLORS["teal"] if gap >= 0 else COLORS["orange"]),
    ]

    trend_source = base[base["anio"].isin([year - 1, year])].copy()
    monthly = trend_source.groupby(["anio", "mes"], as_index=False).agg(occupied=("habitaciones_ocupadas", "sum"), available=("habitaciones_disponibles", "sum"))
    target_month = trend_source.assign(target_rooms=trend_source["habitaciones_disponibles"] * trend_source["meta_ocupacion_pct"]).groupby(["anio", "mes"], as_index=False).agg(target_rooms=("target_rooms", "sum"), target_available=("habitaciones_disponibles", "sum"))
    monthly = monthly.merge(target_month, on=["anio", "mes"])
    monthly["Ocupación"] = 100 * monthly["occupied"] / monthly["available"]
    monthly["Meta"] = monthly["target_rooms"] / monthly["target_available"]
    monthly["Periodo"] = monthly["anio"].astype(str)
    monthly["Mes"] = monthly["mes"].map(MONTH_LABELS)
    trend = px.line(monthly, x="Mes", y="Ocupación", color="Periodo", markers=True,
                    category_orders={"Mes": MONTH_ORDER}, color_discrete_sequence=[COLORS["orange"], COLORS["teal"]],
                    labels={"Ocupación":"Ocupación (%)", "Periodo":"Año"})
    target_line = monthly[monthly["anio"] == year].sort_values("mes")
    trend.add_trace(go.Scatter(x=target_line["Mes"], y=target_line["Meta"], name="Meta", mode="lines", line={"color":"#8b95a5","dash":"dash","width":2}))
    trend.update_layout(template="plotly_white", margin={"l":20,"r":15,"t":18,"b":20}, height=350, legend={"orientation":"h","y":1.12}, hovermode="x unified", font={"color":COLORS["ink"]})
    trend.update_yaxes(ticksuffix="%", gridcolor=COLORS["line"], rangemode="tozero")

    zones = current.groupby("zona_turistica", as_index=False).agg(occupied=("habitaciones_ocupadas","sum"), available=("habitaciones_disponibles","sum"))
    zones["Ocupación"] = 100 * zones["occupied"] / zones["available"]
    zones = zones.sort_values("Ocupación")
    zone_fig = px.bar(zones, x="Ocupación", y="zona_turistica", orientation="h", text=zones["Ocupación"].map(lambda x:f"{x:.1f}%"), color="Ocupación", color_continuous_scale=["#e9a17a", "#f4d8be", "#7fc3b3"], labels={"zona_turistica":"Zona","Ocupación":"Ocupación (%)"})
    zone_fig.update_layout(template="plotly_white", margin={"l":10,"r":10,"t":35,"b":20}, height=330, coloraxis_showscale=False, font={"color":COLORS["ink"]})
    zone_fig.update_xaxes(range=[0,100], ticksuffix="%", gridcolor=COLORS["line"])
    zone_fig.update_traces(textposition="outside", cliponaxis=False)

    heat = current.groupby(["zona_turistica","mes"], as_index=False).agg(occupied=("habitaciones_ocupadas","sum"), available=("habitaciones_disponibles","sum"))
    heat["Ocupación"] = 100 * heat["occupied"] / heat["available"]
    matrix = heat.pivot(index="zona_turistica", columns="mes", values="Ocupación").reindex(columns=range(1,13))
    heat_fig = px.imshow(matrix, aspect="auto", color_continuous_scale=["#f4d8be","#e79b72","#127c78"], labels={"x":"Mes","y":"Zona","color":"Ocupación (%)"}, x=[MONTHS[m] for m in matrix.columns], zmin=0, zmax=100)
    heat_fig.update_layout(template="plotly_white", margin={"l":10,"r":15,"t":35,"b":65}, height=330, font={"color":COLORS["ink"]})
    heat_fig.update_xaxes(tickangle=-35)

    hotel = current.groupby(["id_hotel","nombre_hotel","zona_turistica","categoria_hotel"], as_index=False).agg(occupied=("habitaciones_ocupadas","sum"), available=("habitaciones_disponibles","sum"), revenue=("ingreso_hospedaje","sum"))
    hotel["Ocupación"] = 100 * hotel["occupied"] / hotel["available"]
    hotel["ADR"] = hotel["revenue"] / hotel["occupied"].replace(0, pd.NA)
    scatter = px.scatter(hotel, x="ADR", y="Ocupación", size="revenue", color="zona_turistica", hover_name="nombre_hotel", hover_data={"categoria_hotel":True,"revenue":":,.0f","ADR":":,.0f","Ocupación":":.1f"}, labels={"ADR":"ADR (MXN)","Ocupación":"Ocupación (%)","zona_turistica":"Zona"}, color_discrete_sequence=px.colors.qualitative.Safe)
    scatter.update_layout(template="plotly_white", margin={"l":20,"r":15,"t":30,"b":20}, height=340, legend={"orientation":"h","y":1.16}, font={"color":COLORS["ink"]})
    scatter.update_yaxes(range=[0,100], ticksuffix="%", gridcolor=COLORS["line"])

    below = zones.iloc[0]
    if gap < 0:
        insight_title = f"{below['zona_turistica']} presenta la ocupación más baja"
        insight_copy = f"La ocupación filtrada es {occupancy_pct:.1f}%, {abs(gap):.1f} puntos porcentuales por debajo de la meta ponderada. La zona de menor ocupación registra {below['Ocupación']:.1f}%."
        action = "Acción sugerida: revisar disponibilidad y cancelaciones en la zona rezagada; priorizar una promoción segmentada antes del siguiente periodo de alta demanda."
    else:
        insight_title = "El resultado está por encima de la meta"
        insight_copy = f"La ocupación filtrada supera la meta ponderada por {gap:.1f} puntos. La zona de menor ocupación es {below['zona_turistica']} ({below['Ocupación']:.1f}%)."
        action = "Acción sugerida: sostener tarifas en los periodos fuertes y enfocar paquetes o alianzas en meses y zonas con menor ocupación."
    return cards, trend, zone_fig, heat_fig, scatter, insight_title, insight_copy, action


app.index_string = """<!DOCTYPE html><html lang="es"><head>{%metas%}<title>{%title%}</title>{%favicon%}{%css%}<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
*{box-sizing:border-box}body{margin:0;background:#f5f7f8;color:#18212f;font-family:'DM Sans',Arial,sans-serif}.page{max-width:1500px;margin:auto}.hero{padding:42px clamp(24px,5vw,76px) 36px;background:#172d3b;color:#fff;display:grid;grid-template-columns:1.6fr 1fr;gap:40px;position:relative;overflow:hidden}.hero:after{content:'';position:absolute;width:400px;height:400px;border:1px solid #ffffff18;border-radius:50%;right:24%;top:-290px;box-shadow:0 0 0 45px #ffffff09,0 0 0 90px #ffffff06}.hero-copy,.hero-note{position:relative;z-index:1}.eyebrow{font-size:10px;font-weight:700;letter-spacing:.14em;color:#98c6bd}.hero h1{font:800 clamp(28px,3.5vw,46px)/1.08 Manrope,sans-serif;margin:13px 0 12px;max-width:760px}.hero p{color:#c4d0d6;margin:0;line-height:1.55;max-width:700px}.demo-tag{display:inline-block;margin-top:20px;padding:7px 10px;border:1px solid #e2a572;color:#f3c399;font-size:10px;font-weight:700;letter-spacing:.08em;border-radius:4px}.hero-note{align-self:center;border-left:1px solid #ffffff35;padding-left:28px}.storyline{display:flex;align-items:center;gap:8px;margin:14px 0;color:#f3f5f6;font-size:12px}.step{color:#e7a574;font:700 12px Manrope}.hero-foot{font-size:11px;color:#9fb1ba;margin-top:16px}.main-content{padding:24px clamp(18px,5vw,76px) 36px}.filter-bar{display:flex;align-items:end;gap:14px;background:#fff;border:1px solid #e6ebf1;padding:14px 16px;border-radius:9px}.filter{min-width:190px;flex:1}.filter label{display:block;font-size:11px;font-weight:700;color:#536174;margin:0 0 6px}.filter-hint{font-size:11px;color:#7c8796;max-width:180px;padding-bottom:8px}.Select-control,.Select-menu-outer{border-color:#dce3e9!important}.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0 32px}.kpi-card{background:white;padding:16px 18px;border:1px solid #e6ebf1;border-radius:8px;min-height:112px;box-shadow:0 2px 5px #152d3b06}.kpi-label{font-size:11px;font-weight:600;color:#687586;min-height:30px}.kpi-value{font:800 clamp(20px,2.2vw,28px) Manrope,sans-serif;margin:3px 0 5px}.kpi-note{font-size:10px;color:#8792a0}.content-section{margin:30px 0 38px}.section-heading{margin-bottom:14px}.section-heading h2{font:700 23px Manrope,sans-serif;margin:6px 0;color:#1b2934}.section-heading p{font-size:13px;color:#738090;margin:0}.overview-grid{display:grid;grid-template-columns:2.1fr 1fr;gap:14px}.panel,.insight-panel{background:#fff;border:1px solid #e6ebf1;border-radius:8px;padding:10px 12px;min-width:0}.insight-panel{padding:24px 22px;background:#edf4f2;border-color:#d9e9e4}.insight-panel h3{font:700 19px/1.3 Manrope;margin:9px 0;color:#1b353d}.insight-panel p{font-size:13px;color:#586978;line-height:1.65}.action-callout{border-left:3px solid #d27845;padding:9px 0 9px 12px;margin-top:18px;font-size:12px;line-height:1.6;color:#364a53}.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.panel-wide{grid-column:span 2}.footer{border-top:1px solid #dce3e9;padding:16px 0 0;display:flex;justify-content:space-between;gap:20px;color:#788391;font-size:10px}.js-plotly-plot .plotly .modebar{display:none}
@media(max-width:900px){.hero{grid-template-columns:1fr}.hero-note{border-left:0;border-top:1px solid #ffffff35;padding:18px 0 0}.filter-bar{flex-wrap:wrap}.filter{min-width:150px}.filter-hint{max-width:100%;width:100%}.kpi-grid{grid-template-columns:repeat(2,1fr)}.overview-grid{grid-template-columns:1fr}.panel-wide{grid-column:span 1}.chart-grid{grid-template-columns:1fr}.footer{flex-direction:column}}@media(max-width:520px){.hero{padding:30px 20px}.main-content{padding:18px 14px}.kpi-grid{gap:8px}.kpi-card{padding:13px;min-height:112px}.kpi-label{min-height:38px}.filter{min-width:100%;flex-basis:100%}}
</style></head><body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>"""


if __name__ == "__main__":
    app.run(debug=os.getenv("DASH_DEBUG", "false").lower() == "true", host="127.0.0.1", port=int(os.getenv("PORT", "8050")))
