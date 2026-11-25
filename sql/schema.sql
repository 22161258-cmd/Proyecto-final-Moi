-- Modelo dimensional (constelación) para el Dashboard de Ocupación Hotelera y Derrama Turística en Oaxaca.
-- Basado en datos oficiales de SECTUR Oaxaca / DATATUR (SIITE).
-- Ejecutar en una base PostgreSQL vacía antes de cargar datos con etl/etl.py.

CREATE TABLE IF NOT EXISTS dim_tiempo (
    id_fecha INTEGER PRIMARY KEY,                 -- formato AAAAMMDD (ej. 20250101 para corte mensual)
    fecha DATE NOT NULL UNIQUE,
    anio SMALLINT NOT NULL CHECK (anio BETWEEN 2018 AND 2035),
    mes SMALLINT NOT NULL CHECK (mes BETWEEN 1 AND 12),
    nombre_mes VARCHAR(15) NOT NULL,
    trimestre SMALLINT NOT NULL CHECK (trimestre BETWEEN 1 AND 4)
);

CREATE TABLE IF NOT EXISTS dim_destino (
    id_destino VARCHAR(30) PRIMARY KEY,
    nombre_destino VARCHAR(100) NOT NULL UNIQUE,
    region VARCHAR(60) NOT NULL,
    tipo_destino VARCHAR(60) NOT NULL,
    hoteles_registrados INTEGER CHECK (hoteles_registrados IS NULL OR hoteles_registrados > 0),
    cuartos_registrados INTEGER CHECK (cuartos_registrados IS NULL OR cuartos_registrados > 0)
);

CREATE TABLE IF NOT EXISTS fact_actividad_turistica (
    id_fecha INTEGER NOT NULL REFERENCES dim_tiempo(id_fecha),
    id_destino VARCHAR(30) NOT NULL REFERENCES dim_destino(id_destino),
    cuartos_disponibles INTEGER NOT NULL CHECK (cuartos_disponibles > 0),
    cuartos_ocupados INTEGER NOT NULL CHECK (cuartos_ocupados BETWEEN 0 AND cuartos_disponibles),
    ocupacion_pct_oficial NUMERIC(5,2) NOT NULL CHECK (ocupacion_pct_oficial BETWEEN 0 AND 100),
    derrama_economica_mxn NUMERIC(16,2) NOT NULL CHECK (derrama_economica_mxn >= 0),
    llegada_turistas INTEGER NOT NULL CHECK (llegada_turistas >= 0),
    estadia_promedio NUMERIC(5,2) NOT NULL CHECK (estadia_promedio > 0),
    gasto_promedio_mxn NUMERIC(12,2) NOT NULL CHECK (gasto_promedio_mxn >= 0),
    meta_ocupacion_pct NUMERIC(5,2) NULL CHECK (meta_ocupacion_pct IS NULL OR meta_ocupacion_pct BETWEEN 0 AND 100),
    tipo_cifra VARCHAR(20) NOT NULL DEFAULT 'Cierre' CHECK (tipo_cifra IN ('Cierre', 'Preliminar')),
    PRIMARY KEY (id_fecha, id_destino)
);

CREATE TABLE IF NOT EXISTS fact_turistas_origen (
    id_fecha INTEGER NOT NULL REFERENCES dim_tiempo(id_fecha),
    id_destino VARCHAR(30) NOT NULL REFERENCES dim_destino(id_destino),
    tipo_turista VARCHAR(30) NOT NULL CHECK (tipo_turista IN ('Nacional', 'Extranjero')),
    turistas INTEGER NOT NULL CHECK (turistas >= 0),
    PRIMARY KEY (id_fecha, id_destino, tipo_turista)
);

CREATE TABLE IF NOT EXISTS etl_run_log (
    id_run SERIAL PRIMARY KEY,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(20) NOT NULL CHECK (status IN ('SUCCESS', 'FAILED')),
    source_scope VARCHAR(160) NOT NULL,
    rows_tiempo INTEGER NOT NULL DEFAULT 0 CHECK (rows_tiempo >= 0),
    rows_destino INTEGER NOT NULL DEFAULT 0 CHECK (rows_destino >= 0),
    rows_actividad INTEGER NOT NULL DEFAULT 0 CHECK (rows_actividad >= 0),
    rows_origen INTEGER NOT NULL DEFAULT 0 CHECK (rows_origen >= 0),
    notes TEXT
);

CREATE INDEX IF NOT EXISTS ix_actividad_destino_fecha ON fact_actividad_turistica (id_destino, id_fecha);
CREATE INDEX IF NOT EXISTS ix_actividad_fecha ON fact_actividad_turistica (id_fecha);
CREATE INDEX IF NOT EXISTS ix_origen_tipo_fecha ON fact_turistas_origen (tipo_turista, id_fecha);
CREATE INDEX IF NOT EXISTS ix_tiempo_anio_mes ON dim_tiempo (anio, mes);

-- Vista mensual consolidada: cruza fact_actividad_turistica con la suma agregada de fact_turistas_origen
-- por (id_fecha, id_destino) para evitar duplicar cuartos o derrama económica.
-- Todas las tasas se calculan como razón de sumas (nunca promediando porcentajes).
CREATE OR REPLACE VIEW vw_kpis_mensuales AS
SELECT
    t.id_fecha,
    t.fecha,
    t.anio,
    t.mes,
    t.nombre_mes,
    t.trimestre,
    d.id_destino,
    d.nombre_destino,
    d.region,
    d.tipo_destino,
    f.cuartos_disponibles,
    f.cuartos_ocupados,
    f.ocupacion_pct_oficial,
    ROUND(100.0 * f.cuartos_ocupados / NULLIF(f.cuartos_disponibles, 0), 2) AS ocupacion_pct_calculada,
    f.derrama_economica_mxn,
    f.llegada_turistas,
    f.estadia_promedio,
    f.gasto_promedio_mxn,
    f.meta_ocupacion_pct,
    f.tipo_cifra,
    COALESCE(o.turistas_nacionales, 0) AS turistas_nacionales,
    COALESCE(o.turistas_extranjeros, 0) AS turistas_extranjeros,
    COALESCE(o.turistas_origen_total, 0) AS turistas_origen_total,
    ROUND(100.0 * COALESCE(o.turistas_extranjeros, 0) / NULLIF(f.llegada_turistas, 0), 2) AS pct_turistas_extranjeros,
    ROUND(f.derrama_economica_mxn / NULLIF(f.llegada_turistas, 0), 2) AS derrama_por_turista_mxn,
    ROUND(f.derrama_economica_mxn / NULLIF(f.cuartos_disponibles, 0), 2) AS derrama_por_cuarto_disponible_mxn
FROM fact_actividad_turistica f
JOIN dim_tiempo t USING (id_fecha)
JOIN dim_destino d USING (id_destino)
LEFT JOIN (
    SELECT
        id_fecha,
        id_destino,
        SUM(CASE WHEN tipo_turista = 'Nacional' THEN turistas ELSE 0 END) AS turistas_nacionales,
        SUM(CASE WHEN tipo_turista = 'Extranjero' THEN turistas ELSE 0 END) AS turistas_extranjeros,
        SUM(turistas) AS turistas_origen_total
    FROM fact_turistas_origen
    GROUP BY id_fecha, id_destino
) o USING (id_fecha, id_destino);

-- Vista anual con variación interanual (YoY) usando LAG() por destino y año.
CREATE OR REPLACE VIEW vw_kpis_anuales_yoy AS
WITH agregado_anual AS (
    SELECT
        t.anio,
        COUNT(DISTINCT t.mes) AS meses_cubiertos,
        d.id_destino,
        d.nombre_destino,
        d.region,
        SUM(f.cuartos_disponibles) AS cuartos_disponibles,
        SUM(f.cuartos_ocupados) AS cuartos_ocupados,
        ROUND(100.0 * SUM(f.cuartos_ocupados) / NULLIF(SUM(f.cuartos_disponibles), 0), 2) AS ocupacion_pct,
        SUM(f.derrama_economica_mxn) AS derrama_economica_mxn,
        SUM(f.llegada_turistas) AS llegada_turistas,
        SUM(COALESCE(o.turistas_nacionales, 0)) AS turistas_nacionales,
        SUM(COALESCE(o.turistas_extranjeros, 0)) AS turistas_extranjeros,
        ROUND(SUM(f.derrama_economica_mxn) / NULLIF(SUM(f.llegada_turistas), 0), 2) AS derrama_por_turista_mxn
    FROM fact_actividad_turistica f
    JOIN dim_tiempo t USING (id_fecha)
    JOIN dim_destino d USING (id_destino)
    LEFT JOIN (
        SELECT
            id_fecha,
            id_destino,
            SUM(CASE WHEN tipo_turista = 'Nacional' THEN turistas ELSE 0 END) AS turistas_nacionales,
            SUM(CASE WHEN tipo_turista = 'Extranjero' THEN turistas ELSE 0 END) AS turistas_extranjeros
        FROM fact_turistas_origen
        GROUP BY id_fecha, id_destino
    ) o USING (id_fecha, id_destino)
    GROUP BY t.anio, d.id_destino, d.nombre_destino, d.region
),
con_previo AS (
    SELECT
        *,
        LAG(anio) OVER (PARTITION BY id_destino ORDER BY anio) AS prev_anio,
        LAG(meses_cubiertos) OVER (PARTITION BY id_destino ORDER BY anio) AS prev_meses,
        LAG(ocupacion_pct) OVER (PARTITION BY id_destino ORDER BY anio) AS prev_ocupacion_pct,
        LAG(derrama_economica_mxn) OVER (PARTITION BY id_destino ORDER BY anio) AS prev_derrama_mxn,
        LAG(llegada_turistas) OVER (PARTITION BY id_destino ORDER BY anio) AS prev_llegada_turistas
    FROM agregado_anual
)
SELECT
    anio,
    meses_cubiertos,
    id_destino,
    nombre_destino,
    region,
    cuartos_disponibles,
    cuartos_ocupados,
    ocupacion_pct,
    CASE
        WHEN prev_anio = anio - 1 AND prev_meses = meses_cubiertos
            THEN ROUND(ocupacion_pct - prev_ocupacion_pct, 2)
        ELSE NULL
    END AS variacion_ocupacion_yoy_pp,
    derrama_economica_mxn,
    CASE
        WHEN prev_anio = anio - 1 AND prev_meses = meses_cubiertos
            THEN ROUND(100.0 * (derrama_economica_mxn - prev_derrama_mxn) / NULLIF(prev_derrama_mxn, 0), 2)
        ELSE NULL
    END AS variacion_derrama_yoy_pct,
    llegada_turistas,
    CASE
        WHEN prev_anio = anio - 1 AND prev_meses = meses_cubiertos
            THEN ROUND(100.0 * (llegada_turistas - prev_llegada_turistas) / NULLIF(prev_llegada_turistas, 0), 2)
        ELSE NULL
    END AS variacion_turistas_yoy_pct,
    turistas_nacionales,
    turistas_extranjeros,
    derrama_por_turista_mxn
FROM con_previo
ORDER BY id_destino, anio;
