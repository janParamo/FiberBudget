-- Módulo de Proyectos y Diagramación de Redes FTTH: base (fase 1).
-- Esquema redes en Presupuesto_visio. No toca red_fibra, red_lineas ni red_puntos.
-- Convenciones de todas las tablas editables:
--   version      bloqueo optimista: UPDATE ... WHERE id = ? AND version = ?; 0 filas = otro usuario guardó antes
--   borrado_en   borrado lógico: nada se elimina de verdad, siempre se puede recuperar
--   creado_* / actualizado_*   quién y cuándo (además del historial detallado)

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE redes.usuarios (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre          text NOT NULL CHECK (btrim(nombre) <> ''),
    correo          text CHECK (correo IS NULL OR correo ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    rol             text NOT NULL DEFAULT 'lector' CHECK (rol IN ('administrador', 'editor', 'lector')),
    persona_visor   text,          -- nombre de la persona en VISOR_API_KEYS (modo remoto, X-Visor-Key)
    usuario_windows text,          -- usuario de Windows (modo local)
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,   -- usuario desactivado (se puede reactivar)
    version         integer NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX usuarios_correo_uk ON redes.usuarios (lower(correo)) WHERE correo IS NOT NULL;
CREATE UNIQUE INDEX usuarios_persona_uk ON redes.usuarios (lower(persona_visor)) WHERE persona_visor IS NOT NULL;
CREATE UNIQUE INDEX usuarios_windows_uk ON redes.usuarios (lower(usuario_windows)) WHERE usuario_windows IS NOT NULL;

CREATE TABLE redes.proyectos (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo          text NOT NULL CHECK (btrim(codigo) <> ''),   -- "Identificador" corto y único
    nombre          text NOT NULL CHECK (btrim(nombre) <> ''),
    descripcion     text,
    padre_id        bigint REFERENCES redes.proyectos (id),      -- "Proyectos principales" (jerarquía)
    ubicacion       geometry(Point, 4326),
    area            geometry(Polygon, 4326),                     -- "Diseñar área"
    imagen          bytea CHECK (imagen IS NULL OR octet_length(imagen) <= 2097152),
    imagen_tipo     text CHECK (imagen_tipo IS NULL OR imagen_tipo IN ('image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/svg+xml')),
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1,
    CHECK (padre_id IS NULL OR padre_id <> id)
);
CREATE UNIQUE INDEX proyectos_codigo_uk ON redes.proyectos (lower(codigo)) WHERE borrado_en IS NULL;
CREATE INDEX proyectos_padre_ix ON redes.proyectos (padre_id);
CREATE INDEX proyectos_ubicacion_gix ON redes.proyectos USING gist (ubicacion);
CREATE INDEX proyectos_area_gix ON redes.proyectos USING gist (area);

-- Usuarios con acceso a cada proyecto (los administradores ven todos).
CREATE TABLE redes.proyecto_usuarios (
    proyecto_id  bigint NOT NULL REFERENCES redes.proyectos (id),
    usuario_id   bigint NOT NULL REFERENCES redes.usuarios (id),
    asignado_en  timestamptz NOT NULL DEFAULT now(),
    asignado_por bigint REFERENCES redes.usuarios (id),
    PRIMARY KEY (proyecto_id, usuario_id)
);
CREATE INDEX proyecto_usuarios_usuario_ix ON redes.proyecto_usuarios (usuario_id);

-- Auditoría: cada cambio con su usuario. cambio = {"campo": [antes, después], ...} o la fila completa.
CREATE TABLE redes.historial (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha       timestamptz NOT NULL DEFAULT now(),
    usuario_id  bigint REFERENCES redes.usuarios (id),
    proyecto_id bigint REFERENCES redes.proyectos (id),
    entidad     text NOT NULL,
    entidad_id  bigint,
    accion      text NOT NULL CHECK (accion IN ('crear', 'editar', 'eliminar', 'restaurar', 'duplicar', 'identificar')),
    cambio      jsonb
);
CREATE INDEX historial_entidad_ix ON redes.historial (entidad, entidad_id, fecha DESC);
CREATE INDEX historial_proyecto_ix ON redes.historial (proyecto_id, fecha DESC);
