# App de campo — guía para técnicos

Con la app registra desde el teléfono los **postes, mufas, reservas, solitarias, clientes y cables** que encuentra en campo. El supervisor los ve en su pantalla en cuanto usted los envía.
Funciona en **Android (Chrome)** y en **iPhone (Safari, iOS 16.4 o más nuevo)**. Le deben dar: la **dirección** (empieza con `https://`) y **su clave de técnico** (una propia, de `CAMPO_API_KEYS`; no es la del visor).

> **Por ahora la dirección es de ngrok** (`https://….ngrok-free.dev/campo/`). **La primera vez** que la abra, ngrok muestra una página con un botón azul **«Visit Site»**: tóquelo y siga. Es normal, no es un virus, y solo aparece una vez por teléfono (vuelve a salir si borra los datos del navegador).

## 1. Instalarla (una sola vez, con internet)

### Android
1. Abra la dirección en **Chrome**.
2. Escriba su clave y toque **Entrar**.
3. Toque ☰ → **Instalar app** (si no aparece: los tres puntos de Chrome → *Instalar aplicación* o *Agregar a pantalla principal*).
4. Desde ahora abra la app con el ícono **Campo**.

### iPhone
1. Abra la dirección en **Safari** (no en Chrome ni en la app de WhatsApp: si le llegó por mensaje, copie el enlace y péguelo en Safari).
2. Escriba su clave y toque **Entrar**.
3. Toque el botón **Compartir** (el cuadrito con una flecha hacia arriba, abajo en la pantalla).
4. Baje y toque **Agregar a pantalla de inicio** → **Agregar**.
5. Desde ahora abra la app con el ícono **Campo**, **no** desde Safari.
   > Importante: si usa la app desde Safari sin instalarla, el iPhone puede borrar los puntos que todavía no se enviaron.

Cuando el teléfono pregunte si la app puede usar su **ubicación**, toque **Permitir** (en iPhone: *Permitir al usar la app*). Si dijo que no por error: Ajustes → Privacidad → Localización.

## 2. Empezar el día
1. Abra la app. Verá el mapa a pantalla completa, arriba a la izquierda una **barra de herramientas** (☰ menú, filtro, lista, buscar, compartir) y la **jornada del día** con un círculo con la precisión del GPS (**±5 m**, por ejemplo).
   - **Verde** (±10 m o menos): puede registrar.
   - **Amarillo o rojo**: espere unos segundos a cielo abierto; la precisión mejora sola.
2. El mapa muestra **su posición** (punto azul) y los **postes y mufas que ya existen** para que se oriente; **solo puede verlos**, no editarlos ni borrarlos (al tocarlos sale su nombre y puede ir hacia ellos). El botón de la red los oculta; ◎ centra el mapa en usted. El tipo de mapa (satélite, con calles, calles) se cambia en ☰ → **Tipo de mapa**. En una tablet los formularios salen a un lado y el mapa sigue visible.

## 3. Registrar un punto
1. Párese **junto al poste, mufa o lo que vaya a registrar** y toque el botón verde **＋**.
2. Aparece una **mira** en el centro del mapa, en la posición donde está usted. Arriba elija el tipo: **Poste**, **Mufa**, **Reserva**, **Solitaria**, **Cliente** u **Otro**.
3. Si el GPS no es bueno (el aviso de arriba lo dice), mueva el mapa hasta que la mira quede **exactamente sobre el punto**. Toque **OK** (o **Cancelar**).
4. Complete lo que sepa:
   - **Poste:** tipo: **Ideay tubular**, **Ideay 8/120**, **Ideay 9/120**, **Madera** o **Concreto**.
   - **Mufa:** capacidad (48 o 96) y formato (domo u horizontal).
   - **Nombre:** la app propone uno («Poste 3»); cámbielo si quiere. **Descripción:** lo que ayude a quien lo revise.
   - **Fotos:** **Tomar foto** o **De la galería** (hasta 8). Tome una de lejos y una de cerca.
   - El lápiz junto a las coordenadas permite **corregir la posición** moviendo el mapa.
5. Toque el disquete 💾. Si la app dice **«Ya hay algo aquí: …»**, revise si ya existe ese poste o mufa antes de duplicarlo. Si sale con la flecha ← sin guardar, la app pregunta si guarda los cambios.
6. (Opcional) En ☰ → **Ajustes** puede activar **Agregar punto al instante**: el botón ＋ guarda el punto donde está usted, sin mover el mapa.

## 4. Trazar cable
Toque **＋** y luego uno de los dos botones de la izquierda:
- **Ruta (línea con puntos):** el cable se arma **punto por punto**. El punto elegido siempre está bajo la mira: mueva el mapa para colocarlo; **＋** agrega otro, **−** quita el elegido, **‹ ›** pasan de un punto a otro y el **disquete** termina. Los puntos que quedan sobre un poste o mufa conocida se **pegan** a él (se ponen verdes); también puede tocar un poste del mapa para agregarlo. **✕** cancela (pregunta antes de descartar).
- **Huellas (🚶):** **grabar un recorrido**. Camine por donde pasa el cable; la app agrega un punto cada 5 m (se cambia en Ajustes → *Grabación de recorridos*). Toque **■** al terminar y elija **Guardar**, **Seguir grabando** o **Descartar**.

Al terminar elija el **tipo de cable** (ADSS o FLAT) y los **hilos** si los sabe, escriba la descripción y guarde. Para que el cable pueda aprobarse como cable de la red, **empiece y termine junto a un poste o mufa** (a menos de 20 m).

## 5. Sin señal
No pasa nada: todo queda **guardado en el teléfono**. Arriba aparece una franja amarilla **«N pendientes de enviar»**.
- **Android:** salen solos cuando vuelve la señal, aunque la app esté cerrada.
- **iPhone:** salen cuando **abre la app** con señal (o toque **Enviar ahora**). No cierre la sesión ni borre la app con puntos pendientes.
- Un punto que el supervisor no pueda aceptar por sus datos aparece en rojo **«Con error»**: tóquelo, corríjalo o bórrelo.

### Descargar la zona antes de salir (para ver el mapa sin señal)
Sin señal el teléfono solo muestra el mapa de lugares que ya había visto. Para no quedarse con el mapa en gris:
1. **Con buena señal o Wi-Fi**, antes de salir, acerque el mapa a la zona donde va a trabajar (se necesita un acercamiento medio: si está muy lejos la app se lo pide).
2. Menú ☰ → **Descargar esta zona**. Elija **Calles y postes** (menos mapa, más rápido) o **Con todo el detalle**; la app dice cuántos mosaicos son y cuánto pesa (de unos 5 a 60 MB).
3. Deje marcada **Incluir mufas y postes existentes** para ver también la red de esa zona sin señal, y toque **Descargar**. No cierre la app hasta que termine; si la cancela, se conserva lo ya bajado.
4. En el mismo menú aparecen las **zonas descargadas**: tóquelas para borrarlas y liberar espacio.
- Solo se descarga el mapa **Satélite** (con o sin calles) y **Calles (Esri)**; el de OpenStreetMap no permite descargas.
- Lo descargado sirve para ver el mapa; los puntos y cables nuevos se guardan en el teléfono y salen cuando vuelve la señal, como siempre.

## 6. Su lista, buscar, compartir y terminar el día
- **Lista** (el icono de lista de la barra): muestra lo de hoy con su estado: **Pendiente** (esperando revisión), **Aprobado**, **Corregido** o **Rechazado** (con el motivo). **Explorar** lleva al punto en el mapa; **Organizar** permite elegir varios y **eliminar** los que siguen pendientes. El filtro (embudo) muestra solo ciertos tipos o estados.
- Al tocar un punto o cable en el mapa sale una **tarjeta** abajo: ✏ editar (solo lo pendiente o sin enviar), copiar los detalles, **cómo llegar** (Google Maps, Apple Maps o Waze) y ⋮ más opciones.
- **Buscar** (lupa): por nombre de un punto suyo, de un poste/mufa ya cargado en el mapa, o por **coordenadas** («12.13, -86.25»).
- **Compartir** (icono de la barra): exporta lo levantado a **KML, KMZ o CSV** y lo manda por WhatsApp, correo, etc. Funciona también sin señal.
- Al terminar: ☰ → toque la jornada → **Cerrar la jornada**. Si quedaron puntos sin enviar, la app los envía cuando haya señal. **Abrir una jornada nueva** también está en ☰.
- ☰ → **Ajustes**: tema claro/oscuro, tamaño del texto y de los puntos, formato de coordenadas (decimal, grados-minutos-segundos), unidades, calidad de las fotos y más.

## 7. Si algo no funciona
| Pasa esto | Haga esto |
|---|---|
| Sale una página de ngrok con **«Visit Site»** | Tóquelo; es el aviso normal de la dirección gratuita |
| «La clave no es válida» | Revise que la copió completa, sin espacios; pídala otra vez al administrador |
| «Su usuario no tiene el rol de técnico de campo» | Pida al administrador que le asigne el rol |
| «Esta dirección no es segura (http)» | Está usando una dirección que no empieza con `https://`; pida la correcta |
| Dice «Sin GPS» o no mejora | Salga a cielo abierto; en Ajustes del teléfono revise que **Ubicación** esté encendida y permitida para la app |
| El mapa se ve gris | No hay señal y esa zona no se había visto antes; los puntos se pueden registrar igual (marque en el mapa o use el GPS) |
| La franja amarilla no baja | Toque **Enviar ahora**; si dice «Sin conexión», espere señal. Si dice «Con error», abra el punto en la lista |
| Cambió de teléfono | Instale la app otra vez con la misma clave; los puntos ya enviados están en el servidor |

**Recuerde:** la app solo toma su ubicación **con la app abierta y la pantalla encendida** (los teléfonos no dejan a las apps web seguirlo en segundo plano).
