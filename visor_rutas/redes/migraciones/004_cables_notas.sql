-- Fase 3: editor de red en el mapa. Cables de fibra y notas con formato.
--
-- cables
--   clase            troncal | distribucion | acometida
--   tipo             ADSS | FLAT
--   hilos            12, 24, 48, 72, 96 o 144;  hilos_por_buffer 8 o 12 (los colores TIA se repiten
--                    cada 8 o cada 12 hilos; lo usa el editor de mufa de la fase 4)
--   color            color para dibujarlo en el mapa (#rrggbb)
--   origen/destino   elementos del mismo proyecto donde empieza y termina el cable
--   vertices         [{"lat", "lon", "elemento_id"|null}, ...]: el recorrido; un vértice con
--                    elemento_id está pegado a ese poste / mufa (se mueve con él)
--   geom             el mismo recorrido como LineString (para consultas y exportar)
--   cruces           cruces de calle del cable (reserva por cruce, business_rules.yaml diseno_red)
--   longitud_m       distancia lineal (geodésica);  metraje = detalle calculado con diseno_red
-- notas
--   contexto         mapa | mufa (fase 4: notas dentro del lienzo de una mufa)
--   elemento_id      ancla opcional (la nota se mueve con el elemento); si no, ubicacion / x, y
--   html             texto con formato, ya saneado (sin scripts)

CREATE TABLE redes.cables (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id      bigint NOT NULL REFERENCES redes.proyectos (id),
    nombre           text NOT NULL CHECK (btrim(nombre) <> ''),
    descripcion      text,
    clase            text NOT NULL DEFAULT 'distribucion' CHECK (clase IN ('troncal', 'distribucion', 'acometida')),
    tipo             text NOT NULL DEFAULT 'ADSS' CHECK (tipo IN ('ADSS', 'FLAT')),
    hilos            integer NOT NULL DEFAULT 12 CHECK (hilos IN (12, 24, 48, 72, 96, 144)),
    hilos_por_buffer integer NOT NULL DEFAULT 12 CHECK (hilos_por_buffer IN (8, 12)),
    color            text NOT NULL DEFAULT '#1f6feb' CHECK (color ~ '^#[0-9a-fA-F]{6}$'),
    origen_id        bigint NOT NULL REFERENCES redes.elementos (id),
    destino_id       bigint NOT NULL REFERENCES redes.elementos (id),
    vertices         jsonb NOT NULL,
    geom             geometry(LineString, 4326) NOT NULL,
    cruces           integer NOT NULL DEFAULT 0 CHECK (cruces BETWEEN 0 AND 500),
    longitud_m       numeric(12, 2) NOT NULL DEFAULT 0,
    metraje          jsonb,
    creado_en        timestamptz NOT NULL DEFAULT now(),
    creado_por       bigint REFERENCES redes.usuarios (id),
    actualizado_en   timestamptz,
    actualizado_por  bigint REFERENCES redes.usuarios (id),
    borrado_en       timestamptz,
    version          integer NOT NULL DEFAULT 1,
    CHECK (origen_id <> destino_id)
);
CREATE INDEX cables_proyecto_ix ON redes.cables (proyecto_id) WHERE borrado_en IS NULL;
CREATE INDEX cables_origen_ix ON redes.cables (origen_id);
CREATE INDEX cables_destino_ix ON redes.cables (destino_id);
CREATE INDEX cables_geom_gix ON redes.cables USING gist (geom);

CREATE TABLE redes.notas (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id     bigint NOT NULL REFERENCES redes.proyectos (id),
    contexto        text NOT NULL DEFAULT 'mapa' CHECK (contexto IN ('mapa', 'mufa')),
    mufa_id         bigint REFERENCES redes.elementos (id),
    elemento_id     bigint REFERENCES redes.elementos (id),
    ubicacion       geometry(Point, 4326),
    x               double precision,
    y               double precision,
    html            text NOT NULL CHECK (octet_length(html) <= 65536),
    ancho           integer NOT NULL DEFAULT 220 CHECK (ancho BETWEEN 80 AND 1200),
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE INDEX notas_proyecto_ix ON redes.notas (proyecto_id, contexto) WHERE borrado_en IS NULL;
