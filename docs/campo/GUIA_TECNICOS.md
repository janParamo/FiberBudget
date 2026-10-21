# App de campo — guía para técnicos

Con la app registra desde el teléfono los **postes, mufas, reservas, solitarias, clientes y cables** que encuentra en campo. El supervisor los ve en su pantalla en cuanto usted los envía.
Funciona en **Android (Chrome)** y en **iPhone (Safari, iOS 16.4 o más nuevo)**. Le deben dar: la **dirección** (empieza con `https://`) y **su clave**.

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
1. Abra la app. Arriba verá la jornada del día y un círculo con la precisión del GPS (**±5 m**, por ejemplo).
   - **Verde** (±10 m o menos): puede registrar.
   - **Amarillo o rojo**: espere unos segundos a cielo abierto; la precisión mejora sola.
2. El mapa muestra **su posición** (punto azul) y la **red que ya existe** (postes, mufas y líneas) para que se oriente. El botón ⌁ la oculta; ◎ lo centra en usted; el botón de la derecha cambia entre satélite y calles.

## 3. Registrar un punto
1. Párese **junto al poste, mufa o lo que vaya a registrar**.
2. Toque el botón: **Poste**, **Mufa**, **Reserva**, **Solitaria**, **Cliente** u **Otro**.
3. Si el GPS ya está en verde se abre el formulario. Si no, la app dice **«Esperando mejor señal…»**; puede:
   - esperar a que mejore, o
   - **Usar igual** (queda anotada la precisión), o
   - **Marcar en el mapa**: mueva el mapa hasta que la mira roja quede sobre el punto y toque **Aquí**.
4. Complete lo que sepa:
   - **Poste:** tipo (Ideay, concreto, madera, metal, cliente).
   - **Mufa:** capacidad (48 o 96) y formato (domo u horizontal).
   - **Nombre:** la app propone uno («Poste 3»); cámbielo si quiere. **Notas:** lo que ayude a quien lo revise.
   - **Foto:** toque **📷 Agregar foto** (hasta 8). Tome una de lejos y una de cerca.
5. Toque **Guardar y enviar**. Si la app dice **«Ya hay algo aquí: …»**, revise si ya existe ese poste o mufa antes de duplicarlo.

## 4. Trazar un cable
1. Toque **Trazar cable**.
2. Arme el recorrido como le quede más fácil (puede mezclarlos):
   - **Tocar el mapa** en orden: poste por poste. Si toca cerca de un poste o mufa conocida, el cable se **pega** a ese punto (el vértice se pone verde).
   - **📍 Mi ubicación**: agrega donde está parado.
   - **Centro del mapa**: agrega donde está la mira roja.
   - **● Grabar recorrido**: camine por donde pasa el cable; la app agrega un punto cada 5 m. Toque **■ Detener grabación** al terminar.
   - **Deshacer** quita el último punto.
3. Toque **Terminar**, elija el **tipo de cable** (ADSS o FLAT) y los **hilos** si los sabe, escriba notas y toque **Guardar y enviar**.
4. Para que el cable pueda aprobarse como cable de la red, **empiece y termine junto a un poste o mufa** (a menos de 20 m).

## 5. Sin señal
No pasa nada: todo queda **guardado en el teléfono**. Arriba aparece una franja amarilla **«N pendientes de enviar»**.
- **Android:** salen solos cuando vuelve la señal, aunque la app esté cerrada.
- **iPhone:** salen cuando **abre la app** con señal (o toque **Enviar ahora**). No cierre la sesión ni borre la app con puntos pendientes.
- Un punto que el supervisor no pueda aceptar por sus datos aparece en rojo **«Con error»**: tóquelo, corríjalo o bórrelo.

## 6. Su lista y terminar el día
- El botón 📋 (arriba a la derecha) muestra lo de hoy con su estado: **Pendiente** (esperando revisión), **Aprobado**, **Corregido** o **Rechazado** (con el motivo). Puede **editar o borrar** lo que sigue pendiente.
- Al terminar: ☰ → **Cerrar la jornada**. Si quedaron puntos sin enviar, la app los envía cuando haya señal.

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
