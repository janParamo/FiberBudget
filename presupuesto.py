"""Pure quantity logic: prices and formulas remain in the Excel template."""
import math
import re
import unicodedata
from typing import Any

LatLon = tuple[float, float]


def _bearing(a: LatLon, b: LatLon) -> float:
    """Initial compass bearing in degrees from point a to b. Points are (lat, lon)."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def count_turns(points: list[LatLon], threshold_deg: float) -> int:
    """Count vertices where the route heading changes by >= threshold_deg."""
    pts = [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]  # drop repeats
    turns = 0
    for i in range(1, len(pts) - 1):
        delta = abs(_bearing(pts[i], pts[i + 1]) - _bearing(pts[i - 1], pts[i]))
        delta = min(delta, 360 - delta)
        if delta >= threshold_deg:
            turns += 1
    return turns


def new_pole_positions_by_gaps(
    distance_m: float,
    spacing_m: float,
    existing_positions_m: list[float],
    max_span_m: float | None = None,
    max_span_between_existing_m: float | None = None,
) -> list[float]:
    """Route position (m from the origin) of each new pole that fills a gap.

    A pole already in the database becomes the last installed pole for the
    next gap, so it is never counted again as a new pole. A gap no longer than
    max_span_m (the longest span accepted in the field) needs no new pole;
    longer gaps get poles every spacing_m. max_span_m defaults to spacing_m.
    Between two poles that already stand the span is what the field built, so the
    longer max_span_between_existing_m applies there (the existing poles are used).
    """
    if spacing_m <= 0:
        raise ValueError("spacing_m must be > 0")
    tolerance = 1e-6
    max_span = max(spacing_m, max_span_m or spacing_m)
    max_span_existing = max(max_span, max_span_between_existing_m or 0.0)
    positions = sorted({min(distance_m, max(0.0, float(position)))
                        for position in existing_positions_m})
    last_installed = 0.0
    last_is_existing = False
    new_positions: list[float] = []
    for position in positions:
        if position - last_installed > (max_span_existing if last_is_existing else max_span) + tolerance:
            while last_installed + spacing_m < position - tolerance:
                last_installed += spacing_m
                new_positions.append(last_installed)
        last_installed = max(last_installed, position)
        last_is_existing = True
    if distance_m - last_installed > max_span + tolerance:
        while last_installed + spacing_m <= distance_m + tolerance:
            last_installed += spacing_m
            new_positions.append(last_installed)
    return new_positions


def count_new_poles_by_gaps(
    distance_m: float,
    spacing_m: float,
    existing_positions_m: list[float],
    extra_poles: int = 0,
    max_span_m: float | None = None,
    max_span_between_existing_m: float | None = None,
) -> int:
    """Fill route gaps from each installed pole, placing new poles every spacing.

    Existing positions are measured from the route origin (see new_pole_positions_by_gaps).
    """
    positions = new_pole_positions_by_gaps(distance_m, spacing_m, existing_positions_m, max_span_m,
                                           max_span_between_existing_m)
    return len(positions) + max(0, int(extra_poles))


def tramos_ducto(distance_m: float, pozo_positions_m: list[float], rules: dict[str, Any]) -> list[tuple[float, float]]:
    """Stretches of the route (metres from the connection point) that go in duct, from the wells (pozos) along it. Rules of Jan, 2026-10-20:
    where there are wells the fibre is installed in duct (not aerial) up to the nearest mufa / the client, and where the route leaves the wells
    for the poles there is one aerial stretch and one duct stretch.

    Wells no farther apart than `ducto.pozo_gap_max_m` belong to one duct run (first well .. last well); a run that ends within
    `ducto.extender_a_extremo_m` of the connection mufa or of the client goes all the way to that end (the cable gets into the mufa / the
    building through duct). Returns [] when there are no wells."""
    cfg = rules.get("ducto") or {}
    if not pozo_positions_m or distance_m <= 0:
        return []
    gap = float(cfg.get("pozo_gap_max_m", 100))
    extremo = float(cfg.get("extender_a_extremo_m", 60))
    posiciones = sorted(min(distance_m, max(0.0, float(p))) for p in pozo_positions_m)
    corridas: list[list[float]] = [[posiciones[0], posiciones[0]]]
    for p in posiciones[1:]:
        if p - corridas[-1][1] <= gap:
            corridas[-1][1] = p
        else:
            corridas.append([p, p])
    tramos = []
    for a, b in corridas:
        if a <= extremo:
            a = 0.0
        if distance_m - b <= extremo:
            b = distance_m
        tramos.append((a, b))
    fusion: list[tuple[float, float]] = []                     # runs that now touch are one
    for a, b in tramos:
        if fusion and a <= fusion[-1][1]:
            fusion[-1] = (fusion[-1][0], max(fusion[-1][1], b))
        else:
            fusion.append((a, b))
    return [(round(a, 3), round(b, 3)) for a, b in fusion if b > a]


def tramos_aereos(distance_m: float, ducto: list[tuple[float, float]] | None) -> list[tuple[float, float]]:
    """The rest of the route: the stretches that go on poles (the whole route when there is no duct)."""
    if not ducto:
        return [(0.0, float(distance_m))] if distance_m > 0 else []
    aereos, cursor = [], 0.0
    for a, b in sorted(ducto):
        if a > cursor:
            aereos.append((cursor, a))
        cursor = max(cursor, b)
    if distance_m > cursor:
        aereos.append((cursor, float(distance_m)))
    return [(round(a, 3), round(b, 3)) for a, b in aereos]


def new_pole_positions_in_spans(spans: list[tuple[float, float]], spacing_m: float, existing_positions_m: list[float],
                                max_span_m: float | None = None, max_span_between_existing_m: float | None = None) -> list[float]:
    """Route position of each new pole when only `spans` (the aerial stretches) get poles: every stretch is filled on its own with the poles
    that already stand inside it. The positions are measured from the start of the whole route."""
    nuevos: list[float] = []
    for a, b in spans:
        dentro = [p - a for p in existing_positions_m if a - 1e-6 <= p <= b + 1e-6]
        nuevos.extend(a + x for x in new_pole_positions_by_gaps(b - a, spacing_m, dentro, max_span_m, max_span_between_existing_m))
    return nuevos


def match_marked_poles(marked_m: list[float], new_positions_m: list[float],
                       tolerance_m: float = 0.5) -> tuple[list[float], list[float]]:
    """Split poles marked as existing (route metres) into (matched new-pole positions, unmatched marks).

    Each new-pole position matches at most one mark, so a mark sent twice counts once.
    """
    free = sorted(new_positions_m)
    matched: list[float] = []
    unmatched: list[float] = []
    for mark in marked_m:
        nearest = min(free, key=lambda p: abs(p - mark), default=None)
        if nearest is not None and abs(nearest - mark) <= tolerance_m:
            free.remove(nearest)
            matched.append(nearest)
        elif not any(abs(p - mark) <= tolerance_m for p in matched):
            unmatched.append(mark)
    return sorted(matched), unmatched


def _normalized(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in text if not unicodedata.combining(char)).casefold()


def _bandwidth_value(value: str) -> float:
    """Extract the first numeric bandwidth value, accepting comma decimals."""
    match = re.search(r"\d+(?:[.,]\d+)?", value)
    return float(match.group(0).replace(",", ".")) if match else 0.0


def calcular_metraje_final(distance_m: float, rules: dict[str, Any]) -> float:
    """Add fixed connection reserve and periodic cable reserve to the route."""
    route = rules["route"]
    reserve_interval_m = float(route.get("reserve_interval_m", 0))
    reserve_percent = float(route.get("reserve_percent", 0))
    periodic_reserve_m = (math.ceil(distance_m / reserve_interval_m) * reserve_interval_m * reserve_percent
                 if reserve_interval_m > 0 and reserve_percent > 0 else 0)
    fixed_reserve_m = float(route.get("connection_reserve_m", 0))
    return round(distance_m * (1 + route.get("safety_margin", 0))
                 + periodic_reserve_m + fixed_reserve_m
                 + 2 * route.get("slack_per_endpoint_m", 0), 6)


def calcular_presupuesto(
    distance_m: float,
    route_points: list[LatLon],
    rules: dict[str, Any],
    *,
    service_type: str = "",
    bandwidth: str = "",
    existing_poles: int = 0,
    existing_pole_positions_m: list[float] | None = None,
    connection_is_mufa: bool = False,
    connection_is_reserve: bool = False,
    new_mufa_required: bool = False,
    mufa_count: int | None = None,
    new_connections: int = 1,
    technical_visit: bool = False,
    duct_spans: list[tuple[float, float]] | None = None,
) -> dict[str, int]:
    """Return quantities keyed by the exact labels in the Excel template.

    The route margin and endpoint slack are applied to the aerial-installation
    quantity. Pricing, line totals, taxes and all other formulas stay in Excel.
    """
    if distance_m < 0:
        raise ValueError("distance_m must be >= 0")
    route = rules["route"]
    poles_rules = rules["poles"]
    splice = rules["splice"]
    odf = rules["odf"]
    quantities = {label: 0 for label in rules.get("manual_zero_row_labels", [])}

    final_distance_m = calcular_metraje_final(distance_m, rules)
    route_quantity = math.ceil(final_distance_m)
    flat_install_label = route["aerial_install_row_label"]
    adss_install_label = route.get("adss_install_row_label")
    use_adss = final_distance_m > rules.get("cable", {}).get("adss_threshold_m", float("inf"))
    # Where the route goes through wells the cable is installed in duct: those metres go to the duct row, the rest stays aerial.
    duct_quantity = min(route_quantity, math.ceil(sum(b - a for a, b in duct_spans))) if duct_spans else 0
    if duct_spans and not tramos_aereos(distance_m, duct_spans):
        duct_quantity = route_quantity                  # all in duct: the reserves too (nothing is left on poles)
    aerial_quantity = route_quantity - duct_quantity
    quantities[flat_install_label] = 0 if use_adss else aerial_quantity
    if adss_install_label:
        quantities[adss_install_label] = aerial_quantity if use_adss else 0
    if route.get("duct_install_row_label"):
        quantities[route["duct_install_row_label"]] = duct_quantity

    # Poles follow the physical route; the reserves are coiled cable, not spans between poles.
    turns = count_turns(route_points, poles_rules["corner_angle_deg"])
    required_poles = math.ceil(round(distance_m / poles_rules["spacing_m"], 6))
    required_poles += turns * poles_rules["extra_poles_per_corner"]
    if duct_spans and existing_pole_positions_m is not None:
        # Poles only along the aerial stretches (a pole inside the duct stretch is not used).
        aereos = tramos_aereos(distance_m, duct_spans)
        existing_pole_positions_m = [p for p in existing_pole_positions_m if any(a - 1e-6 <= p <= b + 1e-6 for a, b in aereos)]
        existing_poles = len(existing_pole_positions_m)
        new_poles = (len(new_pole_positions_in_spans(aereos, poles_rules["spacing_m"], existing_pole_positions_m, poles_rules.get("max_span_m"),
                                                     poles_rules.get("max_span_between_existing_m")))
                     + (turns * poles_rules["extra_poles_per_corner"] if aereos else 0))
    elif duct_spans:                      # no positions: poles of the aerial metres only
        aerea_m = sum(b - a for a, b in tramos_aereos(distance_m, duct_spans))
        existing_poles = max(0, int(existing_poles))
        new_poles = max(0, math.ceil(round(aerea_m / poles_rules["spacing_m"], 6)) - existing_poles)
    elif existing_pole_positions_m is None:
        existing_poles = max(0, int(existing_poles))
        new_poles = max(0, required_poles - existing_poles)
    else:
        # One position per physical pole (deduplicated by location); several may share a position.
        existing_poles = len(existing_pole_positions_m)
        new_poles = count_new_poles_by_gaps(
            distance_m,
            poles_rules["spacing_m"],
            existing_pole_positions_m,
            turns * poles_rules["extra_poles_per_corner"],
            poles_rules.get("max_span_m"),
            poles_rules.get("max_span_between_existing_m"),
        )
    quantities[poles_rules["existing_pole_row_label"]] = existing_poles
    quantities[poles_rules["new_pole_row_label"]] = new_poles

    events = rules.get("fixed_events", {})
    effective_mufa_count = (int(mufa_count) if mufa_count is not None
                            else int(connection_is_mufa))
    # Every intervened mufa gets a backbone splice; every new connection a last-mile splice.
    # The mufas up to the splitter plus two of the splitter itself, when the connection is an existing mufa.
    backbone = effective_mufa_count * int(events.get("backbone_splice_per_mufa", 1))
    if connection_is_mufa and not connection_is_reserve and effective_mufa_count > 0:
        backbone += int(events.get("backbone_splice_extra_splitter", 0))
    quantities[splice["backbone_splice_row_label"]] = backbone
    quantities[splice["access_splice_row_label"]] = (
        int(new_connections) * int(events.get("last_mile_splice_per_new_connection", 1)))
    quantities[splice["mufa_intervention_row_label"]] = effective_mufa_count
    # Tapping a reserva means installing a new mufa on it. Its price already covers the
    # intervention, so only existing mufas count as interventions; each new mufa adds sangrias.
    new_mufas = int(new_mufa_required or connection_is_reserve)
    quantities[splice["new_mufa_row_label"]] = new_mufas
    if new_mufas and splice.get("sangria_row_label"):
        quantities[splice["sangria_row_label"]] = new_mufas * int(splice.get("sangrias_per_new_mufa", 0))

    corporate_services = {_normalized(value) for value in odf["corporate_service_values"]}
    is_corporate = (_normalized(service_type) in corporate_services
                    or _bandwidth_value(bandwidth) > odf["corporate_bandwidth_threshold"])
    if "odf_per_new_connection" in events:
        quantities[odf["odf_row_label"]] = (
            int(new_connections) * int(events["odf_per_new_connection"]))
    else:
        quantities[odf["odf_row_label"]] = int(is_corporate)
    if events.get("rotulation_row_label"):
        # Label the cable in every mufa it passes (intervened or new), at least once per connection.
        quantities[events["rotulation_row_label"]] = max(
            int(new_connections) * int(events.get("labeling_min_per_new_connection", 1)),
            effective_mufa_count + new_mufas,
        )
    if events.get("otdr_row_label"):
        # Always certified once per project, regardless of the connection type.
        quantities[events["otdr_row_label"]] = int(events.get("otdr_certification_per_project", 1))
    visita = rules["technical_visit"]
    quantities[visita["visit_row_label"]] = int(visita.get("quantity", 1)) if technical_visit else 0
    return quantities


def requiere_visita_tecnica(textos: list[Any], rules: dict[str, Any]) -> bool:
    """A technical visit is budgeted when the client is in a plaza, a building or a mall: one of `technical_visit.keywords` (whole words or
    phrases, no accents) in the client's name, the ticket comment or the service type."""
    palabras = [_plano_visita(k) for k in rules.get("technical_visit", {}).get("keywords", [])]
    texto = f" {_plano_visita(' '.join(str(t or '') for t in textos))} "
    return any(p and f" {p} " in texto for p in palabras)


def _plano_visita(texto: str) -> str:
    sin = "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Z0-9 ]+", " ", sin.upper()).split())


def seleccionar_tecnologia(bandwidth: str, technology: str | None, raw_comment: str,
                           rules: dict[str, Any]) -> tuple[str, str]:
    """Return (technology, source): request field, then ticket comment, then bandwidth."""
    if technology:
        return technology, "request"
    mentioned = {word.casefold() for word in re.findall(r"\b(gpon|metro)\b", raw_comment or "", re.IGNORECASE)}
    if len(mentioned) == 1:     # both or neither mentioned -> ambiguous, use bandwidth
        return mentioned.pop(), "comment"
    threshold = float(rules["equipment"]["metro_bandwidth_threshold_mbps"])
    return ("metro" if _bandwidth_value(bandwidth) > threshold else "gpon"), "bandwidth"


def calcular_equipos(technology: str, odf_rack_ports: int | None, rules: dict[str, Any]) -> dict[str, int]:
    """Customer equipment for MATERIALES: the technology kit, the ODF 2 Hilos every
    installation gets, and a rack ODF only when the request asks for one."""
    equipment = rules["equipment"]
    items = {label: int(qty) for label, qty in equipment["kits"][technology].items()}
    items[equipment["odf_label"]] = 1
    if odf_rack_ports:
        items[equipment["odf_rack_labels"][odf_rack_ports]] = 1
    return items


def calcular_materiales(distance_m: float, total_poles: int, rules: dict[str, Any]) -> dict[str, Any]:
    """Select cable and hanging hardware quantities from the route length."""
    cable = rules["cable"]
    adss = distance_m > cable["adss_threshold_m"]
    pole_count = max(0, int(total_poles))
    # One clamp type per support point (see cable.hardware_by_cable_type).
    quantities = {
        cable["clevis_label"]: pole_count,
        cable["band_label"]: pole_count,
        cable["buckle_label"]: pole_count,
        cable["s_clamp_label"]: 0 if adss else pole_count * 2,
        cable["ftth_clamp_label"]: 0 if adss else pole_count * 2,   # Flat: as many as S clamps
        cable["green_preformed_label"]: pole_count if adss else 0,   # ADSS only
    }
    return {
        "cable_key": "adss" if adss else "flat",
        "cable_type": "ADSS 24 hilos" if adss else "Flat",
        "cable_material_label": cable["adss_material_label"] if adss else cable["flat_material_label"],
        "quantities": quantities,
    }
