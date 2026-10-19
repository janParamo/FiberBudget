import pytest
import yaml
from pathlib import Path

from presupuesto import (calcular_equipos, calcular_materiales, calcular_metraje_final,
                         calcular_presupuesto, count_new_poles_by_gaps, count_turns,
                         seleccionar_tecnologia)

ROUTE_LABEL = "Instalacion de Fibra Optica Aerea ADSS-FLAT/FTTH (6H - 12H)"
NEW_POLE_LABEL = "Instalacion de poste metalico tipo tuvo 8 mt."
EXISTING_POLE_LABEL = "Instalacion de herraje en poste existente"
ACCESS_SPLICE_LABEL = "Empalme de Fibra Optica Red de Acceso, Ultima Milla"
ODF_LABEL = "Instalacion de Caja Terminal / ODF"
VISIT_LABEL = "Visita Técnica (Certificación de FO existente cuantificación de obra)"
MANUAL_LABEL = "Sangria de Cable o Buffer"

RULES = {
    "route": {"aerial_install_row_label": ROUTE_LABEL, "safety_margin": 0.10,
              "slack_per_endpoint_m": 10},
    "poles": {"new_pole_row_label": NEW_POLE_LABEL, "existing_pole_row_label": EXISTING_POLE_LABEL,
              "spacing_m": 40, "corner_angle_deg": 35, "extra_poles_per_corner": 1,
              "existing_pole_search_buffer_m": 15},
    "splice": {"backbone_splice_row_label": "Backbone", "access_splice_row_label": ACCESS_SPLICE_LABEL,
                "mufa_intervention_row_label": "Mufa existente", "new_mufa_row_label": "Mufa nueva"},
    "odf": {"odf_row_label": ODF_LABEL, "corporate_service_values": ["corporativo", "corporate"],
            "corporate_bandwidth_threshold": 10},
    "technical_visit": {"visit_row_label": VISIT_LABEL},
    "manual_zero_row_labels": [MANUAL_LABEL],
}
STRAIGHT = [(12.0, -86.0), (12.001, -86.0), (12.002, -86.0)]
L_SHAPE = [(12.0, -86.0), (12.001, -86.0), (12.001, -85.999)]   # 90-degree corner


def test_quantities_are_keyed_by_template_labels():
    quantities = calcular_presupuesto(100, STRAIGHT, RULES, existing_poles=1)
    assert quantities[ROUTE_LABEL] == 130
    assert quantities[EXISTING_POLE_LABEL] == 1
    assert quantities[NEW_POLE_LABEL] == 2   # 100 m route / 40 m spacing = 3 poles, 1 exists
    assert quantities[ACCESS_SPLICE_LABEL] == 1
    assert quantities[VISIT_LABEL] == 0   # technical visit is not budgeted


def test_new_mufa_gets_two_sangrias_and_no_intervention():
    rules = {**RULES, "splice": {**RULES["splice"], "sangria_row_label": MANUAL_LABEL,
                                 "sangrias_per_new_mufa": 2}}
    reserve = calcular_presupuesto(100, STRAIGHT, rules, connection_is_reserve=True, mufa_count=0)
    mufa = calcular_presupuesto(100, STRAIGHT, rules, connection_is_mufa=True)
    assert (reserve["Mufa nueva"], reserve["Mufa existente"], reserve[MANUAL_LABEL]) == (1, 0, 2)
    assert (mufa["Mufa nueva"], mufa["Mufa existente"], mufa[MANUAL_LABEL]) == (0, 1, 0)


def test_short_route_reserve_matches_business_rules():
    """55 m from Directions + 35 m connection reserve + 20% of one full 300 m block."""
    rules = {"route": {"reserve_interval_m": 300, "reserve_percent": 0.20, "connection_reserve_m": 35}}
    assert calcular_metraje_final(55, rules) == 150


def test_corner_adds_pole():
    quantities = calcular_presupuesto(100, L_SHAPE, RULES, existing_poles=1)
    assert quantities[NEW_POLE_LABEL] == 3


def test_float_noise_does_not_add_extra_meter():
    assert calcular_presupuesto(1850, STRAIGHT, RULES)[ROUTE_LABEL] == 2055   # not 2056


def test_odf_is_corporate_for_matching_service_or_high_bandwidth():
    residential_high_bandwidth = calcular_presupuesto(
        100, STRAIGHT, RULES, service_type="residencial", bandwidth="100 Mbps")
    residential_low_bandwidth = calcular_presupuesto(
        100, STRAIGHT, RULES, service_type="residencial", bandwidth="10 Mbps")
    corporate_service = calcular_presupuesto(
        100, STRAIGHT, RULES, service_type="Corporativo", bandwidth="1 Mbps")
    assert residential_high_bandwidth[ODF_LABEL] == 1
    assert residential_low_bandwidth[ODF_LABEL] == 0
    assert corporate_service[ODF_LABEL] == 1


def test_manual_rows_are_explicitly_zero():
    quantities = calcular_presupuesto(100, STRAIGHT, RULES)
    assert MANUAL_LABEL in quantities
    assert quantities[MANUAL_LABEL] == 0


def test_production_rule_uses_50m_spacing_and_existing_poles_are_not_new():
    rules_path = Path(__file__).parents[1] / "business_rules.yaml"
    production_rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    quantities = calcular_presupuesto(100, STRAIGHT, production_rules, existing_poles=1)
    assert production_rules["poles"]["spacing_m"] == 50
    assert quantities[production_rules["poles"]["existing_pole_row_label"]] == 1
    assert quantities[production_rules["poles"]["new_pole_row_label"]] == 1


def test_poles_ignore_coiled_reserve():
    """UHM-782-84959: 55 m route (150 m with reserves) already covered by poles at 0, 16.7 and 45.6 m."""
    rules_path = Path(__file__).parents[1] / "business_rules.yaml"
    production_rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    quantities = calcular_presupuesto(55, STRAIGHT, production_rules,
                                      existing_pole_positions_m=[0.0, 16.72, 45.56])
    assert quantities[ROUTE_LABEL] == 150
    assert quantities[production_rules["poles"]["new_pole_row_label"]] == 0
    assert quantities[production_rules["poles"]["existing_pole_row_label"]] == 3


def test_reserve_is_added_every_300m():
    rules_path = Path(__file__).parents[1] / "business_rules.yaml"
    production_rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    quantities = calcular_presupuesto(18000, STRAIGHT, production_rules)
    assert quantities[ROUTE_LABEL] == 0
    assert quantities[production_rules["route"]["adss_install_row_label"]] == 21635


def test_reserve_uses_ceil_at_boundary_and_partial_segment():
    rules_path = Path(__file__).parents[1] / "business_rules.yaml"
    production_rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    assert calcular_metraje_final(300, production_rules) == 395
    assert calcular_metraje_final(301, production_rules) == 456


def test_materials_use_adss_hardware_for_long_routes():
    rules_path = Path(__file__).parents[1] / "business_rules.yaml"
    production_rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    materials = calcular_materiales(18000, 20, production_rules)
    assert materials["cable_type"] == "ADSS 24 hilos"
    assert materials["quantities"]["Clevis tipo D Chico"] == 20
    assert materials["quantities"]['Cinta Band It 3/4" (50mts)'] == 20
    assert materials["quantities"]["Hebilla Band It 3/4"] == 20
    assert materials["quantities"]["Grapa Metalica en S"] == 0
    assert materials["quantities"]["Grapa p/ cable fibra FTTH"] == 0
    assert materials["quantities"]["Preformada Punto Verde ADSS 11.7 mm / 12.8 mm"] == 20


def test_materials_use_flat_grasps_for_short_routes():
    rules_path = Path(__file__).parents[1] / "business_rules.yaml"
    production_rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    materials = calcular_materiales(500, 8, production_rules)
    assert materials["cable_type"] == "Flat"
    # Flat: S clamps and as many FTTH clamps; the green preformed is ADSS only.
    assert materials["quantities"]["Grapa Metalica en S"] == 16
    assert materials["quantities"]["Grapa p/ cable fibra FTTH"] == 16
    assert materials["quantities"]["Preformada Punto Verde ADSS 11.7 mm / 12.8 mm"] == 0


def test_fixed_events_scale_by_route_mufas_and_new_connection():
    rules_path = Path(__file__).parents[1] / "business_rules.yaml"
    production_rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    quantities = calcular_presupuesto(
        150,
        STRAIGHT,
        production_rules,
        mufa_count=3,
        new_connections=1,
    )
    # Matches the manual budget for UHM-782-84959 (MUFA REBECA -> KAREN BERMUDEZ -> CACIQUE).
    assert quantities["Intervencion de Mufa Existente"] == 3
    assert quantities["Empalme de fibra optica cables de Red Backbone (core/troncal)"] == 3
    assert quantities["Empalme de Fibra Optica Red de Acceso, Ultima Milla"] == 1
    assert quantities["Instalacion de Caja Terminal / ODF"] == 1
    assert quantities["Rotulacion de Cable de fibra en mufas y ODF"] == 3
    assert quantities["Caracterizacion de la fibra optica  - Pruebas de OTDR y VFL"] == 2


def _production_rules():
    return yaml.safe_load((Path(__file__).parents[1] / "business_rules.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("bandwidth, technology, comment, expected", [
    ("100 Mbps", None, "", ("gpon", "bandwidth")),             # 100 is not above 100
    ("200 Mbps", None, "", ("metro", "bandwidth")),
    ("200 Mbps", None, "Cliente corporativo pide GPON", ("gpon", "comment")),
    ("50 Mbps", None, "Instalar por Metro Ethernet", ("metro", "comment")),
    ("200 Mbps", None, "Cotizar gpon y metro", ("metro", "bandwidth")),   # ambiguous comment
    ("50 Mbps", None, "Reserva a 120 metros del poste", ("gpon", "bandwidth")),  # "metros" is distance
    ("50 Mbps", "metro", "pide gpon", ("metro", "request")),   # request field wins
])
def test_technology_selection(bandwidth, technology, comment, expected):
    assert seleccionar_tecnologia(bandwidth, technology, comment, _production_rules()) == expected


def test_equipment_kits_and_odf():
    rules = _production_rules()
    gpon = calcular_equipos("gpon", None, rules)
    metro = calcular_equipos("metro", 24, rules)
    assert gpon == {"Huawei HG8310M Gpon": 1, "PATCH CORD SC-SC SM (SINGLE MODE) UPC SIMPLEX 3MTS": 1,
                    "PATCH CORD CAT6 7FT": 1, "HAP AC³ WITH ROUTER/RBD53IG-5HACD2HND": 1, "ODF 2 Hilos": 1}
    assert metro == {"SFS-7020-WA-SC-DD": 1, "SFS-7020-WB-SC-DD": 1, "FMC-1001S": 2,
                     "HAP AC³ WITH ROUTER/RBD53IG-5HACD2HND": 1, "ODF 2 Hilos": 1,
                     "Odf Rack 24 Acopladores": 1}


def test_new_poles_fill_gaps_from_existing_pole_positions():
    assert count_new_poles_by_gaps(100, 50, []) == 2
    assert count_new_poles_by_gaps(100, 50, [30]) == 1
    assert count_new_poles_by_gaps(100, 50, [20, 80]) == 1
    assert count_new_poles_by_gaps(100, 50, [0, 50, 100]) == 0


def test_spans_up_to_max_span_need_no_new_pole():
    """QQC-588-10739 (Shoeless): a 53.4 m span is accepted in the field, no new pole."""
    shoeless = [0.0, 53.4, 62.0, 88.8, 118.1, 149.9]
    assert count_new_poles_by_gaps(150, 50, shoeless) == 1                  # strict 50 m
    assert count_new_poles_by_gaps(150, 50, shoeless, max_span_m=60) == 0
    assert count_new_poles_by_gaps(60, 50, [], max_span_m=60) == 0          # exactly 60 m: ok
    assert count_new_poles_by_gaps(61, 50, [], max_span_m=60) == 1          # longer: pole every 50 m
    assert count_new_poles_by_gaps(200, 50, [0, 130], max_span_m=60) == 3   # gaps 130 and 70


def test_poles_that_already_stand_are_used_even_if_far_apart():
    """Between two existing poles the field's span is accepted (up to the longer limit): no new pole in between."""
    existentes = [40.0, 130.0, 215.0]                                         # spans of 90 and 85 m
    assert count_new_poles_by_gaps(250, 50, existentes, max_span_m=60) == 2   # old rule: a pole inside each gap
    assert count_new_poles_by_gaps(215, 50, existentes, max_span_m=60, max_span_between_existing_m=100) == 0
    # before the first / after the last existing pole the normal limit still applies
    assert count_new_poles_by_gaps(400, 50, existentes, max_span_m=60, max_span_between_existing_m=100) == 3   # 215 -> 400
    assert count_new_poles_by_gaps(130, 50, [130], max_span_m=60, max_span_between_existing_m=100) == 2        # 0 -> 130: 50, 100
    assert count_new_poles_by_gaps(260, 50, [0, 130, 260], max_span_m=60, max_span_between_existing_m=100) == 4   # 130 m spans are too long


def test_count_turns():
    assert count_turns(STRAIGHT, 35) == 0
    assert count_turns(L_SHAPE, 35) == 1


def test_negative_distance_rejected():
    with pytest.raises(ValueError):
        calcular_presupuesto(-1, STRAIGHT, RULES)
