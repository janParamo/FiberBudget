-- =====================================================================
-- Base de datos de la red de fibra óptica (IDEAY)
-- Fuente: diagramas Visio (.vsd / .vsdx) + Excel de anillos
-- Motor: SQLite (compatible con PostgreSQL con cambios mínimos)
-- =====================================================================
PRAGMA foreign_keys = ON;

-- Cada ejecución del importador queda registrada
CREATE TABLE IF NOT EXISTS importaciones (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha             TEXT    NOT NULL,            -- ISO 8601
    carpeta_origen    TEXT    NOT NULL,
    archivos_total    INTEGER NOT NULL DEFAULT 0,
    archivos_ok       INTEGER NOT NULL DEFAULT 0,
    archivos_error    INTEGER NOT NULL DEFAULT 0,
    archivos_duplicados INTEGER NOT NULL DEFAULT 0,
    nodos             INTEGER NOT NULL DEFAULT 0,
    enlaces           INTEGER NOT NULL DEFAULT 0,
    servicios         INTEGER NOT NULL DEFAULT 0,
    notas             TEXT
);

-- Inventario de archivos leídos
CREATE TABLE IF NOT EXISTS archivos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    importacion_id    INTEGER NOT NULL REFERENCES importaciones(id),
    ruta_relativa     TEXT    NOT NULL,
    carpeta           TEXT,                        -- tramo / zona (carpeta padre)
    nombre            TEXT    NOT NULL,
    formato           TEXT    NOT NULL,            -- vsd | vsdx | xlsx
    tipo_diagrama     TEXT,                        -- mufa | subred | red | excel_anillos
    tamano_bytes      INTEGER,
    md5               TEXT    NOT NULL,
    modificado        TEXT,
    estado            TEXT    NOT NULL,            -- ok | error | duplicado
    error             TEXT,
    duplicado_de      INTEGER REFERENCES archivos(id),
    textos            INTEGER DEFAULT 0,
    nodos_detectados  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_archivos_md5 ON archivos(md5);

-- Nodos físicos de la red: mufas, nodos, ODF, mini nodos, reservas
CREATE TABLE IF NOT EXISTS nodos (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre             TEXT    NOT NULL,
    nombre_normalizado TEXT    NOT NULL,
    tipo               TEXT    NOT NULL,           -- MUFA | NODO | MINI_NODO | ODF | RESERVA | SPLITTER | CLIENTE | OTRO
    propietario        TEXT,                       -- IDEAY | UFINET | ENATREL ... si el nombre lo indica
    lat                REAL,
    lon                REAL,
    fuente_coord       TEXT,                       -- visio | excel | estimada_vecinos | NULL
    coord_dispersion_m REAL,                       -- diferencia máxima entre fuentes
    zona               TEXT,                       -- carpeta/tramo donde aparece más
    num_apariciones    INTEGER NOT NULL DEFAULT 0,
    notas              TEXT,                       -- SANGRIA, VALIDAR, NO PROYECTAR ACOMETIDAS...
    requiere_revision  INTEGER NOT NULL DEFAULT 0,
    motivo_revision    TEXT
);
CREATE INDEX IF NOT EXISTS ix_nodos_nombre ON nodos(nombre_normalizado);
CREATE INDEX IF NOT EXISTS ix_nodos_latlon ON nodos(lat, lon);

-- Cada vez que un nodo aparece en un archivo (trazabilidad)
CREATE TABLE IF NOT EXISTS nodo_apariciones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nodo_id         INTEGER NOT NULL REFERENCES nodos(id),
    archivo_id      INTEGER NOT NULL REFERENCES archivos(id),
    rol             TEXT,                          -- principal | vecino | red | excel
    nombre_original TEXT,
    lat             REAL,
    lon             REAL,
    texto_original  TEXT
);
CREATE INDEX IF NOT EXISTS ix_apar_nodo ON nodo_apariciones(nodo_id);

-- Cables / tramos entre nodos
CREATE TABLE IF NOT EXISTS enlaces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nodo_a_id       INTEGER NOT NULL REFERENCES nodos(id),
    nodo_b_id       INTEGER NOT NULL REFERENCES nodos(id),
    hilos_cable     INTEGER,                       -- capacidad del cable (12H, 24H, 48H...)
    longitud_m      REAL,                          -- según etiqueta del diagrama
    hilos_usados    TEXT,                          -- p. ej. "HILOS 17 / 18" (Excel)
    enlace_logico   TEXT,                          -- p. ej. "LAS COLINAS / MERCED"
    fuente          TEXT    NOT NULL,              -- visio_mufa | visio_red | visio_linea | excel
    confianza       TEXT    NOT NULL,              -- alta | media | baja
    archivo_id      INTEGER REFERENCES archivos(id),
    texto_original  TEXT
);
CREATE INDEX IF NOT EXISTS ix_enlaces_a ON enlaces(nodo_a_id);
CREATE INDEX IF NOT EXISTS ix_enlaces_b ON enlaces(nodo_b_id);

-- Clientes / servicios / splitters vistos en los diagramas
CREATE TABLE IF NOT EXISTS servicios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nodo_id         INTEGER REFERENCES nodos(id),
    archivo_id      INTEGER NOT NULL REFERENCES archivos(id),
    tipo            TEXT    NOT NULL,              -- cliente | splitter | enlace | otro
    codigo_cliente  TEXT,                          -- C23227
    id_servicio     TEXT,                          -- ID261553
    descripcion     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_serv_cliente ON servicios(codigo_cliente);

-- Recorridos de anillos (Excel "ACTUALIZACION ENLACES")
CREATE TABLE IF NOT EXISTS anillo_tramos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    archivo_id      INTEGER NOT NULL REFERENCES archivos(id),
    hoja            TEXT    NOT NULL,
    enlace          TEXT,
    orden           INTEGER,
    nodo_id         INTEGER REFERENCES nodos(id),
    en_mufa         TEXT,
    lat             REAL,
    lon             REAL,
    de_mufa         TEXT,
    hilo_entrante   TEXT,
    hacia_mufa      TEXT,
    hilo_saliente   TEXT,
    nota            TEXT
);

-- Todo el texto extraído, para reprocesar sin volver a convertir
CREATE TABLE IF NOT EXISTS textos_crudos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    archivo_id      INTEGER NOT NULL REFERENCES archivos(id),
    pagina          INTEGER,
    x_cm            REAL,
    y_cm            REAL,
    texto           TEXT    NOT NULL,
    clasificacion   TEXT                           -- nodo | cable | cliente | numeracion | otro
);
CREATE INDEX IF NOT EXISTS ix_textos_archivo ON textos_crudos(archivo_id);

-- PILOTO: fusiones detectadas automáticamente en los diagramas (red_fibra/fusiones.py,
-- red_fibra/piloto_fusiones.py). El importador no la llena: queda vacía tras cada importación.
CREATE TABLE IF NOT EXISTS fusiones_piloto (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    archivo_id      INTEGER NOT NULL REFERENCES archivos(id),
    pagina          INTEGER NOT NULL DEFAULT 0,
    entrada         TEXT    NOT NULL,              -- cable / buffer / hilo de entrada
    salida          TEXT    NOT NULL,              -- cable / buffer / hilo de salida, o puerto de splitter / cliente
    hilo_entrada    INTEGER,
    hilo_salida     INTEGER,
    color           TEXT,                          -- color real del trazo (#rrggbb)
    color_tia       TEXT,                          -- "10 violeta" | "otro"
    confianza       REAL    NOT NULL,              -- 0 a 1
    motivo          TEXT,
    x1_cm REAL, y1_cm REAL, x2_cm REAL, y2_cm REAL, -- extremos del trazo en el dibujo
    puntos          TEXT,                          -- JSON [[x, y], ...] en cm
    creado          TEXT
);
CREATE INDEX IF NOT EXISTS ix_fusiones_archivo ON fusiones_piloto(archivo_id);

-- ---------------------------------------------------------------------
-- Vistas de apoyo
-- ---------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_nodos_ubicados AS
SELECT id, nombre, tipo, propietario, lat, lon, fuente_coord, zona, num_apariciones, notas
FROM nodos
WHERE lat IS NOT NULL AND lon IS NOT NULL;

CREATE VIEW IF NOT EXISTS v_enlaces_detalle AS
SELECT e.id, a.nombre AS nodo_a, b.nombre AS nodo_b, e.hilos_cable, e.longitud_m,
       e.hilos_usados, e.enlace_logico, e.fuente, e.confianza, f.ruta_relativa AS archivo
FROM enlaces e
JOIN nodos a ON a.id = e.nodo_a_id
JOIN nodos b ON b.id = e.nodo_b_id
LEFT JOIN archivos f ON f.id = e.archivo_id;

CREATE VIEW IF NOT EXISTS v_revision AS
SELECT id, nombre, tipo, lat, lon, motivo_revision, zona
FROM nodos WHERE requiere_revision = 1;
