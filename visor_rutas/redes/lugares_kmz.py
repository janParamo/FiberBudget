"""Mis lugares <-> KMZ / KML (visor v2, fase 3).

- `exportar`: una carpeta (con sus subcarpetas) a KMZ para Google Earth: carpetas, marcas con su ícono (PNG dibujado aquí, así se ve
  sin internet), rutas y polígonos con su color, grosor, opacidad y relleno, descripciones con formato e imágenes (dentro del KMZ)
  y la vista guardada como LookAt. Además de lo estándar guarda en ExtendedData lo propio (tipo, ícono exacto, propiedades): al volver
  a importar el KMZ queda igual.
- `importar`: un .kmz o .kml (de aquí, de Google Earth o de otro programa) a una carpeta nueva dentro de Mis lugares: carpetas y
  subcarpetas, puntos como marcas, líneas como rutas y polígonos (el contorno exterior), con su nombre, descripción (HTML seguro),
  color, ícono (pushpin de Google por su nombre, o el propio) y vista. Lo que no se puede representar se cuenta como omitido.
"""
import base64
import io
import json
import math
import re
import zipfile
from typing import Any
from xml.sax.saxutils import escape

from lxml import etree

from visor_rutas.redes import lugares, lugares_iconos
from visor_rutas.redes.db import DatosInvalidos

MAX_ARCHIVO = 30 * 1024 * 1024            # a KMZ / KML of this size at most (bytes, already decoded)
MAX_ELEMENTOS = 5_000
MAX_CARPETAS = 2_000
NS = ""                                      # the tags are read without namespace (KML 2.0, 2.1, 2.2): see _sin_espacios
RANGO_ZOOM0 = 35_200_000                    # LookAt range in metres at zoom 0 (approximate: range = RANGO_ZOOM0 / 2**zoom)
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


def _kml_color(hexa: str | None, opacidad: float = 1.0) -> str:
    h = (hexa or "#ffffff").lstrip("#")
    h = h if len(h) == 6 else "ffffff"
    return f"{round(max(0, min(1, opacidad)) * 255):02x}{h[4:6]}{h[2:4]}{h[0:2]}"


def _de_kml_color(valor: str | None) -> tuple[str, float] | None:
    v = (valor or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{8}", v):
        return None
    return f"#{v[6:8]}{v[4:6]}{v[2:4]}", round(int(v[0:2], 16) / 255, 2)


def _cdata(texto: str) -> str:
    return "<![CDATA[" + texto.replace("]]>", "]]]]><![CDATA[>") + "]]>"


# --------------------------------------------------------------------------- exportar

def _estilo_kml(e: dict[str, Any], nombre: str) -> tuple[str, str | None]:
    """(<Style> xml, icon key or None) of an element."""
    st = e["estilo"] or {}
    partes, clave = [], None
    if e["tipo"] in lugares.PUNTUALES:
        ic = lugares_iconos.limpiar_icono(st.get("icono")) or lugares_iconos.ICONO_POR_DEFECTO
        if ic["tipo"] != "ninguno":
            clave = lugares_iconos.clave(ic)
            ancla = 'x="0.5" y="0"' if lugares_iconos.es_gota(ic) else 'x="0.5" y="0.5"'
            partes.append(f'<IconStyle><scale>{ic["escala"]}</scale><Icon><href>files/{clave}.png</href></Icon>'
                          f'<hotSpot {ancla} xunits="fraction" yunits="fraction"/></IconStyle>')
        else:
            partes.append("<IconStyle><scale>0</scale></IconStyle>")
        et = st.get("etiqueta") or {}
        partes.append(f'<LabelStyle><color>{_kml_color(et.get("color") or "#ffffff")}</color><scale>{et.get("escala", 1.0) if et.get("visible", True) else 0}</scale></LabelStyle>')
    else:
        li = st.get("linea") or {}
        partes.append(f'<LineStyle><color>{_kml_color(li.get("color") or "#ffe600", li.get("opacidad", 1.0))}</color><width>{li.get("grosor", 3)}</width></LineStyle>')
        if e["tipo"] in lugares.AREALES:
            re_ = st.get("relleno") or {}
            activo = re_.get("activo", True)
            partes.append(f'<PolyStyle><color>{_kml_color(re_.get("color") or "#ffe600", re_.get("opacidad", 0.3))}</color><fill>{1 if activo else 0}</fill><outline>1</outline></PolyStyle>')
    return f'<Style id="{nombre}">{"".join(partes)}</Style>', clave


def _coords(geo: dict[str, Any]) -> str:
    if geo["type"] == "Point":
        pts = [geo["coordinates"]]
    elif geo["type"] == "LineString":
        pts = geo["coordinates"]
    else:
        pts = geo["coordinates"][0]
    return " ".join(f"{x},{y},0" for x, y in (p[:2] for p in pts))


def _vista_kml(vista: dict[str, Any] | None) -> str:
    if not vista:
        return ""
    rango = round(RANGO_ZOOM0 / (2 ** float(vista.get("zoom", 17))))
    return f"<LookAt><longitude>{vista['lon']}</longitude><latitude>{vista['lat']}</latitude><range>{rango}</range></LookAt>"


def exportar(con: Any, actor: dict[str, Any], *, carpeta_id: int) -> dict[str, Any]:
    """KMZ of a folder with its subfolders (anyone who can see the folder)."""
    lugares._exigir(con, actor, carpeta_id)
    carpetas, _ = lugares._descendientes(con, [int(carpeta_id)])
    filas_c = {f["id"]: dict(f) for f in con.execute("SELECT id, padre_id, nombre, orden FROM redes.lugares_carpetas WHERE id = ANY(%s)", (carpetas,)).fetchall()}
    filas_e = [dict(f) for f in con.execute(
        "SELECT e.id, e.carpeta_id, e.tipo, e.nombre, e.orden, e.descripcion_html, e.estilo, e.vista, e.propiedades, ST_AsGeoJSON(e.geom, 7) AS geom "
        "FROM redes.lugares_elementos e WHERE e.carpeta_id = ANY(%s) AND e.borrado_en IS NULL", (carpetas,)).fetchall()]
    adjuntos = {f["id"]: dict(f) for f in con.execute(
        "SELECT a.id, a.nombre, a.tipo, a.datos FROM redes.lugares_adjuntos a JOIN redes.lugares_elementos e ON e.id = a.elemento_id "
        "WHERE e.carpeta_id = ANY(%s) AND a.borrado_en IS NULL AND e.borrado_en IS NULL", (carpetas,)).fetchall()}
    estilos: dict[str, str] = {}
    iconos: dict[str, dict[str, Any]] = {}
    usados_adj: dict[int, str] = {}

    def descripcion(e: dict[str, Any]) -> str:
        html = e["descripcion_html"] or ""

        def img(m: re.Match) -> str:
            a = adjuntos.get(int(m.group(1)))
            if not a:
                return ""
            nombre = f"adj_{a['id']}.{_EXT.get(a['tipo'], 'png')}"
            usados_adj[a["id"]] = nombre
            return f'<img src="files/{nombre}" width="320">'
        return lugares._IMG_ADJ.sub(img, html)

    def marca(e: dict[str, Any]) -> str:
        geo = json.loads(e["geom"])
        sid, clave = f"s{len(estilos)}", None
        xml, clave = _estilo_kml(e, sid)
        for k, v in estilos.items():                       # the same style is written once
            if v == xml.replace(f'id="{sid}"', f'id="{k}"'):
                sid, xml = k, ""
                break
        if xml:
            estilos[sid] = xml
        if clave:
            iconos[clave] = lugares_iconos.limpiar_icono((e["estilo"] or {}).get("icono")) or lugares_iconos.ICONO_POR_DEFECTO
        ext = [("ideay_tipo", e["tipo"])]
        if clave:
            ext.append(("ideay_icono", json.dumps((e["estilo"] or {}).get("icono"), ensure_ascii=False)))
        if e["tipo"] != "marca" or e["propiedades"]:
            ext.append(("ideay_propiedades", json.dumps(e["propiedades"] or {}, ensure_ascii=False)))
        if e["estilo"]:
            ext.append(("ideay_estilo", json.dumps(e["estilo"], ensure_ascii=False)))
        dato = "".join(f'<Data name="{k}"><value>{escape(v)}</value></Data>' for k, v in ext)
        forma = {"Point": "<Point><coordinates>{c}</coordinates></Point>",
                 "LineString": "<LineString><tessellate>1</tessellate><coordinates>{c}</coordinates></LineString>",
                 "Polygon": "<Polygon><tessellate>1</tessellate><outerBoundaryIs><LinearRing><coordinates>{c}</coordinates></LinearRing></outerBoundaryIs></Polygon>"}[geo["type"]]
        desc = descripcion(e)
        return (f'<Placemark><name>{escape(e["nombre"])}</name>{_vista_kml(e["vista"])}'
                f'{("<description>" + _cdata(desc) + "</description>") if desc else ""}<styleUrl>#{sid}</styleUrl>'
                f'<ExtendedData>{dato}</ExtendedData>{forma.format(c=_coords(geo))}</Placemark>')

    def carpeta(cid: int) -> str:
        c = filas_c[cid]
        hijos = [(h["orden"], 0, h["id"], "c") for h in filas_c.values() if h["padre_id"] == cid]
        hijos += [(e["orden"], 1, e["id"], "e") for e in filas_e if e["carpeta_id"] == cid]
        cuerpo = []
        for _, _, ident, tipo in sorted(hijos):
            cuerpo.append(carpeta(ident) if tipo == "c" else marca(next(e for e in filas_e if e["id"] == ident)))
        return f'<Folder><name>{escape(c["nombre"])}</name>{"".join(cuerpo)}</Folder>'

    raiz = filas_c[int(carpeta_id)]
    cuerpo = carpeta(int(carpeta_id))
    kml = ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f'<name>{escape(raiz["nombre"])}</name>{"".join(estilos.values())}{cuerpo}</Document></kml>')
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml.encode("utf-8"))
        for clave, ic in iconos.items():
            z.writestr(f"files/{clave}.png", lugares_iconos.icono_png(ic))
        for aid, nombre in usados_adj.items():
            z.writestr(f"files/{nombre}", bytes(adjuntos[aid]["datos"]))
    return {"nombre": raiz["nombre"], "tipo": "kmz", "datos": base64.b64encode(salida.getvalue()).decode("ascii"),
            "resumen": {"carpetas": len(filas_c), "lugares": len(filas_e)}}


# --------------------------------------------------------------------------- importar

def _sin_espacios(raiz: Any) -> None:
    """KML 2.0 / 2.1 / 2.2 and files without namespace read the same: every tag keeps only its local name."""
    for e in raiz.iter():
        if isinstance(e.tag, str):
            e.tag = etree.QName(e).localname


def _hijo(e: Any, nombre: str) -> Any:
    return e.find(f"{NS}{nombre}")


def _texto(e: Any, nombre: str) -> str:
    h = _hijo(e, nombre)
    return (h.text or "").strip() if h is not None and h.text else ""


def _lista_coords(texto: str | None) -> list[list[float]]:
    puntos = []
    for trozo in (texto or "").split():
        partes = trozo.split(",")
        try:
            puntos.append([float(partes[0]), float(partes[1])])
        except (ValueError, IndexError):
            continue
    return puntos


def _estilos_del_documento(raiz: Any) -> dict[str, dict[str, Any]]:
    """{style id: estilo del visor} from the <Style> / <StyleMap> of the file."""
    crudos: dict[str, Any] = {}
    for s in raiz.iter(f"{NS}Style"):
        if s.get("id"):
            crudos[s.get("id")] = s
    salida: dict[str, dict[str, Any]] = {}

    def convertir(s: Any) -> dict[str, Any]:
        estilo: dict[str, Any] = {}
        ic = _hijo(s, "IconStyle")
        if ic is not None:
            href = _texto(_hijo(ic, "Icon"), "href") if _hijo(ic, "Icon") is not None else ""
            base = lugares_iconos.desde_href(href) or dict(lugares_iconos.ICONO_POR_DEFECTO)
            try:
                base["escala"] = float(_texto(ic, "scale") or base["escala"])
            except ValueError:
                pass
            col = _de_kml_color(_texto(ic, "color"))
            if col and not href.lower().startswith(("http", "files/")):
                base["color"] = col[0]
            estilo["icono"] = base
        lb = _hijo(s, "LabelStyle")
        if lb is not None:
            col = _de_kml_color(_texto(lb, "color")) or ("#ffffff", 1.0)
            try:
                esc = float(_texto(lb, "scale") or 1)
            except ValueError:
                esc = 1.0
            estilo["etiqueta"] = {"color": col[0], "escala": esc or 1.0, "visible": esc > 0}
        ln = _hijo(s, "LineStyle")
        if ln is not None:
            col = _de_kml_color(_texto(ln, "color")) or ("#ffe600", 1.0)
            try:
                ancho = float(_texto(ln, "width") or 3)
            except ValueError:
                ancho = 3.0
            estilo["linea"] = {"color": col[0], "opacidad": col[1], "grosor": ancho}
        pl = _hijo(s, "PolyStyle")
        if pl is not None:
            col = _de_kml_color(_texto(pl, "color")) or ("#ffe600", 0.3)
            estilo["relleno"] = {"color": col[0], "opacidad": col[1], "activo": _texto(pl, "fill") != "0"}
        return estilo

    for k, s in crudos.items():
        salida[k] = convertir(s)
    for m in raiz.iter(f"{NS}StyleMap"):                 # the normal state of a style map
        for par in m.findall(f"{NS}Pair"):
            if _texto(par, "key") == "normal":
                ref = _texto(par, "styleUrl").lstrip("#")
                if ref in salida and m.get("id"):
                    salida[m.get("id")] = salida[ref]
                elif _hijo(par, "Style") is not None and m.get("id"):
                    salida[m.get("id")] = convertir(_hijo(par, "Style"))
    return salida


def _vista(e: Any) -> dict[str, Any] | None:
    look = _hijo(e, "LookAt")
    if look is None:
        return None
    try:
        rango = float(_texto(look, "range") or RANGO_ZOOM0 / 2 ** 17)
        return {"lat": float(_texto(look, "latitude")), "lon": float(_texto(look, "longitude")), "zoom": math.log2(RANGO_ZOOM0 / max(rango, 1))}
    except (ValueError, ZeroDivisionError):
        return None


def _datos_extendidos(pm: Any) -> dict[str, str]:
    salida = {}
    for d in pm.iter(f"{NS}Data"):
        v = d.find(f"{NS}value")
        if d.get("name") and v is not None and v.text:
            salida[d.get("name")] = v.text
    return salida


def _geometria(pm: Any) -> tuple[str, dict[str, Any]] | None:
    for g in pm.iter():
        etiqueta = etree.QName(g).localname if isinstance(g.tag, str) else ""
        if etiqueta == "Point":
            p = _lista_coords(_texto(g, "coordinates"))
            if p:
                return "marca", {"type": "Point", "coordinates": p[0]}
        elif etiqueta == "LineString":
            p = _lista_coords(_texto(g, "coordinates"))
            if len(p) >= 2:
                return "ruta", {"type": "LineString", "coordinates": p}
        elif etiqueta == "Polygon":
            ext = g.find("outerBoundaryIs/LinearRing/coordinates")
            p = _lista_coords(ext.text if ext is not None else "")
            if len(p) >= 3:
                return "poligono", {"type": "Polygon", "coordinates": [p]}
    return None


def importar(con: Any, actor: dict[str, Any], *, datos: str, nombre: str = "", carpeta_id: int | None = None) -> dict[str, Any]:
    """Imports a .kmz / .kml (base64) into a new folder inside `carpeta_id` (or at the root of the actor's folders)."""
    try:
        crudo = base64.b64decode(str(datos or ""), validate=True)
    except (ValueError, TypeError):
        raise DatosInvalidos({"archivo": "El archivo no se pudo leer"}) from None
    if not crudo or len(crudo) > MAX_ARCHIVO:
        raise DatosInvalidos({"archivo": f"El archivo debe pesar hasta {MAX_ARCHIVO // (1024 * 1024)} MB"})
    imagenes: dict[str, bytes] = {}
    if crudo[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(crudo)) as z:
                kmls = [n for n in z.namelist() if n.lower().endswith(".kml")]
                if not kmls:
                    raise DatosInvalidos({"archivo": "El KMZ no trae ningún KML"})
                kml = z.read("doc.kml" if "doc.kml" in kmls else kmls[0])
                for n in z.namelist():
                    if n.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")) and z.getinfo(n).file_size <= lugares.MAX_ADJUNTO:
                        imagenes[n.replace("\\", "/")] = z.read(n)
        except zipfile.BadZipFile:
            raise DatosInvalidos({"archivo": "El KMZ está dañado"}) from None
    else:
        kml = crudo
    try:
        raiz = etree.fromstring(kml, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=False))
    except etree.XMLSyntaxError:
        raise DatosInvalidos({"archivo": "El KML no es válido"}) from None
    _sin_espacios(raiz)
    estilos = _estilos_del_documento(raiz)
    documento = raiz.find(".//Document")
    contenedor = documento if documento is not None else raiz
    hijos = [h for h in contenedor if isinstance(h.tag, str) and h.tag in ("Folder", "Placemark", "Document")]
    if len(hijos) == 1 and hijos[0].tag in ("Folder", "Document") and _texto(hijos[0], "name") == _texto(contenedor, "name"):
        contenedor = hijos[0]                                              # our own export: Document "X" > Folder "X" is one folder
    nombre_raiz = lugares._texto(_texto(contenedor, "name") or nombre.rsplit(".", 1)[0] or "Importado", lugares.MAX_NOMBRE) or "Importado"
    cuenta = {"carpetas": 0, "lugares": 0, "omitidos": 0}
    omitidos: list[str] = []

    def crear_carpeta(nombre_: str, padre: int | None) -> int:
        cuenta["carpetas"] += 1
        if cuenta["carpetas"] > MAX_CARPETAS:
            raise DatosInvalidos({"archivo": f"Demasiadas carpetas (máximo {MAX_CARPETAS})"})
        return lugares.guardar_carpeta(con, actor, nombre=nombre_ or "Carpeta", padre_id=padre)["id"]

    def procesar(nodo: Any, padre: int) -> None:
        for h in nodo:
            if not isinstance(h.tag, str):
                continue
            etiqueta = etree.QName(h).localname
            if etiqueta in ("Folder", "Document"):
                procesar(h, crear_carpeta(lugares._texto(_texto(h, "name"), lugares.MAX_NOMBRE) or "Carpeta", padre))
            elif etiqueta == "Placemark":
                g = _geometria(h)
                if g is None:
                    cuenta["omitidos"] += 1
                    omitidos.append(_texto(h, "name") or "(sin nombre)")
                    continue
                if cuenta["lugares"] >= MAX_ELEMENTOS:
                    raise DatosInvalidos({"archivo": f"Demasiados lugares (máximo {MAX_ELEMENTOS})"})
                tipo, geo = g
                ext = _datos_extendidos(h)
                if ext.get("ideay_tipo") in lugares.TIPOS and (ext["ideay_tipo"] in lugares.PUNTUALES) == (tipo == "marca") \
                        and (ext["ideay_tipo"] in lugares.LINEALES) == (tipo == "ruta"):
                    tipo = ext["ideay_tipo"]
                estilo = dict(estilos.get(_texto(h, "styleUrl").lstrip("#")) or {})
                for clave in ("ideay_estilo", "ideay_icono"):          # our own export: exact style
                    try:
                        valor = json.loads(ext[clave]) if clave in ext else None
                    except ValueError:
                        valor = None
                    if clave == "ideay_estilo" and isinstance(valor, dict):
                        estilo = valor
                    elif clave == "ideay_icono" and isinstance(valor, dict):
                        estilo["icono"] = valor
                try:
                    propiedades = json.loads(ext["ideay_propiedades"]) if "ideay_propiedades" in ext else {}
                except ValueError:
                    propiedades = {}
                desc, nuevas = _texto(h, "description"), []
                if desc:
                    def img(m: re.Match) -> str:
                        ref = (m.group(1) or "").replace("\\", "/")
                        if ref in imagenes and len(nuevas) < lugares.MAX_ADJUNTOS:
                            nuevas.append({"ref": f"i{len(nuevas)}", "nombre": ref.rsplit("/", 1)[-1], "datos": base64.b64encode(imagenes[ref]).decode("ascii")})
                            return f'<img data-nuevo="i{len(nuevas) - 1}">'
                        return ""
                    desc = re.sub(r"<img\b[^>]*?\bsrc=[\"']([^\"']+)[\"'][^>]*>", img, desc, flags=re.I)
                lugares.guardar_lugar(con, actor, carpeta_id=padre, tipo=tipo, nombre=_texto(h, "name") or "(sin nombre)", geom=geo,
                                      descripcion_html=desc, estilo=estilo, vista=_vista(h),
                                      propiedades=propiedades if isinstance(propiedades, dict) else {}, imagenes=nuevas)
                cuenta["lugares"] += 1

    with con.transaction():                              # all or nothing
        raiz_id = crear_carpeta(nombre_raiz, carpeta_id)
        procesar(contenedor, raiz_id)
    return {**lugares.arbol(con, actor), "carpeta_id": raiz_id, "importados": cuenta, "omitidos": omitidos[:50]}
