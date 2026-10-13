-- respaldo: previo
-- Migración Visio → mufas interactivas, fase 1 (docs/migracion_visio/PLAN.md §5 y FASE0_DIAGNOSTICO.md §2).
-- Modelo para la red existente: proyectos base por región, origen y confianza de cada dato, cables con
-- hilos desconocidos y más configuraciones de buffers, modelo de mufa y bandejas, clientes por puerto
-- de splitter y bitácora de las corridas de migración. No toca red_fibra, red_lineas ni red_puntos.
-- Escrita para poder correrse de nuevo sin error (IF NOT EXISTS / DROP CONSTRAINT IF EXISTS).

-- ---------------------------------------------------------------- dominios: origen y confianza de un dato
DO $$ BEGIN
    CREATE DOMAIN redes.fuente_dato AS text
        CHECK (VALUE IN ('usuario', 'excel_anillos', 'texto_diagrama', 'geometria_visio', 'kmz', 'kayako', 'estimado'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE DOMAIN redes.confianza_dato AS text CHECK (VALUE IN ('verificada', 'alta', 'media', 'baja'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE DOMAIN redes.estado_migracion AS text CHECK (VALUE IN ('automatica', 'en_revision', 'validada', 'editada'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------- proyectos base (uno por región)
ALTER TABLE redes.proyectos
    ADD COLUMN IF NOT EXISTS es_red_base boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS zona text;

-- ---------------------------------------------------------------- elementos
-- tipo odf; ubicación opcional solo si el nodo está "sin ubicar"; origen, confianza, estado de la
-- migración y referencia al Visio (clave = nombre normalizado + coordenada redondeada, ver fase 0 §1.7)
ALTER TABLE redes.elementos DROP CONSTRAINT IF EXISTS elementos_tipo_check;
ALTER TABLE redes.elementos ADD CONSTRAINT elementos_tipo_check CHECK (tipo IN ('poste', 'mufa', 'cliente', 'nodo', 'odf'));
ALTER TABLE redes.elementos
    ADD COLUMN IF NOT EXISTS ubicacion_fuente text NOT NULL DEFAULT 'real',
    ADD COLUMN IF NOT EXISTS fuente redes.fuente_dato,
    ADD COLUMN IF NOT EXISTS confianza redes.confianza_dato,
    ADD COLUMN IF NOT EXISTS estado_migracion redes.estado_migracion,
    ADD COLUMN IF NOT EXISTS ref_visio jsonb;
ALTER TABLE redes.elementos DROP CONSTRAINT IF EXISTS elementos_ubicacion_fuente_check;
ALTER TABLE redes.elementos ADD CONSTRAINT elementos_ubicacion_fuente_check
    CHECK (ubicacion_fuente IN ('real', 'estimada', 'sin_ubicar', 'usuario'));
ALTER TABLE redes.elementos ALTER COLUMN ubicacion DROP NOT NULL;
ALTER TABLE redes.elementos DROP CONSTRAINT IF EXISTS elementos_ubicacion_check;
ALTER TABLE redes.elementos ADD CONSTRAINT elementos_ubicacion_check
    CHECK ((ubicacion IS NULL) = (ubicacion_fuente = 'sin_ubicar'));
CREATE UNIQUE INDEX IF NOT EXISTS elementos_clave_visio_uk ON redes.elementos (proyecto_id, (ref_visio ->> 'clave'))
    WHERE borrado_en IS NULL AND ref_visio ? 'clave';

-- ---------------------------------------------------------------- cables
-- hilos desconocido (NULL) y capacidades de la red existente (2, 4, 6, 8 hilos); buffers de 2 a 12;
-- la configuración "6x4" se calcula (buffers x hilos por buffer), no se escribe aparte
ALTER TABLE redes.cables DROP CONSTRAINT IF EXISTS cables_hilos_check;
ALTER TABLE redes.cables ALTER COLUMN hilos DROP NOT NULL;
ALTER TABLE redes.cables ADD CONSTRAINT cables_hilos_check CHECK (hilos IS NULL OR hilos IN (2, 4, 6, 8, 12, 24, 48, 72, 96, 144));
ALTER TABLE redes.cables DROP CONSTRAINT IF EXISTS cables_hilos_por_buffer_check;
ALTER TABLE redes.cables ADD CONSTRAINT cables_hilos_por_buffer_check CHECK (hilos_por_buffer IN (2, 4, 6, 8, 12));
ALTER TABLE redes.cables
    ADD COLUMN IF NOT EXISTS buffers integer GENERATED ALWAYS AS
        (CASE WHEN hilos IS NULL THEN NULL ELSE (hilos + hilos_por_buffer - 1) / hilos_por_buffer END) STORED,
    ADD COLUMN IF NOT EXISTS configuracion text GENERATED ALWAYS AS
        (CASE WHEN hilos IS NULL THEN NULL
              ELSE ((hilos + hilos_por_buffer - 1) / hilos_por_buffer)::text || 'x' || LEAST(hilos, hilos_por_buffer)::text END) STORED,
    ADD COLUMN IF NOT EXISTS configuracion_estimada boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS tipo_fibra text NOT NULL DEFAULT 'SM dispersión cero',
    ADD COLUMN IF NOT EXISTS fuente redes.fuente_dato,
    ADD COLUMN IF NOT EXISTS confianza redes.confianza_dato,
    ADD COLUMN IF NOT EXISTS geom_fuente text NOT NULL DEFAULT 'usuario',
    ADD COLUMN IF NOT EXISTS estado_migracion redes.estado_migracion,
    ADD COLUMN IF NOT EXISTS ref_visio jsonb;
ALTER TABLE redes.cables DROP CONSTRAINT IF EXISTS cables_geom_fuente_check;
ALTER TABLE redes.cables ADD CONSTRAINT cables_geom_fuente_check CHECK (geom_fuente IN ('kmz', 'recta', 'usuario'));
CREATE UNIQUE INDEX IF NOT EXISTS cables_clave_visio_uk ON redes.cables (proyecto_id, (ref_visio ->> 'clave'))
    WHERE borrado_en IS NULL AND ref_visio ? 'clave';

-- ---------------------------------------------------------------- splitters y conexiones
ALTER TABLE redes.splitters
    ADD COLUMN IF NOT EXISTS propiedades jsonb NOT NULL DEFAULT '{}'::jsonb,     -- olt, puerto_olt, depende_de
    ADD COLUMN IF NOT EXISTS fuente redes.fuente_dato,
    ADD COLUMN IF NOT EXISTS confianza redes.confianza_dato;

ALTER TABLE redes.conexiones
    ADD COLUMN IF NOT EXISTS bandeja integer,
    ADD COLUMN IF NOT EXISTS posicion_en_bandeja integer,
    ADD COLUMN IF NOT EXISTS fuente redes.fuente_dato,
    ADD COLUMN IF NOT EXISTS confianza redes.confianza_dato;
ALTER TABLE redes.conexiones DROP CONSTRAINT IF EXISTS conexiones_bandeja_check;
ALTER TABLE redes.conexiones ADD CONSTRAINT conexiones_bandeja_check
    CHECK ((bandeja IS NULL) = (posicion_en_bandeja IS NULL) AND (bandeja IS NULL OR bandeja BETWEEN 1 AND 8)
           AND (posicion_en_bandeja IS NULL OR posicion_en_bandeja BETWEEN 1 AND 24));
CREATE UNIQUE INDEX IF NOT EXISTS conexiones_posicion_uk ON redes.conexiones (mufa_id, bandeja, posicion_en_bandeja)
    WHERE borrado_en IS NULL AND bandeja IS NOT NULL;

-- ---------------------------------------------------------------- modelo de la mufa y sus bandejas
CREATE TABLE IF NOT EXISTS redes.mufa_modelos (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mufa_id              bigint NOT NULL REFERENCES redes.elementos (id),
    formato              text NOT NULL DEFAULT 'desconocido' CHECK (formato IN ('domo', 'horizontal', 'desconocido')),
    capacidad            integer NOT NULL CHECK (capacidad IN (48, 96)),
    empalmes_por_bandeja integer NOT NULL DEFAULT 24 CHECK (empalmes_por_bandeja BETWEEN 1 AND 24),
    bandejas             integer NOT NULL CHECK (bandejas BETWEEN 1 AND 8),
    modelo_estimado      boolean NOT NULL DEFAULT true,
    fuente               redes.fuente_dato,
    creado_en            timestamptz NOT NULL DEFAULT now(),
    creado_por           bigint REFERENCES redes.usuarios (id),
    actualizado_en       timestamptz,
    actualizado_por      bigint REFERENCES redes.usuarios (id),
    borrado_en           timestamptz,
    version              integer NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS mufa_modelos_mufa_uk ON redes.mufa_modelos (mufa_id) WHERE borrado_en IS NULL;

-- capacidad = empalmes que admite: 24, o salidas + entrada si la bandeja lleva un splitter
CREATE TABLE IF NOT EXISTS redes.mufa_bandejas (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mufa_id         bigint NOT NULL REFERENCES redes.elementos (id),
    numero          integer NOT NULL CHECK (numero BETWEEN 1 AND 8),
    capacidad       integer NOT NULL DEFAULT 24 CHECK (capacidad BETWEEN 1 AND 24),
    splitter_id     bigint REFERENCES redes.splitters (id),
    fuente          redes.fuente_dato,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS mufa_bandejas_numero_uk ON redes.mufa_bandejas (mufa_id, numero) WHERE borrado_en IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS mufa_bandejas_splitter_uk ON redes.mufa_bandejas (splitter_id) WHERE borrado_en IS NULL AND splitter_id IS NOT NULL;

-- ---------------------------------------------------------------- clientes de la red existente
-- puerto_servicios: el cliente de una salida de splitter, aunque el cliente no esté en el mapa
CREATE TABLE IF NOT EXISTS redes.puerto_servicios (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    puerto_id       bigint NOT NULL REFERENCES redes.puertos (id),
    codigo_cliente  text,
    nombre          text,
    id_servicio     text,
    elemento_id     bigint REFERENCES redes.elementos (id),
    fuente          redes.fuente_dato,
    confianza       redes.confianza_dato,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1,
    CHECK (coalesce(codigo_cliente, nombre, id_servicio) IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS puerto_servicios_puerto_uk ON redes.puerto_servicios (puerto_id) WHERE borrado_en IS NULL;

-- mufa_clientes: clientes listados en una mufa sin puerto conocido (fusionados directo, sangría…)
CREATE TABLE IF NOT EXISTS redes.mufa_clientes (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mufa_id         bigint NOT NULL REFERENCES redes.elementos (id),
    codigo_cliente  text,
    nombre          text,
    id_servicio     text,
    elemento_id     bigint REFERENCES redes.elementos (id),
    fuente          redes.fuente_dato,
    confianza       redes.confianza_dato,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1,
    CHECK (coalesce(codigo_cliente, nombre, id_servicio) IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS mufa_clientes_mufa_ix ON redes.mufa_clientes (mufa_id) WHERE borrado_en IS NULL;
CREATE INDEX IF NOT EXISTS mufa_clientes_codigo_ix ON redes.mufa_clientes (codigo_cliente) WHERE borrado_en IS NULL;

-- ---------------------------------------------------------------- corridas de la migración
CREATE TABLE IF NOT EXISTS redes.migracion_visio_corridas (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    inicio      timestamptz NOT NULL DEFAULT now(),
    fin         timestamptz,
    modo        text NOT NULL CHECK (modo IN ('simular', 'real')),
    zona        text,
    respaldo    text,                       -- archivo del respaldo previo
    conteos     jsonb NOT NULL DEFAULT '{}'::jsonb,
    usuario_id  bigint REFERENCES redes.usuarios (id),
    resultado   text CHECK (resultado IN ('ok', 'con_avisos', 'error'))
);

CREATE TABLE IF NOT EXISTS redes.migracion_visio_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    corrida_id  bigint NOT NULL REFERENCES redes.migracion_visio_corridas (id),
    entidad     text NOT NULL,              -- nodo | enlace | splitter | cliente | fusion | mufa
    clave       text,                       -- clave Visio (o archivo)
    accion      text NOT NULL CHECK (accion IN ('crear', 'actualizar', 'omitir', 'conflicto', 'aviso', 'error')),
    resultado   text,
    avisos      jsonb,
    fecha       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS migracion_visio_log_corrida_ix ON redes.migracion_visio_log (corrida_id, entidad);
