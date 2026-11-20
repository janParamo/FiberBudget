-- ODF y OLT de un nodo que vienen del Visio (visor_rutas/redes/nodo.py: convertir_visio): de dónde salieron y si su cantidad de puertos / hilos es una estimación a revisar.
ALTER TABLE redes.nodo_odfs ADD COLUMN IF NOT EXISTS fuente text NOT NULL DEFAULT 'usuario';
ALTER TABLE redes.nodo_odfs ADD COLUMN IF NOT EXISTS estimado boolean NOT NULL DEFAULT false;
ALTER TABLE redes.nodo_odfs ADD COLUMN IF NOT EXISTS ref_elemento_id bigint REFERENCES redes.elementos (id);
CREATE UNIQUE INDEX IF NOT EXISTS nodo_odfs_ref_ux ON redes.nodo_odfs (ref_elemento_id) WHERE borrado_en IS NULL AND ref_elemento_id IS NOT NULL;

ALTER TABLE redes.nodo_olts ADD COLUMN IF NOT EXISTS fuente text NOT NULL DEFAULT 'usuario';
ALTER TABLE redes.nodo_olts ADD COLUMN IF NOT EXISTS estimado boolean NOT NULL DEFAULT false;
