-- App de campo, fase 5: los cables que se trazan en campo se revisan igual que los puntos.
--
-- campo_trazos            + longitud_m (metros del trazo), motivo del rechazo, quién y cuándo lo revisó, y a dónde fue al aprobarlo:
--                         `cable_id` (un cable de la red base / de un proyecto) o `lugar_id` (una ruta de Mis lugares).
-- Tabla existente con columnas nuevas y opcionales: no cambia datos.

ALTER TABLE redes.campo_trazos
    ADD COLUMN IF NOT EXISTS longitud_m     numeric,
    ADD COLUMN IF NOT EXISTS motivo_rechazo text,
    ADD COLUMN IF NOT EXISTS revisado_por   bigint REFERENCES redes.usuarios (id),
    ADD COLUMN IF NOT EXISTS revisado_en    timestamptz,
    ADD COLUMN IF NOT EXISTS cable_id       bigint REFERENCES redes.cables (id),
    ADD COLUMN IF NOT EXISTS lugar_id       bigint REFERENCES redes.lugares_elementos (id);
CREATE INDEX IF NOT EXISTS campo_trazos_estado_ix ON redes.campo_trazos (estado, recibido_en DESC) WHERE borrado_en IS NULL;
CREATE INDEX IF NOT EXISTS campo_trazos_geom_gix ON redes.campo_trazos USING gist (geom);
