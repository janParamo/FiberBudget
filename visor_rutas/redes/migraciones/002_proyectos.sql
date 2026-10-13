-- Fase 2: Proyectos.
--   miniatura   imagen reducida (PNG <= 160 px) para la lista de proyectos; la imagen completa
--               se lee solo al abrir el proyecto.
--   imagen_tipo sin SVG: un SVG puede llevar scripts, y la imagen se muestra dentro del visor.

ALTER TABLE redes.proyectos ADD COLUMN miniatura bytea
    CHECK (miniatura IS NULL OR octet_length(miniatura) <= 262144);

ALTER TABLE redes.proyectos DROP CONSTRAINT IF EXISTS proyectos_imagen_tipo_check;
ALTER TABLE redes.proyectos ADD CONSTRAINT proyectos_imagen_tipo_check
    CHECK (imagen_tipo IS NULL OR imagen_tipo IN ('image/png', 'image/jpeg', 'image/webp', 'image/gif'));

-- Lista de proyectos de un usuario y búsqueda por nombre / código.
CREATE INDEX proyectos_nombre_ix ON redes.proyectos (lower(nombre));
