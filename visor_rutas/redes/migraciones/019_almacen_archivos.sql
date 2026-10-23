-- Almacén de archivos en PostgreSQL: la base es la fuente de verdad y las carpetas del proyecto solo guardan una copia local desechable.
--
-- almacen_archivos   un archivo por (espacio, clave). Espacios en uso (visor_rutas/almacen_archivos.py):
--                      visor       presupuestos del visor (Excel / PDF; antes output/visor)
--                      odg         diagramas Visio ya convertidos, por md5 (antes red_fibra/cache_odg)
--                      diagramas   imágenes de esos diagramas (antes red_fibra/cache_diagramas)
--                      kmz         el KMZ de la red (antes red_kmz/)
--                      datos_kmz   capas, íconos y fotos que salen del KMZ (antes visor_rutas/datos_kmz)
-- Tabla nueva: no cambia datos existentes.

CREATE TABLE IF NOT EXISTS redes.almacen_archivos (
    espacio       text        NOT NULL,
    clave         text        NOT NULL,
    contenido     bytea       NOT NULL,
    tamano        bigint      NOT NULL,
    md5           text        NOT NULL,
    creado_en     timestamptz NOT NULL DEFAULT now(),
    modificado_en timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (espacio, clave)
);
-- Excel, ODG y PNG ya vienen comprimidos: PostgreSQL no pierde tiempo volviéndolos a comprimir.
ALTER TABLE redes.almacen_archivos ALTER COLUMN contenido SET STORAGE EXTERNAL;
CREATE INDEX IF NOT EXISTS almacen_archivos_fecha_ix ON redes.almacen_archivos (espacio, creado_en DESC);
