-- respaldo: previo
-- Visor v2, fase 4 (segunda parte): editar lo que ya existe en el KMZ sin tocar el archivo.
--
-- kmz_cambios   un cambio sobre un elemento del KMZ: renombrarlo / moverlo (accion 'editar') o quitarlo del mapa (accion 'borrar').
--               El elemento se identifica por `clave` = carpeta + nombre original + coordenada redondeada (el mismo criterio que
--               ya funcionó con el Visio); `antes` guarda lo original y `despues` lo nuevo. Hay un solo cambio activo por clave
--               y es de todos (la red es compartida). El archivo KMZ y las tablas red_puntos / red_lineas no se modifican:
--               `publicado` queda en false hasta que exista el paso de publicar (el presupuesto sigue usando PostGIS tal cual).
-- No toca elementos, cables ni proyectos.

CREATE TABLE IF NOT EXISTS redes.kmz_cambios (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clave           text NOT NULL CHECK (btrim(clave) <> ''),
    carpeta         text NOT NULL,
    nombre          text NOT NULL,
    tipo            text NOT NULL CHECK (tipo IN ('punto', 'linea')),
    accion          text NOT NULL CHECK (accion IN ('editar', 'borrar')),
    antes           jsonb NOT NULL,
    despues         jsonb,
    publicado       boolean NOT NULL DEFAULT false,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS kmz_cambios_clave_uk ON redes.kmz_cambios (clave) WHERE borrado_en IS NULL;
