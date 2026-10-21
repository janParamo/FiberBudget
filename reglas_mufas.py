"""Mufas que NO se pueden usar (reglas de Jan, 2026-10-20), en un solo lugar para todo el cálculo.

Una mufa de corte («MC», «MF DE CORTE»), una mufa aérea («MF AEREA CENTRO») y una de punta plana o plancha («MF PUNTA PLANA») no se pueden usar:

  - como **punto de conexión** (la mufa más cercana a la que se conecta el cliente);
  - para contar las **mufas intervenidas** hasta el splitter (ni los empalmes);
  - en la **ruta de fusión**: la fusión pasa de largo (además, ahí tampoco se usa un mini nodo).

Se reconocen por el NOMBRE (palabras completas, sin acentos ni mayúsculas) y, para el punto de conexión, también por la carpeta del KMZ («mufa de corte»,
en `excluded_tipo_keywords`). Un lugar no es una mufa aérea («MF FUERZA AEREA»): las excepciones lo dicen. Todo sale de la sección `mufas_no_usables` de
business_rules.yaml. Aquí no hay base de datos: `patrones_sql` arma las dos expresiones regulares que usa PostgreSQL (db.py) para dejarlas fuera.
"""
import re
import unicodedata
from typing import Any

MOTIVOS_POR_DEFECTO = {
    "de corte": ["MC", "CORTE", "CORTES"],
    "aérea": ["AEREA", "AEREAS", "AEREO", "AEREOS"],
    "punta plana": ["PUNTA PLANA", "PUNTA PLANCHA", "PLANCHA"],
}
SOLO_RUTA_DE_FUSION_POR_DEFECTO = {"mini nodo": ["MINI NODO", "MN"]}
EXCEPCIONES_POR_DEFECTO = ["FUERZA AEREA"]
_ACENTOS = {"A": "AÁÀÂÄ", "E": "EÉÈÊË", "I": "IÍÌÎÏ", "O": "OÓÒÔÖ", "U": "UÚÙÛÜ", "N": "NÑ"}


def plano(texto: Any) -> str:
    """Upper case, no accents, only letters and digits separated by single spaces."""
    t = "".join(c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Z0-9 ]+", " ", t.upper()).split())


def configuracion(rules: dict[str, Any] | None) -> dict[str, Any]:
    """{"motivos": {motivo: [palabras]}, "ruta_fusion": {motivo: [palabras]}, "excepciones": [frases]} from `mufas_no_usables`."""
    cfg = (rules or {}).get("mufas_no_usables") or {}

    def normal(d: dict[str, Any]) -> dict[str, list[str]]:
        return {str(m): [plano(p) for p in ps if plano(p)] for m, ps in d.items()}
    return {"motivos": normal(cfg.get("motivos") or MOTIVOS_POR_DEFECTO),
            "ruta_fusion": normal(cfg.get("solo_ruta_de_fusion") or SOLO_RUTA_DE_FUSION_POR_DEFECTO),
            "excepciones": [plano(p) for p in (cfg.get("excepciones") or EXCEPCIONES_POR_DEFECTO) if plano(p)]}


def motivo(nombre: Any, config: dict[str, Any], en_ruta_de_fusion: bool = False) -> str | None:
    """Why this mufa cannot be used («de corte», «aérea», «punta plana»; «mini nodo» only in the fusion route), None when it can."""
    texto = f" {plano(nombre)} "
    for excepcion in config["excepciones"]:
        texto = texto.replace(f" {excepcion} ", " ")
    grupos = dict(config["motivos"])
    if en_ruta_de_fusion:
        grupos.update(config["ruta_fusion"])
    for razon, palabras in grupos.items():
        if any(f" {p} " in texto for p in palabras):
            return razon
    return None


def usable(nombre: Any, config: dict[str, Any], en_ruta_de_fusion: bool = False) -> bool:
    return motivo(nombre, config, en_ruta_de_fusion) is None


def _regex_palabra(palabra: str) -> str:
    """Postgres pattern of one word or phrase of `plano`: accents allowed in the name, any run of spaces between the words."""
    partes = []
    for c in palabra:
        if c == " ":
            partes.append(r"[[:space:]]+")
        else:
            partes.append(f"[{_ACENTOS[c]}]" if c in _ACENTOS else re.escape(c))
    return "".join(partes)


def _regex(frases: list[str]) -> str | None:
    if not frases:
        return None
    return r"(^|[^[:alnum:]])(" + "|".join(_regex_palabra(p) for p in frases) + r")($|[^[:alnum:]])"


def regex_palabras(frases: list[str]) -> str | None:
    """PostgreSQL pattern (`~*`) for any of these words or phrases as whole words in a name (accents allowed)."""
    return _regex([plano(f) for f in frases if plano(f)])


def patrones_sql(config: dict[str, Any]) -> tuple[str | None, str | None]:
    """(names to leave out, exceptions) as PostgreSQL regular expressions for `~*`; None = nothing to leave out."""
    palabras = [p for ps in config["motivos"].values() for p in ps]
    return _regex(palabras), _regex(config["excepciones"])


def filtrar(items: list[Any], config: dict[str, Any], nombre=lambda x: getattr(x, "nombre", None)) -> list[Any]:
    """The items whose name is usable (mufas of the chain or of the route): the ones that count as intervened."""
    return [x for x in items if usable(nombre(x), config)]
