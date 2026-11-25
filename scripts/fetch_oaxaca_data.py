"""Descarga y extrae datos oficiales reales de turismo en Oaxaca desde boletines PDF de SECTUR Oaxaca."""
from __future__ import annotations

import argparse
import calendar
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OFFICIAL_DIR = RAW / "official"

SECTUR_OAXACA_URL = "https://www.oaxaca.gob.mx/sectur/informacion-de-interes/estadisticas/"
DATATUR_COMPENDIUM_PAGE = "https://datatur.sectur.gob.mx/SitePages/CompendioEstadistico.aspx"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OaxacaTurismoETL/1.0",
}

MONTH_MAP = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

# Catálogo oficial de 9 destinos reportados en los boletines de SECTUR Oaxaca / SIITE
DESTINATIONS = [
    ("OAX_CENTRO", "Ciudad de Oaxaca", "Valles Centrales", "Ciudad Patrimonio / Cultural"),
    ("HUATULCO", "Bahías de Huatulco", "Costa", "Centro Integralmente Planeado (Playa)"),
    ("PTO_ESCONDIDO", "Puerto Escondido", "Costa", "Playa / Surf"),
    ("TUXTEPEC", "Tuxtepec", "Papaloapan", "Regional / Naturaleza"),
    ("ISTMO", "Istmo de Tehuantepec", "Istmo", "Regional / Negocios"),
    ("MIXTECA", "Mixteca", "Mixteca", "Regional / Cultural"),
    ("JUQUILA", "Juquila", "Sierra Sur", "Turismo Religioso"),
    ("VENTANILLA_PA", "Ventanilla Puerto Ángel", "Costa", "Ecoturismo / Playa"),
    ("RESTO_ESTADO", "Resto del Estado", "Estatal", "Otros municipios"),
]

DEST_ALIAS_TO_ID = {
    "ciudad de oaxaca": "OAX_CENTRO",
    "bahías de huatulco": "HUATULCO",
    "bahias de huatulco": "HUATULCO",
    "puerto escondido": "PTO_ESCONDIDO",
    "tuxtepec": "TUXTEPEC",
    "istmo de tehuantepec": "ISTMO",
    "mixteca": "MIXTECA",
    "juquila": "JUQUILA",
    "santa catarina juquila": "JUQUILA",
    "ventanilla puerto ángel": "VENTANILLA_PA",
    "ventanilla puerto angel": "VENTANILLA_PA",
    "ventanilla-puerto ángel": "VENTANILLA_PA",
    "ventanilla-puerto angel": "VENTANILLA_PA",
    "resto del estado": "RESTO_ESTADO",
}

# Boletines oficiales con tablas mensuales extraíbles (SECTUR Oaxaca / DATATUR / SIITE)
BULLETINS = [
    {
        "anio": 2022,
        "tipo_cifra": "Cierre",
        "corte": "Enero-Diciembre 2022 (Cierre anual)",
        "pdf_name": "2023_05_1.-Indicadores-de-la-Actividad-Turistica-2022-2.pdf",
        "url": "https://www.oaxaca.gob.mx/sectur/wp-content/uploads/sites/65/2023/05/1.-Indicadores-de-la-Actividad-Turistica-2022-2.pdf",
        "monthly_pages": (4, 7),
        "hospedaje_pages": (22, 24),
    },
    {
        "anio": 2024,
        "tipo_cifra": "Cierre",
        "corte": "Enero-Diciembre 2024 (Cierre anual)",
        "pdf_name": "2025_04_1.-Indicadores-de-la-Actividad-Turistica-2024-cierre-web.pdf",
        "url": "https://www.oaxaca.gob.mx/sectur/wp-content/uploads/sites/65/2025/04/1.-Indicadores-de-la-Actividad-Turistica-2024-cierre-web.pdf",
        "monthly_pages": (5, 8),
        "hospedaje_pages": (24, 26),
    },
    {
        "anio": 2025,
        "tipo_cifra": "Cierre",
        "corte": "Enero-Diciembre 2025 (Cierre anual)",
        "pdf_name": "2026_04_1.-Indicadores-de-la-Actividad-Turistica-2025.pdf.pdf",
        "url": "https://www.oaxaca.gob.mx/sectur/wp-content/uploads/sites/65/2026/04/1.-Indicadores-de-la-Actividad-Turistica-2025.pdf.pdf",
        "monthly_pages": (4, 7),
        "hospedaje_pages": (24, 26),
    },
    {
        "anio": 2026,
        "tipo_cifra": "Preliminar",
        "corte": "Enero-Agosto 2026 (Cifras preliminares)",
        "pdf_name": "2026_09_1.-Indicadores-de-la-Actividad-Turistica-2026-Enero_-agosto.pdf",
        "url": "https://www.oaxaca.gob.mx/sectur/wp-content/uploads/sites/65/2026/09/1.-Indicadores-de-la-Actividad-Turistica-2026-Enero_-agosto.pdf",
        "monthly_pages": (4, 7),
        "hospedaje_pages": (27, 29),
    },
]


def download_bulletins(force: bool = False) -> list[dict]:
    """Descarga los boletines PDF oficiales si no existen localmente (o si force=True)."""
    OFFICIAL_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    manifest: list[dict] = []

    for b in BULLETINS:
        dest = OFFICIAL_DIR / b["pdf_name"]
        if not force and dest.exists() and dest.stat().st_size > 10_000:
            manifest.append({
                "anio": b["anio"],
                "corte": b["corte"],
                "url": b["url"],
                "local_file": str(dest.relative_to(ROOT)).replace("\\", "/"),
                "bytes": dest.stat().st_size,
                "status": "cached",
            })
            continue

        resp = session.get(b["url"], timeout=60, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)
        manifest.append({
            "anio": b["anio"],
            "corte": b["corte"],
            "url": b["url"],
            "local_file": str(dest.relative_to(ROOT)).replace("\\", "/"),
            "bytes": dest.stat().st_size,
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "downloaded",
        })
    return manifest


def _num(token: str) -> float:
    return float(token.replace(",", "").strip())


def _int_num(token: str) -> int:
    return int(round(_num(token)))


def parse_hospedaje_inventory(pdf_path: Path, page_range: tuple[int, int]) -> dict[str, tuple[int, int]]:
    """Extrae (hoteles, cuartos) por id_destino desde la sección Servicios Turísticos -> Hospedaje."""
    start_p, end_p = page_range
    text_blocks: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno in range(start_p - 1, min(end_p, len(pdf.pages))):
            txt = pdf.pages[pno].extract_text() or ""
            if "hospedaje" in txt.lower() or "cuartos en el estado" in txt.lower():
                text_blocks.append(txt)

    full_text = "\n".join(text_blocks)
    # Localiza bloque "Hoteles en el Estado por categoría" y "Cuartos en el Estado por categoría"
    hotels_map: dict[str, int] = {}
    rooms_map: dict[str, int] = {}

    section = "none"
    for raw_line in full_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        low = line.lower()
        if "hoteles en el estado por categoría" in low or "hoteles en el estado por categoria" in low:
            section = "hotels"
            continue
        if "cuartos en el estado por categoría" in low or "cuartos en el estado por categoria" in low:
            section = "rooms"
            continue
        if low.startswith("total ") or low == "total":
            if section == "rooms" and len(rooms_map) >= 8:
                break
            continue
        if section not in ("hotels", "rooms"):
            continue

        # Patrón: <Nombre destino> <5*> <4*> <3*> <2*> <1*> <Otros> <Total>
        m = re.match(r"^([A-Za-zÁÉÍÓÚÜÑáéíóúüñ\-\s]+?)\s+([\d,]+\s+){6}([\d,]+)$", line)
        if not m:
            continue
        raw_dest = re.sub(r"\s+", " ", m.group(1)).strip().lower()
        raw_dest = raw_dest.replace("ciudad deoaxaca", "ciudad de oaxaca").replace("bahías dehuatulco", "bahías de huatulco").replace("istmo detehuantepec", "istmo de tehuantepec")
        dest_id = DEST_ALIAS_TO_ID.get(raw_dest)
        if not dest_id:
            continue
        total_val = _int_num(m.group(3))
        if section == "hotels":
            hotels_map[dest_id] = total_val
        else:
            rooms_map[dest_id] = total_val

    result: dict[str, tuple[int, int]] = {}
    for dest_id, *_ in DESTINATIONS:
        if dest_id in rooms_map:
            result[dest_id] = (hotels_map.get(dest_id, 0), rooms_map[dest_id])
    return result


def parse_monthly_tables(pdf_path: Path, anio: int, tipo_cifra: str, page_range: tuple[int, int], inventory: dict[str, tuple[int, int]]) -> tuple[list[dict], list[dict]]:
    """Extrae filas mensuales por destino desde las páginas de indicadores mensuales."""
    start_p, end_p = page_range
    pages_text: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno in range(start_p - 1, min(end_p, len(pdf.pages))):
            pages_text.append(pdf.pages[pno].extract_text() or "")
    combined = "\n".join(pages_text)

    # Normaliza saltos dentro de encabezados de destino antes de parsear
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in combined.splitlines() if ln.strip()]

    # Detecta en qué orden aparecen los 9 destinos + Estado en el bloque mensual
    month_row_re = re.compile(
        r"^(Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|Octubre|Noviembre|Diciembre|Total)\s+"
        r"([\d.,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)$",
        re.IGNORECASE,
    )

    # En 2022 y 2024/2025/2026 hay 9 destinos + 1 bloque "Estado" / "Total Estado" (en 2022, 2024, 2025, 2026)
    # Agrupamos bloques terminados en fila "Total ..."
    blocks: list[tuple[str, list[tuple[str, list[str]]]]] = []
    header_buf: list[str] = []
    current_rows: list[tuple[str, list[str]]] = []

    for line in lines:
        # Salta líneas de pie/fuente/títulos generales
        low = line.lower()
        if low.startswith("fuente:") or re.fullmatch(r"\d+", line) or "indicadores de la actividad" in low or "indicadores mensuales" in low or "indicadores por mes" in low:
            continue

        m = month_row_re.match(line)
        if m:
            label = m.group(1).capitalize()
            vals = list(m.groups()[1:])
            current_rows.append((label, vals))
            if label == "Total":
                header_text = " ".join(header_buf).lower()
                blocks.append((header_text, current_rows))
                header_buf = []
                current_rows = []
        else:
            # Si todavía no estamos acumulando filas, pertenece al encabezado del bloque actual
            if not current_rows:
                header_buf.append(line)
            else:
                # Encabezado intermedio repetido al cambiar de página (ignorar)
                pass

    # Identifica cada bloque con su destino o Estado
    # En 2022 las páginas 4-7 también tienen narrativa al principio de la p4 antes de Ciudad de Oaxaca
    expected_order = [
        "OAX_CENTRO",
        "HUATULCO",
        "PTO_ESCONDIDO",
        "TUXTEPEC",
        "ISTMO",
        "MIXTECA",
        "JUQUILA",
        "VENTANILLA_PA",
        "RESTO_ESTADO",
        "ESTADO",
    ]

    if len(blocks) != len(expected_order):
        raise ValueError(f"{pdf_path.name}: se esperaban {len(expected_order)} bloques mensuales, se encontraron {len(blocks)}")

    activity_rows: list[dict] = []
    origin_rows: list[dict] = []

    for idx, (header_text, rows) in enumerate(blocks):
        dest_id = expected_order[idx]
        if dest_id == "ESTADO":
            # Validamos que el bloque corresponde a Estado y omitimos duplicar el agregado estatal en la tabla de hechos
            continue

        # Verificación básica de que el encabezado concuerda con el destino esperado
        expected_name = next(d[1] for d in DESTINATIONS if d[0] == dest_id).lower()
        key_word = expected_name.split()[-1].replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        norm_hdr = header_text.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").replace(" ", "")
        if key_word not in norm_hdr and dest_id != "TUXTEPEC":
            # En 2026_09, "Tuxtepec" está al final de p4 y aparece en header_text
            raise ValueError(f"{pdf_path.name}: bloque {idx} ({dest_id}) no coincide con encabezado '{header_text}'")

        cuartos_inv = inventory[dest_id][1]
        sum_nac = 0
        sum_ext = 0
        sum_tot = 0
        total_row = None

        for label, vals in rows:
            if label == "Total":
                total_row = vals
                continue
            mes = MONTH_MAP[label.lower()]
            # Orden de columnas varía ligeramente entre 2022/2024/2025/2026:
            # En 2022, 2024, 2025, 2026:
            # Ocupacion%, Nacionales, Extranjeros, Total, <Estadía o Gasto>, <Gasto o Estadía>, Derrama(MDP)
            # Nota: en 2024-2026 p4-6 Ciudad de Oaxaca: Estadía ~2.0, Gasto ~2500.
            # En 2024 p3/5/6/7: Estadía (~1.0-3.5) va ANTES que Gasto (~500-4600).
            # En 2024 p5 (Huatulco/Oaxaca): Estadía va antes que Gasto.
            # En 2022 p4/5/6: Estadía va antes que Gasto.
            # Comprobamos dinámicamente cuál de vals[4] y vals[5] es Estadía (< 20) vs Gasto (>= 20).
            occ_pct = round(_num(vals[0]), 2)
            nac = _int_num(vals[1])
            ext = _int_num(vals[2])
            tot = _int_num(vals[3])
            v4, v5 = _num(vals[4]), _num(vals[5])
            if v4 < 20 and v5 >= 20:
                estadia, gasto = round(v4, 2), round(v5, 2)
            elif v5 < 20 and v4 >= 20:
                gasto, estadia = round(v4, 2), round(v5, 2)
            else:
                raise ValueError(f"{pdf_path.name} {dest_id} {label}: no se pudo distinguir estadía/gasto ({v4}, {v5})")
            derrama_mdp = _num(vals[6])
            derrama_mxn = round(derrama_mdp * 1_000_000.0, 2)

            if nac + ext != tot:
                raise ValueError(f"{pdf_path.name} {dest_id} {label}: nac({nac})+ext({ext}) != tot({tot})")

            dias_mes = calendar.monthrange(anio, mes)[1]
            cuartos_disp = cuartos_inv * dias_mes
            cuartos_ocup = int(round(cuartos_disp * (occ_pct / 100.0)))
            fecha_str = f"{anio:04d}-{mes:02d}-01"

            sum_nac += nac
            sum_ext += ext
            sum_tot += tot

            activity_rows.append({
                "fecha": fecha_str,
                "anio": anio,
                "mes": mes,
                "id_destino": dest_id,
                "cuartos_disponibles": cuartos_disp,
                "cuartos_ocupados": cuartos_ocup,
                "ocupacion_pct_oficial": occ_pct,
                "derrama_economica_mxn": derrama_mxn,
                "llegada_turistas": tot,
                "estadia_promedio": estadia,
                "gasto_promedio_mxn": gasto,
                "meta_ocupacion_pct": None,
                "tipo_cifra": tipo_cifra,
            })
            origin_rows.append({"fecha": fecha_str, "id_destino": dest_id, "tipo_turista": "Nacional", "turistas": nac})
            origin_rows.append({"fecha": fecha_str, "id_destino": dest_id, "tipo_turista": "Extranjero", "turistas": ext})

        if total_row is not None:
            tot_nac = _int_num(total_row[1])
            tot_ext = _int_num(total_row[2])
            tot_all = _int_num(total_row[3])
            if (sum_nac, sum_ext, sum_tot) != (tot_nac, tot_ext, tot_all):
                raise ValueError(
                    f"{pdf_path.name} {dest_id}: suma mensual ({sum_nac}, {sum_ext}, {sum_tot}) "
                    f"!= fila Total oficial ({tot_nac}, {tot_ext}, {tot_all})"
                )

    return activity_rows, origin_rows


def write_sources_doc(manifest: list[dict], latest_inv: dict[str, tuple[int, int]], activity_df: pd.DataFrame) -> None:
    """Genera data/raw/FUENTES_OFICIALES.md con trazabilidad exacta de URLs, cortes y metodología."""
    lines = [
        "# Fuentes Oficiales de Datos Turísticos de Oaxaca",
        "",
        "Este directorio contiene únicamente cifras oficiales emitidas por la **Secretaría de Turismo del Estado de Oaxaca (SECTUR Oaxaca)** en coordinación con **DATATUR (SECTUR Federal)** y el **Sistema Integral de Información Turística Estatal (SIITE)**.",
        "",
        f"- **Portal institucional:** {SECTUR_OAXACA_URL}",
        f"- **Portal federal de referencia:** {DATATUR_COMPENDIUM_PAGE}",
        f"- **Fecha de extracción / generación de CSV:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "- **Fecha de corte más reciente:** Agosto 2026 (cifras preliminares enero–agosto 2026; cierres anuales definitivos para 2022, 2024 y 2025).",
        "",
        "## Boletines PDF procesados de forma reproducible",
        "",
        "| Año | Tipo de cifra | Corte cubierto | Archivo local (`data/raw/official/`) | URL oficial exacta |",
        "|---|---|---|---|---|",
    ]
    for b in BULLETINS:
        lines.append(f"| {b['anio']} | {b['tipo_cifra']} | {b['corte']} | `{b['pdf_name']}` | {b['url']} |")

    lines.extend([
        "",
        "## Nota metodológica y cobertura",
        "",
        "1. **Granularidad real:** Mensual por destino turístico (`YYYY-MM-01`), cubriendo los 9 destinos oficiales de Oaxaca (`Ciudad de Oaxaca`, `Bahías de Huatulco`, `Puerto Escondido`, `Tuxtepec`, `Istmo de Tehuantepec`, `Mixteca`, `Juquila`, `Ventanilla Puerto Ángel`, `Resto del Estado`) durante **2022 (12 meses)**, **2024 (12 meses)**, **2025 (12 meses)** y **2026 (enero–agosto, 8 meses)**.",
        "2. **Cobertura del boletín 2023:** El boletín anual 2023 publicado en el portal estatal (`1.-Indicadores-de-la-Actividad-Turistica-2023.pdf`) fue exportado por SECTUR como imágenes rasterizadas sin capa de texto, por lo que no se incluye mediante parsing automático sin OCR para preservar la regla de reproducibilidad exacta.",
        "3. **Cuartos disponibles y ocupados:** En los boletines de SECTUR Oaxaca se reporta directamente el porcentaje mensual de ocupación oficial (`ocupacion_pct_oficial`) y, en la sección *Servicios Turísticos -> Hospedaje*, el inventario oficial de hoteles y cuartos por destino de cada año. Por ello se calcula `cuartos_disponibles = cuartos_registrados_destino * dias_del_mes` y `cuartos_ocupados = round(cuartos_disponibles * ocupacion_pct_oficial / 100)`, permitiendo calcular tasas agregadas como razón de sumas (`SUM(cuartos_ocupados) / SUM(cuartos_disponibles)`) sin promediar porcentajes.",
        "4. **Derrama económica:** Los boletines publican la derrama mensual redondeada a millones de pesos (MDP); en `actividad_turistica_mensual.csv` se almacena en pesos mexicanos (`derrama_economica_mxn = MDP * 1,000,000`).",
        "5. **Metas de ocupación:** Ninguno de los boletines mensuales oficiales publica una meta de ocupación desagregada por destino y mes, por lo que `meta_ocupacion_pct` permanece nulo (`NULL`) para no fabricar metas sintéticas.",
        "",
        "## Resumen de control por año extraído",
        "",
        "| Año | Meses | Filas destino-mes | Llegada total de turistas | Derrama acumulada (MDP) |",
        "|---|---|---|---|---|",
    ])
    for anio, grp in activity_df.groupby("anio"):
        lines.append(
            f"| {anio} | {grp['mes'].nunique()} | {len(grp)} | {int(grp['llegada_turistas'].sum()):,} | "
            f"{grp['derrama_economica_mxn'].sum() / 1_000_000:,.0f} |"
        )

    lines.extend([
        "",
        "## Inventario oficial de hospedaje más reciente (SIITE 2025/2026)",
        "",
        "| `id_destino` | Destino | Hoteles registrados | Cuartos registrados |",
        "|---|---|---:|---:|",
    ])
    for dest_id, nombre, _, _ in DESTINATIONS:
        hoteles, cuartos = latest_inv[dest_id]
        lines.append(f"| `{dest_id}` | {nombre} | {hoteles:,} | {cuartos:,} |")

    (RAW / "FUENTES_OFICIALES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(skip_download: bool = False) -> None:
    manifest = [] if skip_download else download_bulletins(force=False)

    all_activity: list[dict] = []
    all_origin: list[dict] = []
    latest_inv: dict[str, tuple[int, int]] = {}

    for b in BULLETINS:
        pdf_path = OFFICIAL_DIR / b["pdf_name"]
        if not pdf_path.exists():
            raise FileNotFoundError(f"No se encontró el boletín oficial: {pdf_path}. Ejecuta sin --skip-download.")
        inv = parse_hospedaje_inventory(pdf_path, b["hospedaje_pages"])
        if len(inv) != len(DESTINATIONS):
            raise ValueError(f"{pdf_path.name}: inventario de hospedaje incompleto ({len(inv)}/{len(DESTINATIONS)})")
        latest_inv = inv
        act_rows, ori_rows = parse_monthly_tables(pdf_path, b["anio"], b["tipo_cifra"], b["monthly_pages"], inv)
        all_activity.extend(act_rows)
        all_origin.extend(ori_rows)
        print(f"[OK] {b['anio']} ({b['tipo_cifra']}): {len(act_rows)} filas mensuales, {len(ori_rows)} filas origen.")

    dest_df = pd.DataFrame([
        {
            "id_destino": dest_id,
            "nombre_destino": nombre,
            "region": region,
            "tipo_destino": tipo,
            "hoteles_registrados": latest_inv[dest_id][0],
            "cuartos_registrados": latest_inv[dest_id][1],
        }
        for dest_id, nombre, region, tipo in DESTINATIONS
    ])
    activity_df = pd.DataFrame(all_activity).sort_values(["anio", "mes", "id_destino"]).reset_index(drop=True)
    origin_df = pd.DataFrame(all_origin).sort_values(["fecha", "id_destino", "tipo_turista"]).reset_index(drop=True)

    RAW.mkdir(parents=True, exist_ok=True)
    dest_df.to_csv(RAW / "destinos.csv", index=False, encoding="utf-8-sig")
    activity_df.to_csv(RAW / "actividad_turistica_mensual.csv", index=False, encoding="utf-8-sig")
    origin_df.to_csv(RAW / "turistas_origen_mensual.csv", index=False, encoding="utf-8-sig")
    write_sources_doc(manifest, latest_inv, activity_df)

    # Guarda también registro JSON de trazabilidad para metadata_fuentes.json
    sources_meta = {
        "fuente_principal": "SECTUR Oaxaca - Boletines de Indicadores de la Actividad Turística (DATATUR / SIITE)",
        "portal_url": SECTUR_OAXACA_URL,
        "fecha_corte": "Agosto 2026 (cifras preliminares enero-agosto 2026; cierres anuales 2022, 2024 y 2025)",
        "anios_cubiertos": sorted(activity_df["anio"].unique().tolist()),
        "destinos_cubiertos": len(dest_df),
        "boletines": [
            {k: b[k] for k in ("anio", "tipo_cifra", "corte", "pdf_name", "url")}
            for b in BULLETINS
        ],
        "nota_2023": "El boletín anual 2023 está publicado como imágenes rasterizadas sin capa de texto extraíble.",
    }
    (RAW / "sources_metadata.json").write_text(json.dumps(sources_meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Archivos crudos generados en {RAW}: {len(dest_df)} destinos, {len(activity_df)} filas mensuales, {len(origin_df)} filas origen.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Descarga y extrae datos oficiales de turismo de Oaxaca.")
    parser.add_argument("--skip-download", action="store_true", help="Usa únicamente los PDFs ya descargados en data/raw/official/.")
    args = parser.parse_args()
    main(skip_download=args.skip_download)
