-- Esquema de zona (lienzo): un mapa en blanco por zona donde se acomodan las mufas y los nodos (arrastrandolos desde la lista de la zona) para
-- interconectarlas con cables y, despues, conectar hilo con hilo. No es geografico: x, y son del lienzo.
--
-- lienzos            el lienzo de un proyecto (zona); "General" es el primero. Editable (version y borrado logico).
-- lienzo_elementos   donde esta cada mufa / nodo / ODF en el lienzo; se reemplaza completo al guardar.

CREATE TABLE IF NOT EXISTS redes.lienzos (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id     bigint NOT NULL REFERENCES redes.proyectos (id),
    nombre          text NOT NULL DEFAULT 'General' CHECK (btrim(nombre) <> ''),
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS lienzos_proyecto_nombre_ux ON redes.lienzos (proyecto_id, lower(nombre)) WHERE borrado_en IS NULL;

CREATE TABLE IF NOT EXISTS redes.lienzo_elementos (
    lienzo_id   bigint NOT NULL REFERENCES redes.lienzos (id) ON DELETE CASCADE,
    elemento_id bigint NOT NULL REFERENCES redes.elementos (id),
    x           double precision NOT NULL,
    y           double precision NOT NULL,
    PRIMARY KEY (lienzo_id, elemento_id)
);
CREATE INDEX IF NOT EXISTS lienzo_elementos_elemento_ix ON redes.lienzo_elementos (elemento_id);
