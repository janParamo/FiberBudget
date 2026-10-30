"""Incorporar a la red: meter en el archivo RED DE IDEAY.kmz lo que se aplicó al importar KMZ, para que esté en sus carpetas de la red y no en una capa aparte.

Al aplicar una importación (importar_kmz.py) el archivo KMZ no se toca: lo nuevo sale en la capa «Importados (aplicados)», y lo modificado o eliminado en «Cambios al KMZ»
(`kmz_cambios`). `incorporar` (solo administradores) arma un KMZ nuevo con todo eso ya dentro:
  - lo nuevo se agrega como un Placemark en su carpeta (con el estilo de un hermano suyo; si la carpeta no existe se crea);
  - lo renombrado / movido / con otro trazo se corrige en su Placemark, y lo eliminado se quita;
  - el resto del archivo (estilos, íconos, fotos, el orden) queda igual.
Antes de instalarlo se comprueba que el archivo nuevo tiene exactamente los elementos esperados; el anterior se guarda en `anteriores/` (como al subir un KMZ). Después las importaciones
quedan marcadas como incorporadas y los cambios del KMZ ya no hacen falta: la red es el archivo.
"""
import io
import logging
import zipfile
from typing import Any

from lxml import etree

from visor_rutas import kmz_capas
from visor_rutas.redes import actualizar_red, importar_kmz, repositorio, usuarios
from visor_rutas.redes.db import DatosInvalidos, SinPermiso

log = logging.getLogger(__name__)
_local = kmz_capas._local


def _exigir_admin(actor: dict[str, Any]) -> None:
    if not usuarios.es_admin(actor):
        raise SinPermiso("Solo un administrador puede incorporar los cambios al archivo de la red")


def _vigentes(con: Any) -> tuple[list[dict[str, Any]], list[Any], list[Any]]:
    """(elements the applied imports added, changes of the KMZ to apply, imports not yet incorporated)."""
    nuevos = importar_kmz.elementos_importados(con)
    cambios = con.execute("SELECT id, clave, carpeta, accion, antes, despues, importacion_id FROM redes.kmz_cambios WHERE borrado_en IS NULL ORDER BY id").fetchall()
    importaciones = con.execute("SELECT id, archivo FROM redes.kmz_importaciones WHERE estado = 'aplicada' AND borrado_en IS NULL AND incorporada_en IS NULL ORDER BY id").fetchall()
    return nuevos, cambios, importaciones


def previa(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """What «Incorporar a la red» would put in the file (nothing is written)."""
    _exigir_admin(actor)
    nuevos, cambios, importaciones = _vigentes(con)
    return {"agregados": len(nuevos), "modificados": sum(c["accion"] == "editar" for c in cambios), "eliminados": sum(c["accion"] == "borrar" for c in cambios),
            "manuales": sum(c["importacion_id"] is None for c in cambios), "importaciones": [{"id": i["id"], "archivo": i["archivo"]} for i in importaciones]}


# --------------------------------------------------------------------------- el KML

def _hijo(e: Any, nombre: str) -> Any:
    return next((h for h in e if isinstance(h.tag, str) and _local(h) == nombre), None)


def _indexar(documento: Any) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """({folder path: first folder with it}, {key of kmz_cambios: [placemarks]}), built as kmz_capas / importar_kmz name folders and key elements."""
    carpetas: dict[str, Any] = {}
    placemarks: dict[str, list[Any]] = {}

    def recorrer(nodo: Any, ruta: list[str]) -> None:
        nombre = kmz_capas._texto(nodo, "name") or ("(sin nombre)" if _local(nodo) == "Folder" else "Documento")
        ruta_nodo = ruta + [nombre]
        texto = "/".join(ruta_nodo)
        carpetas.setdefault(texto, nodo)
        for hijo in nodo:
            etiqueta = _local(hijo) if isinstance(hijo.tag, str) else ""
            if etiqueta in ("Folder", "Document"):
                recorrer(hijo, ruta_nodo)
            elif etiqueta == "Placemark":
                geo = importar_kmz._simple(kmz_capas._geometria(hijo))
                if geo is None:
                    continue
                ll = importar_kmz.primero(geo)
                clave = importar_kmz.clave_kmz(texto, kmz_capas._texto(hijo, "name") or nombre, ll[0] if ll else None, ll[1] if ll else None)
                placemarks.setdefault(clave, []).append(hijo)

    recorrer(documento, [])
    return carpetas, placemarks


def _texto_hijo(padre: Any, nombre: str, valor: str, ns: str) -> Any:
    h = _hijo(padre, nombre)
    if h is None:
        h = etree.SubElement(padre, f"{{{ns}}}{nombre}")
    h.text = valor
    return h


def _coordenadas(coords: list[list[float]]) -> str:
    return " ".join(f"{c[0]:.8f},{c[1]:.8f},0" for c in coords)


def _coordenadas_de(pm: Any, geometria: str) -> Any:
    return next((e for e in pm.iter() if isinstance(e.tag, str) and _local(e) == "coordinates" and _local(e.getparent()) == geometria), None)


def _editar(pm: Any, despues: dict[str, Any], ns: str) -> bool:
    """Applies a change of kmz_cambios to a placemark (name, place of a point, trace of a line, description)."""
    if despues.get("nombre"):
        _texto_hijo(pm, "name", despues["nombre"], ns)
    if despues.get("descripcion") is not None:
        _texto_hijo(pm, "description", despues["descripcion"], ns)
    if despues.get("lat") is not None:
        c = _coordenadas_de(pm, "Point")
        if c is not None:
            partes = (c.text or "").strip().split(",")
            c.text = f"{despues['lon']:.8f},{despues['lat']:.8f},{partes[2] if len(partes) > 2 else '0'}"
    if despues.get("coords"):
        c = _coordenadas_de(pm, "LineString")
        if c is not None:
            c.text = _coordenadas(despues["coords"])
    return True


def _geometria_kml(padre: Any, geo: dict[str, Any], ns: str) -> bool:
    """Writes the KML geometry of a GeoJSON (Point, LineString, MultiLineString, Polygon) inside a placemark."""
    def sub(p: Any, nombre: str) -> Any:
        return etree.SubElement(p, f"{{{ns}}}{nombre}")

    t = geo.get("type")
    if t == "Point":
        sub(sub(padre, "Point"), "coordinates").text = _coordenadas([geo["coordinates"]])
    elif t == "LineString":
        linea = sub(padre, "LineString")
        sub(linea, "tessellate").text = "1"
        sub(linea, "coordinates").text = _coordenadas(geo["coordinates"])
    elif t == "MultiLineString":
        multi = sub(padre, "MultiGeometry")
        for partes in geo["coordinates"]:
            linea = sub(multi, "LineString")
            sub(linea, "tessellate").text = "1"
            sub(linea, "coordinates").text = _coordenadas(partes)
    elif t == "Polygon":
        poligono = sub(padre, "Polygon")
        for i, anillo in enumerate(geo["coordinates"]):
            sub(sub(sub(poligono, "outerBoundaryIs" if i == 0 else "innerBoundaryIs"), "LinearRing"), "coordinates").text = _coordenadas(anillo)
    else:
        return False
    return True


def _carpeta_destino(documento: Any, carpetas: dict[str, Any], ruta: str, ns: str) -> Any:
    """The folder of that path; the nearest one that exists is used and the rest is created. A path that starts with another document name goes under this one."""
    if ruta in carpetas:
        return carpetas[ruta]
    partes = ruta.split("/")
    nombre_doc = kmz_capas._texto(documento, "name") or "Documento"
    if partes[0] != nombre_doc:
        partes = [nombre_doc] + partes[1:]
    actual, texto = documento, nombre_doc
    for p in partes[1:]:
        texto = f"{texto}/{p}"
        if texto not in carpetas:
            nueva = etree.SubElement(actual, f"{{{ns}}}Folder")
            etree.SubElement(nueva, f"{{{ns}}}name").text = p
            carpetas[texto] = nueva
        actual = carpetas[texto]
    return actual


def _estilo_hermano(carpeta: Any, tipo: str) -> str | None:
    """The style of a placemark of the folder with the same kind of geometry (point / line), for the new ones."""
    for pm in carpeta:
        if isinstance(pm.tag, str) and _local(pm) == "Placemark":
            geo = importar_kmz._simple(kmz_capas._geometria(pm))
            u = _hijo(pm, "styleUrl")
            if geo is not None and importar_kmz._tipo(geo) == tipo and u is not None and u.text:
                return u.text
    return None


def construir(crudo: bytes, nuevos: list[dict[str, Any]], cambios: list[Any]) -> tuple[bytes, dict[str, int]]:
    """The KMZ `crudo` with the new elements added and the changes applied. Returns (new KMZ, {agregados, modificados, eliminados, no_encontrados})."""
    with zipfile.ZipFile(io.BytesIO(crudo)) as z:
        entradas = z.infolist()
        nombre_kml = next((i.filename for i in entradas if i.filename.lower() == "doc.kml"), None) or next((i.filename for i in entradas if i.filename.lower().endswith(".kml")), None)
        if nombre_kml is None:
            raise DatosInvalidos({"archivo": "El KMZ vigente no trae ningún KML"})
        parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False, no_network=True)
        raiz = etree.fromstring(z.read(nombre_kml), parser)
        datos = {i.filename: z.read(i.filename) for i in entradas if i.filename != nombre_kml}
    documento = next((e for e in raiz.iter() if _local(e) == "Document"), raiz)
    ns = etree.QName(documento).namespace or "http://www.opengis.net/kml/2.2"
    carpetas, placemarks = _indexar(documento)
    cuenta = {"agregados": 0, "modificados": 0, "eliminados": 0, "no_encontrados": 0}
    for c in cambios:                                                        # 1) the changes of kmz_cambios
        encontrados = placemarks.get(c["clave"]) or []
        if not encontrados:
            cuenta["no_encontrados"] += 1
            continue
        pm = encontrados[0]
        if c["accion"] == "borrar":
            pm.getparent().remove(pm)
            cuenta["eliminados"] += 1
        elif c["despues"]:
            _editar(pm, c["despues"], ns)
            cuenta["modificados"] += 1
    for e in nuevos:                                                         # 2) what the imports added, in its own folder
        carpeta = _carpeta_destino(documento, carpetas, e["carpeta"], ns)
        pm = etree.Element(f"{{{ns}}}Placemark")
        etree.SubElement(pm, f"{{{ns}}}name").text = e["nombre"] or ""
        if e.get("desc"):
            etree.SubElement(pm, f"{{{ns}}}description").text = e["desc"]
        estilo = _estilo_hermano(carpeta, "punto" if (e["geom"] or {}).get("type") == "Point" else "linea")
        if estilo:
            etree.SubElement(pm, f"{{{ns}}}styleUrl").text = estilo
        if not _geometria_kml(pm, e["geom"] or {}, ns):
            cuenta["no_encontrados"] += 1
            continue
        carpeta.append(pm)
        cuenta["agregados"] += 1
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(nombre_kml, etree.tostring(raiz, xml_declaration=True, encoding="UTF-8"))
        for nombre, contenido in datos.items():
            z.writestr(nombre, contenido)
    return salida.getvalue(), cuenta


def incorporar(con: Any, actor: dict[str, Any]) -> dict[str, Any]:
    """Puts everything the applied imports added and the changes of the KMZ into the file of the network (the old file is kept in `anteriores/`)."""
    _exigir_admin(actor)
    nuevos, cambios, importaciones = _vigentes(con)
    if not (nuevos or cambios or importaciones):
        raise DatosInvalidos({"red": "No hay nada que incorporar: la red ya es el archivo"})
    try:
        actual = kmz_capas.ruta_kmz()
    except kmz_capas.KmzNoEncontrado as exc:
        raise DatosInvalidos({"red": str(exc)}) from None
    crudo = actual.read_bytes()
    esperados = len(importar_kmz.leer(crudo)) + len(nuevos) - sum(c["accion"] == "borrar" for c in cambios)
    nuevo, cuenta = construir(crudo, nuevos, cambios)
    if cuenta["no_encontrados"]:
        raise DatosInvalidos({"red": f"{cuenta['no_encontrados']} cambio(s) no se encontraron en el archivo vigente (cambió después de aplicarlos); no se incorporó nada. "
                                     "Revise los cambios del KMZ."})
    obtenidos = len(importar_kmz.leer(nuevo))
    if obtenidos != esperados:
        raise DatosInvalidos({"red": f"El archivo nuevo traería {obtenidos} elementos y se esperaban {esperados}; no se incorporó nada"})
    with con.transaction():
        for c in cambios:
            con.execute("UPDATE redes.kmz_cambios SET borrado_en = now(), actualizado_por = %s, version = version + 1 WHERE id = %s", (actor["id"], c["id"]))
            repositorio.registrar(con, actor["id"], "kmz_cambio", c["id"], "eliminar", {"incorporado": [False, True]})
        for i in importaciones:
            con.execute("UPDATE redes.kmz_importaciones SET incorporada_en = now() WHERE id = %s", (i["id"],))
            repositorio.registrar(con, actor["id"], "kmz_importacion", i["id"], "editar", {"incorporada": [False, True]})
        instalado = actualizar_red.instalar_kmz(nuevo, actual.name, actor)             # inside the transaction: if the file cannot be written nothing is marked
    log.info("KMZ: incorporated into %s: %s", actual.name, cuenta)
    return {**cuenta, "importaciones": len(importaciones), "archivo": instalado["archivo"], "elementos": instalado["elementos"], "anterior_en": instalado["anterior_en"]}
