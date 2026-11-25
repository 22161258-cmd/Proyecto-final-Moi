# Fuentes Oficiales de Datos Turísticos de Oaxaca

Este directorio contiene únicamente cifras oficiales emitidas por la **Secretaría de Turismo del Estado de Oaxaca (SECTUR Oaxaca)** en coordinación con **DATATUR (SECTUR Federal)** y el **Sistema Integral de Información Turística Estatal (SIITE)**.

- **Portal institucional:** https://www.oaxaca.gob.mx/sectur/informacion-de-interes/estadisticas/
- **Portal federal de referencia:** https://datatur.sectur.gob.mx/SitePages/CompendioEstadistico.aspx
- **Fecha de extracción / generación de CSV:** 2026-11-25 15:58 UTC
- **Fecha de corte más reciente:** Agosto 2026 (cifras preliminares enero–agosto 2026; cierres anuales definitivos para 2022, 2024 y 2025).

## Boletines PDF procesados de forma reproducible

| Año | Tipo de cifra | Corte cubierto | Archivo local (`data/raw/official/`) | URL oficial exacta |
|---|---|---|---|---|
| 2022 | Cierre | Enero-Diciembre 2022 (Cierre anual) | `2023_05_1.-Indicadores-de-la-Actividad-Turistica-2022-2.pdf` | https://www.oaxaca.gob.mx/sectur/wp-content/uploads/sites/65/2023/05/1.-Indicadores-de-la-Actividad-Turistica-2022-2.pdf |
| 2024 | Cierre | Enero-Diciembre 2024 (Cierre anual) | `2025_04_1.-Indicadores-de-la-Actividad-Turistica-2024-cierre-web.pdf` | https://www.oaxaca.gob.mx/sectur/wp-content/uploads/sites/65/2025/04/1.-Indicadores-de-la-Actividad-Turistica-2024-cierre-web.pdf |
| 2025 | Cierre | Enero-Diciembre 2025 (Cierre anual) | `2026_04_1.-Indicadores-de-la-Actividad-Turistica-2025.pdf.pdf` | https://www.oaxaca.gob.mx/sectur/wp-content/uploads/sites/65/2026/04/1.-Indicadores-de-la-Actividad-Turistica-2025.pdf.pdf |
| 2026 | Preliminar | Enero-Agosto 2026 (Cifras preliminares) | `2026_09_1.-Indicadores-de-la-Actividad-Turistica-2026-Enero_-agosto.pdf` | https://www.oaxaca.gob.mx/sectur/wp-content/uploads/sites/65/2026/09/1.-Indicadores-de-la-Actividad-Turistica-2026-Enero_-agosto.pdf |

## Nota metodológica y cobertura

1. **Granularidad real:** Mensual por destino turístico (`YYYY-MM-01`), cubriendo los 9 destinos oficiales de Oaxaca (`Ciudad de Oaxaca`, `Bahías de Huatulco`, `Puerto Escondido`, `Tuxtepec`, `Istmo de Tehuantepec`, `Mixteca`, `Juquila`, `Ventanilla Puerto Ángel`, `Resto del Estado`) durante **2022 (12 meses)**, **2024 (12 meses)**, **2025 (12 meses)** y **2026 (enero–agosto, 8 meses)**.
2. **Cobertura del boletín 2023:** El boletín anual 2023 publicado en el portal estatal (`1.-Indicadores-de-la-Actividad-Turistica-2023.pdf`) fue exportado por SECTUR como imágenes rasterizadas sin capa de texto, por lo que no se incluye mediante parsing automático sin OCR para preservar la regla de reproducibilidad exacta.
3. **Cuartos disponibles y ocupados:** En los boletines de SECTUR Oaxaca se reporta directamente el porcentaje mensual de ocupación oficial (`ocupacion_pct_oficial`) y, en la sección *Servicios Turísticos -> Hospedaje*, el inventario oficial de hoteles y cuartos por destino de cada año. Por ello se calcula `cuartos_disponibles = cuartos_registrados_destino * dias_del_mes` y `cuartos_ocupados = round(cuartos_disponibles * ocupacion_pct_oficial / 100)`, permitiendo calcular tasas agregadas como razón de sumas (`SUM(cuartos_ocupados) / SUM(cuartos_disponibles)`) sin promediar porcentajes.
4. **Derrama económica:** Los boletines publican la derrama mensual redondeada a millones de pesos (MDP); en `actividad_turistica_mensual.csv` se almacena en pesos mexicanos (`derrama_economica_mxn = MDP * 1,000,000`).
5. **Metas de ocupación:** Ninguno de los boletines mensuales oficiales publica una meta de ocupación desagregada por destino y mes, por lo que `meta_ocupacion_pct` permanece nulo (`NULL`) para no fabricar metas sintéticas.

## Resumen de control por año extraído

| Año | Meses | Filas destino-mes | Llegada total de turistas | Derrama acumulada (MDP) |
|---|---|---|---|---|
| 2022 | 12 | 108 | 5,099,619 | 16,194 |
| 2024 | 12 | 108 | 6,063,761 | 22,765 |
| 2025 | 12 | 108 | 6,289,000 | 23,347 |
| 2026 | 8 | 72 | 4,312,798 | 16,970 |

## Inventario oficial de hospedaje más reciente (SIITE 2025/2026)

| `id_destino` | Destino | Hoteles registrados | Cuartos registrados |
|---|---|---:|---:|
| `OAX_CENTRO` | Ciudad de Oaxaca | 340 | 7,521 |
| `HUATULCO` | Bahías de Huatulco | 158 | 5,253 |
| `PTO_ESCONDIDO` | Puerto Escondido | 253 | 5,043 |
| `TUXTEPEC` | Tuxtepec | 42 | 1,263 |
| `ISTMO` | Istmo de Tehuantepec | 109 | 2,305 |
| `MIXTECA` | Mixteca | 86 | 1,716 |
| `JUQUILA` | Juquila | 95 | 1,627 |
| `VENTANILLA_PA` | Ventanilla Puerto Ángel | 218 | 2,125 |
| `RESTO_ESTADO` | Resto del Estado | 383 | 5,087 |
