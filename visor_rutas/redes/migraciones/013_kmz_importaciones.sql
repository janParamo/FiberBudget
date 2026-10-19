-- respaldo: previo
-- Visor v2, fase 5: importar un KMZ a la red (nueva ruta o actualización de toda la red), con comparación, revisión, aplicar,
-- publicar en PostGIS y revertir.
--
-- kmz_importaciones          un archivo importado: nombre, md5, modo ('nueva' | 'actualizacion'), el modo que se sugirió, estado
--                            (pendiente → aplicada → revertida; o descartada), conteos por clase / tipo / carpeta, quién y cuándo la aplicó
--                            y la publicación en red_puntos / red_lineas (con lo que había antes, para revertirla).
-- kmz_importacion_detalle    lo que cambia: un renglón por elemento NUEVO, MODIFICADO o ELIMINADO (los que no cambian solo se cuentan).
--                            Guarda la geometría del archivo y la actual (GeoJSON), qué cambió y si se acepta. Al aplicar, lo modificado /
--                            eliminado de un elemento del KMZ queda en kmz_cambios (012) y lo nuevo se dibuja como capa «Importados».
-- El archivo KMZ y las tablas red_puntos / red_lineas no se tocan al importar ni al aplicar: solo al publicar, y de forma reversible.

CREATE TABLE IF NOT EXISTS redes.kmz_importaciones (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    archivo         text NOT NULL,
    md5             text NOT NULL,
    modo            text NOT NULL CHECK (modo IN ('nueva', 'actualizacion')),
    modo_sugerido   text,
    estado          text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aplicada', 'revertida', 'descartada')),
    conteos         jsonb NOT NULL DEFAULT '{}'::jsonb,
    aplicada_en     timestamptz,
    aplicada_por    bigint REFERENCES redes.usuarios (id),
    revertida_en    timestamptz,
    publicada       boolean NOT NULL DEFAULT false,
    publicacion     jsonb,
    publicada_en    timestamptz,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS kmz_importaciones_estado_ix ON redes.kmz_importaciones (estado, id) WHERE borrado_en IS NULL;

CREATE TABLE IF NOT EXISTS redes.kmz_importacion_detalle (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    importacion_id bigint NOT NULL REFERENCES redes.kmz_importaciones (id),
    clase          text NOT NULL CHECK (clase IN ('nuevo', 'modificado', 'eliminado')),
    carpeta        text NOT NULL,
    nombre         text NOT NULL,
    tipo           text NOT NULL CHECK (tipo IN ('punto', 'linea', 'poligono')),
    geom_nueva     jsonb,
    geom_actual    jsonb,
    descripcion    text,
    props          jsonb NOT NULL DEFAULT '{}'::jsonb,
    aceptado       boolean NOT NULL DEFAULT true,
    aplicado       boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS kmz_importacion_detalle_ix ON redes.kmz_importacion_detalle (importacion_id, clase);

ALTER TABLE redes.kmz_cambios ADD COLUMN IF NOT EXISTS importacion_id bigint;
