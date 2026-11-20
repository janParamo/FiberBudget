-- ODF del nodo: cómo se acomodan sus puertos (columnas × filas, editable en cualquier momento; null = la automática) y la foto del ODF real.
ALTER TABLE redes.nodo_odfs ADD COLUMN IF NOT EXISTS columnas integer CHECK (columnas IS NULL OR columnas BETWEEN 1 AND 144);
ALTER TABLE redes.nodo_odfs ADD COLUMN IF NOT EXISTS filas integer CHECK (filas IS NULL OR filas BETWEEN 1 AND 144);
ALTER TABLE redes.nodo_odfs ADD COLUMN IF NOT EXISTS imagen bytea;
ALTER TABLE redes.nodo_odfs ADD COLUMN IF NOT EXISTS imagen_tipo text;
ALTER TABLE redes.nodo_odfs ADD COLUMN IF NOT EXISTS imagen_version integer NOT NULL DEFAULT 0;
