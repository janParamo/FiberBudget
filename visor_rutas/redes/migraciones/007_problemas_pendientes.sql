-- Fase 7: Problemas y Pendientes (el Backup son archivos: no usa tablas).
--
-- problemas        ligados a un elemento (mufa, poste, cliente, nodo) o a un cable del proyecto.
--                  severidad: baja | media | alta | critica; estado: abierto | en_proceso | cerrado.
--                  ubicacion: dónde estaba el elemento / la mitad del cable al guardar (el mapa usa la
--                  posición actual del elemento si sigue existiendo).
-- problema_fotos   fotos del problema (PNG / JPEG / WEBP / GIF de hasta 2 MB) con miniatura.
-- pendientes       tareas ligadas a un proyecto y, opcionalmente, a un elemento o cable: responsable,
--                  fecha límite, estado: pendiente | en_proceso | hecho.

CREATE TABLE redes.problemas (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id     bigint NOT NULL REFERENCES redes.proyectos (id),
    elemento_id     bigint REFERENCES redes.elementos (id),
    cable_id        bigint REFERENCES redes.cables (id),
    titulo          text NOT NULL CHECK (btrim(titulo) <> ''),
    descripcion     text,
    severidad       text NOT NULL DEFAULT 'media' CHECK (severidad IN ('baja', 'media', 'alta', 'critica')),
    estado          text NOT NULL DEFAULT 'abierto' CHECK (estado IN ('abierto', 'en_proceso', 'cerrado')),
    ubicacion       geometry(Point, 4326),
    cerrado_en      timestamptz,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1,
    CHECK ((elemento_id IS NULL) <> (cable_id IS NULL))
);
CREATE INDEX problemas_proyecto_ix ON redes.problemas (proyecto_id) WHERE borrado_en IS NULL;

CREATE TABLE redes.problema_fotos (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    problema_id  bigint NOT NULL REFERENCES redes.problemas (id),
    imagen       bytea NOT NULL,
    imagen_tipo  text NOT NULL,
    miniatura    bytea NOT NULL,
    creado_en    timestamptz NOT NULL DEFAULT now(),
    creado_por   bigint REFERENCES redes.usuarios (id),
    borrado_en   timestamptz
);
CREATE INDEX problema_fotos_problema_ix ON redes.problema_fotos (problema_id) WHERE borrado_en IS NULL;

CREATE TABLE redes.pendientes (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id     bigint NOT NULL REFERENCES redes.proyectos (id),
    elemento_id     bigint REFERENCES redes.elementos (id),
    cable_id        bigint REFERENCES redes.cables (id),
    titulo          text NOT NULL CHECK (btrim(titulo) <> ''),
    descripcion     text,
    responsable_id  bigint REFERENCES redes.usuarios (id),
    fecha_limite    date,
    estado          text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'en_proceso', 'hecho')),
    hecho_en        timestamptz,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1,
    CHECK (elemento_id IS NULL OR cable_id IS NULL)
);
CREATE INDEX pendientes_proyecto_ix ON redes.pendientes (proyecto_id) WHERE borrado_en IS NULL;
