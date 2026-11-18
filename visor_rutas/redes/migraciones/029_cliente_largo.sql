-- Cliente de un solo hilo: el largo (px) de su línea recta desde el hilo hasta su icono, cuando el usuario lo alarga a mano (null: automático, en cascada).
ALTER TABLE redes.mufa_clientes ADD COLUMN IF NOT EXISTS largo double precision CHECK (largo IS NULL OR largo BETWEEN 10 AND 3000);
