"""Visor v2, fase 2: coordenadas escritas a mano (visor_rutas/coordenadas.py). Los casos están en
vectores_coordenadas.json y los usa también la prueba de la página (el mismo intérprete en JavaScript)."""
import json
from pathlib import Path

import pytest

from visor_rutas import coordenadas

VECTORES = json.loads((Path(__file__).parent / "vectores_coordenadas.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("caso", VECTORES, ids=[c["entrada"] or "(vacío)" for c in VECTORES])
def test_interpreta_cada_formato(caso):
    r = coordenadas.interpretar(caso["entrada"])
    assert r.estado == caso["estado"], (caso, r)
    if caso["estado"] in ("ok", "invertida", "fuera"):
        assert (r.lat, r.lon) == pytest.approx((caso["lat"], caso["lon"]), abs=1e-6)
    if caso["estado"] == "invertida":
        assert r.sugerencia == pytest.approx((caso["lon"], caso["lat"]), abs=1e-6)
    if caso["estado"] == "error":
        assert caso["mensaje"] in r.mensaje


def test_parsear_estricto():
    assert coordenadas.parsear('13°5\'38.09"N 86°0\'7.42"O') == pytest.approx((13.0939139, -86.0020611), abs=1e-6)
    with pytest.raises(coordenadas.CoordenadaNoValida, match="invertidas"):
        coordenadas.parsear("-86.002708, 13.094578")
    with pytest.raises(coordenadas.CoordenadaNoValida, match="fuera de Nicaragua"):
        coordenadas.parsear("40.7128, -74.0060")
    with pytest.raises(coordenadas.CoordenadaNoValida):
        coordenadas.parsear("Ciudad Sandino")


def test_formatos_de_salida():
    assert coordenadas.formato_decimal(13.094578, -86.002708) == "13.094578, -86.002708"
    assert coordenadas.formato_gms(13.0939139, -86.0020611) == '13°5\'38.09"N 86°0\'7.42"O'
    assert coordenadas.formato_gms(-12.5, 80.0) == '12°30\'0"S 80°0\'0"E'
    # a value whose seconds round up to 60 carries into the minutes
    assert coordenadas.formato_gms(13 + 5 / 60, -86.0) == '13°5\'0"N 86°0\'0"O'


def test_ida_y_vuelta_con_el_texto_que_se_copia():
    """What "copiar en grados/minutos/segundos" puts in the clipboard reads back as the same place."""
    for lat, lon in ((13.094578, -86.002708), (12.153328, -86.263438), (11.9994983, -86.1214684)):
        for texto in (coordenadas.formato_decimal(lat, lon), coordenadas.formato_gms(lat, lon)):
            assert coordenadas.parsear(texto) == pytest.approx((lat, lon), abs=1e-4)
