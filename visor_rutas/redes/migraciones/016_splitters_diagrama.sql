-- Splitters leídos de los diagramas de Visio (docs/modulo_redes/ESTUDIO_SPLITTERS.md).
--
-- splitters_diagrama   un renglón por splitter dibujado en un diagrama (`md5` del archivo + `clave` = posición en cm). Cada vez que se genera una
--                      ruta de fusión se leen los diagramas de sus mufas y se guarda lo detectado (`auto`: clase por color o palabra, relación 1/8 o 1/16,
--                      puertos leídos de la lista de clientes) sin tocar lo que una persona ya confirmó. `confirmado` es lo que una persona dijo en
--                      pantalla ({clase, puertos: {"1": "libre"|"ocupado"}}): gana sobre lo automático y sirve de verdad de referencia para mejorar la
--                      lectura. Es de todos (la red es compartida). Tabla nueva: no cambia datos existentes.

CREATE TABLE IF NOT EXISTS redes.splitters_diagrama (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    md5              text NOT NULL CHECK (md5 ~ '^[0-9a-f]{32}$'),
    clave            text NOT NULL CHECK (btrim(clave) <> ''),
    etiqueta         text NOT NULL DEFAULT '',
    x_cm             numeric,
    y_cm             numeric,
    auto             jsonb NOT NULL DEFAULT '{}'::jsonb,
    confirmado       jsonb,
    confirmado_por   bigint REFERENCES redes.usuarios (id),
    confirmado_en    timestamptz,
    veces_visto      integer NOT NULL DEFAULT 1,
    visto_en         timestamptz NOT NULL DEFAULT now(),
    creado_en        timestamptz NOT NULL DEFAULT now(),
    borrado_en       timestamptz,
    version          integer NOT NULL DEFAULT 1,
    UNIQUE (md5, clave)
);
CREATE INDEX IF NOT EXISTS splitters_diagrama_md5_ix ON redes.splitters_diagrama (md5);

