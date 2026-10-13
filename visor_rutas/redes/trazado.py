"""Trazado de hilo de punta a punta (fase 5).

Desde un hilo se sigue la fibra en sus dos sentidos (hacia el origen y hacia el destino de su
cable). En cada mufa o nodo se mira la conexión de ese hilo:
  - fusión con otro hilo        -> se sigue por el cable de ese hilo;
  - entrada de un splitter      -> se abre una rama por cada salida conectada;
  - salida de un splitter       -> se sube por su entrada;
  - conector (entrada/salida)   -> se pasa al otro lado;
  - sin conexión                -> el camino termina ahí ("sin continuidad").
Un cable que llega a un cliente termina el camino en ese cliente.

Resultado: {"inicio": {...}, "sentidos": [{"nombre", "caminos": [camino]}], "resumen": {...},
"cables": [...], "elementos": [...], "hilos": [...], "conexiones": [...]} donde cada camino es
{"pasos": [paso], "fin": {...}, "distancia_m", "avisos": [...]} y un paso es
  {"tipo": "tramo", "cable", "hilo", "desde", "hasta", "longitud_m"}
  {"tipo": "fusion" | "splitter" | "conector", "en", "texto", "conexion_id"}.
Solo lee; no cambia nada.
"""
from typing import Any, Iterator

from visor_rutas.redes import proyectos
from visor_rutas.redes.db import NoEncontrado, SinPermiso

NOMBRE_ESTADO = {"activo": "activo", "oscura": "fibra oscura", "baja": "cliente de baja", "reservado": "reservado", "danado": "dañado"}
MAX_CAMINOS = 400      # a 1x32 after a 1x8 is 256 ends: enough, and it bounds a bad network
MAX_PASOS = 400


class _Red:
    """Lazy cache of the rows the trace reads (one query per element / cable / port)."""

    def __init__(self, con: Any):
        self.con = con
        self._elementos: dict[int, dict[str, Any]] = {}
        self._cables: dict[int, dict[str, Any]] = {}
        self._hilos: dict[int, dict[str, Any]] = {}
        self._puertos: dict[int, dict[str, Any]] = {}

    def elemento(self, id_: int) -> dict[str, Any]:
        if id_ not in self._elementos:
            f = self.con.execute("SELECT id, tipo, subtipo, nombre, codigo, propiedades, ST_Y(ubicacion) AS lat, ST_X(ubicacion) AS lon "
                                 "FROM redes.elementos WHERE id = %s", (id_,)).fetchone()
            self._elementos[id_] = {"id": f["id"], "tipo": f["tipo"], "subtipo": f["subtipo"], "nombre": f["nombre"],
                                    "codigo": f["codigo"], "lat": f["lat"], "lon": f["lon"],
                                    "id_servicio": (f["propiedades"] or {}).get("id_servicio")}
        return self._elementos[id_]

    def cable(self, id_: int) -> dict[str, Any]:
        if id_ not in self._cables:
            f = self.con.execute("SELECT id, nombre, clase, tipo, hilos, hilos_por_buffer, color, longitud_m, metraje, origen_id, destino_id "
                                 "FROM redes.cables WHERE id = %s", (id_,)).fetchone()
            self._cables[id_] = {**dict(f), "longitud_m": float(f["longitud_m"] or 0),
                                 "metraje_m": (f["metraje"] or {}).get("metraje_m")}
        return self._cables[id_]

    def hilo(self, id_: int) -> dict[str, Any]:
        if id_ not in self._hilos:
            f = self.con.execute("SELECT id, cable_id, numero, buffer, color, estado, observacion, borrado_en FROM redes.hilos WHERE id = %s",
                                 (id_,)).fetchone()
            if f is None:
                raise NoEncontrado("El hilo no existe")
            self._hilos[id_] = dict(f)
        return self._hilos[id_]

    def puerto(self, id_: int) -> dict[str, Any]:
        if id_ not in self._puertos:
            f = self.con.execute(
                "SELECT p.id, p.splitter_id, p.conector_id, p.lado, p.numero, s.nombre AS s_nombre, s.salidas, s.relacion, "
                "s.conector AS s_conector, k.nombre AS k_nombre, k.tipo AS k_tipo FROM redes.puertos p "
                "LEFT JOIN redes.splitters s ON s.id = p.splitter_id LEFT JOIN redes.conectores k ON k.id = p.conector_id "
                "WHERE p.id = %s", (id_,)).fetchone()
            self._puertos[id_] = dict(f)
        return self._puertos[id_]

    def puertos_de(self, *, splitter_id: int | None = None, conector_id: int | None = None) -> list[dict[str, Any]]:
        filas = self.con.execute("SELECT id FROM redes.puertos WHERE splitter_id IS NOT DISTINCT FROM %s "
                                 "AND conector_id IS NOT DISTINCT FROM %s ORDER BY lado, numero", (splitter_id, conector_id)).fetchall()
        return [self.puerto(f["id"]) for f in filas]

    def conexion_hilo(self, mufa_id: int, hilo_id: int) -> dict[str, Any] | None:
        return self.con.execute("SELECT * FROM redes.conexiones WHERE mufa_id = %s AND borrado_en IS NULL "
                                "AND (a_hilo_id = %s OR b_hilo_id = %s) LIMIT 1", (mufa_id, hilo_id, hilo_id)).fetchone()

    def conexion_puerto(self, puerto_id: int) -> dict[str, Any] | None:
        return self.con.execute("SELECT * FROM redes.conexiones WHERE borrado_en IS NULL AND (a_puerto_id = %s OR b_puerto_id = %s) "
                                "LIMIT 1", (puerto_id, puerto_id)).fetchone()


def _otro_extremo(c: dict[str, Any], *, hilo_id: int | None = None, puerto_id: int | None = None) -> tuple[int | None, int | None]:
    """The (hilo, puerto) at the other side of connection `c`."""
    if (hilo_id is not None and c["a_hilo_id"] == hilo_id) or (puerto_id is not None and c["a_puerto_id"] == puerto_id):
        return c["b_hilo_id"], c["b_puerto_id"]
    return c["a_hilo_id"], c["a_puerto_id"]



def _breve(e: dict[str, Any]) -> dict[str, Any]:
    return {k: e[k] for k in ("id", "tipo", "subtipo", "nombre", "codigo")}


def _nombre_splitter(p: dict[str, Any]) -> str:
    return f"{p['s_nombre']} (1x{p['salidas']}{' ' + p['relacion'] if p['relacion'] else ''})"


class _Trazado:
    def __init__(self, red: _Red):
        self.red = red
        self.n_caminos = 0

    def _fin(self, pasos: list[dict[str, Any]], distancia: float, motivo: str, texto: str,
             elemento: dict[str, Any] | None = None) -> dict[str, Any]:
        self.n_caminos += 1
        avisos = []
        for p in pasos:
            if p["tipo"] == "tramo" and p["hilo"]["estado"] != "activo":
                avisos.append(f"{p['cable']['nombre']} hilo {p['hilo']['numero']}: {NOMBRE_ESTADO.get(p['hilo']['estado'], p['hilo']['estado'])}")
        return {"pasos": pasos, "distancia_m": round(distancia, 1), "avisos": avisos,
                "fin": {"motivo": motivo, "texto": texto, "elemento": elemento}}

    def por_hilo(self, hilo_id: int, hacia_id: int, pasos: list[dict[str, Any]], distancia: float,
                 visto: frozenset, via: int | None = None) -> Iterator[dict[str, Any]]:
        """Runs fibre `hilo_id` along its cable up to element `hacia_id`, then continues there
        (`via`: the connection that brought the trace onto this fibre)."""
        h = self.red.hilo(hilo_id)
        c = self.red.cable(h["cable_id"])
        desde_id = c["origen_id"] if hacia_id == c["destino_id"] else c["destino_id"]
        desde, hacia = self.red.elemento(desde_id), self.red.elemento(hacia_id)
        paso = {"tipo": "tramo", "cable": {k: c[k] for k in ("id", "nombre", "clase", "tipo", "hilos", "color", "metraje_m")},
                "hilo": {"id": h["id"], "numero": h["numero"], "color": h["color"], "estado": h["estado"],
                         "observacion": h["observacion"]},
                "desde": _breve(desde), "hasta": _breve(hacia), "longitud_m": c["longitud_m"], "via_conexion_id": via}
        pasos = pasos + [paso]
        distancia += c["longitud_m"]
        if self.n_caminos >= MAX_CAMINOS or len(pasos) > MAX_PASOS:
            yield self._fin(pasos, distancia, "limite", "Se detuvo: el recorrido es demasiado largo", _breve(hacia))
            return
        if hacia["tipo"] == "cliente":
            codigo = f" ({hacia['codigo']})" if hacia["codigo"] else ""
            servicio = f" · ID {hacia['id_servicio']}" if hacia["id_servicio"] else ""
            yield self._fin(pasos, distancia, "cliente", f"Cliente {hacia['nombre']}{codigo}{servicio}", _breve(hacia))
            return
        if hacia["tipo"] not in ("mufa", "nodo", "odf"):
            yield self._fin(pasos, distancia, "otro", f"Termina en {hacia['nombre']} ({hacia['tipo']})", _breve(hacia))
            return
        conexion = self.red.conexion_hilo(hacia_id, hilo_id)
        if conexion is None:
            if hacia["tipo"] == "nodo":
                yield self._fin(pasos, distancia, "nodo", f"Llega al nodo {hacia['nombre']}", _breve(hacia))
            else:
                yield self._fin(pasos, distancia, "sin_conexion",
                                f"Sin continuidad: el hilo {h['numero']} no está conectado en {hacia['nombre']}", _breve(hacia))
            return
        otro_hilo, otro_puerto = _otro_extremo(conexion, hilo_id=hilo_id)
        yield from self.extremo(hacia, conexion["id"], otro_hilo, otro_puerto, pasos, distancia, visto, fusion=otro_hilo is not None)

    def extremo(self, mufa: dict[str, Any], conexion_id: int, hilo_id: int | None, puerto_id: int | None,
                pasos: list[dict[str, Any]], distancia: float, visto: frozenset, fusion: bool = False) -> Iterator[dict[str, Any]]:
        """Continues from the far side of connection `conexion_id` inside `mufa` (`fusion`: the
        connection joins two fibres; from a splitter or connector port it does not)."""
        clave = ("h", hilo_id) if hilo_id is not None else ("p", puerto_id)
        if clave in visto:
            yield self._fin(pasos, distancia, "ciclo", f"El recorrido vuelve sobre sí mismo en {mufa['nombre']}", _breve(mufa))
            return
        visto = visto | {clave}
        if hilo_id is not None:
            h = self.red.hilo(hilo_id)
            c = self.red.cable(h["cable_id"])
            siguiente = c["destino_id"] if c["origen_id"] == mufa["id"] else c["origen_id"]
            if fusion:
                pasos = pasos + [{"tipo": "fusion", "en": _breve(mufa), "conexion_id": conexion_id,
                                  "texto": f"Fusión en {mufa['nombre']} con {c['nombre']} hilo {h['numero']}"}]
            yield from self.por_hilo(hilo_id, siguiente, pasos, distancia, visto, via=conexion_id)
            return
        p = self.red.puerto(puerto_id)
        if p["splitter_id"] is not None:
            nombre = _nombre_splitter(p)
            if p["lado"] == "entrada":
                ramas = 0
                for q in self.red.puertos_de(splitter_id=p["splitter_id"]):
                    if q["lado"] != "salida":
                        continue
                    cq = self.red.conexion_puerto(q["id"])
                    if cq is None:
                        continue
                    ramas += 1
                    paso = {"tipo": "splitter", "en": _breve(mufa), "conexion_id": conexion_id, "conexion_salida_id": cq["id"],
                            "splitter_id": p["splitter_id"], "salida": q["numero"],
                            "texto": f"{nombre} en {mufa['nombre']}: entrada → salida {q['numero']}"}
                    h2, p2 = _otro_extremo(cq, puerto_id=q["id"])
                    yield from self.extremo(mufa, cq["id"], h2, p2, pasos + [paso], distancia, visto | {("p", q["id"])})
                if not ramas:
                    yield self._fin(pasos, distancia, "splitter_libre",
                                    f"{nombre} en {mufa['nombre']}: ninguna salida conectada", _breve(mufa))
                return
            entrada = next(q for q in self.red.puertos_de(splitter_id=p["splitter_id"]) if q["lado"] == "entrada")
            paso = {"tipo": "splitter", "en": _breve(mufa), "conexion_id": conexion_id, "splitter_id": p["splitter_id"],
                    "salida": p["numero"], "texto": f"{nombre} en {mufa['nombre']}: salida {p['numero']} → entrada"}
            ce = self.red.conexion_puerto(entrada["id"])
            if ce is None:
                yield self._fin(pasos + [paso], distancia, "sin_conexion", f"{nombre} en {mufa['nombre']}: la entrada no está conectada",
                                _breve(mufa))
                return
            h2, p2 = _otro_extremo(ce, puerto_id=entrada["id"])
            yield from self.extremo(mufa, ce["id"], h2, p2, pasos + [paso], distancia, visto | {("p", entrada["id"])})
            return
        # connector: pass to its other side
        otro_lado = "salida" if p["lado"] == "entrada" else "entrada"
        q = next(x for x in self.red.puertos_de(conector_id=p["conector_id"]) if x["lado"] == otro_lado)
        conector = p["k_nombre"] if p["k_nombre"].lower().startswith("conector") else f"Conector {p['k_nombre']}"
        paso = {"tipo": "conector", "en": _breve(mufa), "conexion_id": conexion_id, "conector_id": p["conector_id"],
                "texto": f"{conector}{' ' + p['k_tipo'] if p['k_tipo'] else ''} en {mufa['nombre']}"}
        cq = self.red.conexion_puerto(q["id"])
        if cq is None:
            yield self._fin(pasos + [paso], distancia, "sin_conexion", f"{conector} en {mufa['nombre']}: el otro lado está libre",
                            _breve(mufa))
            return
        h2, p2 = _otro_extremo(cq, puerto_id=q["id"])
        yield from self.extremo(mufa, cq["id"], h2, p2, pasos + [paso], distancia, visto | {("p", q["id"])})


def trazar(con: Any, actor: dict[str, Any], *, hilo_id: int | None = None, cable_id: int | None = None,
           numero: int | None = None) -> dict[str, Any]:
    """Traces a fibre (by id, or by cable + number) in both directions."""
    red = _Red(con)
    if hilo_id is None:
        fila = con.execute("SELECT id FROM redes.hilos WHERE cable_id = %s AND numero = %s AND borrado_en IS NULL",
                           (int(cable_id or 0), int(numero or 0))).fetchone()
        if fila is None:
            raise NoEncontrado("Ese cable no tiene ese hilo")
        hilo_id = fila["id"]
    h = red.hilo(int(hilo_id))
    if h["borrado_en"] is not None:
        raise NoEncontrado("El hilo fue eliminado")
    c = red.cable(h["cable_id"])
    proyecto_id = con.execute("SELECT proyecto_id FROM redes.cables WHERE id = %s", (c["id"],)).fetchone()["proyecto_id"]
    if not proyectos.puede_ver(con, actor, proyecto_id):
        raise SinPermiso("No tiene acceso a este proyecto")
    t = _Trazado(red)
    sentidos = []
    for nombre, hacia in (("Hacia el origen", c["origen_id"]), ("Hacia el destino", c["destino_id"])):
        caminos = list(t.por_hilo(h["id"], hacia, [], 0.0, frozenset({("h", h["id"])})))
        for camino in caminos:          # the first step is the traced fibre itself in both directions: keep it once
            camino["pasos"] = camino["pasos"][1:]
            camino["distancia_m"] = round(camino["distancia_m"] - c["longitud_m"], 1)
        sentidos.append({"nombre": nombre, "elemento": _breve(red.elemento(hacia)), "caminos": caminos})
    # everything touched, for the map and the mufa canvas
    cables, elementos, hilos, conexiones = {c["id"]}, {c["origen_id"], c["destino_id"]}, {h["id"]}, set()
    for s in sentidos:
        for camino in s["caminos"]:
            for p in camino["pasos"]:
                if p["tipo"] == "tramo":
                    cables.add(p["cable"]["id"]); hilos.add(p["hilo"]["id"])
                    elementos.update((p["desde"]["id"], p["hasta"]["id"]))
                    if p["via_conexion_id"]:
                        conexiones.add(p["via_conexion_id"])
                else:
                    conexiones.update(x for x in (p.get("conexion_id"), p.get("conexion_salida_id")) if x)
                    elementos.add(p["en"]["id"])
    clientes = [cm["fin"]["elemento"] for s in sentidos for cm in s["caminos"] if cm["fin"]["motivo"] == "cliente"]
    origen = red.elemento(c["origen_id"])
    return {"proyecto_id": proyecto_id,
            "inicio": {"hilo": {"id": h["id"], "numero": h["numero"], "color": h["color"], "estado": h["estado"]},
                       "cable": {k: c[k] for k in ("id", "nombre", "clase", "tipo", "hilos", "color", "longitud_m", "metraje_m")},
                       "origen": _breve(origen), "destino": _breve(red.elemento(c["destino_id"]))},
            "sentidos": sentidos,
            "resumen": {"clientes": clientes, "caminos": sum(len(s["caminos"]) for s in sentidos),
                        "sin_continuidad": sum(1 for s in sentidos for cm in s["caminos"] if cm["fin"]["motivo"] in ("sin_conexion", "splitter_libre")),
                        "recortado": t.n_caminos >= MAX_CAMINOS},
            "cables": sorted(cables), "hilos": sorted(hilos), "conexiones": sorted(conexiones),
            "elementos": [red.elemento(i) for i in sorted(elementos)]}
