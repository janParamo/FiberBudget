"""Traffic-origin node from the Visio-derived network database (red_fibra/red_fibra.db).

The connection mufa is matched to its Visio counterpart, in this order:
  a) a Visio mufa within match_radius_m (an exact name wins)
  b) the nearest Visio mufa within fallback_radius_m
  c) by name: a Visio node with a similar normalized name (nodos.nombre_normalizado) within
     name_match.max_distance_m, or without coordinates                       -> confianza baja
  d) by name in the diagram texts (textos_crudos): the mufa is drawn but has no coordinate, so
     it has no node; the walk starts at the mufa a "SPL DEPENDE DE ..." text points to, or at
     the diagram's main mufa, and the drawn name is the first link of the path -> confianza baja
     (only diagrams with a georeferenced mufa within max_distance_m, or with none)
  e) nothing: no path, with a diagnosis of why (diagnostico)
From there the network is walked, mufa by mufa (Visio cables plus the PostGIS upstream chain),
until the first mufa whose diagram labels name a known node ("SPL 1X16 OLT GALERIAS Puerto 6",
"NODO LA MERCED"). Node names and their spellings live in business_rules.yaml.
"""
import logging
import math
import re
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_NODE_KEYWORD = re.compile(r"\b(OLT|NODO)\b")
_NODE_TIPOS = ("NODO", "MINI_NODO", "ODF")   # their own name can carry the node name

# Name matching (c, d). Same normalization as red_fibra/importador.normalizar, without the words
# that only say it is a mufa (MF, MUFA, MN...) or whose it is (IDEAY, UFINET).
_STOP_WORDS = {"DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "A", "AL", "EN", "FTE", "FRENTE"}
_DROPPED_WORDS = {"MUFA", "FOSC", "IDEAY", "UFINET"}
_LEADING_WORDS = {"MINI", "NODO"}
# Words that describe the kind of mufa, not where it is (importador.TOKENS_GENERICOS): a name made
# only of these ("MF DE CORTE 3M") is never matched by name.
_GENERIC_WORDS = {"MUFA", "CORTE", "CONTINUIDAD", "3M", "AEREA", "PEQUENA", "CHATELA", "FOSC", "PLANA",
                  "TECHO", "POSTE", "PARALELA", "NUEVA", "VIEJA", "INTERNA", "EXTERNA", "SANGRIA", "RVA",
                  "RESERVA", "ODF", "A", "B", "IDEAY", "UFINET", "SIN", "NOMBRE", "NODO", "MINI", "OVAL",
                  "OVALADA", "DOMO", "HORIZONTAL", "VERTICAL", "SATURADA", "SPLITTER", "SPL", "CLIENTE", "INFO"}
_SAME_WORD_RATIO = 0.85            # "AGUSTO" ~ "AUGUSTO"; numbers and short words must be equal
_LIST_ITEM = re.compile(r"^\s*\d+\s*[-.)]\s*")                        # "6- CASA GERENCIA ..."
_LABEL_LINE = re.compile(r"^\s*(MUFAS?|MF|MC|MN|MINI\s*NODO|NODO|FOSC)\b", re.I)
_CLIENT_LINE = re.compile(r"\bC\s?\d{4,6}\b|\bID\s*:?\s*\d{5,7}\b", re.I)
_SPLIT_RATIO = re.compile(r"\b\d+\s*[X/]\s*\d+\b")                    # "1/8", "1X16"
_TARGET_NOISE = {"SPL", "SPLITTER", "PRINCIPAL", "SECUNDARIO", "TERCIARIO", "PRIMARIO", "PUERTO", "PTO", "SEC"}
_DEPENDENCY_NEAR_CM = 20.0          # a dependency text this close to the drawn name applies to it
_MAX_CANDIDATES = 5                 # other candidates listed for review


@dataclass
class ChainPoint:
    """A PostGIS mufa of the connection chain, connection mufa first."""
    nombre: str | None
    lat: float
    lon: float
    tipo: str | None = None             # KMZ tipo ("mufa", "reserva"...) of the connection point


@dataclass
class TrafficOrigin:
    node: str | None = None                 # display name from business_rules, e.g. "Nodo Villa Fontana"
    confidence: str | None = None           # alta | media | baja
    label: str | None = None                # diagram text the node was read from
    labelled_mufa: str | None = None        # Visio mufa carrying that label
    # "Origen de tráfico (MF)": the mufa the node's service is taken from (the labelled mufa),
    # only when the path to it is traced cable by cable with alta/media confidence.
    origin_mufa: str | None = None
    path: list[str] = field(default_factory=list)          # Visio mufas, connection mufa first
    path_traced: bool = False               # path follows cables mufa by mufa (not a fallback guess)
    alternatives: list[str] = field(default_factory=list)  # other nodes found at the same distance
    saturated_mufas: list[str] = field(default_factory=list)
    connection_match: dict[str, Any] | None = None          # Visio mufa matched to the connection point
    reason: str | None = None               # why no node was found
    match_method: str | None = None         # a | b | c | d | e (see the module docstring)
    # Why the connection point has no Visio mufa by coordinate: {"caso", "casos", "detalle", ...}
    diagnostico: dict[str, Any] | None = None
    name_match: dict[str, Any] | None = None   # c / d: what was matched by name, where, and the other candidates


def _normalized(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char)).upper()
    return " ".join(text.split())


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------- name matching

def name_tokens(value: str | None) -> list[str]:
    """Words that identify a mufa: "MUFA - CASA GERENCIA OTTO MUNKEL" -> [CASA, GERENCIA, OTTO, MUNKEL]."""
    text = _LIST_ITEM.sub("", _normalized(value))
    text = re.sub(r"\bMF\b|\bMC\b|\bMUFAS?\b", " MUFA ", text)
    text = re.sub(r"\bMN\b", " MINI NODO ", text)
    text = re.sub(r"#\s*", "", text)
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    tokens = [t for t in text.split() if t not in _STOP_WORDS and t not in _DROPPED_WORDS]
    while tokens and tokens[0] in _LEADING_WORDS:
        tokens.pop(0)
    return tokens


def _is_generic(tokens: list[str]) -> bool:
    words = [t for t in tokens if not t.isdigit()]
    return not words or set(words) <= _GENERIC_WORDS


def _same_word(a: str, b: str) -> bool:
    if a == b:
        return True
    if a.isdigit() or b.isdigit() or len(a) < 4 or len(b) < 4:
        return False
    return SequenceMatcher(None, a, b).ratio() >= _SAME_WORD_RATIO


def _token_similarity(ta: list[str], tb: list[str]) -> float:
    """Dice coefficient over words, a misspelled word counting as the same word."""
    if not ta or not tb or _is_generic(ta) or _is_generic(tb):
        return 0.0
    rest, matched = list(tb), 0
    for word in ta:
        for i, other in enumerate(rest):
            if _same_word(word, other):
                matched += 1
                del rest[i]
                break
    return 2 * matched / (len(ta) + len(tb))


def name_similarity(a: str | None, b: str | None) -> float:
    """0..1: "MF CASA GERENCIA OTTO MUNKEL" vs "MUFA - CASA GERENCIA OTTO MUNKEL" = 1.0."""
    return _token_similarity(name_tokens(a), name_tokens(b))


def _initials(tokens: list[str]) -> str:
    """"PLAZA MAYOR 2" -> "PM2" (how the diagrams abbreviate a mufa: "SPL DEPENDE DE 1/8 PM2")."""
    return "".join(t if t.isdigit() else t[0] for t in tokens)


def _name_config(rules: dict[str, Any]) -> dict[str, Any]:
    config = rules.get("traffic_origin", {}).get("name_match") or {}
    return {
        "enabled": bool(config.get("enabled", True)),
        "min_similarity": float(config.get("min_similarity", 0.8)),
        "max_distance_m": float(config.get("max_distance_m", 2000)),
        "search_texts": bool(config.get("search_texts", True)),
        "dependency_words": [_normalized(w) for w in config.get(
            "dependency_words", ["SPL DEPENDE DE", "DEPENDE DE", "VIENE DE", "VIENE DEL"])],
    }


class _NameIndex:
    """Visio mufas by name, loaded once per connection (the report reuses it for every mufa)."""

    def __init__(self, con: Any):
        self.con = con
        self._nodes: list[dict[str, Any]] | None = None
        self._by_word: dict[str, list[int]] = {}

    def nodes(self) -> list[dict[str, Any]]:
        if self._nodes is None:
            self._nodes = []
            for node_id, nombre, lat, lon in self.con.execute(
                    "SELECT id, nombre, lat, lon FROM nodos WHERE tipo IN ('MUFA', 'MINI_NODO')"):
                tokens = name_tokens(nombre)
                if _is_generic(tokens):
                    continue
                self._nodes.append({"id": node_id, "nombre": nombre, "lat": lat, "lon": lon, "tokens": tokens})
                for token in set(tokens):
                    self._by_word.setdefault(token, []).append(len(self._nodes) - 1)
        return self._nodes

    def similar_nodes(self, name: str | None, lat: float, lon: float, min_similarity: float) -> list[dict[str, Any]]:
        """Nodes sharing at least one word with `name` and similar enough, best first."""
        wanted = name_tokens(name)
        if _is_generic(wanted):
            return []
        nodes = self.nodes()
        positions = {i for token in set(wanted) for i in self._by_word.get(token, ())}
        found = []
        for i in positions:
            node = nodes[i]
            similarity = _token_similarity(wanted, node["tokens"])
            if similarity >= min_similarity:
                distance = (None if node["lat"] is None or node["lon"] is None
                            else _distance_m(lat, lon, float(node["lat"]), float(node["lon"])))
                found.append({"id": node["id"], "nombre": node["nombre"], "similitud": round(similarity, 3),
                              "distancia_m": None if distance is None else round(distance, 1)})
        found.sort(key=lambda c: (-c["similitud"], math.inf if c["distancia_m"] is None else c["distancia_m"]))
        return found

    def similar_texts(self, name: str | None, lat: float, lon: float, min_similarity: float) -> list[dict[str, Any]]:
        """Diagram texts (not already Visio nodes) naming `name`: the best line per diagram, best first.

        A line starting with MUFA / MF ... (the mufa's own label) beats a list item or a client text.
        """
        wanted = name_tokens(name)
        if _is_generic(wanted):
            return []
        words = sorted((t for t in wanted if not t.isdigit() and t not in _GENERIC_WORDS and len(t) >= 3),
                       key=len, reverse=True)
        if not words:
            return []
        rows = self.con.execute(
            """SELECT t.archivo_id, t.pagina, t.x_cm, t.y_cm, t.texto, f.ruta_relativa, f.nombre, f.md5
               FROM textos_crudos t JOIN archivos f ON f.id = t.archivo_id
               WHERE f.estado = 'ok' AND upper(t.texto) LIKE ? AND coalesce(t.clasificacion, '') <> 'nodo'""",
            (f"%{words[0]}%",)).fetchall()
        best: dict[int, dict[str, Any]] = {}
        for archivo_id, pagina, x, y, texto, ruta, nombre_archivo, md5 in rows:
            for line in (texto or "").split("\n"):
                line = " ".join(line.split())
                if not line or _CLIENT_LINE.search(line):
                    continue
                similarity = _token_similarity(wanted, name_tokens(line))
                if similarity < min_similarity:
                    continue
                is_label = bool(_LABEL_LINE.match(line))
                key = (similarity, is_label)
                current = best.get(archivo_id)
                if current is None or key > (current["similitud"], current["etiqueta"]):
                    best[archivo_id] = {
                        "archivo_id": archivo_id, "archivo": nombre_archivo, "ruta_relativa": ruta, "md5": md5,
                        "pagina": pagina, "x_cm": x, "y_cm": y, "texto": texto,
                        "nombre_diagrama": _LIST_ITEM.sub("", line),
                        "similitud": round(similarity, 3), "etiqueta": is_label,
                        "validar": "VALIDAR" in _normalized(texto)}
        found = list(best.values())
        for candidate in found:
            candidate["distancia_m"] = self._file_distance(candidate["archivo_id"], lat, lon)
        found.sort(key=lambda c: (-c["similitud"], not c["etiqueta"],
                                  math.inf if c["distancia_m"] is None else c["distancia_m"]))
        return found

    def _file_distance(self, archivo_id: int, lat: float, lon: float) -> float | None:
        """Distance to the nearest georeferenced node drawn in that diagram (tie-break)."""
        distances = [_distance_m(lat, lon, float(a), float(b)) for a, b in self.con.execute(
            """SELECT n.lat, n.lon FROM nodo_apariciones a JOIN nodos n ON n.id = a.nodo_id
               WHERE a.archivo_id = ? AND n.lat IS NOT NULL AND n.lon IS NOT NULL""", (archivo_id,))]
        return round(min(distances), 1) if distances else None


def _dependency_target(con: Any, hit: dict[str, Any], kmz_name: str | None, config: dict[str, Any],
                       matcher: "_AliasMatcher") -> dict[str, Any]:
    """Where the walk starts for a name found in a diagram (case d).

    The "SPL DEPENDE DE ..." text that lists this mufa (else the nearest one on the same page)
    points to a mufa of the same diagram, by name or by initials ("PM2" = PLAZA MAYOR 2), or
    straight to a node ("SPL DEPENDE DE OLT LAS COLINAS"). Otherwise the diagram's main mufa.
    """
    texts = con.execute("SELECT pagina, x_cm, y_cm, texto FROM textos_crudos WHERE archivo_id = ?",
                        (hit["archivo_id"],)).fetchall()
    wanted = name_tokens(kmz_name)
    listing, nearby = [], []
    for pagina, x, y, texto in texts:
        lines = [" ".join(line.split()) for line in (texto or "").split("\n")]
        for i, line in enumerate(lines):
            normalized = _normalized(line)
            word = next((w for w in config["dependency_words"] if w and w in normalized), None)
            if word is None:
                continue
            target = normalized.split(word, 1)[1].strip(" :-")
            entry = {"texto": line, "objetivo": target}
            others = lines[:i] + lines[i + 1:]
            if any(_token_similarity(wanted, name_tokens(o)) >= config["min_similarity"] for o in others):
                listing.append(entry)
            elif (pagina == hit["pagina"] and None not in (x, y, hit["x_cm"], hit["y_cm"])
                  and math.hypot(x - hit["x_cm"], y - hit["y_cm"]) <= _DEPENDENCY_NEAR_CM):
                nearby.append((math.hypot(x - hit["x_cm"], y - hit["y_cm"]), entry))
            break
    dependencies = listing + [entry for _, entry in sorted(nearby, key=lambda pair: pair[0])]
    file_nodes = con.execute(
        """SELECT DISTINCT n.id, n.nombre, a.rol FROM nodo_apariciones a JOIN nodos n ON n.id = a.nodo_id
           WHERE a.archivo_id = ?""", (hit["archivo_id"],)).fetchall()
    for dependency in dependencies:
        node = matcher.node_in(dependency["texto"])
        if node:
            return {"por": "nodo", "nodo": node, "dependencia": dependency["texto"]}
        target_tokens = [t for t in name_tokens(_SPLIT_RATIO.sub(" ", dependency["objetivo"]))
                         if t not in _TARGET_NOISE]
        if not target_tokens:
            continue
        compact = "".join(target_tokens)
        best = None
        for node_id, nombre, _ in file_nodes:
            tokens = name_tokens(nombre)
            score = _token_similarity(target_tokens, tokens)
            if score < config["min_similarity"] and len(compact) >= 2 and compact == _initials(tokens):
                score = config["min_similarity"]
            if score >= config["min_similarity"] and (best is None or score > best[0]):
                best = (score, node_id, nombre)
        if best is not None:
            return {"por": "dependencia", "id": best[1], "nombre": best[2], "dependencia": dependency["texto"]}
    principal = next(((node_id, nombre) for node_id, nombre, rol in file_nodes if rol == "principal"), None)
    if principal is not None:
        return {"por": "principal", "id": principal[0], "nombre": principal[1],
                "dependencia": dependencies[0]["texto"] if dependencies else None}
    return {"por": None, "dependencia": dependencies[0]["texto"] if dependencies else None}


def _diagnosis(point: ChainPoint, nodes: list[dict[str, Any]], texts: list[dict[str, Any]],
               fallback_radius: float, is_reserve: bool) -> dict[str, Any]:
    """Why the connection point has no Visio mufa by coordinate (cases of the README)."""
    name = point.nombre or "el punto de conexión"
    radius = f"ninguna mufa de los diagramas a menos de {fallback_radius:.0f} m"
    if is_reserve:
        return {"caso": "es_reserva", "casos": ["es_reserva"],
                "detalle": f"{name} es una reserva: se instala mufa nueva ({radius})"}
    cases, details = [], []
    far = [n for n in nodes if n["distancia_m"] is not None]
    if far:
        cases.append("a_mayor_distancia")
        details.append(f"hay mufa Visio con nombre parecido: {far[0]['nombre']} a {far[0]['distancia_m']:.0f} m")
    without = [n for n in nodes if n["distancia_m"] is None]
    if without or texts:
        cases.append("sin_coordenada_en_visio")
        if texts:
            near = (f", diagrama a {texts[0]['distancia_m']:.0f} m" if texts[0]["distancia_m"] is not None else "")
            details.append(f"aparece en el diagrama {texts[0]['archivo']} sin coordenada "
                           f"(\"{texts[0]['nombre_diagrama']}\"{near})")
        else:
            details.append(f"{without[0]['nombre']} está en los diagramas sin coordenada")
    validar = next((t for t in texts if t["validar"]), None)
    if validar is not None:
        cases.append("marcada_validar")
        line = next((" ".join(l.split()) for l in validar["texto"].split("\n") if "VALIDAR" in _normalized(l)),
                    "VALIDAR")
        details.append(f"el diagrama dice: {line}")
    if not cases:
        cases.append("no_diagramada")
        details.append(f"{name} no aparece en ningún diagrama Visio")
    return {"caso": cases[0], "casos": cases, "detalle": "; ".join(details) + f" ({radius})",
            "candidatos_nodos": nodes[:_MAX_CANDIDATES],
            "candidatos_diagramas": [{k: t[k] for k in ("archivo", "nombre_diagrama", "similitud", "distancia_m")}
                                     for t in texts[:_MAX_CANDIDATES]]}


@dataclass
class ConnectionMatch:
    """How the connection point was matched to the Visio network (cases a..e)."""
    method: str                                  # a | b | c | d | e
    node_id: int | None = None                   # Visio node the walk starts from
    node_name: str | None = None
    distance_m: float | None = None
    drawn_name: str | None = None                # d: the mufa's name as drawn in the diagram
    direct_node: str | None = None               # d: the dependency text names the node itself
    direct_label: str | None = None
    name_match: dict[str, Any] | None = None
    diagnostico: dict[str, Any] | None = None


def match_connection(con: Any, point: ChainPoint, rules: dict[str, Any],
                     index: _NameIndex | None = None) -> ConnectionMatch:
    """Visio counterpart of the connection point, cases a..e. Read-only; used by the report too."""
    config = rules.get("traffic_origin", {})
    match_radius = float(config.get("match_radius_m", 40))
    fallback_radius = float(config.get("fallback_radius_m", 150))
    found = _nearest_mufa(con, point.lat, point.lon, match_radius, point.nombre)
    if found is not None:
        return ConnectionMatch("a", found[0], found[1], found[2])
    found = _nearest_mufa(con, point.lat, point.lon, fallback_radius)
    if found is not None:
        return ConnectionMatch("b", found[0], found[1], found[2])

    names = _name_config(rules)
    index = index or _NameIndex(con)
    is_reserve = (point.tipo or "").casefold().startswith(("reserva", "rva"))
    nodes = [] if is_reserve else index.similar_nodes(point.nombre, point.lat, point.lon, names["min_similarity"])
    texts = ([] if is_reserve or not names["search_texts"]
             else index.similar_texts(point.nombre, point.lat, point.lon, names["min_similarity"]))
    diagnostico = _diagnosis(point, nodes, texts, fallback_radius, is_reserve)
    if is_reserve or not names["enabled"]:
        return ConnectionMatch("e", diagnostico=diagnostico)

    accepted = [n for n in nodes if n["distancia_m"] is None or n["distancia_m"] <= names["max_distance_m"]]
    if accepted:
        best = accepted[0]
        name_match = {"metodo": "c", "nombre_diagrama": best["nombre"], "nodo_id": best["id"],
                      "similitud": best["similitud"], "distancia_m": best["distancia_m"],
                      "motivo": "emparejado por nombre en la red Visio",
                      "candidatos": [n for n in nodes if n is not best][:_MAX_CANDIDATES]}
        return ConnectionMatch("c", best["id"], best["nombre"], best["distancia_m"],
                               name_match=name_match, diagnostico=diagnostico)
    # A diagram whose nearest georeferenced mufa is beyond max_distance_m is somewhere else.
    near_texts = [t for t in texts if t["distancia_m"] is None or t["distancia_m"] <= names["max_distance_m"]]
    if near_texts:
        hit = near_texts[0]
        matcher = _AliasMatcher(config.get("nodes", {}), config.get("ignore_label_words", []))
        start = _dependency_target(con, hit, point.nombre, names, matcher)
        name_match = {"metodo": "d", "nombre_diagrama": hit["nombre_diagrama"], "similitud": hit["similitud"],
                      "archivo_id": hit["archivo_id"], "archivo": hit["archivo"],
                      "ruta_relativa": hit["ruta_relativa"], "md5": hit["md5"], "pagina": hit["pagina"],
                      "x_cm": hit["x_cm"], "y_cm": hit["y_cm"], "texto": hit["texto"],
                      "distancia_diagrama_m": hit["distancia_m"],
                      "dependencia": start.get("dependencia"), "inicio": start.get("nombre") or start.get("nodo"),
                      "inicio_por": start["por"], "motivo": "emparejado por nombre en diagrama",
                      "candidatos": [{k: t[k] for k in ("archivo", "nombre_diagrama", "similitud", "distancia_m")}
                                     for t in texts if t is not hit][:_MAX_CANDIDATES]}
        return ConnectionMatch("d", start.get("id"), start.get("nombre"), None, drawn_name=hit["nombre_diagrama"],
                               direct_node=start.get("nodo"), direct_label=start.get("dependencia"),
                               name_match=name_match, diagnostico=diagnostico)
    return ConnectionMatch("e", diagnostico=diagnostico)


# --------------------------------------------------------------------------- labels and walk

class _AliasMatcher:
    """Finds a configured node name written after "OLT" or "NODO" in a diagram label."""

    def __init__(self, nodes: dict[str, list[str]], ignore_words: list[str]):
        pairs = [(_normalized(alias), name) for name, aliases in nodes.items() for alias in aliases]
        pairs.sort(key=lambda pair: -len(pair[0]))   # "LA MERCED" before "MERCED"
        self._pattern = re.compile(
            r"(?<![A-Z0-9])(" + "|".join(re.escape(alias) for alias, _ in pairs) + r")(?![A-Z0-9])")
        self._names = dict(pairs)
        self._ignore = [_normalized(word) for word in ignore_words]

    def node_in(self, label: str) -> str | None:
        if not self._names:
            return None
        text = _normalized(label)
        if any(word in text for word in self._ignore):   # backup / redundant links
            return None
        keyword = _NODE_KEYWORD.search(text)
        if keyword is None:
            return None
        match = self._pattern.search(text, keyword.end())   # the node is named after the keyword
        return self._names[match.group(1)] if match else None


def _nearest_mufa(con: Any, lat: float, lon: float, radius_m: float,
                  name: str | None = None) -> tuple[int, str, float] | None:
    """Nearest Visio mufa within radius_m; among several within it, an exact name wins."""
    dlat = radius_m / 111320.0
    dlon = radius_m / (111320.0 * max(math.cos(math.radians(lat)), 0.1))
    rows = con.execute(
        """SELECT id, nombre, lat, lon FROM nodos
           WHERE tipo = 'MUFA' AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?""",
        (lat - dlat, lat + dlat, lon - dlon, lon + dlon)).fetchall()
    candidates = sorted(
        (distance, node_id, nombre) for node_id, nombre, node_lat, node_lon in rows
        if (distance := _distance_m(lat, lon, node_lat, node_lon)) <= radius_m)
    if not candidates:
        return None
    wanted = _normalized(name)
    named = [c for c in candidates if wanted and _normalized(c[2]) == wanted]
    distance, node_id, nombre = (named or candidates)[0]
    return node_id, nombre, distance


def _saturated(con: Any, node_id: int, near_cm: float) -> bool:
    """A "SATURADA" text in the node's own label or written next to it in a diagram."""
    for archivo_id, texto in con.execute(
            "SELECT archivo_id, texto_original FROM nodo_apariciones WHERE nodo_id = ?", (node_id,)):
        if "SATURAD" in _normalized(texto):
            return True
        marks = con.execute(
            """SELECT x_cm, y_cm FROM textos_crudos
               WHERE archivo_id = ? AND upper(texto) LIKE '%SATURAD%'""", (archivo_id,)).fetchall()
        if not marks:
            continue
        for x, y in con.execute(
                "SELECT x_cm, y_cm FROM textos_crudos WHERE archivo_id = ? AND texto = ?",
                (archivo_id, texto)):
            if any(math.hypot(x - mx, y - my) <= near_cm for mx, my in marks):
                return True
    return False


class _PgAdapter:
    """Lets the sqlite-style queries below ("?" placeholders) run on a psycopg connection
    whose search_path points at the red_fibra schema."""

    def __init__(self, conn: Any):
        self._conn = conn

    def execute(self, sql: str, params: tuple = ()) -> Any:
        return self._conn.execute(sql.replace("%", "%%").replace("?", "%s"), params)

    def close(self) -> None:   # the caller owns the connection
        pass


def visio_unavailable(source: Path | Any, point: ChainPoint, rules: dict[str, Any],
                      keywords: list[str]) -> str | None:
    """The mark that says the Visio mufa at this point gives no hilos ("SATURADA", "NO PROYECTAR"...),
    or None. Only the Visio mufa matched by coordinate (match_radius_m) is checked: its notes, and a
    SATURADA text next to its label. source: the SQLite file (Path) or a psycopg connection."""
    if isinstance(source, Path):
        if not source.is_file():
            return None
        con = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    else:
        con = _PgAdapter(source)
    config = rules.get("traffic_origin", {})
    try:
        found = _nearest_mufa(con, point.lat, point.lon, float(config.get("match_radius_m", 40)), point.nombre)
        if found is None:
            return None
        notas = _normalized(con.execute("SELECT notas FROM nodos WHERE id = ?", (found[0],)).fetchone()[0])
        word = next((w for w in (_normalized(k) for k in keywords) if w and w in notas), None)
        if word:
            return f"{word} en el diagrama ({found[1]})"
        if any("SATURAD" in _normalized(k) for k in keywords) and _saturated(
                con, found[0], float(config.get("saturated_text_distance_cm", 3))):
            return f"SATURADA en el diagrama ({found[1]})"
        return None
    finally:
        con.close()


def _walk(con: Any, start: tuple[int, str, float | None], exact_start: bool,
          matched: list[tuple[int, str, float] | None], config: dict[str, Any],
          matcher: _AliasMatcher) -> TrafficOrigin:
    """Breadth-first from the start mufa to the nearest labelled one, then the fallbacks."""
    max_hops = int(config.get("max_hops", 8))
    media_max_hops = int(config.get("media_max_hops", 3))
    adjacency: dict[int, set[int]] = {}
    for a, b in con.execute("SELECT nodo_a_id, nodo_b_id FROM enlaces"):
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    chain_ids = [m[0] for m in matched if m is not None]
    if not exact_start:
        chain_ids.insert(0, start[0])
    for a, b in zip(chain_ids, chain_ids[1:]):
        if a != b:
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)

    names = dict(con.execute("SELECT id, nombre FROM nodos"))
    tipos = dict(con.execute("SELECT id, tipo FROM nodos"))

    def node_labels(node_id: int) -> list[tuple[str, str]]:
        """(node name, label) pairs read from the services drawn at this mufa."""
        texts = [row[0] for row in con.execute(
            "SELECT descripcion FROM servicios WHERE nodo_id = ?", (node_id,))]
        if tipos.get(node_id) in _NODE_TIPOS:
            texts.insert(0, names[node_id])
        return [(node, text) for text in texts if (node := matcher.node_in(text))]

    connection_match = {"name": start[1], "distance_m": None if start[2] is None else round(start[2], 1),
                        "exact": exact_start}
    # Breadth-first, one distance level at a time: the nearest labelled mufas decide.
    parents: dict[int, int | None] = {start[0]: None}
    level, depth = [start[0]], 0
    while level and depth <= max_hops:
        found = {node_id: labels for node_id in level if (labels := node_labels(node_id))}
        if found:
            votes = Counter(node for labels in found.values() for node, _ in labels)
            (best, _), *others = votes.most_common()
            labelled = max(found, key=lambda nid: sum(node == best for node, _ in found[nid]))
            path, current = [], labelled
            while current is not None:
                path.append(current)
                current = parents[current]
            path.reverse()
            alternatives = [node for node, _ in others]
            if alternatives or not exact_start or depth > media_max_hops:
                confidence = "baja"
            else:
                confidence = "alta" if depth == 0 else "media"
            near_cm = float(config.get("saturated_text_distance_cm", 3))
            return TrafficOrigin(
                node=best,
                confidence=confidence,
                label=next(text for node, text in found[labelled] if node == best),
                labelled_mufa=names[labelled],
                origin_mufa=names[labelled] if exact_start and confidence != "baja" else None,
                path=[names[nid] for nid in path],
                path_traced=exact_start,
                alternatives=alternatives,
                saturated_mufas=[names[nid] for nid in path if _saturated(con, nid, near_cm)],
                connection_match=connection_match,
            )
        next_level = []
        for node_id in level:
            for neighbor in sorted(adjacency.get(node_id, ())):
                if neighbor not in parents:
                    parents[neighbor] = node_id
                    next_level.append(neighbor)
        level, depth = next_level, depth + 1

    # Fallbacks (always baja): the main mufa of a diagram the connection mufa is drawn in,
    # then the diagram folder, which usually names its node ("Nodo La Gruta carretera hacia Leon").
    for principal_id, archivo in con.execute(
            """SELECT DISTINCT a2.nodo_id, f.ruta_relativa
               FROM nodo_apariciones a1
               JOIN nodo_apariciones a2 ON a2.archivo_id = a1.archivo_id AND a2.rol = 'principal'
               JOIN archivos f ON f.id = a1.archivo_id
               WHERE a1.nodo_id = ? AND a2.nodo_id <> ?""", (start[0], start[0])).fetchall():
        labels = node_labels(principal_id)
        if labels:
            votes = Counter(node for node, _ in labels)
            (best, _), *others = votes.most_common()
            return TrafficOrigin(
                node=best, confidence="baja",
                label=next(text for node, text in labels if node == best),
                labelled_mufa=names[principal_id], path=[start[1], names[principal_id]],
                alternatives=[node for node, _ in others], connection_match=connection_match,
                reason=f"mufa principal del diagrama {archivo}")
    zona = con.execute("SELECT zona FROM nodos WHERE id = ?", (start[0],)).fetchone()[0]
    node = matcher.node_in(zona or "")
    if node:
        return TrafficOrigin(node=node, confidence="baja", label=zona, path=[start[1]],
                             connection_match=connection_match,
                             reason="nombre de la carpeta del diagrama")
    return TrafficOrigin(
        reason=f"ningún nodo etiquetado a {max_hops} saltos o menos en los diagramas",
        connection_match=connection_match,
    )


def _by_name(con: Any, match: ConnectionMatch, matched: list, config: dict[str, Any],
             matcher: _AliasMatcher) -> TrafficOrigin:
    """Cases c and d: always baja, never traced (the first link is a name, not a cable)."""
    if match.method == "c":
        origin = _walk(con, (match.node_id, match.node_name, match.distance_m), False, matched, config, matcher)
    elif match.direct_node is not None:
        origin = TrafficOrigin(node=match.direct_node, label=match.direct_label)
    elif match.node_id is not None:
        origin = _walk(con, (match.node_id, match.node_name, None), False, matched, config, matcher)
    else:   # a red diagram without a main mufa: only the folder name can tell
        folder = con.execute("SELECT carpeta, ruta_relativa FROM archivos WHERE id = ?",
                             (match.name_match["archivo_id"],)).fetchone()
        node = next((n for n in (matcher.node_in(f or "") for f in (folder or ())) if n), None)
        origin = TrafficOrigin(node=node, label=folder[0] if node and folder else None,
                               reason="nombre de la carpeta del diagrama" if node else None)
    if match.method == "d":
        origin.path = [match.drawn_name] + origin.path
    reasons = [match.name_match["motivo"]] + ([origin.reason] if origin.reason else [])
    if origin.node is None and match.diagnostico:
        reasons.append(match.diagnostico["detalle"])
    origin.reason = "; ".join(reasons)
    if origin.node is not None:
        origin.confidence = "baja"
    origin.origin_mufa = None
    origin.path_traced = False
    origin.match_method = match.method
    origin.name_match = match.name_match
    origin.diagnostico = match.diagnostico
    origin.connection_match = {"name": match.drawn_name or match.node_name,
                               "distance_m": match.distance_m, "exact": False, "method": match.method}
    return origin


def find_traffic_origin(source: Path | Any, chain: list[ChainPoint], rules: dict[str, Any]) -> TrafficOrigin:
    """Nearest labelled node upstream of the connection point (chain[0]).

    source: the SQLite file (Path), or an open psycopg connection to the PostgreSQL copy.
    """
    if not chain:
        return TrafficOrigin(reason="sin punto de conexión")
    if isinstance(source, Path):
        if not source.is_file():
            return TrafficOrigin(reason=f"base de diagramas no encontrada: {source}")
        con = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    else:
        con = _PgAdapter(source)
    config = rules.get("traffic_origin", {})
    matcher = _AliasMatcher(config.get("nodes", {}), config.get("ignore_label_words", []))
    match_radius = float(config.get("match_radius_m", 40))

    try:
        # Visio counterparts of the PostGIS chain; consecutive ones are linked by the chain.
        matched = [_nearest_mufa(con, point.lat, point.lon, match_radius, point.nombre) for point in chain]
        match = match_connection(con, chain[0], rules)
        if match.method in ("a", "b"):
            origin = _walk(con, (match.node_id, match.node_name, match.distance_m), match.method == "a",
                           matched, config, matcher)
            origin.match_method = match.method
            return origin
        if match.method in ("c", "d"):
            return _by_name(con, match, matched, config, matcher)
        return TrafficOrigin(reason=match.diagnostico["detalle"], match_method="e",
                             diagnostico=match.diagnostico)
    finally:
        con.close()
