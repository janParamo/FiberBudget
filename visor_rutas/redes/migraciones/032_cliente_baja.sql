-- Cliente dado de baja en una mufa: se dibuja en celeste (el cliente sigue en la mufa y en sus hilos, solo queda marcado).
ALTER TABLE redes.mufa_clientes ADD COLUMN IF NOT EXISTS baja boolean NOT NULL DEFAULT false;
