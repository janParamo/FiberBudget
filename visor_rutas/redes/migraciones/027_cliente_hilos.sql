-- Clientes con varios hilos: un cliente tiene `hilos` (1 por omisión: una sola línea, como siempre) y cada lugar donde está
-- (un hilo del cable o una salida de splitter) dice cuál de los hilos del cliente llega ahí (`hilo_cliente`). Así un mismo cliente puede
-- estar en distintos hilos (por ejemplo el H1 en un hilo de la mufa y el H2 en una salida de splitter: sangría de un cliente a otro).
-- x, y: dónde dibuja el usuario la tarjeta del cliente en el editor de la mufa (null: automático).
ALTER TABLE redes.mufa_clientes ADD COLUMN IF NOT EXISTS hilos smallint NOT NULL DEFAULT 1 CHECK (hilos BETWEEN 1 AND 48);
ALTER TABLE redes.mufa_clientes ADD COLUMN IF NOT EXISTS x double precision;
ALTER TABLE redes.mufa_clientes ADD COLUMN IF NOT EXISTS y double precision;
ALTER TABLE redes.hilo_servicios ADD COLUMN IF NOT EXISTS hilo_cliente smallint NOT NULL DEFAULT 1 CHECK (hilo_cliente BETWEEN 1 AND 48);
ALTER TABLE redes.puerto_servicios ADD COLUMN IF NOT EXISTS hilo_cliente smallint NOT NULL DEFAULT 1 CHECK (hilo_cliente BETWEEN 1 AND 48);
