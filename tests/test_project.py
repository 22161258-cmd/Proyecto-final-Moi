"""Suite automatizada de auditoría y verificación para el proyecto Oaxaca Turismo.

Cubre:
1. Validaciones y transformaciones del ETL (datos válidos y rechazo de corrupción/rangos/FKs).
2. Integridad de los archivos procesados reales en data/processed/ y metadata_fuentes.json.
3. Esquema SQL (tablas, llaves, constraints y vistas sin duplicación ni YoY engañoso).
4. Cálculo exacto de los 9 KPIs (razón de sumas, nunca promedio de porcentajes) y consistencia con app.py.
5. Callbacks de app.py con filtros normales, por destino, año sin base previa, estado vacío y descarga CSV.
6. Arranque real del servidor Dash y respuesta HTTP 200 en http://127.0.0.1:8050.
"""
from __future__ import annotations

import json
import re
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytest
from dash import no_update

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl import etl  # noqa: E402
import app as dashboard_app  # noqa: E402

PROCESSED = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
SQL_PATH = ROOT / "sql" / "schema.sql"


# ---------------------------------------------------------------------------
# Helpers para pruebas unitarias del ETL
# ---------------------------------------------------------------------------
def _sample_valid_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    destinos = pd.DataFrame(
        [
            {
                "id_destino": "OAX_CENTRO",
                "nombre_destino": "Ciudad de Oaxaca",
                "region": "Valles Centrales",
                "tipo_destino": "Ciudad Patrimonio / Cultural",
                "hoteles_registrados": 340,
                "cuartos_registrados": 7521,
            },
            {
                "id_destino": "HUATULCO",
                "nombre_destino": "Bahías de Huatulco",
                "region": "Costa",
                "tipo_destino": "Centro Integralmente Planeado (Playa)",
                "hoteles_registrados": 158,
                "cuartos_registrados": 5253,
            },
        ]
    )
    actividad = pd.DataFrame(
        [
            {
                "fecha": "2025-01-01",
                "id_destino": "OAX_CENTRO",
                "cuartos_disponibles": 1000,
                "cuartos_ocupados": 800,
                "ocupacion_pct_oficial": 80.0,
                "derrama_economica_mxn": 50_000_000.0,
                "llegada_turistas": 10000,
                "estadia_promedio": 2.0,
                "gasto_promedio_mxn": 2500.0,
                "meta_ocupacion_pct": None,
                "tipo_cifra": "Cierre",
            },
            {
                "fecha": "2025-01-01",
                "id_destino": "HUATULCO",
                "cuartos_disponibles": 200,
                "cuartos_ocupados": 40,
                "ocupacion_pct_oficial": 20.0,
                "derrama_economica_mxn": 10_000_000.0,
                "llegada_turistas": 2000,
                "estadia_promedio": 3.5,
                "gasto_promedio_mxn": 1800.0,
                "meta_ocupacion_pct": None,
                "tipo_cifra": "Cierre",
            },
        ]
    )
    origen = pd.DataFrame(
        [
            {"fecha": "2025-01-01", "id_destino": "OAX_CENTRO", "tipo_turista": "Nacional", "turistas": 8000},
            {"fecha": "2025-01-01", "id_destino": "OAX_CENTRO", "tipo_turista": "Extranjero", "turistas": 2000},
            {"fecha": "2025-01-01", "id_destino": "HUATULCO", "tipo_turista": "Nacional", "turistas": 1500},
            {"fecha": "2025-01-01", "id_destino": "HUATULCO", "tipo_turista": "Extranjero", "turistas": 500},
        ]
    )
    return destinos, actividad, origen


# ---------------------------------------------------------------------------
# 1. Validaciones y transformaciones del ETL
# ---------------------------------------------------------------------------
class TestETLTransformations:
    def test_transform_valid_data_and_deduplication(self):
        dest, act, orig = _sample_valid_frames()
        # Agrega un duplicado controlado para comprobar deduplicación
        act_dup = pd.concat([act, act.iloc[[0]]], ignore_index=True)
        dim_t, dim_d, fact_a, fact_o, quality = etl.transform(dest, act_dup, orig)

        assert len(dim_t) == 1
        assert int(dim_t.iloc[0]["id_fecha"]) == 20250101
        assert dim_t.iloc[0]["nombre_mes"] == "Enero"
        assert int(dim_t.iloc[0]["trimestre"]) == 1
        assert len(dim_d) == 2
        assert len(fact_a) == 2
        assert len(fact_o) == 4
        assert quality["duplicates_removed"]["fact_actividad_turistica"] == 1
        assert quality["reconciled_origin_vs_total_turistas"] is True

    def test_require_columns_rejects_missing(self):
        df = pd.DataFrame({"id_destino": ["OAX_CENTRO"]})
        with pytest.raises(ValueError, match="faltan columnas obligatorias"):
            etl.require_columns(df, {"id_destino", "nombre_destino"}, "destinos.csv")

    @pytest.mark.parametrize("bad_value", [None, "", "   "])
    def test_rejects_null_or_blank_destination_strings(self, bad_value):
        dest, act, orig = _sample_valid_frames()
        dest.loc[0, "nombre_destino"] = bad_value
        with pytest.raises(ValueError, match="destinos.csv"):
            etl.transform(dest, act, orig)

    def test_rejects_orphan_fk_in_actividad(self):
        dest, act, orig = _sample_valid_frames()
        act.loc[0, "id_destino"] = "DESTINO_INEXISTENTE"
        with pytest.raises(ValueError, match="id_destino inexistente"):
            etl.transform(dest, act, orig)

    def test_rejects_orphan_fk_in_origen(self):
        dest, act, orig = _sample_valid_frames()
        orig.loc[0, "id_destino"] = "DESTINO_FANTASMA"
        with pytest.raises(ValueError, match="id_destino inexistente"):
            etl.transform(dest, act, orig)

    @pytest.mark.parametrize(
        "column,bad_val",
        [
            ("ocupacion_pct_oficial", 105.0),
            ("ocupacion_pct_oficial", -1.0),
            ("cuartos_ocupados", 1500),  # mayor que cuartos_disponibles (1000)
            ("cuartos_disponibles", 0),
            ("derrama_economica_mxn", -500.0),
            ("llegada_turistas", -10),
            ("estadia_promedio", 0.0),
            ("gasto_promedio_mxn", -1.0),
            ("meta_ocupacion_pct", 120.0),
            ("tipo_cifra", "Estimado"),
        ],
    )
    def test_rejects_out_of_range_actividad(self, column, bad_val):
        dest, act, orig = _sample_valid_frames()
        act.loc[0, column] = bad_val
        with pytest.raises(ValueError):
            etl.transform(dest, act, orig)

    def test_rejects_invalid_tipo_turista_and_negative_turistas(self):
        dest, act, orig = _sample_valid_frames()
        orig_bad_type = orig.copy()
        orig_bad_type.loc[0, "tipo_turista"] = "Espacial"
        with pytest.raises(ValueError, match="tipo_turista"):
            etl.transform(dest, act, orig_bad_type)

        orig_neg = orig.copy()
        orig_neg.loc[0, "turistas"] = -5
        with pytest.raises(ValueError, match="negativo"):
            etl.transform(dest, act, orig_neg)

    def test_rejects_origin_vs_total_mismatch(self):
        dest, act, orig = _sample_valid_frames()
        orig.loc[0, "turistas"] = 7999  # suma 9999 != 10000
        with pytest.raises(ValueError, match="Inconsistencia entre llegada_turistas"):
            etl.transform(dest, act, orig)

    def test_etl_reproducible_and_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        out1 = tmp_path / "run1"
        out2 = tmp_path / "run2"
        etl.main(raw_dir=RAW, processed_dir=out1)
        etl.main(raw_dir=RAW, processed_dir=out2)

        for fname in (
            "dim_tiempo.csv",
            "dim_destino.csv",
            "fact_actividad_turistica.csv",
            "fact_turistas_origen.csv",
        ):
            assert (out1 / fname).read_bytes() == (out2 / fname).read_bytes()
            assert (out1 / fname).read_bytes() == (PROCESSED / fname).read_bytes()


# ---------------------------------------------------------------------------
# 2. Integridad de data/processed/, metadata_fuentes.json y sql/schema.sql
# ---------------------------------------------------------------------------
class TestProcessedDataAndSchemaIntegrity:
    def test_processed_files_and_metadata_exist(self):
        expected_files = [
            PROCESSED / "dim_tiempo.csv",
            PROCESSED / "dim_destino.csv",
            PROCESSED / "fact_actividad_turistica.csv",
            PROCESSED / "fact_turistas_origen.csv",
            PROCESSED / "metadata_fuentes.json",
            RAW / "FUENTES_OFICIALES.md",
        ]
        for path in expected_files:
            assert path.exists(), f"Falta archivo obligatorio: {path}"
            assert path.stat().st_size > 0, f"Archivo vacío: {path}"

    def test_processed_referential_and_domain_integrity(self):
        dim_t = pd.read_csv(PROCESSED / "dim_tiempo.csv")
        dim_d = pd.read_csv(PROCESSED / "dim_destino.csv")
        fact_a = pd.read_csv(PROCESSED / "fact_actividad_turistica.csv")
        fact_o = pd.read_csv(PROCESSED / "fact_turistas_origen.csv")

        # Llaves primarias únicas
        assert dim_t["id_fecha"].is_unique
        assert dim_d["id_destino"].is_unique
        assert not fact_a.duplicated(["id_fecha", "id_destino"]).any()
        assert not fact_o.duplicated(["id_fecha", "id_destino", "tipo_turista"]).any()

        # Llaves foráneas sin huérfanos
        assert set(fact_a["id_fecha"]).issubset(set(dim_t["id_fecha"]))
        assert set(fact_a["id_destino"]).issubset(set(dim_d["id_destino"]))
        assert set(fact_o["id_fecha"]).issubset(set(dim_t["id_fecha"]))
        assert set(fact_o["id_destino"]).issubset(set(dim_d["id_destino"]))

        # Sin nulos indebidos (únicamente meta_ocupacion_pct puede ser nulo)
        assert dim_t.isna().sum().sum() == 0
        assert dim_d.isna().sum().sum() == 0
        assert fact_o.isna().sum().sum() == 0
        non_meta_cols = [c for c in fact_a.columns if c != "meta_ocupacion_pct"]
        assert fact_a[non_meta_cols].isna().sum().sum() == 0

        # Reglas de rango de negocio
        assert (fact_a["cuartos_disponibles"] > 0).all()
        assert (fact_a["cuartos_ocupados"] >= 0).all()
        assert (fact_a["cuartos_ocupados"] <= fact_a["cuartos_disponibles"]).all()
        assert fact_a["ocupacion_pct_oficial"].between(0, 100).all()
        assert (fact_a["derrama_economica_mxn"] >= 0).all()
        assert (fact_a["llegada_turistas"] >= 0).all()
        assert (fact_a["estadia_promedio"] > 0).all()
        assert (fact_a["gasto_promedio_mxn"] >= 0).all()
        assert set(fact_o["tipo_turista"].unique()) == {"Nacional", "Extranjero"}
        assert (fact_o["turistas"] >= 0).all()

        # Conciliación exacta de turistas totales vs suma por origen
        orig_totals = fact_o.groupby(["id_fecha", "id_destino"], as_index=False)["turistas"].sum()
        merged = fact_a.merge(orig_totals, on=["id_fecha", "id_destino"], how="outer", validate="one_to_one")
        assert (merged["llegada_turistas"] == merged["turistas"]).all()

    def test_metadata_fuentes_official_and_consistent(self):
        meta = json.loads((PROCESSED / "metadata_fuentes.json").read_text(encoding="utf-8"))
        assert "SECTUR" in meta["fuente_oficial"]
        assert "oaxaca.gob.mx" in meta["portal_url"]
        assert len(meta["boletines"]) >= 4
        assert "sintétic" not in json.dumps(meta, ensure_ascii=False).lower()

        qs = meta["quality_summary"]
        assert qs["reconciled_origin_vs_total_turistas"] is True
        assert qs["rows"]["dim_tiempo"] == len(pd.read_csv(PROCESSED / "dim_tiempo.csv"))
        assert qs["rows"]["dim_destino"] == len(pd.read_csv(PROCESSED / "dim_destino.csv"))
        assert qs["rows"]["fact_actividad_turistica"] == len(pd.read_csv(PROCESSED / "fact_actividad_turistica.csv"))
        assert qs["rows"]["fact_turistas_origen"] == len(pd.read_csv(PROCESSED / "fact_turistas_origen.csv"))

    def test_sql_schema_structure_and_views(self):
        sql = SQL_PATH.read_text(encoding="utf-8")
        for table in (
            "dim_tiempo",
            "dim_destino",
            "fact_actividad_turistica",
            "fact_turistas_origen",
            "etl_run_log",
        ):
            assert re.search(rf"CREATE TABLE IF NOT EXISTS\s+{table}\b", sql, re.IGNORECASE)

        assert "CREATE OR REPLACE VIEW vw_kpis_mensuales" in sql
        assert "CREATE OR REPLACE VIEW vw_kpis_anuales_yoy" in sql
        assert "GROUP BY id_fecha, id_destino" in sql  # evita duplicación al cruzar origen
        assert "LAG(" in sql
        assert "prev_anio = anio - 1" in sql
        assert "prev_meses = meses_cubiertos" in sql


# ---------------------------------------------------------------------------
# 3. KPIs (>=7, razón de sumas) y consistencia con app.py
# ---------------------------------------------------------------------------
class TestKPICalculations:
    def test_ratio_of_sums_not_mean_of_percentages(self):
        # Destino A: 800/1000 = 80%, 2000/10000 = 20% ext, estadía 2.0
        # Destino B: 40/200 = 20%, 500/2000 = 25% ext, estadía 3.5
        # Promedio simple de ocupación sería (80+20)/2 = 50.0%, pero razón de sumas es 840/1200 = 70.0%
        df = pd.DataFrame(
            [
                {
                    "cuartos_disponibles": 1000,
                    "cuartos_ocupados": 800,
                    "derrama_economica_mxn": 50_000_000.0,
                    "llegada_turistas": 10000,
                    "turistas_nacionales": 8000,
                    "turistas_extranjeros": 2000,
                    "estadia_promedio": 2.0,
                    "meta_ocupacion_pct": None,
                },
                {
                    "cuartos_disponibles": 200,
                    "cuartos_ocupados": 40,
                    "derrama_economica_mxn": 10_000_000.0,
                    "llegada_turistas": 2000,
                    "turistas_nacionales": 1500,
                    "turistas_extranjeros": 500,
                    "estadia_promedio": 3.5,
                    "meta_ocupacion_pct": None,
                },
            ]
        )
        kpis = dashboard_app.compute_kpis(df)
        assert kpis["ocupacion_pct"] == pytest.approx(70.0, abs=1e-6)
        assert kpis["ocupacion_pct"] != pytest.approx(50.0, abs=1e-2)
        assert kpis["derrama_mxn"] == pytest.approx(60_000_000.0)
        assert kpis["derrama_mdp"] == pytest.approx(60.0)
        assert kpis["llegada_turistas"] == pytest.approx(12000.0)
        assert kpis["pct_extranjeros"] == pytest.approx(100.0 * 2500 / 12000, abs=1e-6)
        assert kpis["derrama_por_turista"] == pytest.approx(5000.0, abs=1e-6)
        assert kpis["derrama_por_cuarto"] == pytest.approx(50_000.0, abs=1e-6)
        assert kpis["cuartos_disponibles"] == pytest.approx(1200.0)
        assert kpis["cuartos_ocupados"] == pytest.approx(840.0)
        assert kpis["estadia_promedio"] == pytest.approx((2.0 * 10000 + 3.5 * 2000) / 12000, abs=1e-6)

    @pytest.mark.parametrize("year", [2025, 2026])
    def test_app_kpis_match_processed_csvs(self, year: int):
        fact_a = pd.read_csv(PROCESSED / "fact_actividad_turistica.csv")
        fact_o = pd.read_csv(PROCESSED / "fact_turistas_origen.csv")
        dim_t = pd.read_csv(PROCESSED / "dim_tiempo.csv")

        ids_year = set(dim_t.loc[dim_t["anio"] == year, "id_fecha"])
        a_y = fact_a[fact_a["id_fecha"].isin(ids_year)]
        o_y = fact_o[fact_o["id_fecha"].isin(ids_year)]

        expected_avail = float(a_y["cuartos_disponibles"].sum())
        expected_occ = float(a_y["cuartos_ocupados"].sum())
        expected_derrama = float(a_y["derrama_economica_mxn"].sum())
        expected_tur = float(a_y["llegada_turistas"].sum())
        expected_ext = float(o_y.loc[o_y["tipo_turista"] == "Extranjero", "turistas"].sum())
        expected_est = float((a_y["estadia_promedio"] * a_y["llegada_turistas"]).sum()) / expected_tur

        app_slice = dashboard_app.DATA[dashboard_app.DATA["anio"] == year]
        kpis = dashboard_app.compute_kpis(app_slice)

        assert kpis["cuartos_disponibles"] == pytest.approx(expected_avail)
        assert kpis["cuartos_ocupados"] == pytest.approx(expected_occ)
        assert kpis["ocupacion_pct"] == pytest.approx(100.0 * expected_occ / expected_avail, abs=1e-6)
        assert kpis["derrama_mxn"] == pytest.approx(expected_derrama)
        assert kpis["llegada_turistas"] == pytest.approx(expected_tur)
        assert kpis["pct_extranjeros"] == pytest.approx(100.0 * expected_ext / expected_tur, abs=1e-6)
        assert kpis["derrama_por_turista"] == pytest.approx(expected_derrama / expected_tur, abs=1e-6)
        assert kpis["derrama_por_cuarto"] == pytest.approx(expected_derrama / expected_avail, abs=1e-6)
        assert kpis["estadia_promedio"] == pytest.approx(expected_est, abs=1e-6)

        # Consistencia con build_destination_summary (sin duplicación al cruzar origen)
        summary = dashboard_app.build_destination_summary(app_slice)
        assert len(summary) == 9
        assert summary["cuartos_disponibles"].sum() == pytest.approx(expected_avail)
        assert summary["derrama_economica_mxn"].sum() == pytest.approx(expected_derrama)
        assert summary["llegada_turistas"].sum() == pytest.approx(expected_tur)


# ---------------------------------------------------------------------------
# 4. Callbacks de app.py y ausencia de referencias sintéticas
# ---------------------------------------------------------------------------
class TestDashboardCallbacks:
    def test_no_synthetic_labels_in_app_source(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8").lower()
        assert "sintético" not in src
        assert "sintetico" not in src
        assert "generate_demo_data" not in src

    @pytest.mark.parametrize("metric", ["ocupacion", "derrama", "turistas"])
    def test_callback_default_filters(self, metric: str):
        res = dashboard_app.update_dashboard(2026, "Todas", "Todos", "Todos", metric)
        cards, trend, dest, heat, orig, orig_sub, scatter, title, copy, action, table = res
        assert len(cards) == 9
        for fig in (trend, dest, heat, orig, scatter):
            assert isinstance(fig, go.Figure)
            assert len(fig.data) >= 1
        assert isinstance(orig_sub, str) and orig_sub
        assert isinstance(title, str) and title
        assert isinstance(copy, str) and copy
        assert isinstance(action, str) and action
        assert len(table) == 9

    def test_callback_single_destination_and_yoy(self):
        res = dashboard_app.update_dashboard(2025, "Todas", "Todos", "Ciudad de Oaxaca", "ocupacion")
        cards, trend, dest, heat, orig, orig_sub, scatter, title, copy, action, table = res
        assert len(cards) == 9
        assert "Ciudad de Oaxaca" in orig_sub
        assert "Ciudad de Oaxaca" in title
        assert "2024" in copy
        assert len(table) == 1
        assert table[0]["nombre_destino"] == "Ciudad de Oaxaca"

    def test_callback_year_without_previous_base(self):
        # 2022: no tiene boletín 2021 y NO debe mencionar erróneamente 2023
        res_2022 = dashboard_app.update_dashboard(2022, "Todas", "Todos", "Todos", "ocupacion")
        cards_22, _, _, _, _, _, _, _, copy_22, _, table_22 = res_2022
        assert len(cards_22) == 9
        assert len(table_22) == 9
        assert "2021" in copy_22
        assert "2023" not in copy_22

        # 2024: no tiene boletín 2023 y explica que 2023 fue publicado como imágenes sin capa de texto
        res_2024 = dashboard_app.update_dashboard(2024, "Todas", "Todos", "Todos", "ocupacion")
        cards_24, _, _, _, _, _, _, _, copy_24, _, table_24 = res_2024
        assert len(cards_24) == 9
        assert len(table_24) == 9
        assert "2023" in copy_24

    def test_callback_empty_filter_state_no_exception(self):
        res = dashboard_app.update_dashboard(2026, "Costa", "Todos", "Ciudad de Oaxaca", "ocupacion")
        cards, trend, dest, heat, orig, orig_sub, scatter, title, copy, action, table = res
        assert len(cards) == 9
        for fig in (trend, dest, heat, orig, scatter):
            assert isinstance(fig, go.Figure)
        assert table == []
        assert "No hay datos" in title

    def test_download_csv_callback(self):
        assert dashboard_app.download_filtered_csv(0, 2026, "Todas", "Todos", "Todos") is no_update
        empty_dl = dashboard_app.download_filtered_csv(1, 2026, "Costa", "Todos", "Ciudad de Oaxaca")
        assert empty_dl is no_update

        dl = dashboard_app.download_filtered_csv(1, 2026, "Todas", "Todos", "Todos")
        assert isinstance(dl, dict)
        assert dl["filename"] == "oaxaca_turismo_2026_resumen.csv"
        assert "Ciudad de Oaxaca" in dl["content"]
        assert "Turistas extranjeros" in dl["content"]


# ---------------------------------------------------------------------------
# 5. Validación de carga del servidor Dash (HTTP 200 en http://127.0.0.1:8050)
# ---------------------------------------------------------------------------
class TestDashServerLive:
    def test_dash_server_responds_http_200(self):
        from werkzeug.serving import make_server

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            in_use = sock.connect_ex(("127.0.0.1", 8050)) == 0
        assert not in_use, "El puerto 8050 ya está ocupado antes de iniciar la prueba del servidor."

        server = make_server("127.0.0.1", 8050, dashboard_app.app.server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            ready = False
            deadline = time.time() + 10.0
            while time.time() < deadline:
                try:
                    with opener.open("http://127.0.0.1:8050/", timeout=2) as resp:
                        if resp.status == 200:
                            html_body = resp.read().decode("utf-8", errors="ignore")
                            assert "Oaxaca" in html_body
                            ready = True
                            break
                except Exception:
                    time.sleep(0.2)

            assert ready, "El servidor Dash no respondió HTTP 200 en http://127.0.0.1:8050/ dentro del tiempo límite."

            with opener.open("http://127.0.0.1:8050/_dash-layout", timeout=5) as resp_layout:
                assert resp_layout.status == 200
                layout_json = json.loads(resp_layout.read().decode("utf-8"))
                assert "props" in layout_json

            with opener.open("http://127.0.0.1:8050/assets/style.css", timeout=5) as resp_css:
                assert resp_css.status == 200
                assert "--teal" in resp_css.read().decode("utf-8", errors="ignore")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


# ---------------------------------------------------------------------------
# 6. Consistencia documental
# ---------------------------------------------------------------------------
class TestDocumentationConsistency:
    def test_required_docs_exist_and_have_no_obsolete_references(self):
        doc_files = [
            ROOT / "README.md",
            ROOT / "docs" / "seccion-5-1.md",
            ROOT / "docs" / "seccion-5-2.md",
            ROOT / "docs" / "seccion-5-3.md",
            ROOT / "docs" / "seccion-5-5.md",
            ROOT / "docs" / "reporte-completo.md",
        ]
        obsolete_tokens = ("dim_hotel", "fact_ocupacion_diaria", "vw_kpis_diarios", "generate_demo_data")
        for doc in doc_files:
            assert doc.exists() and doc.stat().st_size > 500, f"Documento faltante o incompleto: {doc}"
            text = doc.read_text(encoding="utf-8")
            for token in obsolete_tokens:
                assert token not in text, f"Referencia obsoleta '{token}' encontrada en {doc.name}"

        reporte = (ROOT / "docs" / "reporte-completo.md").read_text(encoding="utf-8")
        for section in ("5.1.", "5.2.", "5.3.", "5.5.", "5.5.1.", "5.5.2."):
            assert section in reporte, f"Falta sección {section} en reporte-completo.md"
