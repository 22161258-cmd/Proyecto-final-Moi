"""Genera CSV sintéticos reproducibles para probar el ETL y el dashboard."""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RNG = random.Random(2026)

HOTELS = [
    ("H001", "Hotel Centro", "Centro Histórico", 4, 80),
    ("H002", "Posada del Andador", "Centro Histórico", 3, 45),
    ("H003", "Hotel Santo Domingo", "Centro Histórico", 5, 110),
    ("H004", "Casa Jalatlaco", "Jalatlaco", 4, 52),
    ("H005", "Hotel Reforma", "Reforma", 3, 68),
    ("H006", "Hotel San Felipe", "San Felipe", 4, 72),
    ("H007", "Posada Xochimilco", "Xochimilco", 2, 34),
]
ORIGINS = ["CDMX", "Puebla", "Veracruz", "Jalisco", "Extranjero"]


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    occupancy: list[dict] = []
    tourists: list[dict] = []
    current = date(2024, 1, 1)
    end = date(2026, 12, 31)
    while current <= end:
        seasonal = 0.10 if current.month in (7, 10, 11, 12, 4) else 0.0
        weekend = 0.08 if current.weekday() >= 4 else 0.0
        for hid, name, zone, category, rooms in HOTELS:
            available = rooms
            target = min(0.92, 0.68 + seasonal + weekend + (category - 3) * 0.015)
            occupancy_rate = max(0.25, min(0.98, RNG.gauss(target, 0.09)))
            occupied = round(available * occupancy_rate)
            adr = 950 + category * 340 + (seasonal + weekend) * 1600 + RNG.randint(-180, 240)
            revenue = round(occupied * adr, 2)
            reservations = max(occupied, round(occupied / max(0.5, RNG.uniform(0.84, 0.96))))
            cancellations = max(0, reservations - occupied)
            occupancy.append({
                "fecha": current.isoformat(), "id_hotel": hid, "habitaciones_disponibles": available,
                "habitaciones_ocupadas": occupied, "ingreso_hospedaje": revenue,
                "reservaciones": reservations, "cancelaciones": cancellations,
                "meta_ocupacion_pct": round(min(95, (0.72 + seasonal) * 100), 1),
            })
            remaining = occupied
            weights = [0.34, 0.18, 0.14, 0.12, 0.22]
            for idx, origin in enumerate(ORIGINS):
                count = remaining if idx == len(ORIGINS) - 1 else min(remaining, round(occupied * weights[idx] * RNG.uniform(0.8, 1.2)))
                remaining -= count
                if count:
                    tourists.append({"fecha": current.isoformat(), "id_hotel": hid, "origen": origin, "turistas_hospedados": count})
        current += timedelta(days=1)
    pd.DataFrame(occupancy).to_csv(RAW / "ocupacion_diaria.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(tourists).to_csv(RAW / "turistas_origen.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([
        {"id_hotel": hid, "nombre_hotel": name, "zona_turistica": zone,
         "categoria_hotel": category, "num_habitaciones": rooms}
        for hid, name, zone, category, rooms in HOTELS
    ]).to_csv(RAW / "hoteles.csv", index=False, encoding="utf-8-sig")
    print(f"Datos sintéticos creados en {RAW}")


if __name__ == "__main__":
    main()
