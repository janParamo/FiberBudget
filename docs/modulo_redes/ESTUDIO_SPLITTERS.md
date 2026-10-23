# Estudio medido: leer los splitters de los diagramas de Visio (2026-10-20)

Pregunta de Jan: ¿se puede saber **automáticamente** si un splitter es secundario (morado) o principal (dorado) y si tiene **puertos libres**
(flechas que apuntan a los números del splitter), sabiendo que "las líneas no están unidas al número" y que Visio "las desplaza"?
Todo lo de abajo se midió sobre los 428 diagramas ya importados (`datos/cache/odg`, convertidos con LibreOffice). Los scripts están en
`red_fibra/estudio_splitters/` (cada uno dice qué mide; `odgtools.py` lee un .odg en cm absolutos).

## 1. ¿La conversión desplaza las líneas? **No**

Los diagramas se leen de la conversión de LibreOffice (el "intermediario"). Para saber si esa conversión mueve algo se compararon, en los 43 `.vsdx`
(que sí se pueden leer nativamente) las posiciones del Visio original contra las del `.odg`:

| Medida | Resultado |
|---|---|
| Textos emparejados (misma palabra) | desplazamiento mediano **0,00 cm** en los 43 archivos (traslación 0,0 / 0,0) |
| Conectores / líneas del `.vsdx` | 8 778 conectores, 17 556 extremos: **100 % a ≤ 0,05 cm** del extremo que dice el Visio (en cada archivo hay tantas líneas en el .odg como conectores en el .vsdx) |
| Archivos `.vsd` (386 de 428; no se pueden leer nativamente) | 4 diagramas existen también como `.vsdx`: en 3, el 96–97 % de los extremos coinciden con la conversión del `.vsdx` (la diferencia son 5–9 líneas que están en una versión y no en la otra); el cuarto es otra versión del dibujo |

Nota de método: un primer intento dio 13 % de extremos "desplazados"; era mi lector de `draw:path` (los saltos que Visio dibuja donde dos líneas se cruzan
son curvas). Con el lector corregido (`odgtools.anclas_svg`) el desajuste es 0.

**Conclusión:** lo que se ve "desplazado" no lo causa la conversión: está en el dibujo mismo (las flechas se dibujan cerca del número, no pegadas a él:
la distancia del número a la línea más cercana es de 0,07 a 0,5 cm). Eso es lo que hay que absorber al leer el dibujo.

## 2. Secundario o principal por el color: **sí, es confiable**

El texto del splitter conserva su color en el dibujo (`fo:color`). De 1 782 etiquetas de splitter (textos "SPL …" cortos):

| Color | Etiquetas | Lectura |
|---|---|---|
| Morado `#7030a0` | 806 | **secundario**. De las que dicen la palabra: 280 «SECUNDARIO» contra 1 «PRINCIPAL» (precisión 99,6 %) |
| Naranja / dorado (`#d26d19`, `#ea700d`, `#966115`, `#ea9651`) | 241 | **principal**. De las que dicen la palabra: ~148 «PRINCIPAL» contra 9 «SECUNDARIO» (precisión ~94 %) |
| Negro u otro | 735 | no se puede decir por el color (de las que dicen la palabra: 99 «PRINCIPAL», 46 «SECUNDARIO») |

Cobertura: el color decide el 59 % de los splitters dibujados; el resto hay que mirarlo por la palabra (SECUNDARIO aparece en 466 textos y PRINCIPAL en 310) o dejarlo "por confirmar".
El cuadro de números de puerto (un solo cuadro con "8 7 6 5 4 3 2 1", o "1 2 3 … 8" en una línea) tiene el mismo color que la etiqueta y se encuentra a ≤ 8 cm en el 79 % de los splitters (1 401 de 1 782).

## 3. Puertos libres por las líneas que llegan al número: **no es confiable todavía**

Verdad conocida: solo 280 splitters (13 %) traen la lista "1- cliente … 7- 8-" por puerto; 166 se pudieron emparejar con su splitter dibujado
(52 diagramas): **1 186 puertos, 52 libres (renglón en blanco) y 1 134 ocupados**. Con la posición exacta de cada número (tomada del SVG) y las líneas del .odg:

| Regla ("libre si no llegan líneas…") | Libres encontrados (de 52) | Ocupados tomados por libres (de 1 134) | Precisión de "libre" |
|---|---|---|---|
| ninguna flecha a ≤ 0,4 cm | 32 (62 %) | 141 | 18 % |
| ninguna flecha a ≤ 0,6 cm | 20 (38 %) | 81 | 20 % |
| ninguna línea a ≤ 0,4 cm | 21 (40 %) | 136 | 13 % |
| ≤ 1 flecha a ≤ 0,4 cm | 47 (90 %) | 710 | 6 % |

Los puertos libres y los ocupados se parecen demasiado: la distancia del número a la línea más cercana tiene mediana 0,23 cm en los ocupados y 0,32 cm en los libres.
Adivinar "todos ocupados" acierta el 96 % de los puertos de esta muestra, y ninguna regla de líneas lo supera sin marcar como libres decenas de puertos ocupados.

Por qué no separa (lo que se ve en los dibujos): hay líneas en casi todos los puertos aunque el renglón esté en blanco (cables de reserva en rosa punteado, el haz de
hilos que pasa por el mismo lugar, la propia línea de entrada del splitter); la flecha no se pega al número; y la lista en blanco puede significar "aún no escrito" y no "libre"
(los 52 libres son un puerto por splitter, casi siempre el último). Con tan pocos libres de referencia (52) las cifras tienen mucho margen de error.

## 4. Qué se puede hacer con esto

1. **Ya se puede (alta confianza):** clasificar secundario / principal por el color (y la palabra cuando el color es negro), y encontrar el cuadro de puertos de cada splitter.
2. **Se puede con ayuda:** puertos libres donde hay lista de clientes por puerto (13 % de los splitters; el renglón en blanco es la pista) y donde el texto dice cuántos clientes lleva.
3. **No recomendable automatizar todavía:** "este splitter tiene puerto libre" solo con las líneas. Falta, para lograrlo: seguir la línea de cada número hasta lo que conecta
   (un cliente C#####, otra mufa) y no solo mirar su extremo; y una verdad de referencia más grande (hoy 52 libres). Propuesta de siguiente paso: una pantalla donde la persona confirme
   en el diagrama los puertos libres del splitter secundario elegido, que se guarda y se reutiliza (y sirve de verdad de referencia para mejorar la lectura automática).
4. La **continuidad** (hilos verdes, no se toca) depende de leer el color de los hilos en el mismo dibujo: mismo método (color del trazo), por medir.

## 5. Seguimiento (2026-10-21)
Los pasos 1 y 2 de §4 ya se hacen en cada ruta de fusión (`visor_rutas/splitters_diagrama.py`) y el 3 tiene pantalla (`web/mapa/splitters.js`, tabla `redes.splitters_diagrama`). Nota: la expresión que leía las listas «1- cliente» del estudio dejaba que un renglón en blanco se tragara el siguiente; con la corrección los puertos libres de referencia son más de 52 (las precisiones de §3 son una cota que puede variar al repetir la medición).

## 6. Los «hilos verdes» (continuidad): medido el 2026-10-22 — el color solo **no** sirve

Pregunta (regla 7 de Jan: splitter secundario con puertos libres **y hilos libres entre mufas**): ¿se puede leer del dibujo qué hilos pasan de largo por una mufa
(los «verdes, no se toca») para saber si hay hilos libres hacia el splitter? Se midió con `red_fibra/estudio_splitters/e4_hilos_verdes.py` (lee cada `.odg` con
`fusiones.leer_dibujo` y clasifica el color de cada línea con `color_tia`, el mismo método del piloto de fusiones) sobre los 428 diagramas:

| Color (TIA-598) | Líneas | Con flechas | Diagramas |
|---|---|---|---|
| negro | 19 817 | 40 % | 425 |
| violeta | 8 042 | 89 % | 289 |
| rojo | 7 109 | 91 % | 373 |
| aqua | 6 760 | 98 % | 319 |
| rosa | 5 406 | 98 % | 217 |
| **verde** | **4 802** | **99 %** | **280 (65 %)** |
| naranja | 3 483 | 95 % | 254 |
| azul | 1 284 | 19 % | 181 |

- El verde aparece en el 65 % de los diagramas, pero el **99 % de esas líneas llevan flechas** (son puentes de fusión: el hilo 3 de cada buffer es verde en el código
  TIA), y su largo mediano (8,28 cm) es igual al de las demás (8,48 cm). No hay una marca distinta que separe «hilo verde de continuidad» del «hilo 3 empalmado».
- Las que podrían ser continuidad (verdes, **sin flechas** y de 2 cm o más): solo **7 diagramas** (2 %), 5 de ellos con splitters. Son tan pocas que no sirven de regla.

**Conclusión:** la continuidad no se puede leer automáticamente solo con el color del trazo. Hace falta seguir cada línea hasta lo que une (qué mufa entra y cuál sale) y una
verdad de referencia que hoy no existe. Por eso la regla 7 queda así: el plan **sí corta la ruta** en el primer splitter secundario con puertos libres, y deja como aviso
rojo «validar con Planta Externa que haya hilos libres entre las mufas hasta aquí». Para automatizarlo habría que contar con una lista de hilos libres por cable (por ejemplo, la de
Planta Externa) o que alguien marque en el visor los hilos de continuidad.
