-- Nodo = el lugar físico: aloja ODF y OLT. Tres niveles: el nodo (en el esquema general), sus ODF (con su cantidad de puertos) y sus OLT (con su cantidad de hilos), y los enlaces
-- entre ellos: el puerto de una OLT va a un puerto de un ODF y/o a un hilo de un cable del nodo (que lleva a las mufas). Un ODF puede estar conectado a varias OLT y una OLT a varios ODF.
CREATE TABLE IF NOT EXISTS redes.nodo_odfs (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nodo_id         bigint NOT NULL REFERENCES redes.elementos (id),
    nombre          text NOT NULL CHECK (btrim(nombre) <> ''),
    puertos         integer NOT NULL CHECK (puertos BETWEEN 1 AND 576),
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS nodo_odfs_nombre_ux ON redes.nodo_odfs (nodo_id, lower(nombre)) WHERE borrado_en IS NULL;

CREATE TABLE IF NOT EXISTS redes.nodo_olts (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nodo_id         bigint NOT NULL REFERENCES redes.elementos (id),
    nombre          text NOT NULL CHECK (btrim(nombre) <> ''),
    puertos         integer NOT NULL CHECK (puertos BETWEEN 1 AND 576),
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS nodo_olts_nombre_ux ON redes.nodo_olts (nodo_id, lower(nombre)) WHERE borrado_en IS NULL;

CREATE TABLE IF NOT EXISTS redes.nodo_enlaces (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nodo_id         bigint NOT NULL REFERENCES redes.elementos (id),
    olt_id          bigint NOT NULL REFERENCES redes.nodo_olts (id),
    olt_puerto      integer NOT NULL CHECK (olt_puerto >= 1),
    odf_id          bigint REFERENCES redes.nodo_odfs (id),
    odf_puerto      integer CHECK (odf_puerto >= 1),
    hilo_id         bigint REFERENCES redes.hilos (id),
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1,
    CHECK ((odf_id IS NULL) = (odf_puerto IS NULL)),
    CHECK (odf_id IS NOT NULL OR hilo_id IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS nodo_enlaces_olt_ux ON redes.nodo_enlaces (olt_id, olt_puerto) WHERE borrado_en IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS nodo_enlaces_odf_ux ON redes.nodo_enlaces (odf_id, odf_puerto) WHERE borrado_en IS NULL AND odf_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS nodo_enlaces_hilo_ux ON redes.nodo_enlaces (hilo_id) WHERE borrado_en IS NULL AND hilo_id IS NOT NULL;
