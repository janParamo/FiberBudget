-- respaldo: previo
-- App de campo (PWA): los técnicos registran postes, mufas, reservas, solitarias y otros puntos desde el teléfono y el visor los ve en tiempo real.
--
-- usuarios.rol            nuevo rol «tecnico»: solo crea y edita sus propios puntos pendientes (no edita la red ni los proyectos).
-- campo_jornadas          el día de trabajo de un técnico (abre y cierra).
-- campo_puntos            lo que registra: `uuid_cliente` lo genera el teléfono para que reenviar no duplique; `estado` pendiente → aprobado /
--                         rechazado (o `editado` si lo corrigió quien revisa); al aprobar queda a dónde fue (`elemento_red_id` = red base,
--                         `lugar_id` = Mis lugares).
-- campo_fotos             fotos de un punto: el archivo en disco (CAMPO_FOTOS_DIR) y la miniatura aquí.
-- campo_trazos            cable o recorrido dibujado en campo.
-- campo_ubicaciones       la ÚLTIMA ubicación de cada técnico (una fila por usuario, no hay historial).
-- Un trigger avisa con NOTIFY 'campo' ({tabla, id, cambio, usuario_id}) cada vez que se inserta o cambia algo.

ALTER TABLE redes.usuarios DROP CONSTRAINT IF EXISTS usuarios_rol_check;
ALTER TABLE redes.usuarios ADD CONSTRAINT usuarios_rol_check CHECK (rol IN ('administrador', 'editor', 'lector', 'tecnico'));

CREATE TABLE IF NOT EXISTS redes.campo_jornadas (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id      bigint NOT NULL REFERENCES redes.usuarios (id),
    nombre          text NOT NULL DEFAULT '',
    notas           text NOT NULL DEFAULT '',
    inicio          timestamptz NOT NULL DEFAULT now(),
    fin             timestamptz,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS campo_jornadas_usuario_ix ON redes.campo_jornadas (usuario_id, inicio DESC) WHERE borrado_en IS NULL;
-- one open jornada per technician
CREATE UNIQUE INDEX IF NOT EXISTS campo_jornadas_abierta_uk ON redes.campo_jornadas (usuario_id) WHERE fin IS NULL AND borrado_en IS NULL;

CREATE TABLE IF NOT EXISTS redes.campo_puntos (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid_cliente     text NOT NULL UNIQUE CHECK (uuid_cliente ~ '^[0-9a-fA-F-]{8,64}$'),
    jornada_id       bigint REFERENCES redes.campo_jornadas (id),
    usuario_id       bigint NOT NULL REFERENCES redes.usuarios (id),
    tipo             text NOT NULL CHECK (tipo IN ('poste', 'mufa', 'reserva', 'solitaria', 'cliente', 'otro')),
    subtipo          text,
    nombre           text NOT NULL CHECK (btrim(nombre) <> ''),
    notas            text NOT NULL DEFAULT '',
    ubicacion        geometry(Point, 4326) NOT NULL,
    precision_m      numeric,
    altitud          numeric,
    origen_coord     text NOT NULL DEFAULT 'gps' CHECK (origen_coord IN ('gps', 'mapa')),
    capturado_en     timestamptz NOT NULL,
    recibido_en      timestamptz NOT NULL DEFAULT now(),
    estado           text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aprobado', 'rechazado', 'editado')),
    motivo_rechazo   text,
    revisado_por     bigint REFERENCES redes.usuarios (id),
    revisado_en      timestamptz,
    elemento_red_id  bigint REFERENCES redes.elementos (id),
    lugar_id         bigint REFERENCES redes.lugares_elementos (id),
    creado_en        timestamptz NOT NULL DEFAULT now(),
    creado_por       bigint REFERENCES redes.usuarios (id),
    actualizado_en   timestamptz NOT NULL DEFAULT now(),
    actualizado_por  bigint REFERENCES redes.usuarios (id),
    borrado_en       timestamptz,
    version          integer NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS campo_puntos_usuario_ix ON redes.campo_puntos (usuario_id, actualizado_en DESC);
CREATE INDEX IF NOT EXISTS campo_puntos_jornada_ix ON redes.campo_puntos (jornada_id);
CREATE INDEX IF NOT EXISTS campo_puntos_estado_ix ON redes.campo_puntos (estado, actualizado_en DESC) WHERE borrado_en IS NULL;
CREATE INDEX IF NOT EXISTS campo_puntos_ubicacion_gix ON redes.campo_puntos USING gist (ubicacion);

CREATE TABLE IF NOT EXISTS redes.campo_fotos (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid_cliente    text UNIQUE,
    punto_id        bigint NOT NULL REFERENCES redes.campo_puntos (id),
    archivo         text NOT NULL,
    tipo            text NOT NULL CHECK (tipo IN ('image/jpeg', 'image/png', 'image/webp')),
    tamano          integer NOT NULL CHECK (tamano > 0),
    miniatura       bytea,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS campo_fotos_punto_ix ON redes.campo_fotos (punto_id) WHERE borrado_en IS NULL;

CREATE TABLE IF NOT EXISTS redes.campo_trazos (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uuid_cliente    text NOT NULL UNIQUE CHECK (uuid_cliente ~ '^[0-9a-fA-F-]{8,64}$'),
    jornada_id      bigint REFERENCES redes.campo_jornadas (id),
    usuario_id      bigint NOT NULL REFERENCES redes.usuarios (id),
    geom            geometry(LineString, 4326) NOT NULL,
    postes          jsonb NOT NULL DEFAULT '[]'::jsonb,
    modo            text NOT NULL DEFAULT 'puntos' CHECK (modo IN ('puntos', 'postes', 'recorrido')),
    tipo_cable      text,
    hilos           integer,
    notas           text NOT NULL DEFAULT '',
    estado          text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aprobado', 'rechazado', 'editado')),
    capturado_en    timestamptz NOT NULL,
    recibido_en     timestamptz NOT NULL DEFAULT now(),
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS campo_trazos_usuario_ix ON redes.campo_trazos (usuario_id, recibido_en DESC);

CREATE TABLE IF NOT EXISTS redes.campo_ubicaciones (
    usuario_id      bigint PRIMARY KEY REFERENCES redes.usuarios (id),
    ubicacion       geometry(Point, 4326) NOT NULL,
    precision_m     numeric,
    capturado_en    timestamptz NOT NULL,
    recibido_en     timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION redes.campo_notificar() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    fila jsonb := to_jsonb(CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END);
BEGIN
    PERFORM pg_notify('campo', jsonb_build_object('tabla', TG_TABLE_NAME, 'id', COALESCE(fila ->> 'id', fila ->> 'usuario_id'),
                                                  'cambio', lower(TG_OP), 'usuario_id', fila ->> 'usuario_id')::text);
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS campo_puntos_notificar ON redes.campo_puntos;
CREATE TRIGGER campo_puntos_notificar AFTER INSERT OR UPDATE ON redes.campo_puntos FOR EACH ROW EXECUTE FUNCTION redes.campo_notificar();
DROP TRIGGER IF EXISTS campo_fotos_notificar ON redes.campo_fotos;
CREATE TRIGGER campo_fotos_notificar AFTER INSERT OR UPDATE ON redes.campo_fotos FOR EACH ROW EXECUTE FUNCTION redes.campo_notificar();
DROP TRIGGER IF EXISTS campo_trazos_notificar ON redes.campo_trazos;
CREATE TRIGGER campo_trazos_notificar AFTER INSERT OR UPDATE ON redes.campo_trazos FOR EACH ROW EXECUTE FUNCTION redes.campo_notificar();
DROP TRIGGER IF EXISTS campo_ubicaciones_notificar ON redes.campo_ubicaciones;
CREATE TRIGGER campo_ubicaciones_notificar AFTER INSERT OR UPDATE ON redes.campo_ubicaciones FOR EACH ROW EXECUTE FUNCTION redes.campo_notificar();
