-- Incorporar a la red: lo aplicado de las importaciones de KMZ (lo nuevo, lo modificado, lo eliminado) se mete en el archivo RED DE IDEAY.kmz; las importaciones que ya
-- quedaron dentro del archivo se marcan con la fecha y dejan de salir en la capa «Importados (aplicados)» (ya estan en sus carpetas de la red).
ALTER TABLE redes.kmz_importaciones ADD COLUMN IF NOT EXISTS incorporada_en timestamptz;
