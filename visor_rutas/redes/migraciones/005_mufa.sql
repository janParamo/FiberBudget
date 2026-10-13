-- Fase 4: editor de mufa (diagramación de hilos).
--
-- hilos        uno por hilo de cada cable (numero 1..hilos). El buffer y los colores TIA-598 se
--              calculan con cables.hilos_por_buffer (8 o 12): no se guardan.
--              estado: activo | oscura (fibra oscura) | baja (cliente de baja) | reservado | danado
-- mufa_cables  posición de cada cable en el lienzo de cada mufa (sus dos extremos tienen lienzo)
-- splitters    1x2 .. 1x32, balanceado (relacion NULL) o desbalanceado (relacion "70/30")
-- conectores   conector / adaptador de salida (hacia FAT o cliente)
-- puertos      entrada / salidas numeradas de splitters y conectores
-- conexiones   dentro de una mufa: de un hilo o puerto (a) a un hilo o puerto (b).
--              Un puerto tiene a lo sumo una conexión; un hilo, a lo sumo una por mufa (lo valida
--              redes/mufa.py, porque un hilo tiene dos extremos: uno en cada mufa de su cable).

CREATE TABLE redes.hilos (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cable_id        bigint NOT NULL REFERENCES redes.cables (id),
    numero          integer NOT NULL CHECK (numero BETWEEN 1 AND 144),
    estado          text NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo', 'oscura', 'baja', 'reservado', 'danado')),
    observacion     text,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX hilos_cable_numero_uk ON redes.hilos (cable_id, numero) WHERE borrado_en IS NULL;

-- the cables saved in phase 3 get their fibres now
INSERT INTO redes.hilos (cable_id, numero)
SELECT c.id, g FROM redes.cables c CROSS JOIN LATERAL generate_series(1, c.hilos) AS g WHERE c.borrado_en IS NULL;

CREATE TABLE redes.mufa_cables (
    mufa_id  bigint NOT NULL REFERENCES redes.elementos (id),
    cable_id bigint NOT NULL REFERENCES redes.cables (id),
    x        double precision NOT NULL,
    y        double precision NOT NULL,
    PRIMARY KEY (mufa_id, cable_id)
);

CREATE TABLE redes.splitters (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id     bigint NOT NULL REFERENCES redes.proyectos (id),
    mufa_id         bigint NOT NULL REFERENCES redes.elementos (id),
    nombre          text NOT NULL CHECK (btrim(nombre) <> ''),
    salidas         integer NOT NULL CHECK (salidas IN (2, 4, 8, 16, 32)),
    relacion        text CHECK (relacion IS NULL OR relacion ~ '^[0-9]{1,2}/[0-9]{1,2}$'),
    conector        text,
    x               double precision NOT NULL DEFAULT 0,
    y               double precision NOT NULL DEFAULT 0,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE INDEX splitters_mufa_ix ON redes.splitters (mufa_id) WHERE borrado_en IS NULL;

CREATE TABLE redes.conectores (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id     bigint NOT NULL REFERENCES redes.proyectos (id),
    mufa_id         bigint NOT NULL REFERENCES redes.elementos (id),
    nombre          text NOT NULL CHECK (btrim(nombre) <> ''),
    tipo            text,
    x               double precision NOT NULL DEFAULT 0,
    y               double precision NOT NULL DEFAULT 0,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE INDEX conectores_mufa_ix ON redes.conectores (mufa_id) WHERE borrado_en IS NULL;

CREATE TABLE redes.puertos (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    splitter_id bigint REFERENCES redes.splitters (id),
    conector_id bigint REFERENCES redes.conectores (id),
    lado        text NOT NULL CHECK (lado IN ('entrada', 'salida')),
    numero      integer NOT NULL CHECK (numero BETWEEN 1 AND 32),
    CHECK ((splitter_id IS NULL) <> (conector_id IS NULL)),
    UNIQUE NULLS NOT DISTINCT (splitter_id, conector_id, lado, numero)
);

CREATE TABLE redes.conexiones (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proyecto_id     bigint NOT NULL REFERENCES redes.proyectos (id),
    mufa_id         bigint NOT NULL REFERENCES redes.elementos (id),
    a_hilo_id       bigint REFERENCES redes.hilos (id),
    a_puerto_id     bigint REFERENCES redes.puertos (id),
    b_hilo_id       bigint REFERENCES redes.hilos (id),
    b_puerto_id     bigint REFERENCES redes.puertos (id),
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1,
    CHECK ((a_hilo_id IS NULL) <> (a_puerto_id IS NULL)),
    CHECK ((b_hilo_id IS NULL) <> (b_puerto_id IS NULL))
);
CREATE INDEX conexiones_mufa_ix ON redes.conexiones (mufa_id) WHERE borrado_en IS NULL;
CREATE INDEX conexiones_a_hilo_ix ON redes.conexiones (a_hilo_id) WHERE borrado_en IS NULL;
CREATE INDEX conexiones_b_hilo_ix ON redes.conexiones (b_hilo_id) WHERE borrado_en IS NULL;
CREATE UNIQUE INDEX conexiones_a_puerto_uk ON redes.conexiones (a_puerto_id) WHERE borrado_en IS NULL AND a_puerto_id IS NOT NULL;
CREATE UNIQUE INDEX conexiones_b_puerto_uk ON redes.conexiones (b_puerto_id) WHERE borrado_en IS NULL AND b_puerto_id IS NOT NULL;
