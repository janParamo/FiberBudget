-- Fase 6: diagrama lógico de red.
--
-- diagramas_logicos  diagramas guardados de un proyecto: desde qué elemento (nodo / OLT o mufa) o
--                    splitter se generan, la dirección (derecha: crece hacia la derecha; izquierda:
--                    hacia la izquierda) y si incluyen los clientes (inmuebles). El dibujo NO se
--                    guarda: se genera siempre de las conexiones guardadas (redes/diagrama.py).

CREATE TABLE redes.diagramas_logicos (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id      bigint NOT NULL REFERENCES redes.proyectos (id),
    titulo           text NOT NULL CHECK (btrim(titulo) <> ''),
    elemento_id      bigint REFERENCES redes.elementos (id),
    splitter_id      bigint REFERENCES redes.splitters (id),
    direccion        text NOT NULL DEFAULT 'derecha' CHECK (direccion IN ('derecha', 'izquierda')),
    incluir_clientes boolean NOT NULL DEFAULT false,
    creado_en        timestamptz NOT NULL DEFAULT now(),
    creado_por       bigint REFERENCES redes.usuarios (id),
    actualizado_en   timestamptz,
    actualizado_por  bigint REFERENCES redes.usuarios (id),
    borrado_en       timestamptz,
    version          integer NOT NULL DEFAULT 1,
    CHECK ((elemento_id IS NULL) <> (splitter_id IS NULL))
);
CREATE INDEX diagramas_logicos_proyecto_ix ON redes.diagramas_logicos (proyecto_id) WHERE borrado_en IS NULL;
