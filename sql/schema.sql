-- Modelo dimensional para el dashboard de ocupación hotelera de Oaxaca.
-- Ejecutar en una base vacía antes de cargar datos con etl/etl.py.

CREATE TABLE IF NOT EXISTS dim_tiempo (
    id_fecha INTEGER PRIMARY KEY,                 -- formato AAAAMMDD
    fecha DATE NOT NULL UNIQUE,
    anio SMALLINT NOT NULL,
    mes SMALLINT NOT NULL CHECK (mes BETWEEN 1 AND 12),
    nombre_mes VARCHAR(15) NOT NULL,
    dia SMALLINT NOT NULL CHECK (dia BETWEEN 1 AND 31),
    dia_semana SMALLINT NOT NULL CHECK (dia_semana BETWEEN 1 AND 7),
    trimestre SMALLINT NOT NULL CHECK (trimestre BETWEEN 1 AND 4)
);

CREATE TABLE IF NOT EXISTS dim_hotel (
    id_hotel VARCHAR(20) PRIMARY KEY,
    nombre_hotel VARCHAR(120) NOT NULL,
    zona_turistica VARCHAR(60) NOT NULL,
    categoria_hotel SMALLINT NOT NULL CHECK (categoria_hotel BETWEEN 1 AND 5),
    num_habitaciones INTEGER NOT NULL CHECK (num_habitaciones > 0)
);

CREATE TABLE IF NOT EXISTS fact_ocupacion_diaria (
    id_fecha INTEGER NOT NULL REFERENCES dim_tiempo(id_fecha),
    id_hotel VARCHAR(20) NOT NULL REFERENCES dim_hotel(id_hotel),
    habitaciones_disponibles INTEGER NOT NULL CHECK (habitaciones_disponibles > 0),
    habitaciones_ocupadas INTEGER NOT NULL CHECK (habitaciones_ocupadas BETWEEN 0 AND habitaciones_disponibles),
    ingreso_hospedaje NUMERIC(14,2) NOT NULL CHECK (ingreso_hospedaje >= 0),
    reservaciones INTEGER NOT NULL CHECK (reservaciones >= 0),
    cancelaciones INTEGER NOT NULL CHECK (cancelaciones BETWEEN 0 AND reservaciones),
    meta_ocupacion_pct NUMERIC(5,2) NOT NULL CHECK (meta_ocupacion_pct BETWEEN 0 AND 100),
    PRIMARY KEY (id_fecha, id_hotel)
);

CREATE TABLE IF NOT EXISTS fact_turistas (
    id_fecha INTEGER NOT NULL REFERENCES dim_tiempo(id_fecha),
    id_hotel VARCHAR(20) NOT NULL REFERENCES dim_hotel(id_hotel),
    origen VARCHAR(60) NOT NULL,
    turistas_hospedados INTEGER NOT NULL CHECK (turistas_hospedados >= 0),
    PRIMARY KEY (id_fecha, id_hotel, origen)
);

CREATE INDEX IF NOT EXISTS ix_ocupacion_hotel_fecha ON fact_ocupacion_diaria (id_hotel, id_fecha);
CREATE INDEX IF NOT EXISTS ix_turistas_origen_fecha ON fact_turistas (origen, id_fecha);

-- Las tasas se calculan como razón de sumas para el periodo seleccionado.
CREATE OR REPLACE VIEW vw_kpis_diarios AS
SELECT
    t.anio, t.mes, t.nombre_mes, h.zona_turistica, h.categoria_hotel,
    SUM(f.habitaciones_disponibles) AS habitaciones_disponibles,
    SUM(f.habitaciones_ocupadas) AS habitaciones_ocupadas,
    SUM(f.ingreso_hospedaje) AS ingreso_hospedaje,
    SUM(f.reservaciones) AS reservaciones,
    SUM(f.cancelaciones) AS cancelaciones,
    ROUND(100.0 * SUM(f.habitaciones_ocupadas) / NULLIF(SUM(f.habitaciones_disponibles), 0), 2) AS ocupacion_pct,
    ROUND(SUM(f.ingreso_hospedaje) / NULLIF(SUM(f.habitaciones_ocupadas), 0), 2) AS adr,
    ROUND(SUM(f.ingreso_hospedaje) / NULLIF(SUM(f.habitaciones_disponibles), 0), 2) AS revpar,
    ROUND(100.0 * SUM(f.cancelaciones) / NULLIF(SUM(f.reservaciones), 0), 2) AS tasa_cancelacion_pct,
    ROUND(SUM(f.habitaciones_disponibles * f.meta_ocupacion_pct) / NULLIF(SUM(f.habitaciones_disponibles), 0), 2) AS meta_ocupacion_pct
FROM fact_ocupacion_diaria f
JOIN dim_tiempo t USING (id_fecha)
JOIN dim_hotel h USING (id_hotel)
GROUP BY t.anio, t.mes, t.nombre_mes, h.zona_turistica, h.categoria_hotel;

-- Consulta anual de referencia: ocupación y su diferencia contra el año anterior.
WITH anual AS (
    SELECT t.anio, SUM(f.habitaciones_ocupadas)::NUMERIC / NULLIF(SUM(f.habitaciones_disponibles), 0) * 100 AS ocupacion_pct
    FROM fact_ocupacion_diaria f JOIN dim_tiempo t USING (id_fecha)
    GROUP BY t.anio
)
SELECT anio, ROUND(ocupacion_pct, 2) AS ocupacion_pct,
       ROUND(ocupacion_pct - LAG(ocupacion_pct) OVER (ORDER BY anio), 2) AS variacion_interanual_pp
FROM anual ORDER BY anio;
