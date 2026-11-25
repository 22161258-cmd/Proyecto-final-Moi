"""ETL de ocupación y turistas. Lee CSV crudos, limpia y produce hechos analíticos."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RAW, PROCESSED = ROOT / "data" / "raw", ROOT / "data" / "processed"
load_dotenv(ROOT / ".env")


def require_columns(frame: pd.DataFrame, columns: set[str], source: str) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{source}: faltan columnas obligatorias: {', '.join(sorted(missing))}")


def read_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    hotels = pd.read_csv(RAW / "hoteles.csv")
    occupancy = pd.read_csv(RAW / "ocupacion_diaria.csv")
    tourists = pd.read_csv(RAW / "turistas_origen.csv")
    require_columns(hotels, {"id_hotel", "nombre_hotel", "zona_turistica", "categoria_hotel", "num_habitaciones"}, "hoteles.csv")
    require_columns(occupancy, {"fecha", "id_hotel", "habitaciones_disponibles", "habitaciones_ocupadas", "ingreso_hospedaje", "reservaciones", "cancelaciones", "meta_ocupacion_pct"}, "ocupacion_diaria.csv")
    require_columns(tourists, {"fecha", "id_hotel", "origen", "turistas_hospedados"}, "turistas_origen.csv")
    return hotels, occupancy, tourists


def transform(hotels: pd.DataFrame, occupancy: pd.DataFrame, tourists: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    hotels = hotels.drop_duplicates("id_hotel").copy()
    hotels["id_hotel"] = hotels["id_hotel"].astype(str)
    hotels["categoria_hotel"] = pd.to_numeric(hotels["categoria_hotel"], errors="raise").astype(int)
    hotels["num_habitaciones"] = pd.to_numeric(hotels["num_habitaciones"], errors="raise").astype(int)
    if not hotels["categoria_hotel"].between(1, 5).all() or (hotels["num_habitaciones"] <= 0).any():
        raise ValueError("Categoría de hotel debe estar entre 1 y 5 y las habitaciones deben ser positivas.")

    occupancy = occupancy.copy()
    occupancy["id_hotel"] = occupancy["id_hotel"].astype(str)
    occupancy["fecha"] = pd.to_datetime(occupancy["fecha"], errors="coerce").dt.normalize()
    numeric = ["habitaciones_disponibles", "habitaciones_ocupadas", "ingreso_hospedaje", "reservaciones", "cancelaciones", "meta_ocupacion_pct"]
    for column in numeric:
        occupancy[column] = pd.to_numeric(occupancy[column], errors="coerce")
    occupancy = occupancy.dropna(subset=["fecha", "id_hotel", *numeric])
    occupancy = occupancy.drop_duplicates(["fecha", "id_hotel"], keep="last")
    if not occupancy["id_hotel"].isin(hotels["id_hotel"]).all():
        raise ValueError("Hay registros diarios con id_hotel que no existe en hoteles.csv.")
    invalid = (
        (occupancy["habitaciones_disponibles"] <= 0)
        | (occupancy["habitaciones_ocupadas"] < 0)
        | (occupancy["habitaciones_ocupadas"] > occupancy["habitaciones_disponibles"])
        | (occupancy["ingreso_hospedaje"] < 0)
        | (occupancy["reservaciones"] < 0)
        | (occupancy["cancelaciones"] < 0)
        | (occupancy["cancelaciones"] > occupancy["reservaciones"])
    )
    invalid_target = ~occupancy["meta_ocupacion_pct"].between(0, 100)
    if invalid.any() or invalid_target.any():
        raise ValueError(f"Se encontraron {int(invalid.sum() + invalid_target.sum())} filas con valores fuera de rango en ocupacion_diaria.csv.")
    integer_columns = ["habitaciones_disponibles", "habitaciones_ocupadas", "reservaciones", "cancelaciones"]
    if any((occupancy[c] % 1 != 0).any() for c in integer_columns):
        raise ValueError("Habitaciones, reservaciones y cancelaciones deben ser valores enteros.")
    occupancy[integer_columns] = occupancy[integer_columns].astype(int)

    tourists = tourists.copy()
    tourists["id_hotel"] = tourists["id_hotel"].astype(str)
    tourists["fecha"] = pd.to_datetime(tourists["fecha"], errors="coerce").dt.normalize()
    tourists["turistas_hospedados"] = pd.to_numeric(tourists["turistas_hospedados"], errors="coerce")
    tourists = tourists.dropna(subset=["fecha", "id_hotel", "origen", "turistas_hospedados"])
    tourists = tourists.drop_duplicates(["fecha", "id_hotel", "origen"], keep="last")
    if (tourists["turistas_hospedados"] < 0).any() or (tourists["turistas_hospedados"] % 1 != 0).any() or not tourists["id_hotel"].isin(hotels["id_hotel"]).all():
        raise ValueError("Turistas debe ser un entero no negativo y cada id_hotel debe existir en hoteles.csv.")
    tourists["turistas_hospedados"] = tourists["turistas_hospedados"].astype(int)

    all_dates = pd.concat([occupancy["fecha"], tourists["fecha"]]).drop_duplicates().sort_values()
    dim_time = pd.DataFrame({"fecha": all_dates})
    dim_time["id_fecha"] = dim_time["fecha"].dt.strftime("%Y%m%d").astype(int)
    dim_time["anio"] = dim_time["fecha"].dt.year
    dim_time["mes"] = dim_time["fecha"].dt.month
    dim_time["nombre_mes"] = dim_time["fecha"].dt.month.map({1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"})
    dim_time["dia"] = dim_time["fecha"].dt.day
    dim_time["dia_semana"] = dim_time["fecha"].dt.dayofweek + 1
    dim_time["trimestre"] = dim_time["fecha"].dt.quarter
    date_key = dim_time.set_index("fecha")["id_fecha"]

    occupancy["id_fecha"] = occupancy["fecha"].map(date_key).astype(int)
    fact_occupancy = occupancy[["id_fecha", "id_hotel", *numeric]].rename(columns={"meta_ocupacion_pct": "meta_ocupacion_pct"})
    tourists["id_fecha"] = tourists["fecha"].map(date_key).astype(int)
    fact_tourists = tourists[["id_fecha", "id_hotel", "origen", "turistas_hospedados"]]
    dim_time["fecha"] = dim_time["fecha"].dt.date
    return hotels, dim_time, fact_occupancy, fact_tourists


def write_csvs(hotels: pd.DataFrame, dim_time: pd.DataFrame, occupancy: pd.DataFrame, tourists: pd.DataFrame) -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    hotels.to_csv(PROCESSED / "dim_hotel.csv", index=False, encoding="utf-8-sig")
    dim_time.to_csv(PROCESSED / "dim_tiempo.csv", index=False, encoding="utf-8-sig")
    occupancy.to_csv(PROCESSED / "fact_ocupacion_diaria.csv", index=False, encoding="utf-8-sig")
    tourists.to_csv(PROCESSED / "fact_turistas.csv", index=False, encoding="utf-8-sig")


def load_postgres(hotels: pd.DataFrame, dim_time: pd.DataFrame, occupancy: pd.DataFrame, tourists: pd.DataFrame, url: str) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE fact_turistas, fact_ocupacion_diaria, dim_hotel, dim_tiempo RESTART IDENTITY CASCADE"))
        dim_time.to_sql("dim_tiempo", connection, if_exists="append", index=False, method="multi", chunksize=1000)
        hotels.to_sql("dim_hotel", connection, if_exists="append", index=False, method="multi", chunksize=1000)
        occupancy.to_sql("fact_ocupacion_diaria", connection, if_exists="append", index=False, method="multi", chunksize=1000)
        tourists.to_sql("fact_turistas", connection, if_exists="append", index=False, method="multi", chunksize=1000)
    engine.dispose()


def main() -> None:
    hotels, occupancy, tourists = read_inputs()
    result = transform(hotels, occupancy, tourists)
    write_csvs(*result)
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        load_postgres(*result, database_url)
        print("ETL terminado: archivos CSV y PostgreSQL actualizados.")
    else:
        print("ETL terminado: archivos CSV actualizados. DATABASE_URL no está configurada; se omitió PostgreSQL.")


if __name__ == "__main__":
    main()
