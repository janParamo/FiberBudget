-- Planificación de cuadrillas: las actividades (instalaciones de presupuestos) que se asignan a las cuadrillas, sus estados, sus puntos de control y los tiempos.
--
-- plan_empresas              Tamos, Telenic (servicios tercerizados) e IDEAY (propia).
-- plan_cuadrillas            las cuadrillas de cada empresa (2 de cada una al empezar); `tipo` = tercerizada / propia.
-- plan_cuadrilla_miembros    los usuarios (rol «tecnico») que trabajan en esa cuadrilla: lo que ven en la app de la cuadrilla es lo de SU cuadrilla.
-- plan_control_catalogo      los puntos de control, en orden (llegada, inspección, postes, acometida, equipos del cliente, fusiones).
-- plan_actividades           una instalación: nace de un presupuesto del visor de rutas (o de Kayako, o a mano); estado, cuadrilla, cola y tiempos.
-- plan_actividad_control     el avance de cada actividad en cada punto de control (quién y cuándo lo marcó; la cuadrilla o planificación).
-- plan_actividad_historial   cada cambio de estado, para saber el tiempo en cada fase.
-- plan_mensajes              el chat entre la cuadrilla y planificación (por actividad). Queda lista la tabla; la pantalla viene al final.
--
-- Estados de una actividad:  inactivo (con presupuesto, sin cuadrilla) -> asignado (puesta en la cola de una cuadrilla) -> en_revision (se revisa si se hará)
-- -> en_curso (la cuadrilla la ejecuta) -> terminado.  Además: pausado (con motivo), no_viable (la revisión dijo que no se hace) y cancelado.
-- Tiempos: espera = desde que se asignó hasta que empezó (iniciada_en); ejecución = desde que empezó hasta que terminó (menos lo pausado).
-- Planificación puede dar por iniciada una actividad si la cuadrilla se olvidó (iniciada_por = 'planificacion').
-- Un trigger avisa con NOTIFY 'planificacion' ({tabla, id, cambio}) cada vez que se inserta o cambia algo.


CREATE TABLE IF NOT EXISTS redes.plan_empresas (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre      text NOT NULL UNIQUE CHECK (btrim(nombre) <> ''),
    tercerizada boolean NOT NULL DEFAULT true,
    creado_en   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS redes.plan_cuadrillas (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    empresa_id      bigint NOT NULL REFERENCES redes.plan_empresas (id),
    nombre          text NOT NULL UNIQUE CHECK (btrim(nombre) <> ''),
    telefono        text NOT NULL DEFAULT '',
    notas           text NOT NULL DEFAULT '',
    activa          boolean NOT NULL DEFAULT true,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS redes.plan_cuadrilla_miembros (
    cuadrilla_id bigint NOT NULL REFERENCES redes.plan_cuadrillas (id) ON DELETE CASCADE,
    usuario_id   bigint NOT NULL REFERENCES redes.usuarios (id),
    creado_en    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cuadrilla_id, usuario_id)
);
CREATE INDEX IF NOT EXISTS plan_miembros_usuario_ix ON redes.plan_cuadrilla_miembros (usuario_id);

CREATE TABLE IF NOT EXISTS redes.plan_control_catalogo (
    clave       text PRIMARY KEY CHECK (clave ~ '^[a-z_]{3,40}$'),
    etiqueta    text NOT NULL,
    orden       integer NOT NULL,
    obligatorio boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS redes.plan_actividades (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket            text NOT NULL DEFAULT '',
    cliente_nombre    text NOT NULL CHECK (btrim(cliente_nombre) <> ''),
    codigo_cliente    text NOT NULL DEFAULT '',
    contacto_nombre   text NOT NULL DEFAULT '',
    contacto_telefono text NOT NULL DEFAULT '',
    direccion         text NOT NULL DEFAULT '',
    ubicacion         geometry(Point, 4326) NOT NULL,
    origen            text NOT NULL DEFAULT 'visor' CHECK (origen IN ('visor', 'kayako', 'manual')),
    presupuesto_clave text,                       -- el Excel del presupuesto en el almacén de archivos (espacio «visor»)
    presupuesto_total numeric,
    resumen           jsonb NOT NULL DEFAULT '{}'::jsonb,   -- metraje, postes, cable, conexión... (lo que traiga el presupuesto)
    estado            text NOT NULL DEFAULT 'inactivo' CHECK (estado IN ('inactivo', 'asignado', 'en_revision', 'en_curso', 'pausado', 'terminado', 'no_viable', 'cancelado')),
    motivo_estado     text NOT NULL DEFAULT '',
    cuadrilla_id      bigint REFERENCES redes.plan_cuadrillas (id),
    cola_orden        integer NOT NULL DEFAULT 0,
    prioridad         integer NOT NULL DEFAULT 0,
    asignada_en       timestamptz,
    iniciada_en       timestamptz,
    iniciada_por      text CHECK (iniciada_por IN ('cuadrilla', 'planificacion')),
    terminada_en      timestamptz,
    pausada_desde     timestamptz,
    pausa_total_s     integer NOT NULL DEFAULT 0,
    notas             text NOT NULL DEFAULT '',
    creado_en         timestamptz NOT NULL DEFAULT now(),
    creado_por        bigint REFERENCES redes.usuarios (id),
    actualizado_en    timestamptz NOT NULL DEFAULT now(),
    actualizado_por   bigint REFERENCES redes.usuarios (id),
    borrado_en        timestamptz,
    version           integer NOT NULL DEFAULT 1,
    CHECK (estado = 'inactivo' OR estado IN ('no_viable', 'cancelado') OR cuadrilla_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS plan_act_estado_ix ON redes.plan_actividades (estado) WHERE borrado_en IS NULL;
CREATE INDEX IF NOT EXISTS plan_act_cuadrilla_ix ON redes.plan_actividades (cuadrilla_id, cola_orden) WHERE borrado_en IS NULL;
CREATE INDEX IF NOT EXISTS plan_act_ticket_ix ON redes.plan_actividades (ticket) WHERE borrado_en IS NULL;
-- una cuadrilla ejecuta una actividad a la vez
CREATE UNIQUE INDEX IF NOT EXISTS plan_act_una_en_curso_uk ON redes.plan_actividades (cuadrilla_id) WHERE estado = 'en_curso' AND borrado_en IS NULL;

CREATE TABLE IF NOT EXISTS redes.plan_actividad_control (
    actividad_id bigint NOT NULL REFERENCES redes.plan_actividades (id) ON DELETE CASCADE,
    clave        text NOT NULL REFERENCES redes.plan_control_catalogo (clave),
    estado       text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'en_proceso', 'hecho')),
    marcado_en   timestamptz,
    marcado_por  bigint REFERENCES redes.usuarios (id),
    origen       text CHECK (origen IN ('cuadrilla', 'planificacion')),
    ubicacion    geometry(Point, 4326),
    nota         text NOT NULL DEFAULT '',
    PRIMARY KEY (actividad_id, clave)
);

CREATE TABLE IF NOT EXISTS redes.plan_actividad_historial (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actividad_id bigint NOT NULL REFERENCES redes.plan_actividades (id) ON DELETE CASCADE,
    de           text,
    a            text NOT NULL,
    en           timestamptz NOT NULL DEFAULT now(),
    por          bigint REFERENCES redes.usuarios (id),
    origen       text CHECK (origen IN ('cuadrilla', 'planificacion', 'sistema')),
    cuadrilla_id bigint REFERENCES redes.plan_cuadrillas (id),
    motivo       text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS plan_hist_actividad_ix ON redes.plan_actividad_historial (actividad_id, en);

CREATE TABLE IF NOT EXISTS redes.plan_mensajes (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actividad_id bigint NOT NULL REFERENCES redes.plan_actividades (id) ON DELETE CASCADE,
    de_usuario   bigint NOT NULL REFERENCES redes.usuarios (id),
    de_origen    text NOT NULL CHECK (de_origen IN ('cuadrilla', 'planificacion')),
    texto        text NOT NULL CHECK (btrim(texto) <> ''),
    enviado_en   timestamptz NOT NULL DEFAULT now(),
    leido_en     timestamptz
);
CREATE INDEX IF NOT EXISTS plan_mensajes_actividad_ix ON redes.plan_mensajes (actividad_id, enviado_en);

-- Empresas y cuadrillas de partida (2 de Tamos, 2 de Telenic —terceros— y 2 de IDEAY —propias—) y los puntos de control.
INSERT INTO redes.plan_empresas (nombre, tercerizada) VALUES ('Tamos', true), ('Telenic', true), ('IDEAY', false) ON CONFLICT (nombre) DO NOTHING;
INSERT INTO redes.plan_cuadrillas (empresa_id, nombre)
    SELECT e.id, e.nombre || ' ' || n FROM redes.plan_empresas e CROSS JOIN (VALUES (1), (2)) AS v(n) ON CONFLICT (nombre) DO NOTHING;
INSERT INTO redes.plan_control_catalogo (clave, etiqueta, orden, obligatorio) VALUES
    ('llegada', 'Llegó al lugar', 1, true),
    ('inspeccion', 'Inspección hecha', 2, true),
    ('postes', 'Levantado de postes', 3, false),
    ('acometida', 'Acometida del cliente', 4, true),
    ('equipos_cliente', 'Instalación de los equipos del cliente', 5, true),
    ('fusiones', 'Fusión de hilos en las mufas', 6, true)
ON CONFLICT (clave) DO NOTHING;

CREATE OR REPLACE FUNCTION redes.plan_avisar() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('planificacion', json_build_object('tabla', TG_TABLE_NAME, 'id', COALESCE(NEW.id, 0), 'cambio', lower(TG_OP))::text);
    RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS plan_actividades_avisa ON redes.plan_actividades;
CREATE TRIGGER plan_actividades_avisa AFTER INSERT OR UPDATE ON redes.plan_actividades FOR EACH ROW EXECUTE FUNCTION redes.plan_avisar();
DROP TRIGGER IF EXISTS plan_mensajes_avisa ON redes.plan_mensajes;
CREATE TRIGGER plan_mensajes_avisa AFTER INSERT ON redes.plan_mensajes FOR EACH ROW EXECUTE FUNCTION redes.plan_avisar();
