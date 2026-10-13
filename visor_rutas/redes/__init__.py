"""Módulo de Proyectos y Diagramación de Redes FTTH del visor (docs/modulo_redes/ESPECIFICACION.md).

Los usuarios diseñan y documentan sus redes (postes, mufas, clientes, cables, hilos, splitters)
en el esquema `redes` de la base Presupuesto_visio (VISIO_DB_*). No toca el presupuesto
(main.py, /presupuesto), ni red_lineas / red_puntos, ni el esquema red_fibra.

  db.py           conexión y errores para el usuario
  migrar.py       aplica migraciones/NNN_*.sql al iniciar (una vez, con advisory lock)
  repositorio.py  actualizaciones con versión (bloqueo optimista) e historial
  usuarios.py     identificación (Windows en local, X-Visor-Key en remoto), roles y permisos
  api.py          ServicioRedes.llamar(metodo, args): lo que usan ventana_web.Api y /visor/redes/*

Solo corre en la PC del servidor (modo local y la API): el .exe remoto no lo incluye.
"""
