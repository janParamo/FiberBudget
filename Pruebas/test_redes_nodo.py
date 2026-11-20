"""El nodo como lugar físico (visor_rutas/redes/nodo.py): sus ODF con sus puertos, sus OLT con sus hilos y los enlaces entre ellos y los hilos de los cables hacia las mufas."""
import pytest

from redes_base import base_redes, con_redes  # noqa: F401  (fixtures)
from test_redes_lienzo import zona  # noqa: F401  (fixture)
from visor_rutas.redes import nodo, usuarios
from visor_rutas.redes.db import DatosInvalidos, NoEncontrado, SinPermiso


def _por_nombre(lista, nombre):
    return next(x for x in lista if x["nombre"] == nombre)


def test_a_node_has_its_odfs_and_olts_and_the_ports_are_free_or_used(zona):
    con, admin, p, ids = zona
    r = nodo.leer(con, admin, nodo_id=ids["n"])
    assert r["nodo"]["nombre"] == "Nodo Jalapa" and r["odfs"] == [] and r["olts"] == [] and [c["nombre"] for c in r["cables"]] == ["Troncal"]
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], nombre="ODF A", puertos=24)
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], puertos=48)                                        # the name by default counts the ones there are
    assert [(o["nombre"], o["puertos"], o["libres"]) for o in r["odfs"]] == [("ODF 2", 48, 48), ("ODF A", 24, 24)]
    r = nodo.guardar_olt(con, admin, nodo_id=ids["n"], nombre="OLT Granada", puertos=16)
    odf, olt, troncal = _por_nombre(r["odfs"], "ODF A"), r["olts"][0], r["cables"][0]
    # port 1 of OLT Granada goes to port 5 of ODF A and to fibre 3 of the Troncal (which goes to MF Uno)
    hilo3 = next(f for f in troncal["fibras"] if f["numero"] == 3)
    r = nodo.guardar_enlace(con, admin, nodo_id=ids["n"], olt_id=olt["id"], olt_puerto=1, odf_id=odf["id"], odf_puerto=5, hilo_id=hilo3["id"])
    e = r["enlaces"][0]
    assert (e["olt_nombre"], e["olt_puerto"], e["odf_nombre"], e["odf_puerto"], e["hilo_numero"], e["cable_nombre"], e["destino_nombre"]) == ("OLT Granada", 1, "ODF A", 5, 3, "Troncal", "MF Uno")
    odf, olt = _por_nombre(r["odfs"], "ODF A"), r["olts"][0]
    assert (odf["ocupados"], odf["libres"], olt["ocupados"], olt["libres"]) == (1, 23, 1, 15)
    # the same OLT port set again changes the link (it does not make a second one); an ODF can be on several OLTs and an OLT on several ODFs
    odf2 = _por_nombre(r["odfs"], "ODF 2")
    r = nodo.guardar_enlace(con, admin, nodo_id=ids["n"], olt_id=olt["id"], olt_puerto=1, odf_id=odf2["id"], odf_puerto=1, hilo_id=hilo3["id"])
    assert len(r["enlaces"]) == 1 and r["enlaces"][0]["odf_nombre"] == "ODF 2"
    r = nodo.guardar_olt(con, admin, nodo_id=ids["n"], nombre="OLT Masaya", puertos=8)
    masaya = _por_nombre(r["olts"], "OLT Masaya")
    r = nodo.guardar_enlace(con, admin, nodo_id=ids["n"], olt_id=masaya["id"], olt_puerto=2, odf_id=odf2["id"], odf_puerto=2)             # ODF 2 on two OLTs
    assert sorted((e["olt_nombre"], e["odf_puerto"]) for e in r["enlaces"] if e["odf_nombre"] == "ODF 2") == [("OLT Granada", 1), ("OLT Masaya", 2)]
    r = nodo.guardar_enlace(con, admin, nodo_id=ids["n"], olt_id=olt["id"], olt_puerto=1, quitar=True)
    assert [e["olt_nombre"] for e in r["enlaces"]] == ["OLT Masaya"]


def test_a_port_or_a_fibre_takes_only_one_link_and_what_does_not_exist_is_refused(zona):
    con, admin, p, ids = zona
    nodo.guardar_odf(con, admin, nodo_id=ids["n"], nombre="ODF A", puertos=12)
    r = nodo.guardar_olt(con, admin, nodo_id=ids["n"], nombre="OLT 1", puertos=4)
    r = nodo.guardar_olt(con, admin, nodo_id=ids["n"], nombre="OLT 2", puertos=4)
    odf, o1, o2 = r["odfs"][0], _por_nombre(r["olts"], "OLT 1"), _por_nombre(r["olts"], "OLT 2")
    hilo = r["cables"][0]["fibras"][0]
    nodo.guardar_enlace(con, admin, nodo_id=ids["n"], olt_id=o1["id"], olt_puerto=1, odf_id=odf["id"], odf_puerto=1, hilo_id=hilo["id"])
    with pytest.raises(DatosInvalidos) as e:
        nodo.guardar_enlace(con, admin, nodo_id=ids["n"], olt_id=o2["id"], olt_puerto=1, odf_id=odf["id"], odf_puerto=1)          # the same ODF port
    assert "ya está conectado a OLT 1" in e.value.errores["ODF"]
    with pytest.raises(DatosInvalidos):
        nodo.guardar_enlace(con, admin, nodo_id=ids["n"], olt_id=o2["id"], olt_puerto=1, hilo_id=hilo["id"])                        # the same fibre
    with pytest.raises(DatosInvalidos):
        nodo.guardar_enlace(con, admin, nodo_id=ids["n"], olt_id=o2["id"], olt_puerto=9, odf_id=odf["id"], odf_puerto=2)            # the OLT has 4
    with pytest.raises(DatosInvalidos):
        nodo.guardar_enlace(con, admin, nodo_id=ids["n"], olt_id=o2["id"], olt_puerto=1, odf_id=odf["id"], odf_puerto=13)           # the ODF has 12
    with pytest.raises(DatosInvalidos):
        nodo.guardar_enlace(con, admin, nodo_id=ids["n"], olt_id=o2["id"], olt_puerto=1)                                              # to nothing
    with pytest.raises(DatosInvalidos):
        nodo.guardar_odf(con, admin, nodo_id=ids["n"], nombre="odf a", puertos=24)                                                    # the name is not repeated
    with pytest.raises(DatosInvalidos):
        nodo.guardar_odf(con, admin, nodo_id=ids["n"], puertos=0)
    fibra_de_mufa = DatosInvalidos
    otro_cable = con.execute("SELECT h.id FROM redes.hilos h JOIN redes.cables c ON c.id = h.cable_id WHERE c.nombre = 'Distribución' LIMIT 1").fetchone()["id"]
    with pytest.raises(fibra_de_mufa):
        nodo.guardar_enlace(con, admin, nodo_id=ids["n"], olt_id=o2["id"], olt_puerto=2, hilo_id=otro_cable)                          # a fibre that is not of a cable of the node
    with pytest.raises(NoEncontrado):
        nodo.leer(con, admin, nodo_id=ids["m1"])                                                                                      # a mufa is not a node


def test_resizing_deleting_and_permissions(zona):
    con, admin, p, ids = zona
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], nombre="ODF A", puertos=24)
    r = nodo.guardar_olt(con, admin, nodo_id=ids["n"], nombre="OLT 1", puertos=8)
    odf, olt, hilo = r["odfs"][0], r["olts"][0], r["cables"][0]["fibras"][1]
    nodo.guardar_enlace(con, admin, nodo_id=ids["n"], olt_id=olt["id"], olt_puerto=3, odf_id=odf["id"], odf_puerto=10, hilo_id=hilo["id"])
    with pytest.raises(DatosInvalidos):
        nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], puertos=9)                                                   # port 10 is in use
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], nombre="ODF Principal", puertos=12)
    assert (r["odfs"][0]["nombre"], r["odfs"][0]["puertos"]) == ("ODF Principal", 12)
    # deleting the ODF: the link keeps its fibre and loses the port; deleting the OLT takes its links
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], eliminar=True)
    assert r["odfs"] == [] and len(r["enlaces"]) == 1 and r["enlaces"][0]["odf_id"] is None and r["enlaces"][0]["hilo_numero"] == 2
    r = nodo.guardar_olt(con, admin, nodo_id=ids["n"], olt_id=olt["id"], eliminar=True)
    assert r["olts"] == [] and r["enlaces"] == []
    lector = usuarios.guardar(con, admin, datos={"nombre": "Ana", "rol": "lector", "persona_visor": "ana"})["usuario"]
    with pytest.raises(SinPermiso):
        nodo.guardar_odf(con, lector, nodo_id=ids["n"], nombre="X", puertos=12)


def _v(lat, lon):
    return {"lat": lat, "lon": lon}


def test_the_odfs_and_olts_of_the_visio_are_brought_into_their_node(con_redes):
    """An ODF goes to the node its cable reaches (or through another ODF), else to the nearest node; the ODFs of mufas and clients stay out; the OLT comes from the name of the node."""
    from visor_rutas.redes import proyectos, red
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Red existente – Managua", "codigo": "BASE-MGA"})["proyecto"]
    r = red.guardar(con, admin, proyecto_id=p["id"], cambios={
        "elementos": [{"id": "n", "tipo": "nodo", "subtipo": "nodo", "nombre": "NODO LA MERCED", "lat": 12.1300, "lon": -86.2500},
                      {"id": "o1", "tipo": "odf", "nombre": "ODF A / 48P", "lat": 12.13005, "lon": -86.2500},                  # 6 m from the node, 48 ports in its name
                      {"id": "o2", "tipo": "odf", "nombre": "ODF B", "lat": 12.2000, "lon": -86.2000},                          # far, but its cable reaches the node
                      {"id": "o3", "tipo": "odf", "nombre": "ODF C", "lat": 12.2001, "lon": -86.2001},                          # joined to o2: goes with it
                      {"id": "o4", "tipo": "odf", "nombre": "ODF DE UN CLIENTE", "lat": 12.3000, "lon": -86.1000},              # far, no cable to a node: stays out
                      {"id": "m", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF X", "lat": 12.1310, "lon": -86.2500}],
        "cables": [{"id": "k1", "nombre": "Salida ODF B", "hilos": 24, "origen_id": "o2", "destino_id": "n", "vertices": [_v(12.2000, -86.2000), _v(12.1300, -86.2500)]},
                   {"id": "k2", "nombre": "B a C", "hilos": 12, "origen_id": "o3", "destino_id": "o2", "vertices": [_v(12.2001, -86.2001), _v(12.2000, -86.2000)]},
                   {"id": "k3", "nombre": "ODF A a mufa", "hilos": 12, "origen_id": "o1", "destino_id": "m", "vertices": [_v(12.13005, -86.2500), _v(12.1310, -86.2500)]}]})
    ids = r["ids"]
    lector = usuarios.guardar(con, admin, datos={"nombre": "Ana", "rol": "lector", "persona_visor": "ana"})["usuario"]
    with pytest.raises(SinPermiso):
        nodo.convertir_visio(con, lector)
    simulado = nodo.convertir_visio(con, admin, simular=True)
    assert (simulado["odfs_nuevos"], simulado["olts_nuevas"], simulado["simulado"]) == (3, 1, True) and [o["nombre"] for o in simulado["sin_nodo"]] == ["ODF DE UN CLIENTE"]
    assert nodo.leer(con, admin, nodo_id=ids["n"])["odfs"] == []                                    # simulating writes nothing
    hecho = nodo.convertir_visio(con, admin, simular=False)
    assert (hecho["odfs_nuevos"], hecho["olts_nuevas"]) == (3, 1)
    v = nodo.leer(con, admin, nodo_id=ids["n"])
    odfs = {o["nombre"]: o for o in v["odfs"]}
    assert set(odfs) == {"ODF A / 48P", "ODF B", "ODF C"} and odfs["ODF A / 48P"]["puertos"] == 48 and odfs["ODF A / 48P"]["estimado"] is False
    assert odfs["ODF B"]["puertos"] == 24 and odfs["ODF B"]["estimado"] is True and odfs["ODF B"]["fuente"] == "visio"                    # from its biggest cable
    assert [c["otro"] for c in odfs["ODF A / 48P"]["cables_visio"]] == ["MF X"]                      # its cable to the mufa is still there, shown beside it
    assert [(o["nombre"], o["fuente"], o["estimado"]) for o in v["olts"]] == [("OLT MERCED", "visio", True)]
    # it can be repeated (nothing is made twice), the elements and cables are still there, and a size set by a person is no longer an estimate
    assert nodo.convertir_visio(con, admin, simular=False)["odfs_nuevos"] == 0
    assert con.execute("SELECT count(*) AS n FROM redes.elementos WHERE tipo = 'odf' AND borrado_en IS NULL").fetchone()["n"] == 4
    r2 = nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odfs["ODF B"]["id"], puertos=48)
    assert next(o for o in r2["odfs"] if o["nombre"] == "ODF B")["estimado"] is False


def test_the_ports_of_an_odf_are_read_from_its_name_else_from_its_cables_else_12():
    assert nodo.puertos_del_nombre("ODF 48P IDEAY #3 ARRIBA 1U", []) == (48, False)
    assert nodo.puertos_del_nombre("ODF #3 24H EN RACK DEL OLT", []) == (24, False)
    assert nodo.puertos_del_nombre("NODO CASITA NUEVO ODF PARED 4 PUERTOS", []) == (4, False)
    assert nodo.puertos_del_nombre("ODF NODO IDEAY FUSIONADO / 1-12 H", []) == (12, False)
    assert nodo.puertos_del_nombre("ODF A", [24, 12]) == (24, True) and nodo.puertos_del_nombre("ODF A", [30]) == (48, True) and nodo.puertos_del_nombre("ODF A", []) == (12, True)


def _png(color=(200, 30, 30), lado=40):
    import base64, io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (lado, lado // 2), color).save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode("ascii")


def test_the_layout_of_the_ports_is_editable_and_must_cover_the_ports(zona):
    con, admin, p, ids = zona
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], nombre="ODF A", puertos=32)
    odf = r["odfs"][0]
    assert (odf["columnas"], odf["filas"], odf["disposicion_propia"]) == (12, 3, False)                                  # the automatic one: 12 columns
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], columnas=8, filas=4)
    odf = r["odfs"][0]
    assert (odf["columnas"], odf["filas"], odf["disposicion_propia"]) == (8, 4, True)
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], columnas=4)                                     # only the columns: the rows are worked out
    assert (r["odfs"][0]["columnas"], r["odfs"][0]["filas"]) == (4, 8)
    for columnas, filas in ((4, 7), (4, 9), (3, 3), (0, 200)):                                                              # not enough places, an empty row, too few, out of range
        with pytest.raises(DatosInvalidos):
            nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], columnas=columnas, filas=filas)
    assert (nodo.leer(con, admin, nodo_id=ids["n"])["odfs"][0]["columnas"]) == 4                                           # a refused change leaves it as it was
    # resizing it to a number of ports the layout no longer covers goes back to the automatic layout; one it still covers is kept
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], puertos=30)
    assert (r["odfs"][0]["columnas"], r["odfs"][0]["filas"]) == (4, 8)                                                       # 4 × 8 still fits 30
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], puertos=12)
    assert (r["odfs"][0]["columnas"], r["odfs"][0]["disposicion_propia"]) == (12, False)
    # a new layout together with a new number of ports is checked against the new number
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], puertos=24, columnas=6, filas=4)
    assert (r["odfs"][0]["puertos"], r["odfs"][0]["columnas"], r["odfs"][0]["filas"]) == (24, 6, 4)
    # empty / 0: the automatic one again
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], columnas=0, filas=0)
    assert r["odfs"][0]["disposicion_propia"] is False
    # created with its layout in one go
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], nombre="ODF B", puertos=32, columnas=4, filas=8)
    assert [(o["nombre"], o["columnas"], o["filas"]) for o in r["odfs"] if o["nombre"] == "ODF B"] == [("ODF B", 4, 8)]


def test_the_photo_of_the_real_odf_is_kept_apart_and_can_be_changed_and_taken_off(zona):
    con, admin, p, ids = zona
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], nombre="ODF A", puertos=24)
    odf = r["odfs"][0]
    assert odf["tiene_imagen"] is False and nodo.imagen_odf(con, admin, odf_id=odf["id"]) == {"imagen": None, "version": 0}
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], imagen=_png())
    assert r["odfs"][0]["tiene_imagen"] is True and r["odfs"][0]["imagen_version"] == 1 and "imagen" not in r["odfs"][0]               # the node does not carry the picture
    foto = nodo.imagen_odf(con, admin, odf_id=odf["id"])
    assert foto["imagen"].startswith("data:image/png;base64,") and foto["version"] == 1
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], imagen=_png((10, 10, 200)))
    assert r["odfs"][0]["imagen_version"] == 2 and nodo.imagen_odf(con, admin, odf_id=odf["id"])["imagen"] != foto["imagen"]
    with pytest.raises(DatosInvalidos):
        nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], imagen="data:image/png;base64,AAAA")                         # not an image
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], odf_id=odf["id"], quitar_imagen=True)
    assert r["odfs"][0]["tiene_imagen"] is False and nodo.imagen_odf(con, admin, odf_id=odf["id"])["imagen"] is None
    # created with its photo in one go; a reader sees it but cannot change it
    r = nodo.guardar_odf(con, admin, nodo_id=ids["n"], nombre="ODF B", puertos=12, imagen=_png())
    assert next(o for o in r["odfs"] if o["nombre"] == "ODF B")["tiene_imagen"] is True
    lector = usuarios.guardar(con, admin, datos={"nombre": "Ana", "rol": "lector", "persona_visor": "ana"})["usuario"]
    with pytest.raises(SinPermiso):
        nodo.guardar_odf(con, lector, nodo_id=ids["n"], odf_id=odf["id"], imagen=_png())


def test_the_nearest_mufa_is_offered_and_the_node_is_connected_to_it_with_a_cable(con_redes):
    from visor_rutas.redes import proyectos, red
    con = con_redes
    admin = usuarios.identificar(con, usuario_windows="jgutierrez")
    p = proyectos.guardar(con, admin, datos={"nombre": "Red existente – Granada", "codigo": "BASE-GRA"})["proyecto"]
    ids = red.guardar(con, admin, proyecto_id=p["id"], cambios={"elementos": [
        {"id": "n", "tipo": "nodo", "subtipo": "nodo", "nombre": "NODO GRANADA", "lat": 11.9300, "lon": -85.9560},
        {"id": "m1", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF CERCANA", "lat": 11.9310, "lon": -85.9560},
        {"id": "m2", "tipo": "mufa", "subtipo": "empalme", "nombre": "MF LEJANA", "lat": 11.9500, "lon": -85.9560}]})["ids"]
    v = nodo.leer(con, admin, nodo_id=ids["n"])
    assert v["cables"] == [] and v["mufa_cercana"]["nombre"] == "MF CERCANA" and 100 < v["mufa_cercana"]["distancia_m"] < 120      # nothing connected yet: the nearest mufa
    v = nodo.conectar_mufa(con, admin, nodo_id=ids["n"], mufa_id=ids["m1"], hilos=48)
    assert [(c["nombre"], c["hilos"], c["otro"]["nombre"], len(c["fibras"])) for c in v["cables"]] == [("NODO GRANADA – MF CERCANA", 48, "MF CERCANA", 48)]
    assert v["mufa_cercana"] is None                                                                  # already connected to a mufa: no suggestion
    for malo in (7, 6, "x"):
        with pytest.raises(DatosInvalidos):
            nodo.conectar_mufa(con, admin, nodo_id=ids["n"], mufa_id=ids["m2"], hilos=malo)
