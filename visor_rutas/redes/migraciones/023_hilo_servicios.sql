-- Cliente de un hilo: un cliente identificado (codigo C#####, nombre, ID de servicio) puede estar en un hilo de manera individual (por ejemplo el hilo 1 de un
-- cable), no solo en la salida de un splitter. Igual que puerto_servicios, pero colgado de un hilo; a lo sumo uno activo por hilo.
CREATE TABLE IF NOT EXISTS redes.hilo_servicios (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hilo_id         bigint NOT NULL REFERENCES redes.hilos (id),
    codigo_cliente  text,
    nombre          text,
    id_servicio     text,
    elemento_id     bigint REFERENCES redes.elementos (id),
    fuente          redes.fuente_dato,
    confianza       redes.confianza_dato,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    creado_por      bigint REFERENCES redes.usuarios (id),
    actualizado_en  timestamptz,
    actualizado_por bigint REFERENCES redes.usuarios (id),
    borrado_en      timestamptz,
    version         integer NOT NULL DEFAULT 1,
    CHECK (coalesce(codigo_cliente, nombre, id_servicio) IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS hilo_servicios_hilo_uk ON redes.hilo_servicios (hilo_id) WHERE borrado_en IS NULL;
