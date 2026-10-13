-- respaldo: previo
-- Migración Visio, fase 4 (docs/migracion_visio/PLAN.md, regla 6.5 y sección 8): modelo de la mufa y bandejas.
-- La posición de un empalme en su bandeja la puede poner la regla (estimada) o el usuario; y el modelo
-- de la mufa guarda por qué se eligió (cable mayor, cantidad de splitters…) y sus avisos (excede capacidad…).
-- Escrita para poder correrse de nuevo sin error.

ALTER TABLE redes.conexiones
    ADD COLUMN IF NOT EXISTS posicion_estimada boolean NOT NULL DEFAULT false;

ALTER TABLE redes.mufa_modelos
    ADD COLUMN IF NOT EXISTS motivo text,
    ADD COLUMN IF NOT EXISTS avisos jsonb NOT NULL DEFAULT '[]'::jsonb;
