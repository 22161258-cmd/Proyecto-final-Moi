"""ETL oficial de ocupación hotelera y derrama turística en Oaxaca.

Lee los CSV oficiales extraídos en data/raw/, ejecuta validaciones de esquema,
tipos, rangos, llaves foráneas y duplicados, genera los archivos analíticos
limpios en data/processed/ (incluyendo metadata_fuentes.json) y carga de forma
idempotente en PostgreSQL cuando DATABASE_URL está configurada.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
load_dotenv(ROOT / ".env")

MONTH_NAMES_ES = {
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

REQUIRED_DEST_COLS = {
    "id_destino",
    "nombre_destino",
    "region",
    "tipo_destino",
    "hoteles_registrados",
    "cuartos_registrados",
}
REQUIRED_ACT_COLS = {
    "fecha",
    "id_destino",
    "cuartos_disponibles",
    "cuartos_ocupados",
    "ocupacion_pct_oficial",
    "derrama_economica_mxn",
    "llegada_turistas",
    "estadia_promedio",
    "gasto_promedio_mxn",
    "meta_ocupacion_pct",
    "tipo_cifra",
}
REQUIRED_ORIG_COLS = {"fecha", "id_destino", "tipo_turista", "turistas"}


def configure_logger() -> logging.Logger:
    logger = logging.getLogger("oaxaca_etl")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


LOGGER = configure_logger()


def require_columns(frame: pd.DataFrame, columns: set[str], source: str) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{source}: faltan columnas obligatorias: {', '.join(sorted(missing))}")


def read_inputs(raw_dir: Path = RAW) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    destinos = pd.read_csv(raw_dir / "destinos.csv")
    actividad = pd.read_csv(raw_dir / "actividad_turistica_mensual.csv")
    origen = pd.read_csv(raw_dir / "turistas_origen_mensual.csv")

    require_columns(destinos, REQUIRED_DEST_COLS, "destinos.csv")
    require_columns(actividad, REQUIRED_ACT_COLS, "actividad_turistica_mensual.csv")
    require_columns(origen, REQUIRED_ORIG_COLS, "turistas_origen_mensual.csv")
    LOGGER.info(
        "Entradas leídas: destinos=%d, actividad=%d, origen=%d",
        len(destinos),
        len(actividad),
        len(origen),
    )
    return destinos, actividad, origen


def _ensure_integers(series: pd.Series, name: str) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.isna().any() or (numeric % 1 != 0).any():
        raise ValueError(f"La columna '{name}' contiene valores no enteros o nulos.")
    return numeric.astype(int)


def _ensure_nonempty_strings(frame: pd.DataFrame, columns: tuple[str, ...], source: str) -> None:
    for col in columns:
        if frame[col].isna().any():
            raise ValueError(f"{source} contiene valores nulos en '{col}'.")
        cleaned = frame[col].astype(str).str.strip()
        if (cleaned == "").any():
            raise ValueError(f"{source} contiene cadenas vacías en '{col}'.")
        frame[col] = cleaned


def transform(
    destinos: pd.DataFrame,
    actividad: pd.DataFrame,
    origen: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    quality: dict[str, Any] = {}

    # 1. Validación de dim_destino
    dest_df = destinos.copy()
    _ensure_nonempty_strings(dest_df, ("id_destino", "nombre_destino", "region", "tipo_destino"), "destinos.csv")

    dup_dest = int(dest_df.duplicated("id_destino").sum())
    if dup_dest:
        LOGGER.warning("Se eliminaron %d filas duplicadas en destinos.csv.", dup_dest)
        dest_df = dest_df.drop_duplicates("id_destino", keep="last")
    dest_df["hoteles_registrados"] = _ensure_integers(dest_df["hoteles_registrados"], "hoteles_registrados")
    dest_df["cuartos_registrados"] = _ensure_integers(dest_df["cuartos_registrados"], "cuartos_registrados")
    if (dest_df["hoteles_registrados"] <= 0).any() or (dest_df["cuartos_registrados"] <= 0).any():
        raise ValueError("hoteles_registrados y cuartos_registrados deben ser positivos en destinos.csv.")
    dest_df = dest_df[
        ["id_destino", "nombre_destino", "region", "tipo_destino", "hoteles_registrados", "cuartos_registrados"]
    ].reset_index(drop=True)

    # 2. Validación de fact_actividad_turistica
    act = actividad.copy()
    _ensure_nonempty_strings(act, ("id_destino", "tipo_cifra"), "actividad_turistica_mensual.csv")
    act["fecha"] = pd.to_datetime(act["fecha"], format="%Y-%m-%d", errors="coerce").dt.normalize()
    if act["fecha"].isna().any():
        raise ValueError("actividad_turistica_mensual.csv contiene fechas inválidas o nulas.")

    for col in ("cuartos_disponibles", "cuartos_ocupados", "llegada_turistas"):
        act[col] = _ensure_integers(act[col], col)

    for col in ("ocupacion_pct_oficial", "derrama_economica_mxn", "estadia_promedio", "gasto_promedio_mxn"):
        act[col] = pd.to_numeric(act[col], errors="coerce")
        if act[col].isna().any():
            raise ValueError(f"actividad_turistica_mensual.csv contiene valores inválidos o nulos en '{col}'.")

    act["meta_ocupacion_pct"] = pd.to_numeric(act["meta_ocupacion_pct"], errors="coerce")

    dup_act = int(act.duplicated(["fecha", "id_destino"]).sum())
    if dup_act:
        LOGGER.warning("Se eliminaron %d filas duplicadas en actividad_turistica_mensual.csv.", dup_act)
        act = act.drop_duplicates(["fecha", "id_destino"], keep="last")

    # Llave foránea contra dim_destino
    orphan_act = set(act["id_destino"]) - set(dest_df["id_destino"])
    if orphan_act:
        raise ValueError(f"actividad_turistica_mensual.csv referencia id_destino inexistente(s): {sorted(orphan_act)}")

    # Validación de rangos de negocio
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
    meta_invalid = act["meta_ocupacion_pct"].notna() & (~act["meta_ocupacion_pct"].between(0, 100))
    if invalid_act.any() or meta_invalid.any():
        n_bad = int(invalid_act.sum() + meta_invalid.sum())
        raise ValueError(f"Se encontraron {n_bad} filas fuera de rango en actividad_turistica_mensual.csv.")

    # 3. Validación de fact_turistas_origen
    orig = origen.copy()
    _ensure_nonempty_strings(orig, ("id_destino", "tipo_turista"), "turistas_origen_mensual.csv")
    orig["fecha"] = pd.to_datetime(orig["fecha"], format="%Y-%m-%d", errors="coerce").dt.normalize()
    if orig["fecha"].isna().any():
        raise ValueError("turistas_origen_mensual.csv contiene fechas inválidas o nulas.")
    orig["turistas"] = _ensure_integers(orig["turistas"], "turistas")

    dup_orig = int(orig.duplicated(["fecha", "id_destino", "tipo_turista"]).sum())
    if dup_orig:
        LOGGER.warning("Se eliminaron %d filas duplicadas en turistas_origen_mensual.csv.", dup_orig)
        orig = orig.drop_duplicates(["fecha", "id_destino", "tipo_turista"], keep="last")

    orphan_orig = set(orig["id_destino"]) - set(dest_df["id_destino"])
    if orphan_orig:
        raise ValueError(f"turistas_origen_mensual.csv referencia id_destino inexistente(s): {sorted(orphan_orig)}")
    if not orig["tipo_turista"].isin(["Nacional", "Extranjero"]).all():
        raise ValueError("tipo_turista debe ser 'Nacional' o 'Extranjero'.")
    if (orig["turistas"] < 0).any():
        raise ValueError("turistas no puede ser negativo.")

    # Conciliación entre suma por origen y llegada_turistas reportada
    orig_sum = orig.groupby(["fecha", "id_destino"], as_index=False)["turistas"].sum()
    reconcile = act[["fecha", "id_destino", "llegada_turistas"]].merge(
        orig_sum, on=["fecha", "id_destino"], how="left"
    )
    if reconcile["turistas"].isna().any():
        raise ValueError("Faltan desgloses de origen para uno o más registros de actividad.")
    mismatch = reconcile[reconcile["llegada_turistas"] != reconcile["turistas"].astype(int)]
    if not mismatch.empty:
        raise ValueError(
            f"Inconsistencia entre llegada_turistas y suma Nacional+Extranjero en {len(mismatch)} registros."
        )

    # 4. Construcción de dim_tiempo
    all_dates = pd.concat([act["fecha"], orig["fecha"]]).drop_duplicates().sort_values()
    dim_tiempo = pd.DataFrame({"fecha": all_dates})
    dim_tiempo["id_fecha"] = dim_tiempo["fecha"].dt.strftime("%Y%m%d").astype(int)
    dim_tiempo["anio"] = dim_tiempo["fecha"].dt.year.astype(int)
    dim_tiempo["mes"] = dim_tiempo["fecha"].dt.month.astype(int)
    dim_tiempo["nombre_mes"] = dim_tiempo["mes"].map(MONTH_NAMES_ES)
    dim_tiempo["trimestre"] = dim_tiempo["fecha"].dt.quarter.astype(int)
    date_to_id = dim_tiempo.set_index("fecha")["id_fecha"]

    act["id_fecha"] = act["fecha"].map(date_to_id).astype(int)
    fact_actividad = act[
        [
            "id_fecha",
            "id_destino",
            "cuartos_disponibles",
            "cuartos_ocupados",
            "ocupacion_pct_oficial",
            "derrama_economica_mxn",
            "llegada_turistas",
            "estadia_promedio",
            "gasto_promedio_mxn",
            "meta_ocupacion_pct",
            "tipo_cifra",
        ]
    ].sort_values(["id_fecha", "id_destino"]).reset_index(drop=True)

    orig["id_fecha"] = orig["fecha"].map(date_to_id).astype(int)
    fact_origen = orig[["id_fecha", "id_destino", "tipo_turista", "turistas"]].sort_values(
        ["id_fecha", "id_destino", "tipo_turista"]
    ).reset_index(drop=True)

    dim_tiempo["fecha"] = dim_tiempo["fecha"].dt.strftime("%Y-%m-%d")
    dim_tiempo = dim_tiempo[["id_fecha", "fecha", "anio", "mes", "nombre_mes", "trimestre"]].reset_index(drop=True)

    quality = {
        "duplicates_removed": {
            "dim_destino": dup_dest,
            "fact_actividad_turistica": dup_act,
            "fact_turistas_origen": dup_orig,
        },
        "null_meta_ocupacion_rows": int(fact_actividad["meta_ocupacion_pct"].isna().sum()),
        "rows": {
            "dim_tiempo": len(dim_tiempo),
            "dim_destino": len(dest_df),
            "fact_actividad_turistica": len(fact_actividad),
            "fact_turistas_origen": len(fact_origen),
        },
        "reconciled_origin_vs_total_turistas": True,
        "years_covered": sorted(dim_tiempo["anio"].unique().tolist()),
        "months_per_year": dim_tiempo.groupby("anio")["mes"].nunique().to_dict(),
        "total_turistas_acumulados": int(fact_actividad["llegada_turistas"].sum()),
        "total_derrama_acumulada_mxn": float(round(fact_actividad["derrama_economica_mxn"].sum(), 2)),
    }
    LOGGER.info(
        "Transformación validada: tiempo=%d, destinos=%d, actividad=%d, origen=%d",
        len(dim_tiempo),
        len(dest_df),
        len(fact_actividad),
        len(fact_origen),
    )
    return dim_tiempo, dest_df, fact_actividad, fact_origen, quality


def build_metadata(
    dim_tiempo: pd.DataFrame,
    dest_df: pd.DataFrame,
    fact_actividad: pd.DataFrame,
    quality: dict[str, Any],
    raw_dir: Path = RAW,
) -> dict[str, Any]:
    sources_path = raw_dir / "sources_metadata.json"
    base_sources: dict[str, Any] = {}
    if sources_path.exists():
        base_sources = json.loads(sources_path.read_text(encoding="utf-8"))

    # Fecha de corte real observada en los datos procesados
    max_fecha = str(dim_tiempo["fecha"].max())
    corte_legible = base_sources.get(
        "fecha_corte",
        f"Corte hasta {max_fecha}",
    )

    return {
        "proyecto": "Dashboard de Ocupación Hotelera y Derrama Turística en Oaxaca",
        "fuente_oficial": base_sources.get(
            "fuente_principal",
            "SECTUR Oaxaca / DATATUR (SIITE)",
        ),
        "portal_url": base_sources.get(
            "portal_url",
            "https://www.oaxaca.gob.mx/sectur/informacion-de-interes/estadisticas/",
        ),
        "fecha_corte": corte_legible,
        "ultima_fecha_datos": max_fecha,
        "etl_executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "boletines": base_sources.get("boletines", []),
        "nota_cobertura": base_sources.get("nota_2023", ""),
        "destinos": dest_df["nombre_destino"].tolist(),
        "quality_summary": quality,
    }


def write_outputs(
    dim_tiempo: pd.DataFrame,
    dest_df: pd.DataFrame,
    fact_actividad: pd.DataFrame,
    fact_origen: pd.DataFrame,
    metadata: dict[str, Any],
    processed_dir: Path = PROCESSED,
) -> None:
    processed_dir.mkdir(parents=True, exist_ok=True)
    dim_tiempo.to_csv(processed_dir / "dim_tiempo.csv", index=False, encoding="utf-8-sig")
    dest_df.to_csv(processed_dir / "dim_destino.csv", index=False, encoding="utf-8-sig")
    fact_actividad.to_csv(processed_dir / "fact_actividad_turistica.csv", index=False, encoding="utf-8-sig")
    fact_origen.to_csv(processed_dir / "fact_turistas_origen.csv", index=False, encoding="utf-8-sig")
    (processed_dir / "metadata_fuentes.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    LOGGER.info("Archivos procesados escritos en %s", processed_dir)


def load_postgres(
    dim_tiempo: pd.DataFrame,
    dest_df: pd.DataFrame,
    fact_actividad: pd.DataFrame,
    fact_origen: pd.DataFrame,
    metadata: dict[str, Any],
    url: str,
) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    scope = f"SECTUR Oaxaca {metadata['quality_summary']['years_covered']}"
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "TRUNCATE fact_turistas_origen, fact_actividad_turistica, dim_destino, dim_tiempo CASCADE"
                )
            )
            dim_tiempo_db = dim_tiempo.copy()
            dim_tiempo_db["fecha"] = pd.to_datetime(dim_tiempo_db["fecha"]).dt.date
            dim_tiempo_db.to_sql("dim_tiempo", conn, if_exists="append", index=False, method="multi", chunksize=500)
            dest_df.to_sql("dim_destino", conn, if_exists="append", index=False, method="multi", chunksize=500)
            fact_actividad.to_sql(
                "fact_actividad_turistica", conn, if_exists="append", index=False, method="multi", chunksize=500
            )
            fact_origen.to_sql(
                "fact_turistas_origen", conn, if_exists="append", index=False, method="multi", chunksize=500
            )
            conn.execute(
                text(
                    """
                    INSERT INTO etl_run_log
                        (status, source_scope, rows_tiempo, rows_destino, rows_actividad, rows_origen, notes)
                    VALUES
                        (:status, :scope, :rt, :rd, :ra, :ro, :notes)
                    """
                ),
                {
                    "status": "SUCCESS",
                    "scope": scope,
                    "rt": len(dim_tiempo),
                    "rd": len(dest_df),
                    "ra": len(fact_actividad),
                    "ro": len(fact_origen),
                    "notes": f"Corte: {metadata['fecha_corte']}",
                },
            )
        LOGGER.info("Carga idempotente a PostgreSQL completada y registrada en etl_run_log.")
    except Exception as exc:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO etl_run_log (status, source_scope, notes)
                        VALUES ('FAILED', :scope, :notes)
                        """
                    ),
                    {"scope": scope, "notes": str(exc)[:500]},
                )
        except Exception:
            pass
        raise
    finally:
        engine.dispose()


def main(raw_dir: Path = RAW, processed_dir: Path = PROCESSED) -> dict[str, Any]:
    destinos, actividad, origen = read_inputs(raw_dir)
    dim_tiempo, dest_df, fact_actividad, fact_origen, quality = transform(destinos, actividad, origen)
    metadata = build_metadata(dim_tiempo, dest_df, fact_actividad, quality, raw_dir)
    write_outputs(dim_tiempo, dest_df, fact_actividad, fact_origen, metadata, processed_dir)

    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        load_postgres(dim_tiempo, dest_df, fact_actividad, fact_origen, metadata, database_url)
        print("ETL terminado: archivos CSV, metadata_fuentes.json y PostgreSQL actualizados.")
    else:
        print(
            "ETL terminado: archivos CSV y metadata_fuentes.json actualizados. "
            "DATABASE_URL no está configurada; se omitió PostgreSQL."
        )
    return metadata


if __name__ == "__main__":
    main()
