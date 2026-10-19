"""Coordenadas escritas a mano: decimal, grados-minutos-segundos y grados-minutos decimales (visor v2, fase 2).

    13.094578, -86.002708 | 13.094578 -86.002708 | 13.094578;-86.002708
    13°5'38.09"N 86°0'7.42"O   (también W, º, espacios: 13 5 38.09 N 86 0 7.42 W; con la letra delante: N13 5 38.09 W86 0 7.42)
    13 5.6348N 86 0.1237W

`interpretar` no lanza errores: devuelve el estado para mostrarlo en el buscador. `parsear` es la versión estricta.
La misma gramática está en visor_rutas/web/mapa/coordenadas.js; los dos se prueban con los casos de
Pruebas/vectores_coordenadas.json (si cambia uno, cambia el otro).

Reglas:
  - Cualquier otra letra que no sea N, S, E, W u O (norte, sur, este, oeste/oeste) significa "esto no es una coordenada":
    así un nombre de mufa como "MF 12 NORTE" nunca se toma por una coordenada.
  - Con letras (dos, una por eje) el orden no importa: N/S es la latitud y E/W/O la longitud. S, W y O son negativas.
  - Sin letras, el primero es la latitud y el segundo la longitud.
  - Debe caer en Nicaragua; si solo cabe con latitud y longitud al revés, el estado es "invertida" y trae la sugerencia.
"""
import re
from dataclasses import dataclass
from typing import Any

from config import NI_LAT_MAX, NI_LAT_MIN, NI_LON_MAX, NI_LON_MIN

OK, INVERTIDA, FUERA, ERROR, NO_ES = "ok", "invertida", "fuera", "error", "no_coordenada"
_HEMISFERIO = {"N": ("lat", 1), "S": ("lat", -1), "E": ("lon", 1), "W": ("lon", -1), "O": ("lon", -1)}
_UNIDADES = str.maketrans({"º": "°", "˚": "°", "′": "'", "’": "'", "´": "'", "ʹ": "'", "″": '"', "”": '"', "“": '"', "ʺ": '"'})
_TOKEN = re.compile(r"""(?P<hem>(?<![A-Za-z])[NSEWOnsewo](?![A-Za-z]))|(?P<num>[-+]?\d+(?:\.\d+)?)""")


@dataclass
class Resultado:
    estado: str
    lat: float | None = None
    lon: float | None = None
    mensaje: str = ""
    sugerencia: tuple[float, float] | None = None       # (lat, lon) when the order looks swapped

    def como_dict(self) -> dict[str, Any]:
        return {"estado": self.estado, "lat": self.lat, "lon": self.lon, "mensaje": self.mensaje,
                "sugerencia": list(self.sugerencia) if self.sugerencia else None}


class CoordenadaNoValida(ValueError):
    pass


def en_nicaragua(lat: float, lon: float) -> bool:
    return NI_LAT_MIN <= lat <= NI_LAT_MAX and NI_LON_MIN <= lon <= NI_LON_MAX


def _grupo_a_grados(numeros: list[str], eje_maximo: float) -> float:
    """[grados] | [grados, minutos decimales] | [grados, minutos, segundos] -> grados decimales (con signo del primero)."""
    d = float(numeros[0])
    signo = -1 if numeros[0].lstrip().startswith("-") else 1
    if len(numeros) > 1 and d != int(d):
        raise CoordenadaNoValida("Los grados con decimales no llevan minutos")
    m = float(numeros[1]) if len(numeros) > 1 else 0.0
    s = float(numeros[2]) if len(numeros) > 2 else 0.0
    if len(numeros) > 1 and (m < 0 or m >= 60 or numeros[1].startswith(("-", "+"))):
        raise CoordenadaNoValida("Los minutos van de 0 a 59")
    if len(numeros) > 2 and (s < 0 or s >= 60 or numeros[2].startswith(("-", "+"))):
        raise CoordenadaNoValida("Los segundos van de 0 a 59")
    if len(numeros) > 2 and m != int(m):
        raise CoordenadaNoValida("Los minutos con decimales no llevan segundos")
    valor = abs(d) + m / 60 + s / 3600
    if valor > eje_maximo:
        raise CoordenadaNoValida(f"El valor {valor:.6f} se sale del rango (±{eje_maximo:g})")
    return signo * valor


def _separar(texto: str) -> list[tuple[str, str]]:
    """The text as tokens [("hem", "N"), ("num", "13"), ...]; None if it holds anything else but separators/units."""
    limpio = texto.translate(_UNIDADES)
    resto = _TOKEN.sub(" ", limpio)
    if re.search(r"[^\s,;°'\"()\[\]]", resto):             # another letter or symbol: it is not a coordinate
        return []
    return [("hem" if m.group("hem") else "num", (m.group("hem") or m.group("num"))) for m in _TOKEN.finditer(limpio)]


def _valores(texto: str) -> tuple[float, float]:
    fichas = _separar(texto)
    if not fichas or not any(t == "num" for t, _ in fichas):
        raise CoordenadaNoValida("no es una coordenada")
    letras = [v.upper() for t, v in fichas if t == "hem"]
    grupos: list[tuple[list[str], str | None]] = []
    if letras:
        if len(letras) != 2:
            raise CoordenadaNoValida("Indique las dos letras (por ejemplo N y O), o ninguna")
        sufijo = fichas[0][0] == "num"                        # 13 5 38 N 86 0 7 O   (or N 13 5 38 O 86 0 7)
        actual: list[str] = []
        pendiente: str | None = None
        for tipo, valor in fichas:
            if tipo == "num":
                actual.append(valor)
            elif sufijo:
                grupos.append((actual, valor.upper()))
                actual = []
            else:
                if actual:
                    grupos.append((actual, pendiente))
                actual, pendiente = [], valor.upper()
        if not sufijo:
            grupos.append((actual, pendiente))
        elif actual:
            raise CoordenadaNoValida("Sobran números después de la última letra")
        if len(grupos) != 2 or any(not g[0] for g in grupos):
            raise CoordenadaNoValida("Cada coordenada necesita sus números")
    else:
        numeros = [v for t, v in fichas]
        if len(numeros) not in (2, 4, 6):
            raise CoordenadaNoValida("Escriba latitud y longitud (decimal, o grados minutos segundos)")
        mitad = len(numeros) // 2
        grupos = [(numeros[:mitad], None), (numeros[mitad:], None)]
    ejes = [(_HEMISFERIO[l][0] if l else None) for _, l in grupos]
    if letras and (ejes[0] == ejes[1]):
        raise CoordenadaNoValida("Una letra es de latitud (N o S) y la otra de longitud (E, O o W)")
    valores = []
    for (numeros, letra), eje in zip(grupos, ejes):
        v = _grupo_a_grados(numeros, 90 if eje == "lat" or (eje is None and len(valores) == 0) else 180)
        if letra:
            v = abs(v) * _HEMISFERIO[letra][1] if numeros[0].lstrip()[0] not in "-" else -abs(v)
        valores.append(v)
    if letras and ejes[0] == "lon":                           # longitude written first
        valores.reverse()
    return valores[0], valores[1]


def interpretar(texto: str) -> Resultado:
    """What the search box does with the typed text: ok / invertida / fuera / error / no_coordenada."""
    texto = (texto or "").strip()
    if not texto or not re.search(r"\d", texto):
        return Resultado(NO_ES)
    try:
        lat, lon = _valores(texto)
    except CoordenadaNoValida as exc:
        # Only digits, N/S/E/W/O and separators, with two numbers or more: it was meant as a coordinate, say why not.
        # Anything else (a name, one number) is a normal search.
        numeros = [v for t, v in _separar(texto) if t == "num"]
        return Resultado(ERROR, mensaje=str(exc)) if str(exc) != "no es una coordenada" and len(numeros) >= 2 else Resultado(NO_ES)
    if en_nicaragua(lat, lon):
        return Resultado(OK, lat, lon)
    if en_nicaragua(lon, lat):
        return Resultado(INVERTIDA, lat, lon, f"Latitud y longitud parecen invertidas: ({lat}, {lon})", (lon, lat))
    return Resultado(FUERA, lat, lon, f"La coordenada ({lat:.6f}, {lon:.6f}) está fuera de Nicaragua "
                                      f"(latitud {NI_LAT_MIN}..{NI_LAT_MAX}, longitud {NI_LON_MIN}..{NI_LON_MAX})")


def parsear(texto: str) -> tuple[float, float]:
    """(lat, lon) of a coordinate inside Nicaragua; CoordenadaNoValida with the reason otherwise."""
    r = interpretar(texto)
    if r.estado == OK:
        return r.lat, r.lon
    raise CoordenadaNoValida(r.mensaje or "No se reconoce la coordenada: " + repr(texto))


def formato_decimal(lat: float, lon: float) -> str:
    return f"{lat:.6f}, {lon:.6f}"


def _gms(valor: float, positivo: str, negativo: str) -> str:
    letra = positivo if valor >= 0 else negativo
    v = abs(valor)
    grados = int(v)
    minutos = int((v - grados) * 60)
    segundos = round((v - grados - minutos / 60) * 3600, 2)
    if segundos >= 60:                                      # 59.999 s rounds up
        segundos, minutos = 0.0, minutos + 1
    if minutos >= 60:
        minutos, grados = 0, grados + 1
    return f"{grados}°{minutos}'{segundos:g}\"{letra}"


def formato_gms(lat: float, lon: float) -> str:
    """13°5'38.09"N 86°0'7.42"O  (O = oeste, as Google Earth in Spanish)."""
    return f"{_gms(lat, 'N', 'S')} {_gms(lon, 'E', 'O')}"
