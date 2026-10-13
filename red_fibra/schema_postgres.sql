-- =====================================================================
-- Red de fibra óptica IDEAY - esquema PostgreSQL
-- Se crea dentro del esquema "red_fibra". No requiere PostGIS.
-- Ejecutar una sola vez (pgAdmin > Query Tool, o psql -f schema_postgres.sql)
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS red_fibra;
SET search_path TO red_fibra;

CREATE TABLE IF NOT EXISTS importaciones (
    id                  BIGINT PRIMARY KEY,
    fecha               TIMESTAMP NOT NULL,
    carpeta_origen      TEXT NOT NULL,
    archivos_total      INTEGER NOT NULL DEFAULT 0,
    archivos_ok         INTEGER NOT NULL DEFAULT 0,
    archivos_error      INTEGER NOT NULL DEFAULT 0,
    archivos_duplicados INTEGER NOT NULL DEFAULT 0,
    nodos               INTEGER NOT NULL DEFAULT 0,
    enlaces             INTEGER NOT NULL DEFAULT 0,
    servicios           INTEGER NOT NULL DEFAULT 0,
    notas               TEXT,
    publicado_en        TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS archivos (
    id               BIGINT PRIMARY KEY,
    importacion_id   BIGINT NOT NULL REFERENCES importaciones(id),
    ruta_relativa    TEXT NOT NULL,
    carpeta          TEXT,
    nombre           TEXT NOT NULL,
    formato          TEXT NOT NULL,
    tipo_diagrama    TEXT,
    tamano_bytes     BIGINT,
    md5              TEXT NOT NULL,
    modificado       TIMESTAMP,
    estado           TEXT NOT NULL,
    error            TEXT,
    duplicado_de     BIGINT REFERENCES archivos(id),
    textos           INTEGER DEFAULT 0,
    nodos_detectados INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_archivos_md5 ON archivos(md5);

CREATE TABLE IF NOT EXISTS nodos (
    id                 BIGINT PRIMARY KEY,
    nombre             TEXT NOT NULL,
    nombre_normalizado TEXT NOT NULL,
    tipo               TEXT NOT NULL,      -- MUFA | NODO | MINI_NODO | ODF | RESERVA | SPLITTER | CLIENTE | OTRO
    propietario        TEXT,
    lat                DOUBLE PRECISION,
    lon                DOUBLE PRECISION,
    fuente_coord       TEXT,               -- visio | excel | excel+visio | estimada_vecinos | NULL
    coord_dispersion_m DOUBLE PRECISION,
    zona               TEXT,
    num_apariciones    INTEGER NOT NULL DEFAULT 0,
    notas              TEXT,
    requiere_revision  BOOLEAN NOT NULL DEFAULT FALSE,
    motivo_revision    TEXT
);
CREATE INDEX IF NOT EXISTS ix_nodos_nombre ON nodos(nombre_normalizado);
CREATE INDEX IF NOT EXISTS ix_nodos_latlon ON nodos(lat, lon);
CREATE INDEX IF NOT EXISTS ix_nodos_tipo   ON nodos(tipo);

CREATE TABLE IF NOT EXISTS nodo_apariciones (
    id              BIGINT PRIMARY KEY,
    nodo_id         BIGINT NOT NULL REFERENCES nodos(id),
    archivo_id      BIGINT NOT NULL REFERENCES archivos(id),
    rol             TEXT,
    nombre_original TEXT,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    texto_original  TEXT
);
CREATE INDEX IF NOT EXISTS ix_apar_nodo ON nodo_apariciones(nodo_id);

CREATE TABLE IF NOT EXISTS enlaces (
    id             BIGINT PRIMARY KEY,
    nodo_a_id      BIGINT NOT NULL REFERENCES nodos(id),
    nodo_b_id      BIGINT NOT NULL REFERENCES nodos(id),
    hilos_cable    INTEGER,
    longitud_m     DOUBLE PRECISION,
    hilos_usados   TEXT,
    enlace_logico  TEXT,
    fuente         TEXT NOT NULL,          -- excel | visio_mufa | visio_red | visio_linea
    confianza      TEXT NOT NULL,          -- alta | media | baja
    archivo_id     BIGINT REFERENCES archivos(id),
    texto_original TEXT
);
CREATE INDEX IF NOT EXISTS ix_enlaces_a ON enlaces(nodo_a_id);
CREATE INDEX IF NOT EXISTS ix_enlaces_b ON enlaces(nodo_b_id);

CREATE TABLE IF NOT EXISTS servicios (
    id             BIGINT PRIMARY KEY,
    nodo_id        BIGINT REFERENCES nodos(id),
    archivo_id     BIGINT NOT NULL REFERENCES archivos(id),
    tipo           TEXT NOT NULL,          -- cliente | splitter | otro
    codigo_cliente TEXT,
    id_servicio    TEXT,
    descripcion    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_serv_cliente ON servicios(codigo_cliente);
CREATE INDEX IF NOT EXISTS ix_serv_nodo    ON servicios(nodo_id);

CREATE TABLE IF NOT EXISTS anillo_tramos (
    id            BIGINT PRIMARY KEY,
    archivo_id    BIGINT NOT NULL REFERENCES archivos(id),
    hoja          TEXT NOT NULL,
    enlace        TEXT,
    orden         INTEGER,
    nodo_id       BIGINT REFERENCES nodos(id),
    en_mufa       TEXT,
    lat           DOUBLE PRECISION,
    lon           DOUBLE PRECISION,
    de_mufa       TEXT,
    hilo_entrante TEXT,
    hacia_mufa    TEXT,
    hilo_saliente TEXT,
    nota          TEXT
);

CREATE TABLE IF NOT EXISTS textos_crudos (
    id            BIGINT PRIMARY KEY,
    archivo_id    BIGINT NOT NULL REFERENCES archivos(id),
    pagina        INTEGER,
    x_cm          DOUBLE PRECISION,
    y_cm          DOUBLE PRECISION,
    texto         TEXT NOT NULL,
    clasificacion TEXT
);
CREATE INDEX IF NOT EXISTS ix_textos_archivo ON textos_crudos(archivo_id);

-- PILOTO: fusiones detectadas automáticamente en los diagramas (red_fibra/fusiones.py)
CREATE TABLE IF NOT EXISTS fusiones_piloto (
    id            BIGINT PRIMARY KEY,
    archivo_id    BIGINT NOT NULL REFERENCES archivos(id),
    pagina        INTEGER NOT NULL DEFAULT 0,
    entrada       TEXT NOT NULL,
    salida        TEXT NOT NULL,
    hilo_entrada  INTEGER,
    hilo_salida   INTEGER,
    color         TEXT,
    color_tia     TEXT,
    confianza     DOUBLE PRECISION NOT NULL,
    motivo        TEXT,
    x1_cm DOUBLE PRECISION, y1_cm DOUBLE PRECISION, x2_cm DOUBLE PRECISION, y2_cm DOUBLE PRECISION,
    puntos        TEXT,
    creado        TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_fusiones_archivo ON fusiones_piloto(archivo_id);

-- ---------------------------------------------------------------------
-- Distancia en metros entre dos coordenadas (fórmula de Haversine)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION distancia_m(lat1 DOUBLE PRECISION, lon1 DOUBLE PRECISION,
                                       lat2 DOUBLE PRECISION, lon2 DOUBLE PRECISION)
RETURNS DOUBLE PRECISION LANGUAGE SQL IMMUTABLE AS $$
    SELECT 2 * 6371000 * asin(sqrt(
        power(sin(radians(lat2 - lat1) / 2), 2) +
        cos(radians(lat1)) * cos(radians(lat2)) * power(sin(radians(lon2 - lon1) / 2), 2)
    ));
$$;

-- ---------------------------------------------------------------------
-- Nodos más cercanos a una coordenada.
-- Ejemplo: SELECT * FROM red_fibra.nodos_cercanos(12.1533, -86.2634, 2000, 5);
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION nodos_cercanos(p_lat DOUBLE PRECISION, p_lon DOUBLE PRECISION,
                                          p_radio_m DOUBLE PRECISION DEFAULT 5000,
                                          p_n INTEGER DEFAULT 5,
                                          p_solo_reales BOOLEAN DEFAULT FALSE)
RETURNS TABLE (id BIGINT, nombre TEXT, tipo TEXT, propietario TEXT, lat DOUBLE PRECISION,
               lon DOUBLE PRECISION, fuente_coord TEXT, zona TEXT, notas TEXT,
               distancia_m DOUBLE PRECISION, enlaces BIGINT, clientes BIGINT)
LANGUAGE SQL STABLE AS $$
    WITH caja AS (
        SELECT p_radio_m / 111320.0 AS dlat,
               p_radio_m / (111320.0 * greatest(cos(radians(p_lat)), 0.1)) AS dlon
    ), candidatos AS (
        SELECT n.*, red_fibra.distancia_m(p_lat, p_lon, n.lat, n.lon) AS dist
        FROM red_fibra.nodos n, caja
        WHERE n.lat BETWEEN p_lat - caja.dlat AND p_lat + caja.dlat
          AND n.lon BETWEEN p_lon - caja.dlon AND p_lon + caja.dlon
          AND n.tipo IN ('MUFA', 'NODO', 'MINI_NODO', 'ODF')
          AND (NOT p_solo_reales OR n.fuente_coord <> 'estimada_vecinos')
    )
    SELECT c.id, c.nombre, c.tipo, c.propietario, c.lat, c.lon, c.fuente_coord, c.zona, c.notas,
           round(c.dist::numeric, 1)::double precision,
           (SELECT count(*) FROM red_fibra.enlaces e WHERE e.nodo_a_id = c.id OR e.nodo_b_id = c.id),
           (SELECT count(DISTINCT s.codigo_cliente) FROM red_fibra.servicios s
             WHERE s.nodo_id = c.id AND s.tipo = 'cliente')
    FROM candidatos c
    WHERE c.dist <= p_radio_m
    ORDER BY c.dist
    LIMIT p_n;
$$;

-- ---------------------------------------------------------------------
-- Vistas de apoyo
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_nodos_ubicados AS
SELECT id, nombre, tipo, propietario, lat, lon, fuente_coord, zona, num_apariciones, notas
FROM nodos WHERE lat IS NOT NULL AND lon IS NOT NULL;

CREATE OR REPLACE VIEW v_enlaces_detalle AS
SELECT e.id, a.nombre AS nodo_a, b.nombre AS nodo_b, e.hilos_cable, e.longitud_m,
       e.hilos_usados, e.enlace_logico, e.fuente, e.confianza, f.ruta_relativa AS archivo
FROM enlaces e
JOIN nodos a ON a.id = e.nodo_a_id
JOIN nodos b ON b.id = e.nodo_b_id
LEFT JOIN archivos f ON f.id = e.archivo_id;

CREATE OR REPLACE VIEW v_revision AS
SELECT id, nombre, tipo, lat, lon, motivo_revision, zona
FROM nodos WHERE requiere_revision;

CREATE OR REPLACE VIEW v_ultima_importacion AS
SELECT * FROM importaciones ORDER BY id DESC LIMIT 1;
