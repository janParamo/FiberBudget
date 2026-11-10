-- Roles nuevos de usuarios.rol:
--   super_administrador  lo mismo que un administrador y ademas es el unico que gestiona a los administradores (los crea, los cambia de rol, los desactiva); nadie mas lo modifica.
--   guest                usa el mapa, genera rutas y presupuestos y edita la ruta que genera el generador; nada mas (no ve redes, tickets, campo ni usuarios, ni edita Mis lugares ni el KMZ).
--   prueba               solo lectura en todo (mas calcular rutas y presupuestos): para probar los endpoints sin riesgo.
ALTER TABLE redes.usuarios DROP CONSTRAINT IF EXISTS usuarios_rol_check;
ALTER TABLE redes.usuarios ADD CONSTRAINT usuarios_rol_check
    CHECK (rol IN ('super_administrador', 'administrador', 'editor', 'lector', 'tecnico', 'guest', 'prueba'));
