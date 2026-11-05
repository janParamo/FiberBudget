# 2026-11-05

## La ruta del presupuesto guarda todo lo que usa

- Al generar un presupuesto, en «Mis lugares» → «Presupuestos» se crea **una carpeta por presupuesto** (`<código>_<cliente>`) con: la **ruta**, el **punto exacto del cliente** (elemento «cliente»), la **acometida** (cable de clase acometida del final de la ruta al cliente) y los **postes nuevos** que la ruta necesita (un elemento «poste» por cada uno). Los números (metraje final, reserva, postes existentes) quedan en las propiedades de la ruta.
- Generar otra vez el mismo presupuesto: si la ruta no se tocó, se reemplaza todo (los postes nuevos de antes se borran y se crean los de ahora); si se editó, lo nuevo va al lado como «… (2)».
- **Al editar la ruta guardada** (Mis lugares → Editar), la pestaña «Medidas» enseña, como al medir y mientras se mueven los puntos: longitud, reserva, metraje final, acometida al cliente, metraje total, postes existentes, postes nuevos que pide el presupuesto y cuántos de los postes nuevos guardados se siguen usando, con un aviso de cuáles se borrarán.
- **Al guardar la edición**: los postes nuevos guardados que quedan a más de 25 m de la ruta (`poles.existing_pole_search_buffer_m`) se borran solos, y la acometida pasa a salir del nuevo final de la ruta y terminar en el cliente (que no se mueve). Una ruta que no es de un presupuesto no se toca.
- Código: `visor_rutas/redes/lugares_presupuesto.py` (`guardar_ruta`, `al_editar_ruta`, `resumen_ruta`; método `resumen_ruta_presupuesto`), gancho en `lugares.guardar_lugar`, `main._ruta_a_lugares` / `ruta_lugares.guardar` (reciben los postes nuevos y el punto del cliente), `web/lugares/mis_lugares.js` y `dialogo.js`. Pruebas: `test_redes_lugares_presupuesto.py`, `test_visor_pagina_ruta_presupuesto.py`.
- Las rutas guardadas ANTES de este cambio siguen sueltas en «Presupuestos» (sin cliente ni postes): al generar de nuevo ese presupuesto se crea su carpeta nueva.
