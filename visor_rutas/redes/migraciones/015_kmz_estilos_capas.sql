-- respaldo: previo
-- Visor v2, fase 9 (continuación): los íconos de lo que dibuja el propio visor (postes y mufas de la ruta, nodos Visio, mufa buscada, punto de
-- conexión y cliente) también se pueden cambiar, y el cambio es de todos. Se guardan en la misma tabla kmz_estilos con alcance 'capa' y
-- clave «capa|<id>|» (por ejemplo «capa|poste|»).

ALTER TABLE redes.kmz_estilos DROP CONSTRAINT IF EXISTS kmz_estilos_alcance_check;
ALTER TABLE redes.kmz_estilos ADD CONSTRAINT kmz_estilos_alcance_check CHECK (alcance IN ('elemento', 'carpeta', 'capa'));
