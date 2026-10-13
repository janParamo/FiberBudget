-- Sección 8 de la especificación (datos y arquitectura): lo que faltaba del modelo.
--
-- 1) hilos guarda también su buffer y su color TIA-598 (8.1: "hilos (cable, número, buffer,
--    color TIA, estado)"). Los calcula la base con triggers a partir de cables.hilos_por_buffer,
--    así quedan bien venga de donde venga la escritura (editor, Duplicar, restaurar un respaldo)
--    y se recalculan si el cable cambia de 12 a 8 hilos por buffer.
--      buffer        1, 2, 3…          = (numero - 1) / hilos_por_buffer + 1
--      color         color del hilo    = TIA[(numero - 1) % hilos_por_buffer]   (se repite cada 8 o 12)
--      color_buffer  color del tubo    = TIA[(buffer - 1) % 12]
-- 2) mufa_cables.version: la posición de un cable en el lienzo de la mufa también lleva bloqueo
--    optimista (8.1: "toda escritura con versión por registro").
-- 3) Índices de las columnas que más se consultan y no tenían.

CREATE FUNCTION redes.color_tia(indice integer) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT (ARRAY['azul', 'naranja', 'verde', 'café', 'gris', 'blanco', 'rojo', 'negro', 'amarillo', 'violeta', 'rosa', 'aqua'])
           [((indice % 12) + 12) % 12 + 1]
$$;

ALTER TABLE redes.hilos ADD COLUMN buffer integer, ADD COLUMN color text, ADD COLUMN color_buffer text;

CREATE FUNCTION redes.hilos_buffer_color() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    por_buffer integer;
BEGIN
    SELECT hilos_por_buffer INTO por_buffer FROM redes.cables WHERE id = NEW.cable_id;
    por_buffer := COALESCE(NULLIF(por_buffer, 0), 12);
    NEW.buffer := (NEW.numero - 1) / por_buffer + 1;
    NEW.color := redes.color_tia((NEW.numero - 1) % por_buffer);
    NEW.color_buffer := redes.color_tia(NEW.buffer - 1);
    RETURN NEW;
END
$$;

CREATE TRIGGER hilos_buffer_color BEFORE INSERT OR UPDATE OF numero, cable_id ON redes.hilos
    FOR EACH ROW EXECUTE FUNCTION redes.hilos_buffer_color();

CREATE FUNCTION redes.cables_recolorear_hilos() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE redes.hilos SET numero = numero WHERE cable_id = NEW.id;       -- fires hilos_buffer_color
    RETURN NULL;
END
$$;

CREATE TRIGGER cables_recolorear_hilos AFTER UPDATE OF hilos_por_buffer ON redes.cables
    FOR EACH ROW WHEN (OLD.hilos_por_buffer IS DISTINCT FROM NEW.hilos_por_buffer)
    EXECUTE FUNCTION redes.cables_recolorear_hilos();

UPDATE redes.hilos SET numero = numero;                                   -- existing fibres
ALTER TABLE redes.hilos ALTER COLUMN buffer SET NOT NULL, ALTER COLUMN color SET NOT NULL, ALTER COLUMN color_buffer SET NOT NULL;

ALTER TABLE redes.mufa_cables ADD COLUMN version integer NOT NULL DEFAULT 1;

CREATE INDEX conexiones_proyecto_ix ON redes.conexiones (proyecto_id) WHERE borrado_en IS NULL;
CREATE INDEX splitters_proyecto_ix ON redes.splitters (proyecto_id) WHERE borrado_en IS NULL;
CREATE INDEX conectores_proyecto_ix ON redes.conectores (proyecto_id) WHERE borrado_en IS NULL;
CREATE INDEX mufa_cables_cable_ix ON redes.mufa_cables (cable_id);
CREATE INDEX pendientes_responsable_ix ON redes.pendientes (responsable_id) WHERE borrado_en IS NULL;
CREATE INDEX problemas_elemento_ix ON redes.problemas (elemento_id) WHERE borrado_en IS NULL;
CREATE INDEX problemas_cable_ix ON redes.problemas (cable_id) WHERE borrado_en IS NULL;
