-- Lado de los puntos de conexión de un cable en la mufa: por omisión los de los cables que llegan van a la derecha y los de los que salen a la izquierda;
-- con `espejo` el usuario los pasa al otro lado (para conectarlos con los hilos de otras mufas sin cruzar la caja).
ALTER TABLE redes.mufa_cables ADD COLUMN IF NOT EXISTS espejo boolean NOT NULL DEFAULT false;
