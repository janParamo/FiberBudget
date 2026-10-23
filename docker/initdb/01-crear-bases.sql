-- Solo se ejecuta la PRIMERA vez que arranca el contenedor "db" (volumen pgdata vacio).
-- Crea las dos bases del proyecto con PostGIS: Presupuesto_fibra (el KMZ: red_puntos / red_lineas) y Presupuesto_visio (diagramas Visio,
-- modulo de redes y almacen de archivos). El esquema `redes` y sus tablas los crea el servicio solo (migraciones 001 en adelante).
CREATE DATABASE "Presupuesto_fibra";
CREATE DATABASE "Presupuesto_visio";

\connect "Presupuesto_fibra"
CREATE EXTENSION IF NOT EXISTS postgis;

\connect "Presupuesto_visio"
CREATE EXTENSION IF NOT EXISTS postgis;
