# Solicitud de acceso de solo lectura a la base de Kayako desde la VM del servicio de presupuestos

Fecha: 2026-11-10

## 1. Qué se pide
Autorizar que la máquina virtual del servicio de presupuestos (Fiber Budget) se conecte a la base de datos de Kayako **en modo solo lectura**, con el **mismo usuario de solo lectura** que ya usa hoy la PC de desarrollo.

| | |
|---|---|
| **Origen (a autorizar)** | VM del servicio (Ubuntu 24.04, el servicio corre en un contenedor Docker). IP interna **10.0.40.154**; hacia Internet sale con la IP pública **[COMPLETAR: IP pública de salida de la VM]**, que es la que verá el servidor de Kayako |
| **Destino** | `soporte.ideay.com`, puerto **3306** (MySQL/MariaDB) |
| **Base** | `kayako_fusion` |
| **Usuario** | el usuario de solo lectura que ya existe para este programa (hoy autorizado solo desde la PC de desarrollo) |
| **Qué cambia** | que ese usuario también pueda entrar desde `10.0.40.154` (permiso `'usuario'@'<IP que vea el servidor>'` y regla de firewall hacia el 3306) |

Hoy la conexión desde la VM falla con `(2003, "Can't connect to MySQL server on 'soporte.ideay.com' (timed out)")`: la conexión no llega (no es un problema de usuario ni de contraseña, que se validan después de conectar). `soporte.ideay.com` resuelve a `186.1.31.11`; desde la PC de desarrollo funciona. Desde la PC de desarrollo funciona, como se muestra abajo.

## 2. Para qué se usa
El programa muestra a los usuarios internos los tickets de tres departamentos de Kayako: **Fibra Optica** (pedidos de presupuesto), **Incidencias Masivas** e **Instalaciones**, para consultarlos junto con la red de fibra. No escribe en Kayako de ninguna manera.

## 3. Garantías de solo lectura
- La conexión abre con `SET SESSION TRANSACTION READ ONLY` como primera instrucción.
- Las únicas sentencias que ejecuta son `SELECT` (listadas completas en el punto 5). No hay `INSERT`, `UPDATE`, `DELETE` ni cambios de estructura.
- Los datos de la conexión están en un archivo de configuración de la VM, fuera del código.

## 4. Permisos mínimos necesarios
Basta con `SELECT` sobre estas 8 tablas de `kayako_fusion` (ningún otro permiso):

`swtickets`, `swticketposts`, `swticketnotes`, `swusers`, `swuserorganizations`, `swcustomfieldvalues`, `swcustomfields`, `swcustomfieldoptions`

Ejemplo de la concesión (a ajustar al nombre real del usuario):
```sql
GRANT SELECT ON kayako_fusion.swtickets TO 'USUARIO'@'10.0.40.154';
GRANT SELECT ON kayako_fusion.swticketposts TO 'USUARIO'@'10.0.40.154';
GRANT SELECT ON kayako_fusion.swticketnotes TO 'USUARIO'@'10.0.40.154';
GRANT SELECT ON kayako_fusion.swusers TO 'USUARIO'@'10.0.40.154';
GRANT SELECT ON kayako_fusion.swuserorganizations TO 'USUARIO'@'10.0.40.154';
GRANT SELECT ON kayako_fusion.swcustomfieldvalues TO 'USUARIO'@'10.0.40.154';
GRANT SELECT ON kayako_fusion.swcustomfields TO 'USUARIO'@'10.0.40.154';
GRANT SELECT ON kayako_fusion.swcustomfieldoptions TO 'USUARIO'@'10.0.40.154';
```

## 5. Las consultas que ejecuta el programa (texto exacto)
Los `%s` son parámetros que se envían por separado (no se concatenan al texto).

### 5.1 Al abrir la conexión
```sql
SET SESSION TRANSACTION READ ONLY
```

### 5.2 Lista de tickets (carpeta «Presupuesto»: departamento de Fibra Optica, estado Abierto, últimos 30 días, máximo 300)
Parámetros, en orden: id del campo personalizado «Ejecutivo de cuenta» (64), departamento (`%Fibra%Optica%`), estado (`Abierto`), fecha mínima de actividad (Unix) y límite.
```sql
SELECT T.ticketid AS id, T.ticketmaskid AS ticket, T.subject AS asunto, T.fullname AS cliente, CFO.optionvalue AS ejecutivo,
       T.departmenttitle AS departamento, T.tickettypetitle AS tipo, T.ticketstatustitle AS estado, T.ownerstaffname AS owner, T.dateline AS creado,
       TP.contents AS primer_comentario, TP.ishtml AS primer_html,
       CASE WHEN TL.ticketpostid <> TP.ticketpostid THEN TL.contents ELSE NULL END AS ultimo_comentario,
       CASE WHEN TL.ticketpostid <> TP.ticketpostid THEN TL.ishtml ELSE NULL END AS ultimo_html,
       GREATEST(IFNULL(T.dateline, 0), IFNULL(T.lastactivity, 0), IFNULL(TP.editeddateline, 0), IFNULL(TL.dateline, 0), IFNULL(TL.editeddateline, 0)) AS ultima_actividad, T.prioritytitle AS prioridad, ORG.organizationname AS organizacion, T.lastreplier AS ultimo_respondedor,
       T.totalreplies AS respuestas, T.duetime AS vence
FROM kayako_fusion.swtickets AS T
  LEFT JOIN kayako_fusion.swusers AS U ON U.userid = T.userid
  LEFT JOIN kayako_fusion.swuserorganizations AS ORG ON ORG.userorganizationid = U.userorganizationid
  LEFT JOIN kayako_fusion.swticketposts AS TP ON TP.ticketpostid = T.firstpostid
  LEFT JOIN kayako_fusion.swticketposts AS TL ON TL.ticketpostid = T.lastpostid
  LEFT JOIN kayako_fusion.swcustomfieldvalues AS CFV ON CFV.typeid = T.ticketid AND CFV.customfieldid = %s
  LEFT JOIN kayako_fusion.swcustomfieldoptions AS CFO ON CFO.customfieldoptionid = CFV.fieldvalue
WHERE T.departmenttitle LIKE %s AND T.ticketstatustitle IN (%s) AND GREATEST(IFNULL(T.dateline, 0), IFNULL(T.lastactivity, 0), IFNULL(TP.editeddateline, 0), IFNULL(TL.dateline, 0), IFNULL(TL.editeddateline, 0)) >= %s
ORDER BY GREATEST(IFNULL(T.dateline, 0), IFNULL(T.lastactivity, 0), IFNULL(TP.editeddateline, 0), IFNULL(TL.dateline, 0), IFNULL(TL.editeddateline, 0)) DESC
LIMIT %s
```

### 5.3 Lista de tickets (carpetas «Incidencias masivas» e «Instalaciones»)
Misma consulta, con otro departamento y con la condición de estado así (Incidencias masivas: todos menos `Cerrado`; Instalaciones: solo `Abierto`, `Agendado`, `Planificación`, `En Progreso`, `En Espera del Cliente`). Máximo 1000 filas. En el ejemplo, la condición de «todos menos Cerrado»:
```sql
SELECT T.ticketid AS id, T.ticketmaskid AS ticket, T.subject AS asunto, T.fullname AS cliente, CFO.optionvalue AS ejecutivo,
       T.departmenttitle AS departamento, T.tickettypetitle AS tipo, T.ticketstatustitle AS estado, T.ownerstaffname AS owner, T.dateline AS creado,
       TP.contents AS primer_comentario, TP.ishtml AS primer_html,
       CASE WHEN TL.ticketpostid <> TP.ticketpostid THEN TL.contents ELSE NULL END AS ultimo_comentario,
       CASE WHEN TL.ticketpostid <> TP.ticketpostid THEN TL.ishtml ELSE NULL END AS ultimo_html,
       GREATEST(IFNULL(T.dateline, 0), IFNULL(T.lastactivity, 0), IFNULL(TP.editeddateline, 0), IFNULL(TL.dateline, 0), IFNULL(TL.editeddateline, 0)) AS ultima_actividad, T.prioritytitle AS prioridad, ORG.organizationname AS organizacion, T.lastreplier AS ultimo_respondedor,
       T.totalreplies AS respuestas, T.duetime AS vence
FROM kayako_fusion.swtickets AS T
  LEFT JOIN kayako_fusion.swusers AS U ON U.userid = T.userid
  LEFT JOIN kayako_fusion.swuserorganizations AS ORG ON ORG.userorganizationid = U.userorganizationid
  LEFT JOIN kayako_fusion.swticketposts AS TP ON TP.ticketpostid = T.firstpostid
  LEFT JOIN kayako_fusion.swticketposts AS TL ON TL.ticketpostid = T.lastpostid
  LEFT JOIN kayako_fusion.swcustomfieldvalues AS CFV ON CFV.typeid = T.ticketid AND CFV.customfieldid = %s
  LEFT JOIN kayako_fusion.swcustomfieldoptions AS CFO ON CFO.customfieldoptionid = CFV.fieldvalue
WHERE T.departmenttitle LIKE %s AND T.ticketstatustitle NOT IN (%s) AND GREATEST(IFNULL(T.dateline, 0), IFNULL(T.lastactivity, 0), IFNULL(TP.editeddateline, 0), IFNULL(TL.dateline, 0), IFNULL(TL.editeddateline, 0)) >= %s
ORDER BY GREATEST(IFNULL(T.dateline, 0), IFNULL(T.lastactivity, 0), IFNULL(TP.editeddateline, 0), IFNULL(TL.dateline, 0), IFNULL(TL.editeddateline, 0)) DESC
LIMIT %s
```

### 5.4 Campos adicionales de los tickets de la lista (código de cliente, sucursal, servicio, medio, coordenadas)
```sql
SELECT V.typeid AS ticketid, F.title AS titulo, COALESCE(O.optionvalue, V.fieldvalue) AS valor
FROM kayako_fusion.swcustomfieldvalues AS V
  JOIN kayako_fusion.swcustomfields AS F ON F.customfieldid = V.customfieldid
  LEFT JOIN kayako_fusion.swcustomfieldoptions AS O ON O.customfieldid = V.customfieldid AND O.customfieldoptionid = V.fieldvalue
WHERE V.typeid IN (%s) AND F.title IN (%s)
```

### 5.5 Historial de un ticket (solo de tickets de Incidencias Masivas e Instalaciones; se ejecuta al abrir un ticket)
```sql
SELECT ticketid FROM kayako_fusion.swtickets WHERE ticketid = %s AND departmenttitle IN (%s, %s)

SELECT ticketpostid AS id, dateline, fullname AS autor, creator, staffid, isprivate, ishtml, hasattachments, contents
FROM kayako_fusion.swticketposts WHERE ticketid = %s ORDER BY dateline, ticketpostid LIMIT %s

SELECT ticketnoteid AS id, dateline, staffname AS autor, isedited, notecolor, note
FROM kayako_fusion.swticketnotes WHERE linktype = 1 AND linktypeid = %s ORDER BY dateline, ticketnoteid LIMIT %s
```

## 6. Carga esperada
Una conexión por proceso del servicio (una sola, reutilizada). La lista de tickets se vuelve a leer cada 2 minutos mientras alguien tenga el programa abierto en esa pantalla, y al abrir cada carpeta; el historial solo al abrir un ticket. Todas las consultas están acotadas por `LIMIT` (300, 1000 y 300). Son pocos usuarios internos.

## 7. Prueba de que hoy funciona desde la PC de desarrollo
Ejecutada el 2026-11-10 17:04 con el mismo programa (`herramientas/kayako_vista_previa.py --probar`, solo lectura):

```
Conectado (solo lectura). MySQL 10.0.25-MariaDB; 261 tablas; 265620 tickets en total.
```
