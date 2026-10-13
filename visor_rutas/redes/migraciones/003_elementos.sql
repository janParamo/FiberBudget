-- Elementos de red de un proyecto (postes, mufas, casas de cliente, nodos / OLT).
-- Fase 2: la ventana "Datos del proyecto" ya maneja los clientes del proyecto (varios por
-- proyecto); la fase 3 (editor de mapa) usa la misma tabla para postes, mufas y nodos.
--   tipo         poste | mufa | cliente | nodo
--   subtipo      poste: ideay / concreto / madera / metal / cliente; mufa: empalme / distribucion (FDT) /
--                terminal (FAT); nodo: olt / nodo
--   codigo       cliente: C##### (único dentro del proyecto)
--   propiedades  datos propios del tipo (id_servicio, capacidad en hilos, bandejas...)
--   ref_externa  enlace a una mufa existente de la red (KMZ o Visio), si la representa

CREATE TABLE redes.elementos (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id     bigint NOT NULL REFERENCES redes.proyectos (id),
    tipo            text NOT NULL CHECK (tipo IN ('poste', 'mufa', 'cliente', 'nodo')),
    subtipo         text,
    nombre          text NOT NULL CHECK (btrim(nombre) <> ''),
    codigo          text,
    ubicacion       geometry(Point, 4326) NOT NULL,
    propiedades     jsonb NOT NULL DEFAULT '{}'::jsonb,
    ref_externa     jsonb,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE INDEX elementos_proyecto_ix ON redes.elementos (proyecto_id, tipo) WHERE borrado_en IS NULL;
CREATE INDEX elementos_ubicacion_gix ON redes.elementos USING gist (ubicacion);
CREATE UNIQUE INDEX elementos_cliente_codigo_uk ON redes.elementos (proyecto_id, lower(codigo))
    WHERE tipo = 'cliente' AND codigo IS NOT NULL AND borrado_en IS NULL;
