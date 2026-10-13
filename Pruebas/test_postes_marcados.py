"""New poles marked on the viewer map as already standing (click on a grey pole).

A marked pole is charged as an existing pole instead of a new 8 m pole, in the approximate
budget and in "Generar presupuesto". POST /presupuesto (n8n) never gets marks and answers
exactly as before.
"""
from fastapi.testclient import TestClient

from presupuesto import count_new_poles_by_gaps, match_marked_poles, new_pole_positions_by_gaps
from test_visor_presupuesto import BODY, HEADERS, _campos, entorno  # noqa: F401  (fixture)


def test_positions_are_the_counted_new_poles():
    for distance, existing in [(100, []), (150, [30]), (400, [0, 130]), (61, []), (1850, [50.0])]:
        posiciones = new_pole_positions_by_gaps(distance, 50, existing, 60)
        assert len(posiciones) == count_new_poles_by_gaps(distance, 50, existing, 0, 60)
    assert count_new_poles_by_gaps(100, 50, [], 2) == 4                     # corner poles still added


def test_marks_match_new_pole_positions_once():
    nuevas = [100.0, 150.0, 200.0]
    assert match_marked_poles([150.0, 100.2], nuevas) == ([100.0, 150.0], [])
    assert match_marked_poles([150.0, 150.0], nuevas) == ([150.0], [])      # same pole sent twice
    assert match_marked_poles([125.0, 999.0], nuevas) == ([], [125.0, 999.0])
    assert match_marked_poles([], nuevas) == ([], [])


def _cantidades(respuesta, rules):
    q = respuesta["quantities"]
    return q[rules["poles"]["new_pole_row_label"]], q[rules["poles"]["existing_pole_row_label"]]


def test_marked_poles_are_charged_as_existing(entorno):
    main, pv, _, _ = entorno
    from visor_rutas import calculo
    rules = main.load_rules(main.settings.rules_path)
    cache = pv.CacheRutas()
    with calculo.usando_rutas(cache):
        ruta = calculo.calcular_ruta(12.1364, -86.2514)
    metros = ruta["postes_nuevos"]["metros"]
    assert len(metros) == len(ruta["postes_nuevos"]["posiciones"]) >= 3

    base = pv.generar(pv.construir_solicitud(_campos()), cache)
    marcado = pv.generar(pv.construir_solicitud(_campos()), cache, postes_existentes_m=metros[:2])
    nuevos, existentes = _cantidades(base, rules)
    assert _cantidades(marcado, rules) == (nuevos - 2, existentes + 2)
    assert marcado["budget"]["new_poles_8m"] == nuevos - 2
    assert marcado["budget"]["existing_poles"] == base["budget"]["existing_poles"] + 2
    assert marcado["budget"]["required_poles"] == base["budget"]["required_poles"]   # same hardware
    assert marcado["budget"]["new_poles_marked_existing_m"] == metros[:2]
    assert pv.resultado_para_visor(marcado)["postes_marcados"] == 2
    assert any("2 poste(s) nuevo(s) marcado(s)" in a for a in marcado["warnings"])
    assert "new_poles_marked_existing_m" not in base["budget"]

    # A mark that is not a new pole of this route is not applied, and says so.
    otro = pv.generar(pv.construir_solicitud(_campos()), cache, postes_existentes_m=[metros[0] + 7.0])
    assert _cantidades(otro, rules) == (nuevos, existentes)
    assert any("no coinciden con esta ruta" in a for a in otro["warnings"])


def test_estimate_and_form_carry_the_marks(entorno):
    _, pv, _, _ = entorno
    from visor_rutas import calculo, ventana_web
    api = ventana_web.Api()
    with calculo.usando_rutas(api._rutas):
        ruta = calculo.calcular_ruta(12.1364, -86.2514)
    metros = ruta["postes_nuevos"]["metros"]

    est = api.estimar_presupuesto(12.1364, -86.2514, ruta["ruta"]["metraje_final_m"], [metros[0]])
    assert est["ok"] and est["supuestos"]["postes_marcados"] == 1
    assert est["resultado"]["postes_marcados"] == 1

    form = api.generar_presupuesto({**_campos(), pv.CAMPO_POSTES_MARCADOS: [metros[0], "x", -3, None]})
    assert form["ok"] and form["resultado"]["postes_marcados"] == 1
    assert pv.postes_marcados(None) is None and pv.postes_marcados([]) is None
    assert pv.postes_marcados([1, "2.5", float("nan")]) == [1.0, 2.5]


def test_api_presupuesto_is_unchanged(entorno):
    main, _, _, _ = entorno
    respuesta = TestClient(main.app).post("/presupuesto", json=BODY, headers=HEADERS).json()
    assert "new_poles_marked_existing_m" not in respuesta["budget"]
    assert not any("marcado" in a for a in respuesta["warnings"])
