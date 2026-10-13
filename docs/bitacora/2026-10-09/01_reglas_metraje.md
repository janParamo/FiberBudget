# Reglas de metraje para el diseño de red (D3): lo que Jan debe especificar

En el editor de mapa (fase 3), cada cable mostrará su **metraje** y el **detalle**, como en `docs/modulo_redes/img/06_detalle_metraje_cable.png`. Las reglas irán en `business_rules.yaml`, en una sección nueva `diseno_red` con comentarios. **No cambian** las reglas del presupuesto (`route:`), que siguen igual para n8n.

| # | Regla | Qué significa | Hoy en el presupuesto (`route:`) | Ejemplo de la imagen 06 | Lo que Jan debe decir |
|---|---|---|---|---|---|
| 1 | **Distancia lineal** | Largo del cable dibujado en el mapa, siguiendo sus vértices y postes | igual (distancia de la ruta) | 197 m | Nada: se calcula sola |
| 2 | **Contingencia** | Margen extra sobre la distancia | `safety_margin: 0.0` (0 %) | 20 m | ¿Porcentaje o metros fijos por cable? ¿Cuánto? |
| 3 | **Salida de nodo** | Metros extra cuando el cable sale de un nodo / OLT | no existe (`slack_per_endpoint_m: 0`) | 0 m | ¿Metros por cable que sale de un nodo? |
| 4 | **Reserva por mufa** | Metros que se dejan enrollados en cada mufa por la que el cable entra o termina | `connection_reserve_m: 35` (una vez por presupuesto) | 1 × 40 m | ¿Metros por mufa? ¿Cuentan las dos puntas del cable, o solo donde hay fusión? |
| 5 | **Reserva por tendido** | Reserva periódica a lo largo del cable | `reserve_interval_m: 300` y `reserve_percent: 0.20` (cada 300 m se suma el 20 %) | 0 × 50 m | ¿El mismo cálculo del presupuesto (cada 300 m, 20 %), o "X m cada Y m"? |
| 6 | **Reserva por cruce** | Metros extra por cada cruce de calle | no existe | 1 × 60 m | ¿Metros por cruce? ¿El usuario indica cuántos cruces tiene el cable, o se intenta detectar? |
| 7 | **Extremo en cliente** | Holgura en la casa del cliente (acometida) | `slack_per_endpoint_m: 0` | — | ¿Metros por extremo en un cliente? |
| 8 | **¿Varían por tipo?** | Valores distintos según la clase de cable o la construcción | — | — | ¿Los mismos valores para troncal, distribución y acometida? ¿Y para ADSS y FLAT? |
| 9 | **Redondeo** | Cómo se presenta el total | el presupuesto redondea hacia arriba al metro | — | ¿Al metro hacia arriba está bien? |

**Propuesta para responder rápido:** "usa los mismos valores del presupuesto". En ese caso:

| Regla | Valor |
|---|---|
| Contingencia | 0 % |
| Reserva de tendido | cada 300 m, 20 % |
| Reserva por mufa | 35 m por mufa |
| Salida de nodo | 0 |
| Cruce | 0 |
| Extremo en cliente | 0 |
| Redondeo | al metro hacia arriba |
| Por tipo de cable | los mismos valores para todos |
