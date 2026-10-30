-- Sangría: una fusión hilo con hilo que, además de seguir su camino, alimenta a un cliente (o a otro ramal) en esa misma mufa: el hilo queda con dos extremos.
-- Se marca en la conexión y se dibuja en rojo.
ALTER TABLE redes.conexiones ADD COLUMN IF NOT EXISTS sangria boolean NOT NULL DEFAULT false;
