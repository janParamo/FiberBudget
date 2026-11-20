-- Cliente en el segmento de un hilo (como en el Visio: la flecha del cliente al hilo del cable, aunque el hilo siga su camino), además del cliente en el extremo del hilo
-- (el tramo final por donde llega al cliente). Un hilo puede tener uno de cada clase.
ALTER TABLE redes.hilo_servicios ADD COLUMN IF NOT EXISTS segmento boolean NOT NULL DEFAULT false;
DROP INDEX IF EXISTS redes.hilo_servicios_hilo_uk;
CREATE UNIQUE INDEX IF NOT EXISTS hilo_servicios_hilo_clase_uk ON redes.hilo_servicios (hilo_id, segmento) WHERE borrado_en IS NULL;
