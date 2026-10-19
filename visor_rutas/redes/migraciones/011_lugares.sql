-- respaldo: previo
-- Visor v2, fase 3: "Mis lugares" (carpetas y elementos propios de cada usuario, como en Google Earth).
--
-- lugares_carpetas     árbol de carpetas por usuario (padre_id); `visible` es la casilla de una carpeta sin elementos,
--                      `expandida` lo que se ve abierto. Se puede compartir una carpeta (y con ella sus subcarpetas).
-- lugares_elementos    marca de posición, ruta, polígono y, cuando se dibuje red en una carpeta (fase 4), mufa, poste,
--                      cliente, nodo, odf y cable. `estilo` (ícono, color, escala, línea, relleno), `vista` (centro y zoom
--                      guardados) y `propiedades` (en un cable: clase, ADSS/FLAT, hilos, a qué se une cada extremo) son jsonb.
-- lugares_adjuntos     imágenes locales de la descripción (PNG / JPEG / WEBP / GIF de hasta 2 MB), en la base: viajan con
--                      los respaldos de la base y funcionan en modo remoto.
-- lugares_compartidas  con quién se comparte una carpeta (solo lectura o edición). El dueño siempre puede todo.
-- No toca las tablas de proyectos ni de la red: es lo personal de cada quien.

CREATE TABLE IF NOT EXISTS redes.lugares_carpetas (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id      bigint NOT NULL REFERENCES redes.usuarios (id),
    padre_id        bigint REFERENCES redes.lugares_carpetas (id),
    nombre          text NOT NULL CHECK (btrim(nombre) <> ''),
    orden           integer NOT NULL DEFAULT 0,
    visible         boolean NOT NULL DEFAULT true,
    expandida       boolean NOT NULL DEFAULT false,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1,
    CHECK (padre_id IS NULL OR padre_id <> id)
);
CREATE INDEX IF NOT EXISTS lugares_carpetas_usuario_ix ON redes.lugares_carpetas (usuario_id, padre_id) WHERE borrado_en IS NULL;

CREATE TABLE IF NOT EXISTS redes.lugares_elementos (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    carpeta_id       bigint NOT NULL REFERENCES redes.lugares_carpetas (id),
    tipo             text NOT NULL CHECK (tipo IN ('marca', 'ruta', 'poligono', 'mufa', 'poste', 'cliente', 'nodo', 'odf', 'cable')),
    nombre           text NOT NULL CHECK (btrim(nombre) <> ''),
    descripcion_html text,
    geom             geometry(Geometry, 4326) NOT NULL,
    estilo           jsonb NOT NULL DEFAULT '{}'::jsonb,
    vista            jsonb,
    propiedades      jsonb NOT NULL DEFAULT '{}'::jsonb,
    orden            integer NOT NULL DEFAULT 0,
    visible          boolean NOT NULL DEFAULT true,
    creado_en        timestamptz NOT NULL DEFAULT now(),
    creado_por       bigint REFERENCES redes.usuarios (id),
    actualizado_en   timestamptz,
    actualizado_por  bigint REFERENCES redes.usuarios (id),
    borrado_en       timestamptz,
    version          integer NOT NULL DEFAULT 1,
    CHECK ((tipo IN ('marca', 'mufa', 'poste', 'cliente', 'nodo', 'odf') AND GeometryType(geom) = 'POINT')
        OR (tipo IN ('ruta', 'cable') AND GeometryType(geom) = 'LINESTRING')
        OR (tipo = 'poligono' AND GeometryType(geom) = 'POLYGON'))
);
CREATE INDEX IF NOT EXISTS lugares_elementos_carpeta_ix ON redes.lugares_elementos (carpeta_id) WHERE borrado_en IS NULL;
CREATE INDEX IF NOT EXISTS lugares_elementos_geom_ix ON redes.lugares_elementos USING gist (geom) WHERE borrado_en IS NULL;

CREATE TABLE IF NOT EXISTS redes.lugares_adjuntos (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    elemento_id bigint NOT NULL REFERENCES redes.lugares_elementos (id),
    nombre      text NOT NULL,
    tipo        text NOT NULL,
    datos       bytea NOT NULL,
    creado_en   timestamptz NOT NULL DEFAULT now(),
    creado_por  bigint REFERENCES redes.usuarios (id),
    borrado_en  timestamptz
);
CREATE INDEX IF NOT EXISTS lugares_adjuntos_elemento_ix ON redes.lugares_adjuntos (elemento_id) WHERE borrado_en IS NULL;

CREATE TABLE IF NOT EXISTS redes.lugares_compartidas (
    carpeta_id    bigint NOT NULL REFERENCES redes.lugares_carpetas (id),
    usuario_id    bigint NOT NULL REFERENCES redes.usuarios (id),
    puede_editar  boolean NOT NULL DEFAULT false,
    creado_en     timestamptz NOT NULL DEFAULT now(),
    creado_por    bigint REFERENCES redes.usuarios (id),
    PRIMARY KEY (carpeta_id, usuario_id)
);
