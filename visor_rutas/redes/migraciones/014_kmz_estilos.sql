-- respaldo: previo
-- Visor v2, fase 9: ícono / color / tamaño propio para los elementos del KMZ (mufas, postes, clientes, líneas…).
--
-- kmz_estilos   el estilo que se le pone a UN elemento del KMZ (alcance 'elemento', `clave` = la misma que usa kmz_cambios: carpeta + nombre
--               original + coordenada) o a TODA una carpeta (alcance 'carpeta', `clave` = «carpeta|*|»). `estilo` es un JSON con `icono`
--               ({tipo, id, color, escala, opacidad}, como los íconos de Mis lugares) para puntos y/o `linea` ({color, grosor, opacidad}).
--               Un elemento con estilo propio gana sobre el de su carpeta. Es de todos (la red es compartida): lo cambian administradores y
--               editores. El archivo KMZ y las tablas del presupuesto no se tocan. Hay un solo estilo activo por clave.

CREATE TABLE IF NOT EXISTS redes.kmz_estilos (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clave           text NOT NULL CHECK (btrim(clave) <> ''),
    alcance         text NOT NULL CHECK (alcance IN ('elemento', 'carpeta')),
    carpeta         text NOT NULL,
    nombre          text NOT NULL DEFAULT '',
    estilo          jsonb NOT NULL,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS kmz_estilos_clave_uk ON redes.kmz_estilos (clave) WHERE borrado_en IS NULL;
