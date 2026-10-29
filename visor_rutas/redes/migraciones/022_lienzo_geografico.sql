-- Esquema de zona con las coordenadas reales: las cajas se colocan donde estan las mufas en el mapa (sin mapa de fondo). Para que todos vean lo mismo,
-- el esquema guarda el punto de referencia (origen) y la escala (pixeles del lienzo por metro) con los que se calculan esas posiciones.
ALTER TABLE redes.lienzos ADD COLUMN IF NOT EXISTS origen_lat double precision CHECK (origen_lat IS NULL OR origen_lat BETWEEN -90 AND 90);
ALTER TABLE redes.lienzos ADD COLUMN IF NOT EXISTS origen_lon double precision CHECK (origen_lon IS NULL OR origen_lon BETWEEN -180 AND 180);
ALTER TABLE redes.lienzos ADD COLUMN IF NOT EXISTS escala double precision NOT NULL DEFAULT 2 CHECK (escala BETWEEN 0.05 AND 50);
