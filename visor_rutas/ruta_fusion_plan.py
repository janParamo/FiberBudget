"""Plan de la ruta de fusión (visor v2, fase 4B): qué mufas se intervienen, con qué hilos y qué se escribe en cada paso.

Sale de las paradas que ya arma `fusion.ruta_fusion` (del OLT al punto de conexión, según los diagramas Visio y el Excel de anillos) y
se escribe como en el libro de rutas de fusión, **del cliente hacia la potencia**:

  - Primera caja: `En MF {NOMBRE} {lat}°, {lon}° ingresar la acometida del cliente. H1 del cliente fusionarlo con H{n} hacia MF {SIGUIENTE}`
  - Intermedia:   `En MF {NOMBRE} {lat}°, {lon}° H{a} hacia MF {ANTERIOR} fusionarlo con H{b} hacia MF {SIGUIENTE}`
  - Con splitter: `… fusionarlo con H{n} del SPL 1/8`; mufa nueva: `instalar MF FOSC`.

Reglas de Jan (business_rules.yaml, `ruta_fusion`): una mufa **aérea** (queda suspendida en los cables) y una mufa **de corte** no se
tocan (la fusión pasa de largo); se reconocen por el nombre ("MF FUERZA AEREA" es un lugar, no una mufa aérea: está en las excepciones);
el usuario puede marcar o desmarcar "no tocar" a mano. La mufa donde entra el cliente siempre se toca. Los hilos se proponen solo con
lo que se sabe (Excel de anillos); donde no hay dato queda `H__` ("por identificar"). Todo el plan es editable antes de exportar.
Aquí no hay base de datos: `armar` recibe el resultado del cálculo y `redactar` rehace los textos de un plan editado.
"""
import re
import unicodedata
from typing import Any

import main
import reglas_mufas
from visor_rutas import splitters_diagrama

HILO_CLIENTE = "H1"
HILO_DESCONOCIDO = "H__"
MAX_PASOS = 60
MAX_TEXTO = 600
SPLITTERS = ("1/2", "1/4", "1/8", "1/16", "1/32")
_PREFIJO_MF = re.compile(r"^\s*(MF|MUFA|MUFAS|MC|NODO|MINI\s*NODO|MN|ODF|FOSC|SPL)\b", re.I)
_NUMERO = re.compile(r"(\d{1,3})")


def _plano(texto: Any) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Z0-9 ]+", " ", t.upper()).split())


def reglas() -> dict[str, Any]:
    """The rules of the mufas that cannot be used (business_rules.yaml: `mufas_no_usables`, reglas_mufas.py)."""
    return reglas_mufas.configuracion(main.load_rules(main.settings.rules_path))


def motivo_no_tocar(nombre: str, config: dict[str, Any] | None = None) -> str | None:
    """"de corte" / "aérea" / "punta plana" / "mini nodo" when the mufa's name says so (whole words; the exceptions are places,
    not mufas), else None: the fusion passes by a mufa like that."""
    return reglas_mufas.motivo(nombre, config or reglas(), en_ruta_de_fusion=True)


def hilo(valor: Any) -> str:
    """"H12" / "12" / "hilo 12" -> "H12"; nothing usable -> "H__"."""
    m = _NUMERO.search(str(valor or ""))
    return f"H{int(m.group(1))}" if m and int(m.group(1)) > 0 else HILO_DESCONOCIDO


def con_mf(nombre: str) -> str:
    nombre = " ".join(str(nombre or "").split())
    return nombre if not nombre or _PREFIJO_MF.match(nombre) else f"MF {nombre}"


def _coords(lat: Any, lon: Any) -> str:
    try:
        return f"{float(lat):.6f}°, {float(lon):.6f}°"
    except (TypeError, ValueError):
        return ""


def _hilos_de_anillo(parada: dict[str, Any], hacia_cliente: str | None, hacia_potencia: str | None) -> tuple[str, str]:
    """(hilo hacia el lado del cliente, hilo hacia el lado de la potencia) of the Excel of rings, H__ when it does not say."""
    a, b = _plano(hacia_cliente), _plano(hacia_potencia)
    mejor: tuple[int, str, str] | None = None
    for fila in parada.get("hilos_anillo") or []:
        de, hacia = _plano(fila.get("de_mufa")), _plano(fila.get("hacia_mufa"))
        for (lado_a, lado_b, h_a, h_b) in ((de, hacia, fila.get("hilo_entrante"), fila.get("hilo_saliente")),
                                           (hacia, de, fila.get("hilo_saliente"), fila.get("hilo_entrante"))):
            puntos = (1 if a and lado_a and (a in lado_a or lado_a in a) else 0) + (1 if b and lado_b and (b in lado_b or lado_b in b) else 0)
            if puntos and (mejor is None or puntos > mejor[0]):
                mejor = (puntos, hilo(h_a), hilo(h_b))
    return (mejor[1], mejor[2]) if mejor else (HILO_DESCONOCIDO, HILO_DESCONOCIDO)


def armar(datos: dict[str, Any]) -> dict[str, Any]:
    """The plan of a calculated route (`calcular_ruta` result): one step per mufa of the path, client side first."""
    paradas = list(reversed(datos.get("ruta_fusion") or []))
    nodo = (datos.get("origen_trafico") or {}).get("nodo")
    config = reglas()
    pasos = []
    for i, p in enumerate(paradas):
        anterior = paradas[i - 1]["nombre"] if i > 0 else None
        siguiente = paradas[i + 1]["nombre"] if i + 1 < len(paradas) else None
        ha, hb = _hilos_de_anillo(p, anterior, siguiente or nodo)
        motivo = None if i == 0 else motivo_no_tocar(p["nombre"], config)
        pasos.append({"id": f"p{i + 1}", "tipo": "mufa", "nombre": p["nombre"], "lat": p.get("lat"), "lon": p.get("lon"), "tocar": motivo is None,
                      "motivo": motivo, "hilo_cliente": ha, "hilo_potencia": hb, "splitter": None, "texto_manual": None,
                      "fuente_hilos": "excel" if HILO_DESCONOCIDO not in (ha, hb) else p.get("fuente_hilos", "sin_dato"),
                      "por_nombre": bool(p.get("emparejado_por_nombre")), "info_splitter": None})
    avisos = []
    # Splitters read from the diagrams: each usable stop says which one it has; the first stop (client side) with a secondary that has free
    # ports gets its splitter (the hilo is fused there). A secondary whose ports nobody has confirmed is only mentioned.
    corte = None
    for i, (paso, parada) in enumerate(zip(pasos, paradas)):
        elegido = splitters_diagrama.preferido(parada.get("splitters_diagrama") or [])
        if elegido is None or not paso["tocar"]:
            continue
        paso["info_splitter"] = splitters_diagrama.descripcion(elegido)[:200]
        if corte is None and elegido["clase"] == "secundario" and elegido["libres"] and elegido.get("ratio") in SPLITTERS:
            paso["splitter"], corte = elegido["ratio"], i
            avisos.append(f"{con_mf(paso['nombre'])}: {paso['info_splitter']}; se fusiona ahí. Validar con Planta Externa los puertos en el diagrama "
                          "y que haya hilos libres entre las mufas hasta aquí")
        elif elegido["clase"] == "secundario" and elegido["desconocidos"]:
            avisos.append(f"{con_mf(paso['nombre'])}: tiene un splitter secundario con puertos por confirmar; ábralo en «Splitters» de la parada")
    # The fusion route stops at that splitter (rule 7): the client is served from it, so the mufas after it, towards the power, are passed by.
    # They stay in the plan, not touched, so the user can mark them again if the splitter turns out not to be usable.
    if corte is not None:
        dejadas = [p for p in pasos[corte + 1:] if p["tocar"]]
        for p in dejadas:
            p["tocar"], p["motivo"] = False, "después del splitter"
        if dejadas:
            avisos.append(f"La ruta se detiene en {con_mf(pasos[corte]['nombre'])} (splitter secundario con puertos libres): las {len(dejadas)} mufa(s) que siguen hacia la "
                          "potencia ya no se tocan. Si ese splitter no se puede usar, márquelas de nuevo")
    if paradas and paradas[0]["nombre"] and motivo_no_tocar(paradas[0]["nombre"], config):
        avisos.append(f"La mufa de conexión {paradas[0]['nombre']} es {motivo_no_tocar(paradas[0]['nombre'], config)}: "
                      "el cliente entra ahí, así que se toca; validar con Planta Externa")
    # More mufas than `splitter_secundario.max_mufas` up to the splitter: suggest a secondary splitter in a NEW mufa on the nearest reserva
    # (calculo.py looked the reservas up). A suggestion: the user edits or removes the step; the budget does not change.
    maximo = int((main.load_rules(main.settings.rules_path).get("splitter_secundario") or {}).get("max_mufas", 10))
    tocadas = sum(1 for p in pasos if p["tocar"])
    reservas = datos.get("reservas_cercanas") or []
    if tocadas > maximo:
        if reservas:
            r = reservas[0]
            pasos.insert(0, {"id": "p0", "tipo": "nueva", "nombre": "MF NUEVA", "lat": r.get("lat"), "lon": r.get("lon"), "tocar": True, "motivo": None,
                             "hilo_cliente": HILO_DESCONOCIDO, "hilo_potencia": HILO_DESCONOCIDO, "splitter": "1/8", "texto_manual": None,
                             "fuente_hilos": "sin_dato", "por_nombre": False})
            avisos.append(f"Hay {tocadas} mufas por intervenir (más de {maximo}): se sugiere instalar un splitter secundario en una MF NUEVA en la reserva "
                          f"{r.get('nombre') or ''} ({r.get('distancia_m', 0):.0f} m del cliente) y conectarlo al splitter principal con hilos disponibles; "
                          "validar con Planta Externa")
        else:
            avisos.append(f"Hay {tocadas} mufas por intervenir (más de {maximo}): conviene instalar un splitter secundario en una MF NUEVA sobre una reserva, "
                          "pero no se encontró ninguna reserva cerca del cliente")
    plan = {"pasos": pasos, "potencia": nodo, "compartir_potencia": False, "avisos_rojos": avisos}
    return redactar(plan)


def _destino(paso: dict[str, Any] | None, plan: dict[str, Any]) -> str:
    if paso is None:
        return str(plan.get("potencia") or "la potencia")
    return con_mf(paso["nombre"])


def redactar(plan: dict[str, Any]) -> dict[str, Any]:
    """Validates an (edited) plan and writes the text of every step to touch, client side first. Steps that are not touched get no
    text. Returns a new plan with `texto` in each step, `tocadas` (how many mufas are intervened) and `lineas` (what goes in the Excel)."""
    if not isinstance(plan, dict) or not isinstance(plan.get("pasos"), list):
        raise ValueError("Plan de ruta de fusión no válido")
    if len(plan["pasos"]) > MAX_PASOS:
        raise ValueError(f"Una ruta de fusión puede tener hasta {MAX_PASOS} pasos")
    pasos = []
    for i, p in enumerate(plan["pasos"]):
        if not isinstance(p, dict):
            raise ValueError("Paso no válido")
        nombre = " ".join(str(p.get("nombre") or "").split())[:160]
        if not nombre:
            raise ValueError(f"El paso {i + 1} no tiene nombre")
        splitter = p.get("splitter") if p.get("splitter") in SPLITTERS else None
        tipo = p.get("tipo") if p.get("tipo") in ("mufa", "nueva") else "mufa"
        manual = " ".join(str(p.get("texto_manual") or "").split())[:MAX_TEXTO] or None
        pasos.append({"id": str(p.get("id") or f"p{i + 1}")[:20], "tipo": tipo, "nombre": nombre, "lat": _numero(p.get("lat")), "lon": _numero(p.get("lon")),
                      "tocar": bool(p.get("tocar", True)), "motivo": p.get("motivo") if isinstance(p.get("motivo"), str) else None,
                      "hilo_cliente": hilo(p.get("hilo_cliente")), "hilo_potencia": hilo(p.get("hilo_potencia")), "splitter": splitter,
                      "texto_manual": manual, "fuente_hilos": p.get("fuente_hilos") or "usuario", "por_nombre": bool(p.get("por_nombre")),
                      "info_splitter": " ".join(str(p.get("info_splitter") or "").split())[:200] or None})
    tocados = [p for p in pasos if p["tocar"]]
    lineas = []
    for k, p in enumerate(tocados):
        ant = tocados[k - 1] if k > 0 else None
        sig = tocados[k + 1] if k + 1 < len(tocados) else None
        p["texto"] = p["texto_manual"] or _texto(p, ant, sig, plan, k == 0)
        lineas.append(p["texto"])
    for p in pasos:
        p.setdefault("texto", None)
    avisos = [" ".join(str(a).split())[:MAX_TEXTO] for a in (plan.get("avisos_rojos") or []) if str(a).strip()][:10]
    return {"pasos": pasos, "potencia": plan.get("potencia"), "compartir_potencia": bool(plan.get("compartir_potencia")),
            "avisos_rojos": avisos, "tocadas": len(tocados), "lineas": lineas}


def _numero(v: Any) -> float | None:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _texto(p: dict[str, Any], ant: dict[str, Any] | None, sig: dict[str, Any] | None, plan: dict[str, Any], primero: bool) -> str:
    donde = f"En {con_mf(p['nombre'])} {_coords(p['lat'], p['lon'])}".strip()
    hacia_potencia = f"hacia {_destino(sig, plan)}"
    if p["splitter"]:
        sale = f"con {p['hilo_potencia']} del SPL {p['splitter']}"
    else:
        sale = f"con {p['hilo_potencia']} {hacia_potencia}"
    if p["tipo"] == "nueva":
        donde += " instalar MF FOSC y"
    if primero:
        texto = f"{donde} ingresar la acometida del cliente. {HILO_CLIENTE} del cliente fusionarlo {sale}"
    else:
        texto = f"{donde} {p['hilo_cliente']} hacia {_destino(ant, plan)} fusionarlo {sale}"
    if HILO_DESCONOCIDO in (p["hilo_cliente"] if not primero else "", p["hilo_potencia"]):
        texto += " (hilos por identificar)"
    return texto
