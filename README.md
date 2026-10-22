# Fiber Budget Service

FastAPI service that receives a ticket from n8n, finds the connection point (nearest
mufa or reserva in the KMZ data, backed by the Visio network), gets the street route
from Google Directions, calculates quantities, and fills the company's Excel template. The workbook is the source
of truth for prices, formulas and layout.

## Structure

```
fiber_budget/
├── main.py               # FastAPI app, routes (/presupuesto, /origen), ngrok tunnel
├── visor_api.py          # /visor/*: the route viewer on other computers (own X-Visor-Key)
├── empaquetar_visor.py   # builds VisorRutas.exe + VisorRutas.zip (called by build_visor.bat)
├── build_visor.bat       # PyInstaller: remote-mode viewer for other computers
├── db.py                 # PostGIS (KMZ): connection point, mufa chain, poles, route mufas
├── routing.py            # Google Directions client (with retry/backoff)
├── presupuesto.py        # Pure quantity logic (labor, materials, equipment)
├── excel_generator.py    # Fills the template, inserts the route map
├── recalc.py             # LibreOffice recalculation: caches formula results
├── origen.py             # Traffic-origin node and mufa path from the Visio network;
│                         # connection-mufa matching (coordinate, then by name) and diagnosis
├── red_fibra_pg.py       # Visio network in PostgreSQL: nearest node, "origen" block
├── mapa_ruta.py          # Satellite route map (Esri tiles + Pillow)
├── config.py             # Env vars, logging, rules loader
├── business_rules.yaml   # Quantity rules and stable template labels only
├── start_service.bat     # Windows loopback/Uvicorn launcher
├── requirements.txt
├── .env.example
├── templates/            # The company's real workbook
├── output/               # Generated Excel files, mapas/, budget_index.json
├── logs/                 # service.log (rotating)
├── red_fibra/            # Visio importer, SQLite copy, PostgreSQL publisher,
│                         # reporte_emparejamiento.py (KMZ mufas vs Visio, Excel for Planta Externa)
└── Pruebas/              # everything for testing: automated tests (DB and Google mocked),
                          # pytest.ini and make_sample_template.py (test fixture workbook)
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configure

1. `cp .env.example .env` and fill in DB credentials, `GOOGLE_API_KEY` and
   `SERVICE_API_KEY` (generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
2. Copy the company's real workbook to the path in `TEMPLATE_PATH`.
  The workbook must contain `Presupuesto`, `Ruta proyectada`, `COSTOS`,
  `MATERIALES` and `Variación de costos`.
3. Keep the exact line descriptions in column E of `Presupuesto`. The service
  finds them by text and writes quantities only to column G. It never changes
  catalog sheets, material formulas, subtotals, taxes or totals.
4. Review `business_rules.yaml` for quantity rules, row labels, pole spacing,
  route-sheet labels and the list of technician-completed rows.

The Google key needs the **Directions API** enabled. The database must have
`red_lineas(id, tipo, geom)` with `geom` in SRID 4326 and `red_puntos(id, tipo, geom)`
for existing-pole detection (ideally with GiST indexes).
If your primary key column is not `id`, change it in `db.py`.

## Run

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

On Windows, use `start_service.bat`; it activates `.venv`, reads `API_HOST` and
`API_PORT` from the validated settings, and starts one Uvicorn worker. The
defaults bind only to loopback, so the ngrok tunnel is the only network entry
point. The service validates credentials at startup and removes expired Excel
files and maps without deleting the ticket idempotency index. Application logs
rotate at 5 MB with three backups in `LOG_FILE`.

The ngrok tunnel starts and stops with the service (Python SDK, inside the app's
lifespan): it forwards `NGROK_DOMAIN` to `API_HOST:API_PORT` using `NGROK_AUTHTOKEN`.
Leave `NGROK_DOMAIN` empty to run without a tunnel. Restart `start_service.bat`
after changing code or `.env`; `business_rules.yaml` is read on every request.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest Pruebas
```

The service never uses the `Pruebas` folder; it only runs when the tests are run.

### n8n Request

In an n8n HTTP Request node, select `POST`, set the public tunnel URL, choose
JSON for the body, and add `Content-Type: application/json` plus
`X-API-Key: <SERVICE_API_KEY>` as headers. Keep the key in an n8n credential.

Equivalent command-line request:

```bat
curl.exe -X POST "https://fiber-api.example.com/presupuesto" ^
  -H "Content-Type: application/json" ^
  -H "X-API-Key: YOUR_SERVICE_API_KEY" ^
  --data-raw "{\"ticket_id\":\"T-1001\",\"client_name\":\"Juan Perez\",\"client_code\":\"C05000\",\"sales_exec\":\"Ana Lopez\",\"contact_name\":\"Juan Perez\",\"contact_phone\":\"5880 9994\",\"raw_comment\":\"\",\"latitude\":12.1364,\"longitude\":-86.2514,\"service_type\":\"internet\",\"medium\":\"fibra\",\"bandwidth\":\"100 Mbps\"}"
```

The request body does not include `budget_id`; use a stable, unique `ticket_id`.
Repeated submissions of that ticket return its original budget. Example response:

```json
{
  "budget_id": "a1b2c3d4e5f607182930abcdef123456",
  "ticket_id": "T-1001",
  "distance_km": 1.85,
  "exceeds_5km": false,
  "status": "ok",
  "quantities": {
    "Instalacion de Fibra Optica Area ADSS (24H - 48H)": 2305,
    "Instalacion de poste metalico tipo tuvo 8 mt.": 45,
    "Instalacion de herraje en poste existente": 1
  },
  "pending_validation_poles": [
    {
      "id": 8,
      "latitude": 12.135,
      "longitude": -86.25,
      "distance_along_route_m": 50.0
    }
  ],
  "pending_validation_items": [
    {"item": "Instalacion de poste metalico tipo tuvo 9 mt.", "quantity": 0}
  ],
  "excel_path": "C:/fiber_budget/output/Juan_Perez_a1b2c3d4e5f607182930abcdef123456.xlsx"
}
```

`distance_km` is rounded to three decimals. `exceeds_5km` compares the route
distance to `budget_alerts.distance_threshold_km` in `business_rules.yaml`.
`pending_validation_poles` lists database poles found near the route for field
verification. The `.xlsx` is available from the protected
`GET /presupuesto/{budget_id}/excel` endpoint.

Ticket mappings are stored atomically in `output/budget_index.json`. Keep the
configured single Uvicorn worker: the in-process lock prevents duplicate
budgets for simultaneous requests in that service process.

Health check:

```bash
curl https://fiber-api.example.com/health
```


## Status codes

| Code | Meaning |
|------|---------|
| 200 | Budget generated |
| 422 | Invalid/missing fields, or coordinates outside Nicaragua's bounding box |
| 401 | Missing or wrong `X-API-Key` |
| 404 | No eligible segment, no Google route, or budget Excel does not exist |
| 502 | Google Directions API failed (calls are retried 3x with backoff first) |
| 500 | Database query or unexpected internal error |
| 503 | PostgreSQL health check failed |

## Notes

- **Coordinate order:** the API receives `(latitude, longitude)`. PostGIS `ST_MakePoint`
  takes `(longitude, latitude)`; the Directions API takes `"lat,lng"`. Each spot is
  documented in `db.py` and `routing.py`.
- **Connection point:** always an existing `red_puntos` point, never a projection
  onto a `red_lineas` line. Order: the nearest valid mufa within
  `connection.mufa_search_radius_m` (500 m by default), else the nearest reserva
  within that radius, else the nearest mufa or reserva at any distance.
  **Checked by route and hilos** (`connection.route_selection`): when that point's Google
  route is more than `detour_factor` (2x) its straight distance and `min_detour_m` (300 m)
  longer, or its KMZ name/description or its Visio mufa carries an `unavailable_keywords` mark
  ("MF ELIMINADA", "PROBABLEMENTE NO EXISTA", "SATURADA", "NO REALIZAR PRESUPUESTOS"…), the
  `max_candidates` (5) nearest KMZ mufas within `candidate_radius_m` (2 km) are compared by
  Google route length (one call each, driving) and the shortest one without marks is used.
  Example: client 12.104408, -86.220292 → MF CASA GERENCIA is 610 m away but 3324 m by
  street; MF BERTHA GAMEZ (1350 m) is "MF ELIMINADA"; MF DE CORTE (1396 m) is used, with
  MF OSCAR SANCHEZ (1426 m) next. `connection_point.selection` lists the points compared and a
  warning asks to validate available hilos; if none is available the nearest is kept and
  flagged. The viewer makes the same choice (only with a Google route). Its
  coordinate is the Directions origin, and its `nombre` is written after
  `Origen de trafico (MF):` in `Ruta proyectada`. An existing mufa
  sets `Intervencion de Mufa Existente` to 1. A reserva means a new mufa:
  `Instalacion de mufas` = 1 and `splice.sangrias_per_new_mufa` (2) sangrias,
  with no intervention, because the new-mufa price already includes it.
  `Caracterizacion de la fibra optica - Pruebas de OTDR y VFL` is always 1.
  `Origen de Tráfico (Nodo)` comes from the Visio diagrams (see Traffic-origin node).
- **Intervened mufas = every mufa used to bring the hilo to the client.** When the
  Visio diagrams trace the path cable by cable from the (exactly matched) connection
  mufa to the mufa labelled with the origin node, every mufa on that path is
  intervened (`traffic_origin.count_path_mufas`; `budget.mufa_count_source` =
  `diagramas`). Otherwise the PostGIS chain below counts (`postgis`).
- **Intervened mufas and fixed events (PostGIS chain):** when the connection point is an existing
  mufa, the service follows existing `red_lineas` fiber lines upstream, mufa by
  mufa (fewest hops, then nearest), until it reaches the first distribution mufa
  (`connection.upstream_chain`). Rules, checked in order: a cable labelled with 24
  or more hilos passes it (`cable_24h`); a trunk-type line or a line named or
  described TRONCAL/BACKBONE passes it (`linea_troncal`); its own description says
  TRONCAL/BACKBONE (`mufa_troncal`). The matching rule is returned as
  `budget.distribution_reason`. Every mufa on that chain is intervened, plus any
  other mufa within the route buffer. Each intervened mufa adds one
  `Intervencion de Mufa Existente` and one backbone splice, and the cable is
  labelled once per mufa (at least once per connection). If no distribution mufa
  is found within `max_hops`, only the connection mufa counts and a warning is
  logged. Each new client connection adds one last-mile splice and one ODF; OTDR
  certification is always added once per project.
- **Pricing model:** prices, formulas, taxes and layout are owned by the Excel
  workbook. `business_rules.yaml` contains no monetary values.
- **Route reserve:** the production rule always adds 35 m for the customer
  connection: 15 m for the mufa and 20 m for the indoor installation. It also
  adds 20% of each 300 m block (60 m per block) to the measured route. A partial
  block counts as a complete block. This final metrage is used for the cable
  quantity only.
- **Poles:** poles are calculated over the physical route distance, not the
  final metrage (reserves are coiled cable, not spans between poles). A gap
  between poles up to `poles.max_span_m` (60 m) is accepted and needs no new pole;
  a longer gap gets new poles every `spacing_m` (50 m). Required
  poles come from spacing plus route corners;
  the production rule places the 8 m pole type every 50 m, existing `red_puntos`
  poles within the configured buffer are projected onto the route and used as
  the last installed pole for each gap. Existing poles are written to the
  existing-pole labor row, while new poles are written to the 8 m labor row and
  the `POSTE 8 MTRS` material row. Hardware quantities use the total of existing
  and new poles. Records less than 2 m apart are treated as one physical pole to
  avoid duplicate counting (by location, not route position: two real poles beyond
  the route's end share its last point and still count twice);
  no extra corner poles are added under this rule. The API response exposes
  `required_poles`, `existing_poles`, `existing_pole_positions_m` and
  `new_poles_8m` for auditing.
- **Manual completion:** `Instalacion de poste metalico tipo tuvo 9 mt.`,
  `Desplazamiento a [Ciudad] / [xxx] Km`, `Sangria de Cable o Buffer`,
  `Levantamieto de hilos mufa`, `Movimiento de Reserva existente` and
  `Instalacion de Fibra en Ducto ADSS-FLAT/FTTH...` are always written as zero
  and require technician completion before sending a client budget.
- **Cable and hardware:** routes whose final metrage is over 600 m use the
  `Instalacion de Fibra Optica Area ADSS (24H - 48H)` labor row and
  `FIBRA OPTICA 24 Hilos ADSS SingleMode Span 150 m`; they use one clevis, band
  and buckle plus one green preformed unit per pole. Routes at or below 600 m
  use the 12-hilos Flat labor/material rows and one clevis, band and buckle plus
  two S clamps and two FTTH clamps per pole (no green preformed).
  Fiber material counts aerial metres only (duct is not budgeted for now):
  `cable.fiber_material_from_install` writes `=G12` to the Flat fiber row and `=G13`
  to the ADSS 24H fiber row, replacing the template's `=G12+G28`.
  For example, 18,000 m with 20 total poles (10 new and 10 existing) selects
  ADSS and writes 20 clevises, 20 bands, 20 buckles, 0 S clamps, 0 FTTH
  clamps and 20 green preformed units.
- **Customer equipment:** written to the fixed-value quantity cells of the
  MATERIALES rows (never over a formula). Technology comes from the optional
  `technology` field (`gpon`/`metro`), else from a single "gpon" or "metro" word in
  `raw_comment`, else bandwidth above 100 Mbps means Metro. GPON adds Huawei
  HG8310M, patch cord SC-SC, patch cord CAT6 and HAP AC³; Metro adds SFS-7020-WA,
  SFS-7020-WB, 2 FMC-1001S and HAP AC³. Both always add one ODF 2 Hilos; the
  optional `odf_rack_ports` (12 or 24) adds a rack ODF on top of it. Items with no row in the
  template are listed in `pending_validation_items` and
  `equipment.missing_in_template`. Kits live under `equipment` in
  `business_rules.yaml`. The technical visit is not budgeted (always 0).
- **Template formulas are protected:** the service never writes a value over a cell
  that holds a formula in the template. If it tries, the formula is kept and the
  attempt is reported in `warnings` and the log. The only exceptions are cells a
  rule names explicitly: the date rewrite, `cable.hardware_by_cable_type` and
  `cable.fiber_material_from_install`.
- **Hanging hardware:** `cable.hardware_by_cable_type` sets these MATERIALES rows by
  cable type and may replace their template formula. Flat: 2 S clamps per pole
  (template formula) and as many FTTH clamps (live formula to the S-clamp row); green
  preformed 0. ADSS: no clamps, only one green preformed per pole (live formula
  to the Band It buckle row); S and FTTH clamps 0.
- **Pole material:** new 8 m poles are also written to `poles.new_pole_material_row_label`
  (`POSTE 8 MTRS`), unless the template already computes that row. This also lets the
  ALCALDIA row (10% when poles are charged) activate.
- **Visio network as backup of the KMZ (`red_fibra_pg.py`):** the Visio network lives in
  PostgreSQL (`VISIO_DB_*`, schema `red_fibra`, separate from `DB_*`, which holds the KMZ).
  The KMZ still decides the connection point (mufa, then reserva, within 500 m). If it has
  nothing that close, the nearest Visio node (`red_fibra.nodos_cercanos`, `RADIO_BUSQUEDA_M`
  around the client) becomes the route start when it is closer than the KMZ's farther point.
  Candidate rules: estimated coordinates drop out when a real one exists; a MUFA/NODO beats a
  MINI_NODO/ODF less than 50 m closer; `VALIDAR` or an estimated coordinate sets
  `requiere_revision`. A KMZ point with no Visio mufa within `traffic_origin.match_radius_m`
  is also flagged. The response's `origen` block (`fuente`: `red_fibra`, `metodo_anterior`
  or `sin_conexion_bd`) describes the point the route starts from, with the Visio
  alternatives and the date of the last network load. `Punto de conexión` in the Excel gets
  "(Coordenada estimada / validar en campo)" or "(No se encontró nodo de red a menos de X m;
  validar con Planta Externa)" when flagged. If the Visio database is down, everything runs
  on the KMZ and the SQLite file. `GET /origen?lat=&lon=&radio=` returns the same block
  (no route distance) plus `origen_trafico` without generating a budget.
- **Budget note (`budget_note`):** every budget (API/n8n and viewer) shows "Sujeto a
  disponibilidad de postes de concreto sobre la ruta" at the bottom of each page
  (`Ruta proyectada` D70 and `Presupuesto` E91 with the current template: two rows under the
  signatures, in the wide left-aligned column). Change the text or remove the block in
  `business_rules.yaml`; it is never written over a filled cell.
- **Route map (`mapa_ruta.py`):** a 1000x700 satellite image (Esri World Imagery plus Esri
  street labels, zoom up to 18) with the route in yellow, the connection point in green, the
  client in red, nearby network nodes in blue and existing poles in white, plus a legend. It
  is placed, keeping its proportions, inside the "ESQUEMA DE RUTA PROYECTADA" box of
  `Ruta proyectada`. It is added to the package directly, so the template's logos and drawings
  stay. Saved as `output/mapas/<ticket_id>.png` (removed with the other expired output). Tiles
  are downloaded with a 10 s timeout (`route_map.tile_timeout_s`). If they fail, the box says
  "Mapa no disponible" and the budget is still produced. The response's `ruta` block has
  `puntos`, `aproximada` (always false: no Google route means no budget), `mapa_generado`,
  `mapa_archivo` and `google_maps_url`. `route_map.enabled: false` turns the map off.
- **Origen de trafico (MF) / (Nodo):** Nodo = the OLT as the technicians write it
  ("OLT GRUTA XAVIER"); MF = the mufa the node's service is taken from (the mufa carrying
  that label), filled only when the path to it is traced with `alta`/`media` confidence,
  otherwise empty. The connection mufa itself goes in `Punto de conexión`.
- **Traffic-origin node:** read from the Visio network (PostgreSQL, or `red_fibra/red_fibra.db`
  as fallback; built by `red_fibra/importador.py`, path in `RED_FIBRA_DB`). The connection mufa
  and its PostGIS upstream chain are matched to the Visio network, in this order
  (`origen.match_connection`, shared by the API, the viewer and the report):
  a) a Visio mufa within `traffic_origin.match_radius_m` (40 m; an exact name wins);
  b) the nearest one within `fallback_radius_m` (150 m);
  c) **by name** in the Visio nodes: same normalized name (no accents, no MF/MUFA/MN prefixes,
     no IDEAY/UFINET; misspelled words count, numbers must be equal) with similarity
     >= `name_match.min_similarity`, within `name_match.max_distance_m` or without coordinates;
  d) **by name in the diagram texts** (`textos_crudos`): the mufa is drawn without coordinates,
     so the importer made no node for it. The walk starts at the mufa a "SPL DEPENDE DE …" /
     "VIENE DE …" text of that diagram points to (by name or initials: "PM2" = PLAZA MAYOR 2;
     a text naming the OLT itself gives the node directly), else at the diagram's main mufa.
     The drawn name ("MUFA - CASA GERENCIA OTTO MUNKEL") is the first link of the path;
  e) nothing: no path.
  c and d are always `baja`, set `match_method` and `name_match` (file, text, other candidates)
  in `traffic_origin`, and never count the diagram path as intervened mufas (the PostGIS chain
  counts, as with b). Whenever a and b fail, `traffic_origin.diagnostico` says why:
  `a_mayor_distancia` (a similar Visio mufa X m away), `sin_coordenada_en_visio` (drawn in
  diagram <file> without coordinates), `marcada_validar` (the diagram says VALIDAR),
  `no_diagramada` (in no diagram) or `es_reserva` (a reserva: a new mufa is installed). It
  replaces the generic "no mufa within 150 m" message in `warnings`, in `GET /origen`
  (`origen_trafico.diagnostico`, `metodo`, `emparejamiento`) and in the viewer.
  `name_match.enabled: false` keeps only the diagnosis. The network is then walked mufa
  by mufa (Visio cables plus the PostGIS chain) to the nearest mufa whose labels name a
  node after "OLT" or "NODO" ("SPL 1X16 OLT GALERIAS Puerto 6"). Node spellings are
  listed in `traffic_origin.nodes`; backup labels (RESPALDO, REDUNDAN) are ignored.
  Fallbacks: the main mufa of a diagram the connection mufa is drawn in, then the
  diagram folder name. Confidence: `alta` (label on the connection mufa), `media` (up to
  `media_max_hops` mufas away), `baja` (farther, tied nodes or a fallback; the cell shows
  "(validar)" and the field is listed in `pending_validation_fields`). Mufas marked
  SATURADA in the diagrams on that path are reported in `warnings`. Details are in the
  response's `traffic_origin`. If nothing is found or the lookup fails, the cell shows
  "Pendiente de validar" and the budget is still produced. The same node applies to
  GPON and Metro.
- **Cached values:** after generation, LibreOffice (headless, own temporary profile,
  always-recalculate) computes the workbook, and the results are stored as cached
  values for every formula in `Presupuesto` and `Ruta proyectada` inside the original
  package (styles and drawings are untouched). Readers that do not recalculate
  (n8n, pandas, previews) then see real totals. `LIBREOFFICE_PATH` is optional
  (autodetected). If LibreOffice is missing or fails, the budget is still produced,
  `values_cached` is `false` and the reason is in `warnings`; Excel still recalculates
  on open.
- **Excel writes:** the service writes quantities only to the Mano de Obra rows
  12 through 32. The MATERIALES section remains formula-driven by the workbook;
  the service does not overwrite its formulas or labels.
- **Formulas:** openpyxl preserves formulas but does not calculate them; Excel
  recalculates when the generated file is opened.
- **Openpyxl limits:** it preserves formulas, styles and number formats, but may drop
  images, charts or form controls from a template. Check your real template once.
- **Excel download:** each workbook is saved as `OUTPUT_DIR/<client_name>_<budget_id>.xlsx`.
  Characters Windows forbids in file names are removed from `client_name` and
  spaces become `_`. The `budget_id` suffix keeps names unique and is how the
  download endpoint finds the file. The API response includes `budget_id`; download it with
  `GET /presupuesto/{budget_id}/excel` and the same `X-API-Key` header. The ID is
  alphanumeric and the endpoint rejects path traversal.
- **PDF download (`pdf_export.py`):** `GET /presupuesto/{budget_id}/pdf` (same key; the
  POST response gives it as `pdf_url`). LibreOffice converts the workbook on the first
  request and the PDF is saved next to the Excel and reused while it is newer. Only the
  visible sheets at the front are exported (`Ruta proyectada` and `Presupuesto`, one page
  each by the template's print setup); LibreOffice would otherwise also print the hidden
  price catalogs. Cell notes are not exported. One conversion runs at a time. 404 if the
  Excel does not exist, 503 "LibreOffice no disponible" if LibreOffice is not found, 500
  if the conversion fails.
- Retry with backoff (`tenacity`) is used only for Google calls, because Directions
  intermittently returns 5xx / `UNKNOWN_ERROR` / rate-limit responses that succeed on retry.

## Example request / response

Request body:

```json
{
  "ticket_id": "T-1001",
  "client_name": "Juan Perez",
  "client_code": "C05000",
  "sales_exec": "Ana Lopez",
  "contact_name": "Juan Perez",
  "contact_phone": "5880 9994",
  "raw_comment": "Texto original del ticket",
  "technology": null,
  "odf_rack_ports": null,
  "latitude": 12.1364,
  "longitude": -86.2514,
  "service_type": "internet",
  "medium": "fibra",
  "bandwidth": "100 Mbps"
}
```

Response (illustrative structure; prices and totals are calculated by Excel):

```json
{
  "budget_id": "a1b2c3d4e5f607182930abcdef123456",
  "ticket_id": "T-1001",
  "distance_km": 1.85,
  "exceeds_5km": false,
  "status": "ok",
  "connection_point": {
    "latitude": 12.1341, "longitude": -86.2489,
    "segment_id": 4821, "segment_tipo": "aereo",
    "straight_distance_to_segment_m": 312.4
  },
  "route": {"distance_m": 1850.0, "duration_s": 300.0, "turns": 4},
  "budget": {
    "route_distance_m": 1850.0, "turns": 4,
    "existing_poles": 4,
    "quantities": {
      "Instalacion de Fibra Optica Aerea ADSS-FLAT/FTTH (6H - 12H)": 2055,
      "Instalacion de poste metalico tipo tuvo 8 mt.": 48,
      "Instalacion de herraje en poste existente": 4,
      "Visita Técnica (Certificación de FO existente cuantificación de obra)": 1
    }
  },
  "quantities": {"Instalacion de Fibra Optica Area ADSS (24H - 48H)": 2055},
  "pending_validation_poles": [],
  "pending_validation_items": [{"item": "Sangria de Cable o Buffer", "quantity": 0}],
  "excel_path": "/path/to/fiber_budget/output/Juan_Perez_a1b2c3d4e5f607182930abcdef123456.xlsx"
}
```

Errors use `{"error": "...", "detail": "..."}`. For example, a 401 response is
`{"error": "unauthorized", "detail": "Invalid or missing X-API-Key"}`.

## Visor de rutas (escritorio)

Programa local de Windows para ver en un mapa la ruta que usaría el presupuesto y, desde el
menú ☰, generar presupuestos para revisarlos. La interfaz es HTML + Leaflet dentro de una
ventana **pywebview** (motor WebView2 de Windows); la ventana Tkinter anterior queda como
respaldo. No usa el servidor FastAPI, ngrok, puertos ni navegador externo: funciona con la API
encendida o apagada. Los presupuestos del visor se guardan solo en `output/visor/`, **nunca**
en `budget_index.json` ni en el resto de `output/`, y no se envían a nadie. Consulta las bases
(KMZ/PostGIS y Visio) y Google Directions con las credenciales del mismo `.env`.

Todo el código está en `visor_rutas/` y **no modifica** los archivos del servicio: llama a
sus funciones (`main._resolver_conexion`, `main._traffic_origin`, `main._origen_block`,
`db.*`, `routing.get_route`, `presupuesto.*`) con las mismas reglas de `business_rules.yaml`.
El conteo de mufas intervenidas, que en `main.py` está dentro de la generación del
presupuesto, está copiado en `visor_rutas/calculo.py`; la prueba
`test_visor_da_las_mismas_cantidades_que_el_presupuesto` avisa si alguna vez difieren.

```
visor_rutas/
├── __main__.py      # arranque: ventana web, o Tkinter si falla (o con --tk); log en logs/visor.log
├── calculo.py       # calcular_ruta(lat, lon) -> dict, sin interfaz
├── fusion.py        # ruta de fusión (OLT -> mufas -> conexión) y diagrama_svg()/diagrama_png() con LibreOffice
├── presupuesto_visor.py  # presupuestos del visor con main._generar_presupuesto_con: formulario,
│                         # estimación, output/visor, caché de rutas de Google, resumen del Excel
├── excel_html.py    # hoja del Excel generado -> tabla HTML (valores, nunca fórmulas)
├── ventana_web.py   # ventana pywebview + Api para JavaScript (modo local, o remoto con remoto.py)
├── remoto.py        # ProveedorRemoto: los mismos métodos de Api, pedidos a /visor/* por ngrok
├── config_visor.py  # %APPDATA%\VisorRutas\config.json: modo, URL y clave (cifrada con DPAPI)
├── remoto_main.py   # arranque de VisorRutas.exe (siempre remoto; avisa si falta WebView2)
├── kmz_capas.py     # KMZ de la red -> caché del panel Lugares (python -m visor_rutas.kmz_capas)
├── datos_kmz/       # esa caché (se genera sola; datos de la empresa, no va en el .exe)
├── redes/           # módulo de Proyectos y Diagramación de Redes (esquema `redes`; ver abajo)
├── ventana.py       # ventana Tkinter + tkintermapview (respaldo)
└── web/
    ├── visor.html   # estructura: menú lateral, mapa, panel Lugares, panel de resumen, vistas, barra inferior
    ├── visor.css
    ├── visor.js     # mapa, capas, íconos, resumen, historial, medición
    ├── menu.js      # menú lateral: vistas con íconos, contraer a solo íconos
    ├── lugares.js   # panel Lugares: árbol del KMZ, capas, buscador, troncales, secciones propias
    ├── mapa/        # módulos del mapa (visor v2): capas_visor.js = "Mapa base" y "Capas del visor"; coordenadas.js, buscador.js, pin.js = buscador de coordenadas con pincho
    ├── lugares/     # Mis lugares (visor v2): iconos.js, dialogo.js, dibujar_red.js, mis_lugares.js (+ mis_lugares.css); barra_herramientas.js está en mapa/
    ├── redes/       # vistas del módulo de redes (comun.js, usuarios.js, redes.css)
    └── lib/         # copias LOCALES (sin CDN), con sus licencias MIT:
        ├── leaflet/            # Leaflet 1.9.4 (js, css, imágenes)
        ├── markercluster/      # leaflet.markercluster 1.5.3
        └── polylinedecorator/  # leaflet-polylinedecorator 1.6.0
Visor de rutas.bat   # lanzador sin consola (pythonw.exe -m visor_rutas)
```

`visor.html` se abre desde disco (`file://`, sin servidor ni puertos) y solo carga
librerías de `web/lib/`, así funciona aunque la red corporativa bloquee los CDN. JavaScript
llama a Python con `window.pywebview.api.calcular(texto)`; pywebview ejecuta cada llamada en
su propio hilo, por eso la ventana no se congela mientras se calcula. La validación de la
coordenada y todo el cálculo siguen en Python (`calculo.py`).

**Menú lateral** (`web/menu.js`): siempre visible a la izquierda, con ícono y texto. «‹» lo
contrae a solo íconos y «›» lo vuelve a expandir; el estado se recuerda en
`%APPDATA%\VisorRutas\preferencias.json` (pywebview corre en modo privado y no guarda el
`localStorage`). Opciones: **Mapa**, **Presupuestos** (la vista "Generar presupuesto"),
**Proyectos**, **Problemas**, **Pendientes**, **Usuarios**, **Backup** y **Configuración**. La
opción activa se resalta. Las de fases todavía no hechas salen en gris con "Pronto" ("Próximamente"
al pasar el mouse). Abajo se ve el usuario identificado del módulo de redes.

### Módulo de Proyectos y Diagramación de Redes

Especificación: `docs/modulo_redes/ESPECIFICACION.md` (por fases; las imágenes de `img/` son
solo referencia). Los usuarios diseñarán y documentarán sus redes de fibra (postes, mufas,
clientes, cables, hilos, splitters) en PostgreSQL, sin quitar la consulta de las mufas
existentes ni sus diagramas Visio. **No toca** el presupuesto (`main.py`, `/presupuesto`, n8n),
ni `red_lineas` / `red_puntos`, ni el esquema `red_fibra`.

| Fase | Estado |
|---|---|
| 1. Menú, usuarios, migraciones | **hecha** |
| 2. Proyectos (con varios clientes por proyecto) e historial de presupuestos | **hecha** |
| 3. Editor de red en el mapa | **hecha** |
| 4. Editor de mufa (hilos, splitters, conectores, conexiones) | **hecha** |
| 5. Trazado de hilo de punta a punta (panel y mapa), y secciones 5.1–5.3 completas | **hecha** |
| 6. Diagrama lógico de red automático, con leyenda y exportación PNG / PDF | **hecha** |
| 7. Problemas, Pendientes y Backup (respaldo, restauración, exportación KMZ / GeoJSON) | **hecha** |
| Sección 8. Datos y arquitectura: revisión del modelo, migración 008, verificación de integridad, `docs/modulo_redes/ARQUITECTURA.md` | **hecha** (espera el OK de Jan) |

**Migración de los Visio a mufas interactivas** ([docs/migracion_visio/PLAN.md](docs/migracion_visio/PLAN.md); por fases, cada una con el OK de Jan):

| Fase | Estado |
|---|---|
| 0. Diagnóstico ([FASE0_DIAGNOSTICO.md](docs/migracion_visio/FASE0_DIAGNOSTICO.md)): cobertura medida, modelo, reglas | **hecha y aprobada** |
| 1. Modelo: migración `009_red_existente.sql` (respaldo automático previo) y `migracion_visio` en `business_rules.yaml` | **hecha y aprobada** |
| 2. Migrar toda la red base (`visor_rutas/redes/migrar_visio.py`, reporte Excel en `output/migracion_visio/`) | **hecha y aprobada** |
| 3. Splitters, clientes y empalmes (`visor_rutas/redes/migrar_visio_contenido.py`, corre con el mismo comando) | **hecha y corrida en real** el 2026-10-13 (espera el OK de Jan) |
| 4. Modelo y bandejas · 5. Interactividad · 6. Tablero · 7. Reimportación | pendientes |

Uso de la migración (lee `red_fibra` y el KMZ solo para leer; antes de escribir hace un respaldo; es idempotente: lo ya migrado no se repite):

```powershell
.\.venv\Scripts\python.exe -m visor_rutas.redes.migrar_visio --simular              # solo el reporte Excel, no escribe
.\.venv\Scripts\python.exe -m visor_rutas.redes.migrar_visio                        # migra (respaldo previo + reporte)
.\.venv\Scripts\python.exe -m visor_rutas.redes.migrar_visio --zona "León"          # un proyecto base o una carpeta Visio
.\.venv\Scripts\python.exe -m visor_rutas.redes.migrar_visio --solo-mufas lista.txt # un nombre de mufa por línea
```

La red migrada queda en 13 **proyectos base** ("Red existente – Managua", "– León"…): todos los ven sin estar asignados y los editores pueden editarlos. La región sale de la carpeta del Visio (`migracion_visio.proyectos_base`); una mufa de una ruta troncal sin región va a la región cuyo centro tiene a menos de `troncales_a_region_km` (5 km). Si cambian esas reglas, la siguiente corrida **mueve** lo ya migrado (con su contenido), salvo lo que un usuario editó.

Dentro de cada mufa (fase 3): splitters con OLT, puerto OLT y potencia; la salida de cada splitter con su cliente (de las listas numeradas del Visio); el botón **Clientes (N)** con los clientes de la mufa sin puerto conocido; los clientes ubicados en el mapa (punta de su acometida del KMZ), y los empalmes del Excel de anillos. Al pasar sobre un empalme se ve de dónde salió el dato. Las mufas sin coordenada quedan "sin ubicar" (no se dibujan; el mapa dice cuántas hay) y los cables sin cantidad de hilos se ven grises con "hilos desconocidos" hasta que alguien la indique.

**Arquitectura y modelo de datos:** [docs/modulo_redes/ARQUITECTURA.md](docs/modulo_redes/ARQUITECTURA.md) (diagrama entidad-relación, diccionario de cada tabla, reglas de versión, borrado lógico e historial, flujo local y remoto, módulos, permisos, respaldos y cómo agregar una tabla o un método).

**Base de datos:** esquema `redes` en `Presupuesto_visio` (`VISIO_DB_*` del `.env`), con
**PostGIS** activado (`CREATE EXTENSION postgis`, instalado dentro del esquema `redes`, así
`public` no se toca). Tablas de la fase 1:

| Tabla | Contenido |
|---|---|
| `migraciones` | scripts aplicados (versión, nombre, checksum, fecha) |
| `usuarios` | nombre, correo, rol (administrador / editor / lector), persona del visor, usuario de Windows |
| `proyectos` | código único, nombre, proyecto padre, ubicación y área (geometry 4326), imagen (bytea ≤ 2 MB) |
| `proyecto_usuarios` | usuarios con acceso a cada proyecto |
| `historial` | auditoría: fecha, usuario, proyecto, entidad, acción y cambio (`{"campo": [antes, después]}`) |

- **Versión por registro (bloqueo optimista):** si otro usuario guardó antes, el visor avisa ("Recargue") y no pisa su cambio.
- **Borrado lógico** (`borrado_en`): nada se elimina de verdad y siempre se puede recuperar.
- **Migraciones** en `visor_rutas/redes/migraciones/NNN_nombre.sql`. Se aplican solas la primera vez que el visor (o `/visor/redes/*`) usa la base, solo las que faltan, con un *advisory lock* para que dos procesos no las apliquen a la vez. A mano: `.\.venv\Scripts\python.exe -m visor_rutas.redes.migrar`.

**Usuarios** (menú → Usuarios). Nadie escribe su nombre: cada persona se identifica sola al abrir el visor.
- En esta PC (modo local), por su **usuario de Windows**. Si todavía no hay ningún administrador activo, queda como **administrador**.
- En otra PC (`VisorRutas.exe`), por su **X-Visor-Key**: la "persona" de `VISOR_API_KEYS`, nunca un nombre enviado por el cliente. Entra como **lector**; una clave remota nunca se vuelve administradora sola.
- **Roles:** administrador (todo, incluidos los usuarios), editor (edita los proyectos donde está asignado) y lector (solo los ve).
- El administrador crea y edita usuarios, ve su historial y los **desactiva o reactiva** (borrado lógico). Siempre debe quedar al menos un administrador activo.

**Proyectos** (menú → Proyectos; `visor_rutas/redes/proyectos.py`, `web/redes/proyectos.js`, migración `002_proyectos.sql`):
- **Lista** con "Filtrar proyectos" (nombre, identificador o descripción). Los subproyectos aparecen debajo de su proyecto principal.
- Cada tarjeta lleva la miniatura y las acciones **Información**, **Historial** (quién cambió qué y cuándo), **Editar datos**, **Duplicar** y **Eliminar**. Eliminar pide confirmación y es borrado lógico: un administrador marca *Ver eliminados* y **Restaura**. Clic en la tarjeta: abre el proyecto en el editor de red del mapa.
- Botón **+ Crear proyecto** abajo a la derecha.
- **Datos del proyecto:**
  - **imagen** PNG/JPG/WEBP/GIF de hasta 2 MB, guardada en la base con una miniatura de 160 px; los SVG no se aceptan porque pueden llevar scripts;
  - **nombre** e **identificador** obligatorios; el identificador es único entre los proyectos activos, sin espacios;
  - **usuarios con acceso**, **proyecto principal** (jerarquía; no se permiten ciclos) y descripción;
  - **buscar por dirección**: Google Geocoding con la clave del `.env`, Nicaragua primero. También se puede pegar una coordenada `lat, lon`, que no usa Google;
  - **minimapa** Mapa/Satélite: clic o arrastrar el marcador para la ubicación;
  - **Diseñar área**: polígono con Leaflet-Geoman, editable moviendo sus vértices; si se cruza consigo mismo se rechaza.
  - **Clientes del proyecto** (varios por proyecto):
    - cada uno con nombre, código C##### (único en el proyecto), ID de servicio y coordenada;
    - **＋ Agregar en el mapa** (cada clic agrega uno; con ese modo, la dirección o una coordenada pegada también agregan un cliente) y **Pegar coordenadas** (una por línea: `lat, lon[, nombre][, código]`);
    - marcadores verdes arrastrables;
    - son elementos tipo `cliente` de `redes.elementos`, los mismos que dibuja el editor de mapa.
- **Permisos:**
  - administrador: todos los proyectos;
  - editor: crea proyectos (queda asignado) y edita los suyos;
  - lector: solo ve los suyos.
- No se puede eliminar un proyecto con subproyectos activos. Para restaurarlo, su identificador debe seguir libre.
- **Duplicar** copia los datos, la imagen, el área y los usuarios, con identificador `-COPIA`, y también la red: elementos, cables, notas, hilos con su estado, splitters, conectores y conexiones de cada mufa.
- En remoto, la búsqueda de dirección **sí cuenta** para el límite por hora, porque usa Google.

**Editor de red en el mapa** (fase 3; clic en la tarjeta del proyecto; `web/redes/editor_mapa.js`, `visor_rutas/redes/red.py`, migraciones `003_elementos.sql` y `004_cables_notas.sql`):
- El mapa principal entra en **modo edición del proyecto**. Siguen las capas del visor (Lugares/KMZ, Visio, ruta); encima se ven el área del proyecto (línea punteada) y su red.
- Arriba aparece la franja del proyecto: nombre, "N cambios sin guardar", la **paleta**, deshacer/rehacer, **Guardar** y **Cerrar proyecto**.
- **Paleta** (arrastrar y soltar en el mapa, o clic y luego clic en el mapa):

  | Elemento | Datos |
  |---|---|
  | Poste | concreto / IDEAY / madera / metal / cliente |
  | Mufa | empalme, distribución (FDT, cuadro amarillo) o terminal (FAT, círculo magenta); capacidad en hilos y bandejas |
  | Cliente | código C#####, ID de servicio |
  | Nodo / OLT | triángulo |

  Al soltar se pide el **nombre** (obligatorio) y los datos del tipo.
- **Cable:**
  - se piden nombre, clase (troncal / distribución / acometida), tipo **ADSS o FLAT** (FLAT se dibuja con guiones), **hilos** (12–144), **hilos por buffer** (8 o 12), **color**, cruces de calle y descripción;
  - se dibuja con clic en el elemento de inicio, puntos intermedios y el elemento final. Los clics cerca de un poste o mufa **se pegan** a él (18 px), y un clic en una mufa, cliente o nodo termina el cable;
  - doble clic o Enter terminan en el último elemento, Retroceso quita un punto y Esc cancela;
  - con el cable seleccionado, sus vértices se arrastran (cerca de un elemento se pegan), doble clic en un vértice lo quita y el **+** a mitad de tramo agrega uno.
- **Metraje** al pasar el mouse por un cable, con distancia lineal, contingencia, salida de nodo y reservas por mufa, tendido, cruce y cliente. Usa la sección `diseno_red` de `business_rules.yaml`, que tiene **los mismos valores del presupuesto** (decisión de Jan): 0 % de contingencia, 35 m por extremo en mufa, cada 300 m un 20 %, y 0 en cruce, nodo y cliente.
- **Seleccionar** (clic) muestra abajo un inspector con *Editar* (F2), *Duplicar* y *Eliminar* (Supr). **Mover**: arrastrar; los cables pegados y las notas ancladas lo siguen. Eliminar un elemento con cables pide confirmación: los cables que terminan en él se eliminan y los que solo pasan quedan despegados.
- **Notas** con formato (Quill: letra, tamaño, negrita, cursiva, colores, listas, alineación), sueltas en el mapa o **ancladas** a un elemento. El HTML se sanea en el servidor (`redes/texto.py`).
- **Deshacer / rehacer** (Ctrl+Z / Ctrl+Y). **Guardar** (Ctrl+S) es explícito y aplica todo en **una transacción**: si otro usuario guardó antes alguno de los registros, nada se guarda y se ofrece recargar. "Cerrar proyecto" avisa si hay cambios sin guardar. Cada cambio queda en el historial del proyecto.
- **Enter o doble clic sobre una mufa:**
  - **del proyecto** → **editor de mufa** (ver abajo). La mufa debe estar guardada y el mapa sin cambios pendientes;
  - **existente de la red** (punto de una carpeta MUFA en Lugares, o nodo Visio) → su **diagrama Visio** en el panel Diagrama, con el mismo visor de "Ver diagrama" (selector si tiene varios). El popup de esas mufas también tiene el botón *Ver diagrama Visio*.
- Un **lector** ve el proyecto sin paleta ni edición. Duplicar un proyecto copia también su red.
- **Librerías nuevas:** `web/lib/quill/` (Quill 2.0.3, BSD-3).

**Editor de mufa** (fase 4; Enter o doble clic en una mufa del proyecto; `web/redes/editor_mufa.js` con Konva, `visor_rutas/redes/mufa.py`, migración `005_mufa.sql`):
- Ventana grande (con botón maximizar) con **solo lo que entra y sale de esa mufa**:
  - los cables que **llegan**, a la izquierda; los que **salen**, a la derecha;
  - cada cable tiene un encabezado `Cable | origen | destino | hilos`, una barra por buffer y sus hilos numerados con los **colores TIA-598**: 1 azul, 2 naranja, 3 verde, 4 café, 5 gris, 6 blanco, 7 rojo, 8 negro, 9 amarillo, 10 violeta, 11 rosa, 12 aqua. Con 8 hilos por buffer, los colores se repiten cada 8;
  - los hilos de cada cable se crean solos al guardar el cable en el mapa. Si se cambia la cantidad de hilos, se agregan los que faltan o se dan de baja los que sobran. No se puede reducir si alguno de los hilos sobrantes está conectado: primero hay que quitar esas conexiones.
- **Conectar:** arrastrar desde un hilo (círculo) hasta otro hilo o hasta un puerto de un splitter o conector.
  - La línea es ortogonal y del color del hilo (la salida de un splitter toma el color del hilo que lo alimenta).
  - Una **fusión** une hilos de cables distintos.
  - Cada hilo y cada puerto admite una sola conexión en la mufa.
- **Splitters** 1x2, 1x4, 1x8, 1x16, 1x32 y desbalanceados 1x2 70/30, 80/20, 90/10 (solo 1x2; la relación debe sumar 100), con tipo de conector (RC, APC…).
  - Se agregan en la columna central.
  - Doble clic, F2 o Enter para editarlos.
  - No se puede reducir el número de salidas si hay salidas conectadas por encima del nuevo tamaño.
- **Conectores** (adaptadores) con entrada y salida.
- **Estado de cada hilo** (clic derecho o el selector *Estado del hilo*):

  | Estado | Cómo se ve |
  |---|---|
  | Activo | color normal |
  | Fibra oscura | gris y punteado |
  | Cliente de baja | borde rojo punteado |
  | Reservado | borde azul |
  | Dañado | borde rojo con una ✕ |

- **Tooltips** (sección 5.1 de la especificación):
  - **del cable**, al pasar el mouse por su marco, su encabezado o sus **barras de buffer**:
    - nombre, clase, tipo, hilos (por buffer y cantidad de buffers), origen → destino;
    - estado de sus hilos (por ejemplo, "46 activos · 1 en fibra oscura · 1 dañado");
    - cuántos hilos están conectados aquí y en la mufa del otro extremo;
    - **METRAJE = N m** con su detalle, como en la imagen 06: distancia lineal, contingencia, salida de nodo, y N° de reservas × mufa, × tendido y × cruce (cantidad, und × m, total);
  - **del hilo**: color y buffer, estado (con su observación), con qué está conectado aquí y en el otro extremo, los datos del cable y el mismo detalle de metraje.
- **Caja de destino al final de cada hilo en uso** (sección 5.3, como en la imagen 08): cada hilo conectado en esta mufa, o en la del otro extremo, lleva una caja con el color del hilo y su destino.
  - El texto es, por ejemplo, «→ FAT 1 · Conector A (entrada)», «← Nodo Central · sin conectar allá» o «→ Casa Pérez · cliente».
  - Así, desde el troncal se ve a qué mufa o cliente sigue cada hilo.
  - Doble clic en la caja (o seleccionar el hilo y Enter) abre el editor de esa mufa. La caja sale en cursiva si el hilo solo está conectado en el otro extremo.
- **Tooltip de los puertos** de splitters y conectores: a qué están conectados y, si siguen por un hilo, hacia dónde (por ejemplo, «Splitter 1 salida 1 · 1x8 · Conectado a: Drop FAT 1 hilo 1 · Sigue hacia FAT 1 · Conector A (entrada)»). Si el puerto está libre, también lo dice.
- **Caja «→ destino»** de cada cable (abajo): doble clic (o seleccionar el cable y Enter) abre el editor de la mufa o nodo del otro extremo. Las **migas de pan** (`Proyecto › MF Norte › FAT 1`) permiten volver. Si hay cambios sin guardar, pregunta antes de salir.
- **Notas** con formato (Quill) sobre el lienzo, arrastrables.
- **Edición del lienzo:**
  - eliminar con Supr (líneas, splitters, conectores, notas);
  - alinear y distribuir (Ctrl+clic para elegir varios); *Ordenar* vuelve a la distribución automática;
  - deshacer y rehacer (Ctrl+Z / Ctrl+Y);
  - zoom con la rueda, desplazamiento arrastrando el fondo, *Ajustar*.
  - Las posiciones de los cables, splitters y notas se guardan por mufa.
- **Aplicar** (Ctrl+S) guarda sin cerrar y **Guardar / Cerrar** guarda y sale.
  - Todo se guarda en una transacción, con bloqueo optimista, y queda en el historial del proyecto.
  - Las validaciones también se hacen en el servidor: el hilo debe pertenecer a un cable de esa mufa, la fusión debe unir cables distintos, y hay una conexión por hilo y por puerto.
- **Al cambiar la red en el mapa:**
  - eliminar un cable quita sus conexiones y da de baja sus hilos;
  - si el cable deja de llegar a una mufa, se quitan las conexiones que tenía allí;
  - eliminar una mufa quita sus splitters, conectores y conexiones.
  - Todo es borrado lógico.
- *Código QR* aparece desactivado (opción futura).
- **Tablas nuevas:**

  | Tabla | Contenido |
  |---|---|
  | `hilos` | número y estado por cable |
  | `mufa_cables` | posición de cada cable en cada mufa |
  | `splitters`, `conectores` | elementos dentro de la mufa |
  | `puertos` | puertos de splitters y conectores |
  | `conexiones` | extremo A ↔ extremo B; cada extremo es un hilo o un puerto |

- **Librería nueva:** `web/lib/konva/` (Konva 9.3.18, MIT).

**Trazado de hilo** (fase 5; `visor_rutas/redes/trazado.py`, `web/redes/trazado.js`; sin tablas nuevas, solo lee):
- **Cómo se abre:**
  - en el editor de mufa: seleccionar un hilo y presionar *Trazar hilo*, la tecla **T**, o clic derecho → *Trazar este hilo*;
  - en el mapa: seleccionar un cable, escribir el número de hilo en el inspector y presionar *Trazar hilo* (o Enter).
- **Qué hace:** sigue la fibra en los dos sentidos de su cable (hacia el origen y hacia el destino). En cada mufa mira la conexión del hilo:

  | Conexión en la mufa | El trazado… |
  |---|---|
  | fusión con otro hilo | sigue por el cable de ese hilo |
  | entrada de un splitter | abre un camino por cada salida conectada |
  | salida de un splitter | sube por su entrada |
  | conector | pasa al otro lado |
  | ninguna | termina: **sin continuidad** |

  Un cable que llega a un cliente termina el camino en ese cliente. Llegar a un nodo sin más conexiones también lo termina.
- **Panel de trazado** (a la derecha):
  - resumen: a qué cliente(s) llega el hilo y cuántos caminos quedan sin continuidad;
  - cada camino paso a paso: tramos de cable con el número y color del hilo, fusiones, splitters (qué salida), conectores, y el final;
  - distancia de cada camino (suma de las longitudes de los cables) y avisos de hilos que no están activos (dañado, fibra oscura…);
  - clic en una mufa del recorrido: abre su editor de mufa.
- **Resaltado:**
  - en el editor de mufa, las conexiones y hilos del recorrido se ven con brillo amarillo y el resto se atenúa (también al navegar a otra mufa);
  - *Ver en el mapa* cierra el editor de mufa (si hay cambios sin guardar, pregunta) y resalta en amarillo los cables y elementos del recorrido en el mapa del proyecto, con la etiqueta del cliente al que llega.
  - Cerrar el panel quita el resaltado.
- **Usa lo guardado:**
  - en el editor de mufa, si hay cambios sin aplicar, ofrece *Aplicar y trazar*;
  - al aplicar con el panel abierto, el trazado se actualiza;
  - en el mapa, avisa si el cable tiene cambios sin guardar.
- Sirve también para un lector: solo lee. En remoto, `POST /visor/redes/trazar_hilo`, sin contar para el límite por hora.
- **Límites:** hasta 400 caminos por trazado (por ejemplo, 1x8 seguido de 1x32 da 256). Los recorridos que vuelven sobre sí mismos se cortan con el aviso "vuelve sobre sí mismo".

**Diagrama lógico de red** (fase 6; `visor_rutas/redes/diagrama.py`, `web/redes/diagrama.js`, migración `006_diagramas.sql`):
- **Cómo se abre:** el botón *Diagrama lógico* en la tarjeta del proyecto, en la franja del editor de mapa, o en el editor de mufa (desde esta mufa).
- **Ventana "Diagrama lógico de red":**
  - arriba, el **formulario**: título (se llena solo), **elemento de inicio** (nodo / OLT, mufa o splitter), **dirección** (derecha o izquierda) e *Incluir inmuebles / clientes*, con *Generar*, *Guardar* y *Nuevo*;
  - debajo, la **tabla de diagramas guardados** del proyecto: título, elemento, caja, dirección e incluir clientes. Clic en una fila genera ese diagrama y la papelera lo elimina;
  - el diagrama se dibuja abajo.
- **Se genera automáticamente** de las conexiones **guardadas**; el diagrama guardado solo recuerda el inicio, la dirección y lo de los clientes:
  - desde el inicio se siguen "hacia adelante" los cables que **salen** de cada caja (origen → destino, como se dibujaron en el mapa), caja por caja;
  - cada caja muestra su símbolo, nombre y splitters, por ejemplo «FAT 1 (1x8)». Adentro van sus splitters y conectores, y líneas internas de cuántos hilos van de la entrada a cada splitter y de cada splitter a cada salida (×N);
  - entre cajas van los cables con nombre, hilos y usados, coloreados **por capacidad**;
  - si se arranca en un splitter, en esa caja solo se siguen los cables que salen de ese splitter;
  - sin "incluir clientes", la caja dice «+ N clientes (no incluidos)».
- **Leyenda FTTH:**

  | Símbolo | Elemento |
  |---|---|
  | triángulo naranja | OLT / nodo |
  | círculo rojo | SC (mufa de empalme) |
  | cuadro amarillo | FDT (mufa de distribución) |
  | círculo magenta | FAT (mufa terminal) |
  | punto morado | derivación (la caja reparte a 2 o más cables) |

  Los colores de cable por capacidad (144 rojo, 48 morado…) se cambian en `business_rules.yaml` → `diagrama_logico.colores_capacidad`. No afectan el presupuesto.
- **Uso:** zoom con la rueda, desplazamiento arrastrando, *Ajustar*. **Clic en una caja** abre su editor de mufa.
- **Exportar PNG / PDF:** el dibujo completo, con título, fecha y leyenda, se guarda donde se elija (diálogo de Windows). El PDF es de una página, hecho con Pillow, y funciona igual en el `.exe`.
- **Permisos:** un lector ve y genera diagramas, pero no los guarda. *Duplicar* proyecto copia también sus diagramas guardados. Si se elimina el elemento de inicio, la tabla lo marca "eliminado" y hay que elegir otro.

**Problemas** (fase 7.1; menú → Problemas; `visor_rutas/redes/problemas.py`, `web/redes/problemas.js`, migración `007_problemas_pendientes.sql`):
- Cada problema está ligado a un **elemento** (mufa, poste, cliente, nodo) o a un **cable** de un proyecto.
- **Datos:**
  - título;
  - descripción;
  - **severidad:** baja, media, alta o crítica;
  - **estado:** abierto, en proceso o cerrado; al cerrarlo se guarda la fecha;
  - **fotos:** hasta 6, de PNG, JPG, WEBP o GIF de hasta 2 MB, con miniatura. Clic en una foto la muestra completa;
  - quién lo reportó y quién lo cambió (historial).
- **Lista** con filtros por proyecto, estado (por defecto, abiertos y en proceso), severidad y texto. Botón *Mapa* en cada fila.
- **En el mapa del proyecto:**
  - los problemas se ven como **íconos de alerta** del color de su severidad: verde, amarillo, naranja o rojo; los cerrados, atenuados;
  - el filtro está en la franja del proyecto: abiertos, abiertos de severidad alta y crítica, todos, u ocultar;
  - el ícono sigue al elemento si se mueve;
  - clic en un ícono muestra un resumen con la foto y el botón *Abrir*;
  - el inspector de cada elemento o cable tiene **⚠ Problema** (reportar uno ahí) y **Pendiente**.
- **Permisos:** cualquier usuario con acceso al proyecto puede reportar un problema, incluido un lector (quien está en campo). Lo cambian, cierran o eliminan quien edita el proyecto o quien lo reportó.

**Pendientes** (fase 7.2; menú → Pendientes; `visor_rutas/redes/pendientes.py`, `web/redes/pendientes.js`):
- Tareas de un proyecto, por ejemplo "validar existencia de mufa" o "dar continuidad a hilos". Se pueden ligar a un elemento o cable.
- Cada tarea tiene **responsable** (usuarios del proyecto y administradores), **fecha límite** y **estado** (por hacer, en proceso, hecho).
- **Lista** con filtros: proyecto, estado (por defecto, por hacer y en proceso), responsable (asignados a mí, sin responsable), *Solo vencidos* y texto.
- Las **vencidas** se ven en rojo. El botón **✓ Hecho** de cada fila la cierra rápido.
- **Permisos:** las crea, edita y elimina quien edita el proyecto. El **responsable** puede cambiar el estado aunque sea lector.

**Backup** (fase 7.4; menú → Backup; `visor_rutas/redes/respaldo.py`, `web/redes/respaldos.js`):
- **Crear respaldo** (solo administradores) escribe en la carpeta de respaldos del servidor, con fecha y hora:
  - `respaldo_redes_AAAA-MM-DD_HHMMSS.json`: **todos los proyectos con todo su contenido** (datos e imagen, usuarios, elementos, cables, notas, hilos y sus estados, lienzos de mufa, splitters, conectores, conexiones, diagramas, problemas con fotos y pendientes);
  - además, `…sql`: el esquema `redes` completo con **pg_dump**, si está instalado. Se busca en `C:\Program Files\PostgreSQL\*\bin` o en el PATH; `REDES_PG_DUMP` en el `.env` lo fija. Sirve para recuperar la base entera con `psql`.
- **Carpeta:** `respaldos_redes\` junto al proyecto, o la que diga `REDES_RESPALDOS_DIR` en el `.env`. La pantalla la muestra. **Contiene datos:** no se publica, igual que `output\`.
- **Lista de respaldos:** fecha, quién lo creó, proyectos, tamaño y si tiene el `.sql`, con *Descargar* (`.json` o `.sql`) y **Restaurar…**:
  - se elige un proyecto del respaldo y, con confirmación, se crea una **copia nueva** con identificador `-R1`, `-R2`… y nombre "(restaurado AAAA-MM-DD)";
  - **nunca pisa el proyecto actual**;
  - queda en el historial.
- **Verificar la base** (solo administradores; también `.\.venv\Scripts\python.exe -m visor_rutas.redes.verificar`) revisa 12 reglas que cruzan tablas y solo lee:
  - **errores:** hilos completos y con su buffer y color; conexiones con hilos o puertos válidos y de cables que llegan a esa mufa; un hilo conectado una vez por mufa; salidas de splitter dentro de su tamaño; cables sin extremos eliminados;
  - **avisos:** vértices, diagramas, problemas o pendientes que apuntan a algo eliminado o a un usuario desactivado.
- **Exportar un proyecto** (cualquier usuario que lo puede ver):
  - **KMZ** para Google Earth: carpetas Área, Nodos / OLT, Mufas, Postes, Clientes, Cables (con su color y grosor por clase) y Problemas, con los íconos dentro del KMZ, así se abre sin internet;
  - **GeoJSON** con los mismos elementos y sus datos, para un SIG.
- Los archivos se guardan donde se elija, con el diálogo de Windows (`Api.guardar_archivo`), también en el `.exe`.

**Historial de presupuestos** (menú → Presupuestos → pestaña *Historial*):
- Lista los Excel que generó el visor en `output/visor/` (en remoto, los del servidor), del más nuevo al más viejo, con cliente, fecha y coordenada leídos del nombre del archivo.
- Tiene filtro y la casilla *Incluir aproximados*.
- Clic en uno: se ven sus hojas, el PDF, *Guardar como…* y *Abrir en Excel*, igual que un presupuesto recién generado.
- En remoto: `GET /visor/presupuestos` y `/visor/presupuestos/{id}`, con ids en vez de rutas del servidor.

**Código:**
- `visor_rutas/redes/`:
  - `db.py`: conexión de lectura y escritura propia del módulo; la de `red_fibra_pg` sigue siendo de solo lectura.
  - `migrar.py`.
  - `repositorio.py`: versión e historial en la misma transacción.
  - `usuarios.py`, `proyectos.py`, `elementos.py` (clientes del proyecto), `red.py` (red del editor), `mufa.py` (editor de mufa), `trazado.py` (trazado de hilo), `diagrama.py` (diagrama lógico), `problemas.py`, `pendientes.py`, `respaldo.py` (backup y exportación KMZ / GeoJSON), `verificar.py` (integridad), `metraje.py`, `texto.py` (HTML seguro), `lugares.py`, `lugares_kmz.py`, `lugares_iconos.py` y `lugares_red.py` (Mis lugares y su red).
  - `api.py`: `ServicioRedes.llamar(metodo, args)`, con una lista cerrada de métodos.
- `web/lib/geoman/`: Leaflet-Geoman free 2.17.0 (MIT), copia local.
- **Modo local:** `ventana_web.Api.redes(metodo, args)`.
- **Modo remoto:** `POST /visor/redes/{metodo}` `{"args": {...}}` con `X-Visor-Key`. No cuenta para el límite por hora.
- El `.exe` lleva solo las páginas (`web/menu.js`, `web/redes/`); el backend del módulo corre en el servidor.

**Pruebas** (`Pruebas/test_redes_base.py`, `test_redes_proyectos.py`, `test_redes_editor.py`, `test_redes_mufa.py`, `test_redes_trazado.py`, `test_redes_diagrama.py`, `test_redes_fase7.py`, `test_redes_seccion8.py`, `test_redes_visio_modelo.py`): usan una base temporal `redes_pruebas_<pid>_<azar>` en el PostgreSQL local, que se crea y se borra en cada corrida. Nunca tocan `Presupuesto_visio`: el código se niega a borrar cualquier base cuyo nombre no empiece por `redes_pruebas`. Sin PostgreSQL esas pruebas se saltan.

**Instalar** (una vez, sin permisos de administrador):

```powershell
.\.venv\Scripts\python.exe -m pip install pywebview tkintermapview
```

pywebview usa el motor **WebView2** (viene con Windows 10/11 actualizados y con Edge). Si
pywebview no está instalado o WebView2 falla, el visor anota el motivo en `logs/visor.log` y
abre la ventana Tkinter.

**Abrir:** doble clic en `Visor de rutas.bat`, o desde la carpeta del proyecto
`.\.venv\Scripts\pythonw.exe -m visor_rutas`. Para forzar la ventana Tkinter:
`.\.venv\Scripts\pythonw.exe -m visor_rutas --tk`.

**Acceso directo en el Escritorio:** clic derecho en `Visor de rutas.bat` → *Mostrar más
opciones* → *Enviar a* → *Escritorio (crear acceso directo)*. Para cambiar el ícono: clic
derecho en el acceso directo → *Propiedades* → *Cambiar icono…*.

**Uso (ventana web):**
- **Barra inferior:** pegue la coordenada del cliente (`12.153328, -86.263438`; también con
  espacio o punto y coma) y presione Enter o *Generar ruta*. Python valida que esté dentro de
  Nicaragua y avisa si latitud y longitud parecen invertidas; el mensaje sale en rojo. Mientras
  calcula se muestra "Calculando…" y el botón queda desactivado. El botón ▾ (o la flecha ↓)
  muestra las últimas 10 coordenadas (solo mientras el visor está abierto). *Limpiar* borra la
  ruta y el resumen.
- **Capas** (un solo panel: las secciones *Mapa base* y *Capas del visor* arriba del árbol de
  **Lugares**; ya no hay un recuadro flotante aparte): *Satélite* = Esri World Imagery +
  nombres de calles Esri World Transportation; *Calles* = Esri World Street Map. Casillas
  (con la casilla de tres estados del encabezado) para mostrar u ocultar: postes existentes,
  postes nuevos, mufas en ruta, mufas intervenidas, nodos Visio cercanos, camino de la fibra,
  mufa buscada, mis medidas y la red Visio completa. Las que se llenan con un cálculo quedan
  **deshabilitadas, con un tooltip** ("se llena al generar una ruta / al buscar una mufa / al
  medir en el mapa") hasta que haya algo que mostrar; las dos de *Red Visio* indican su zoom
  mínimo (12). Los botones **＋ / −** del zoom están abajo a la derecha y se corren a la
  izquierda cuando el panel derecho está abierto; la pestaña *Lugares ›* (panel plegado) ya
  no queda tapada. Los `z-index` de todo lo que flota sobre el mapa están en una sola tabla
  (variables `--z-*` al inicio de `visor.css`).
- **Mapa:** ruta amarilla con borde oscuro y flechas de la conexión hacia el cliente (naranja
  punteada si es aproximada); acometida al cliente en verde punteado (desde 1 m, igual que
  el mapa del Excel). Punto de conexión = pin verde y cliente = pin rojo, con el nombre
  siempre visible; mufas en ruta = naranja; mufas intervenidas = naranja con borde grueso;
  nodos Visio = rombo azul; postes existentes = blanco; postes nuevos = gris (agrupados al
  alejar el zoom). Al pasar el mouse se ve el nombre; con clic, un popup con tipo, distancia,
  notas, coordenada y *Copiar coordenada*. Al generar, el zoom abarca todos los elementos.
  La leyenda (abajo a la izquierda) se pliega con un clic.
- **Postes nuevos que ya existen:** clic en un poste nuevo (gris) lo marca como existente
  (blanco con borde verde, pasa a la capa *Postes existentes*); otro clic lo vuelve a nuevo, y
  *Desmarcar todos* en la tarjeta *Postes* los restablece. Cada marca baja en 1 la instalación
  de poste nuevo (y el material POSTE 8 MTRS) y sube en 1 los postes existentes; el herraje no
  cambia porque el total de postes es el mismo. El presupuesto aproximado se recalcula solo
  y *Generar presupuesto* aplica las marcas si la coordenada del formulario es la de la ruta del
  mapa. Las marcas viajan como metros de la ruta y el servicio solo acepta las que coinciden
  con un poste nuevo de esa ruta (las demás se avisan y se cobran como nuevas). Los postes
  extra por esquina no tienen posición y no se pueden marcar. `POST /presupuesto` (n8n) no
  cambia.
- **Panel de resumen** (derecha, **oculto hasta que haya un resultado**: se abre solo al generar
  una ruta, al buscar una mufa o al terminar una medida; 300 px de ancho, se redimensiona
  arrastrando su borde y se contrae con ❯ a una pestaña lateral; *Limpiar* lo cierra si no queda
  nada que mostrar): avisos en amarillo, punto de conexión
  (nombre, tipo, fuente, distancia lineal, "Validar en campo"), distancia por ruta, acometida,
  reserva y metraje final, tipo de cable, postes existentes y nuevos, mufas intervenidas (lista
  y fuente), origen de tráfico (nodo OLT, MF, confianza, camino), nodos Visio cercanos y mis
  medidas. *Copiar resumen* copia todo en texto plano.
- **Clic derecho en el mapa:** *Usar esta coordenada* (llena el campo), *Copiar coordenada*
  y *Medir desde aquí*.
- **Medir:** botón *📏 Medir* (o *Medir desde aquí*). Cada clic agrega un punto; mientras se
  mueve el mouse se ve el tramo y el total en metros. Doble clic, Enter, clic derecho o
  *✔ Terminar medida* terminan; Retroceso quita el último punto; Esc cancela. Los clics cerca
  de un punto de la ruta, un poste, una mufa o un nodo se pegan a ese punto. La medida queda
  con los metros de cada tramo y el total; con clic sobre ella se puede copiar o borrar.
  **Varias medidas sin borrar la anterior:** mientras mide, *＋ Nueva medida* (o la tecla
  **N**) guarda la medida en curso y empieza otra de inmediato **de otro color** (8 colores
  que se distinguen sobre el satélite, en ciclo). Cada medida conserva su color en la línea,
  los puntos, la etiqueta y la lista *Mis medidas* del panel (con una muestra del color y la
  suma de todas). *Borrar medidas* las quita todas; *Limpiar* no las borra. La distancia es
  la geodésica (haversine, la misma fórmula que usa el servicio).
  **Metraje final y total:** al terminar una medida el visor calcula, con las reglas de negocio
  (`business_rules.yaml`, las mismas del presupuesto), el **metraje final** (distancia + 20 % por
  bloque de 300 m + reservas de conexión y de puntas), el cable (Flat o ADSS según el umbral), los
  postes existentes y nuevos y, unos segundos después, el **total** (llena la misma plantilla de
  Excel y la recalcula con LibreOffice, así que es el que daría un presupuesto con esas
  cantidades). Se ve en la etiqueta de la línea, en el clic sobre ella y en *Mis medidas*, con
  *Descargar Excel* y *Ver detalle*. No usa Google. Supone una conexión de cliente al final y
  ninguna mufa intervenida (sección `visor_medicion` de `business_rules.yaml`), servicio y equipo
  de `visor_estimacion`; es un cálculo aproximado, no enviado. Código: `visor_rutas/medicion.py`,
  `web/mapa/medicion_total.js`; en modo remoto `POST /visor/medicion`.

**Menú ☰** (arriba a la izquierda; Esc o clic afuera lo cierra):
- *Mapa y ruta*: la vista principal de siempre.
- *Generar presupuesto*: la vista del presupuesto completo (abajo). El mapa conserva su estado.

**Generar presupuesto** (presupuesto completo, como el de n8n, pero no se envía):
- **Formulario** con los campos de la API (`TicketRequest`) y sus mismas validaciones: ticket
  (vacío = `VISOR-AAAAMMDD-HHMMSS`), cliente, código, ejecutivo, contacto (vacío = el cliente),
  teléfono, coordenada en un solo campo (`12.15, -86.26`, misma validación que la barra:
  dentro de Nicaragua, aviso si está invertida), servicio (Residencial / Empresarial /
  Corporativo), medio (FO), velocidad, tecnología (Automático / GPON / Metro), ODF de rack
  (Ninguno / 12 / 24) y comentario. Los errores se marcan en rojo en cada campo. *Usar
  coordenada del mapa* copia la del cliente de la ruta generada.
- **Generar presupuesto** llama a la **misma función que `POST /presupuesto`**
  (`main._generar_presupuesto_con`: punto de conexión elegido por ruta, Google en modo
  driving, cantidades, mapa satelital, plantilla y recalc con LibreOffice). El visor solo le
  pasa dos parámetros opcionales, que la API usa con sus valores por defecto: `output_dir`
  (`output/visor`) y `get_route` (el caché de rutas de la sesión). No escribe
  `budget_index.json` (eso lo hace solo el endpoint) y no envía nada. Tarda lo mismo que
  la API (10–40 s, sobre todo LibreOffice y el mapa).
- **Resultado:** pestañas *Presupuesto* y *Ruta proyectada* con la hoja dibujada como tabla
  (`excel_html.py`): anchos de columna, celdas combinadas, filas/columnas ocultas, negritas,
  colores, bordes, alineación y formatos de moneda (C$), número y porcentaje, con el logo y
  el **mapa** en su lugar. Muestra **valores, nunca fórmulas** (los que dejó LibreOffice).
  Zoom − / +. Pestaña *PDF*: el PDF de `pdf_export` (el mismo de `GET /presupuesto/{id}/pdf`).
- **Botones:** *Guardar Excel como…* y *Guardar PDF como…* (diálogo de Windows), *Abrir en
  Excel* y *Abrir carpeta* (Explorador con el archivo seleccionado).
- **Avisos y pendientes:** los `warnings` de la respuesta y los pendientes de validación
  (campos, partidas manuales en 0, postes existentes a validar).
- **Sin LibreOffice:** el Excel se genera igual; las celdas calculadas se ven "—" y se avisa
  que los totales se ven al abrirlo en Excel; la pestaña PDF queda desactivada.

**Presupuesto aproximado** (pestaña *Presupuesto* del panel derecho, junto a *Ruta de fusión* y
*Diagrama*):
- Se calcula **solo, después de dibujar la ruta**, en segundo plano: el mapa no espera al Excel.
  Mientras tanto la pestaña muestra una ruedita y "Calculando presupuesto aproximado…". Si se
  genera otra ruta antes de que termine, el resultado viejo se descarta. Sin ruta de Google
  (ruta aproximada) no se estima.
- Usa la **misma generación** con valores por defecto de `business_rules.yaml`, sección
  `visor_estimacion`: 10 Mbps, medio FO, tecnología automática (con 10 Mbps sale GPON por
  `equipment.metro_bandwidth_threshold_mbps`), sin ODF de rack, y cliente / código / ejecutivo
  / contacto = "Estimación visor". Servicio: **Residencial** si el metraje final es ≤
  `cable.adss_threshold_m` (600 m, cable Flat) y **Empresarial** si lo supera (ADSS).
- **No vuelve a llamar a Google:** el visor guarda en memoria las rutas que ya pidió en la
  sesión (por coordenada de origen y destino, 30 min), así que la estimación reutiliza la
  ruta del mapa y las de las mufas candidatas.
- La tarjeta muestra la etiqueta **"Aproximado – no enviado"**, el TOTAL, los supuestos
  (servicio, velocidad, tecnología, cable, metraje final contra el umbral), el desglose
  plegable de *Mano de obra* y *Materiales* (solo líneas con cantidad > 0: descripción,
  cantidad, total) y los totales tal como los calcula la plantilla (Alcaldía, Subtotal,
  Costo Total el 7,29 %, TOTAL), ubicados por sus etiquetas, no por número de fila.
- Botones: *Descargar Excel* (guardar como…), *Ver detalle* (abre la vista *Generar
  presupuesto* con ese Excel) y *Ajustar datos* (abre el formulario prellenado con la
  coordenada y los supuestos para cambiarlos y generar uno completo).
- Sin LibreOffice muestra las cantidades y avisa que los montos requieren LibreOffice.

**Archivos del visor:** `output/visor/<cliente o Estimacion>_<lat>_<lon>_<AAAAMMDD-HHMMSS>.xlsx`
(y su `.pdf` al pedirlo), con el mapa en `output/visor/mapas/`. Al abrir el visor y antes de
cada presupuesto se borran los de `output/visor` más viejos que `OUTPUT_RETENTION_DAYS`; la
limpieza de la API no entra en esa carpeta y la del visor no toca `output/` ni
`budget_index.json`.

**Ruta de fusión** (pestaña *Ruta de fusión* del panel, `visor_rutas/fusion.py`):

- **Qué muestra.** Para el cliente consultado, cómo llega el servicio mufa por mufa: desde el OLT/nodo del origen de tráfico, pasando por cada mufa del camino de los diagramas Visio (`origen_trafico.camino`), hasta el punto de conexión y el cliente. Usa solo datos que ya están en la base de diagramas (PostgreSQL `red_fibra`, o `red_fibra/red_fibra.db` si no hay conexión).
- **Datos por mufa:**
  - hilos de entrada y salida del Excel de anillos;
  - splitters, puertos, OLT, hilos y buffers escritos en su diagrama;
  - clientes fusionados ahí;
  - notas (SANGRIA, VALIDAR, SATURADA…);
  - los diagramas donde aparece.
- **Insignia de fuente:**
  - **Excel anillos** (verde)
  - **Texto del diagrama** (azul)
  - **Sin dato de hilos** (gris)
  
  Si un nombre de mufa se repite en la base, se elige la que está unida por cable a la mufa anterior. Si no se puede asegurar, aparece *Validar mufa*.
- **Mufa de conexión emparejada por nombre** (casos c y d del origen de tráfico): ese eslabón lleva la insignia naranja **Por nombre – validar**. Si la mufa está dibujada sin coordenada (caso d), aparece con su nombre tal cual está en el diagrama, sin punto en el mapa, y su botón **Ver diagrama** abre el archivo donde se encontró el nombre, con zoom a ese texto y los textos cercanos (VALIDAR, SPL…).
- **Diagnóstico.** Cuando la mufa de conexión no tiene mufa Visio a menos de 150 m, la tarjeta *Origen de tráfico* y la pestaña *Ruta de fusión* muestran por qué, con insignias: *Mufa parecida a mayor distancia*, *Sin coordenada en Visio*, *Marcada VALIDAR en el diagrama*, *No diagramada* o *Es reserva (mufa nueva)*, más el detalle (nombre y metros, o archivo del diagrama). Reemplaza el mensaje genérico de 150 m. También se copia con *Copiar resumen* y *Copiar ruta de fusión*.
- **En el mapa:** una línea **morada punteada** une las mufas del camino (casilla *Camino de la fibra*). No entra en el zoom automático, porque el camino al OLT puede medir kilómetros. Clic en una mufa del panel centra el mapa en ella.
- **Ver diagrama:** abre el diagrama Visio real de esa mufa en la pestaña *Diagrama* del panel (ver abajo), con zoom de rueda, arrastre y un selector cuando la mufa aparece en varios diagramas.
  - **Formato SVG (vectorial):** se ve nítido con cualquier zoom, incluso en los diagramas de varios metros de ancho (el mayor mide 4,45 m). El zoom redimensiona la imagen en lugar de escalarla, así que se vuelve a dibujar nítida en cada nivel.
  - **Primera vez:** se convierte desde `red_fibra/cache_odg` con LibreOffice, en unos 5–15 s según el tamaño, y queda en `red_fibra/cache_diagramas/<md5>_0.svg`. Solo si el SVG falla se usa un PNG (`<md5>_0.png`).
  - **Sin LibreOffice:** muestra "Diagrama no disponible (falta LibreOffice)".
  - **Diagramas originales:** no hace falta tenerlos (.vsd/.vsdx); el `.odg` ya conserva todo el dibujo vectorial.
- **Copiar ruta de fusión** copia una línea por mufa, en texto plano.
- **Si algo falla.** Si no se puede armar la ruta de fusión, la ruta del cliente se calcula igual: `ruta_fusion` queda vacía y se agrega un aviso. Pasa lo mismo si el origen de tráfico no tiene camino en los diagramas o si no hay base de diagramas.
- **Fusiones del piloto.** La casilla *Mostrar fusiones detectadas (piloto)* aparece **solo si existe la tabla `fusiones_piloto`** y viene **apagada**. Al marcarla, cada mufa muestra en un bloque aparte, con la insignia naranja **Piloto – validar**, las fusiones que detectó el piloto en sus diagramas. Se muestran ordenadas por confianza y nunca se mezclan con los hilos del Excel ni cambian la insignia de fuente. En un diagrama de red o subred solo se toman las fusiones cercanas a la etiqueta de esa mufa. Ver *Piloto de fusiones* más abajo.

**Buscador de mufas y coordenadas, y pestaña *Diagrama*:**

- **Coordenadas (visor v2):** el mismo buscador acepta coordenadas escritas a mano y **no calcula nada** (la barra inferior queda como está). Formatos: decimal (`13.094578, -86.002708`, con espacio o con `;`), grados-minutos-segundos como en Google Earth (`13°5'38.09"N 86°0'7.42"O`, también `W`, `º`, solo espacios `13 5 38.09 N 86 0 7.42 W`, o con la letra delante `N13 5 38.09 W86 0 7.42`) y grados con minutos decimales (`13 5.6348N 86 0.1237W`). Con letras el orden no importa; sin letras el primero es la latitud y la longitud va con signo menos. Debe caer en Nicaragua: si solo cabe con latitud y longitud al revés, avisa y ofrece la forma correcta; si no, dice que está fuera. Un nombre como "MF 12 NORTE" nunca se toma por coordenada (cualquier otra letra la descarta).
- **Pincho:** Enter (o clic en "Ir a la coordenada …") vuela y pone un **pincho amarillo** con la etiqueta de la coordenada en decimal (casilla *Coordenada buscada*; hay uno solo, buscar otra lo mueve). Clic en el pincho: *Copiar decimal*, *Copiar grados*, *Guardar en Mis lugares* (deshabilitado hasta Mis lugares), *Usar para generar ruta* (llena la barra inferior sin calcular) y *Quitar*.
- **Varias fuentes:** si no es una coordenada, el buscador pregunta a todas y las muestra juntas, cada una con su título: mufas y nodos Visio, el KMZ (por nombre; sin postes ni pozos), y la red base (lo creado en el módulo de redes y los clientes por nombre o código; una mufa migrada de Visio ya sale en la primera). Mis lugares se sumará en su fase. Una fuente que falla no oculta a las otras.
- El lector de coordenadas está dos veces, en `visor_rutas/coordenadas.py` y en `web/mapa/coordenadas.js`; los dos se prueban con los mismos casos (`Pruebas/vectores_coordenadas.json`).
- **Buscador:** está arriba, al centro del mapa (`web/mapa/buscador.js`). Escribe parte del nombre de la mufa: "puma", "MF loyola", "semaforos dorado"… No importan mayúsculas ni acentos, y MF/MC/MUFA cuentan igual, como en el importador.
- **Resultados:** muestra hasta 20 nodos (mufas, nodos, ODF…) de la base de diagramas, primero el nombre exacto y luego los que aparecen en más diagramas. Se navega con ↑ ↓ y Enter, o con clic.
- **Al elegir una mufa:**
  - el mapa la marca con un **pin rosado** y su nombre (casilla *Mufa buscada*) y la centra en la parte visible del mapa;
  - el panel abre la pestaña **Diagrama** y se ensancha. Muestra los datos de la mufa (tipo, zona, coordenada, insignia de fuente, hilos del Excel, splitters) y su diagrama Visio, con un selector si aparece en varios.
- **Dónde está la mufa en el diagrama:** el visor hace zoom a su etiqueta y la marca con un **círculo rosado**. *Ubicar mufa* vuelve a ella, *Completo* muestra todo el diagrama y ⛶ lo abre en pantalla completa.
  - La posición sale de `textos_crudos`, la etiqueta de la mufa en ese diagrama.
  - En los diagramas propios donde el importador no reconoció el título, se busca el texto que mejor coincide con el nombre: se ubican 289 de 337 mufas con diagrama propio y todas las de diagramas de red.
  - Si no se encuentra, el diagrama se muestra completo con un aviso.
- **Ancho del panel:** se cambia arrastrando su borde izquierdo. Se recuerda un ancho para *Diagrama* y otro para las demás pestañas.

**Mis lugares y la barra de herramientas (visor v2, fase 3):** carpetas y elementos propios de cada usuario, como en Google Earth (`visor_rutas/redes/lugares.py`, `lugares_kmz.py`, `lugares_iconos.py`; `web/lugares/*`, `web/mapa/barra_herramientas.js`). Migración `011_lugares.sql`.

- **En el árbol:** la raíz **Mis lugares** está arriba de la red del KMZ, con sus carpetas y elementos, casillas de tres estados (se guardan), cuenta de elementos, y **Compartidas conmigo** cuando alguien te compartió algo. Doble clic: vuela al elemento o encuadra la carpeta. **Arrastrar y soltar** mueve a otra carpeta y ordena a mano (arriba / abajo de una fila = antes / después; en el centro de una carpeta = adentro). Qué carpetas están abiertas se recuerda en tu equipo.
- **Barra de herramientas** (arriba del mapa, bajo el buscador): *Marca de posición* (un clic en el mapa), *Polígono* y *Ruta* (un clic por punto y doble clic para terminar; el doble clic ya no hace zoom), *Medir* (el mismo botón de la barra de abajo). Mufa, poste, cliente y cable (dibujar red en una carpeta, fase 4), Importar (fase 5) y Coordenadas masivas (fase 6) están deshabilitados con su tooltip.
- **Ventana flotante** (sin fondo que bloquee el mapa; se mueve por su cabecera): nombre, carpeta, y las pestañas *Descripción* (texto con formato, *Agregar vínculo*, *Agregar imagen local*: PNG / JPEG / WEBP / GIF de hasta 2 MB, guardadas en la base), *Estilo, color* (ícono, color, escala y opacidad del ícono; nombre junto al pincho; color, grosor y opacidad de la línea; relleno del polígono), *Ver* (centro y zoom guardados, *Instantánea de vista actual*) y *Medidas* (longitud de una ruta; perímetro y área de un polígono, en vivo). La latitud y longitud de una marca se escriben en decimal o en grados, minutos y segundos, y el pincho se arrastra. Los vértices de una ruta o polígono se mueven, se agregan (el punto del medio de un tramo) y se quitan en el mapa.
- **Íconos propios**, sin Google: pushpins de 10 colores, letras A–Z, números 1–10 y 8 figuras, con el selector de la imagen 06 de la especificación.
- **Clic derecho en una carpeta:** *Nueva carpeta*, *Agregar marca de posición aquí* (al centro de la vista), *Agregar ruta*, *Agregar polígono*, *Encuadrar*, *Cambiar nombre*, *Compartir…*, *Exportar a KMZ*, *Importar KMZ aquí…*, *Guardar como proyecto* (deshabilitado hasta que las carpetas lleven elementos de red, fase 4) y *Eliminar* (con confirmación; se lleva sus subcarpetas y elementos, con borrado lógico). Clic en un elemento: popup con su descripción e imágenes y *Editar*, *Eliminar*, *Ir a la vista*, *Copiar coordenada*.
- **Exportar a KMZ:** la carpeta con sus subcarpetas, íconos dibujados dentro del archivo (se ve sin internet), colores, grosor, relleno, descripciones con sus imágenes y la vista guardada. **Importar:** un `.kmz` / `.kml` (de aquí, de Google Earth o de otro programa; KML 2.0, 2.1 y 2.2) a una carpeta nueva, todo o nada; los pushpins de Google se reconocen por su nombre y lo que viene de aquí vuelve idéntico. Hasta 30 MB y 5 000 lugares por archivo.
- **Compartir:** una carpeta (y sus subcarpetas) con otras personas, en solo lectura o con edición. Quien la recibe la ve en *Compartidas conmigo* (sus casillas valen solo en su ventana); lo que cree dentro de una carpeta compartida es del dueño; solo el dueño comparte, mueve o elimina la carpeta compartida.
- **Búsqueda:** el buscador de arriba también encuentra lugares propios por nombre. El botón *Guardar en Mis lugares* del pincho de una coordenada abre la ventana de una marca con esa posición.
- **Personal:** cualquier usuario activo del módulo tiene sus lugares (también un lector, no es la red) y nadie más los ve, ni un administrador, salvo lo compartido. Funciona igual en modo remoto (todo pasa por `redes`). No forman parte de los respaldos de proyectos; sí de los de la base entera (`pg_dump`).

**Red dibujada en una carpeta (visor v2, fase 4):** mufas, postes, clientes, nodos/OLT, ODF y cables se dibujan **en el mapa principal y viven en una carpeta de Mis lugares**, sin abrir un proyecto (`redes/lugares_red.py`, `web/lugares/dibujar_red.js`; sin migración nueva: son lugares con `tipo` mufa / poste / cliente / nodo / odf / cable y sus datos en `propiedades`).

- **Puntos:** botones de la barra (o clic derecho en la carpeta → *Agregar mufa / poste / cliente / nodo / ODF*), un clic en el mapa y la ventana flotante abre en **Datos de red**: tipo (mismos que el editor de proyectos), capacidad y bandejas de la mufa, código C##### e ID de servicio del cliente. El ícono sale del tipo (el servidor lo vuelve a poner); el pincho se arrastra mientras la ventana está abierta.
- **Cable:** botón *Cable*: clic en el elemento de inicio, en el recorrido (los puntos se pegan a postes y mufas a 18 px, como en el editor) y **doble clic en el elemento final** (Enter termina, Retroceso quita el último punto, Esc cancela). Después se elige clase (troncal / distribución / acometida), ADSS o FLAT, hilos, hilos por buffer, cruces y color. Los extremos toman la posición de sus elementos y **el metraje** se calcula en el servidor con las reglas `diseno_red` (se ve en el popup del cable). Si se mueve un elemento, **el extremo de sus cables lo sigue**; para borrar uno con cables, el visor pregunta si se eliminan juntos.
- **Guardar como proyecto:** clic derecho en la carpeta → copia a un proyecto nuevo (código `LUG-…`, tú como usuario asignado) los elementos de la carpeta y sus subcarpetas y los cables que unen dos de ellos (los vértices pegados a un poste quedan anclados), con las mismas validaciones del editor de proyectos. Las marcas, rutas y polígonos quedan solo en la carpeta; la carpeta no cambia. Pide permiso de editor. Exportar a KMZ ya lleva estos elementos (ícono y color del tipo, cables con su color y grosor por clase).
**Entrar a cualquier mufa y editar lo que ya existe (visor v2, fase 4, segunda parte):** migración `012_kmz_cambios.sql`, `redes/kmz_cambios.py`, `web/lugares/kmz_cambios.js`.

- **Entrar a la mufa:** el popup de una mufa del KMZ (carpetas «MUFA…») tiene **Entrar a la mufa** (también doble clic o Enter): abre su editor. Si la migración no la tiene, el visor pregunta si crea **una mufa vacía en ese punto** (queda en el proyecto base `BASE-VISOR`, ligada al KMZ por nombre y posición; entrar otra vez la encuentra, no se duplica) para armar sus bandejas y empalmes. Si no se acepta, abre el diagrama Visio como antes. Crear pide ser administrador o editor.
- **Editar el KMZ sin tocar el archivo:** cualquier elemento del KMZ (puntos y líneas) se puede **Renombrar**, **Mover** (puntos: se arrastra un pin y se suelta) o **Eliminar** (quitar del mapa) desde su popup; **Deshacer cambios** lo deja como estaba. El cambio se guarda en `redes.kmz_cambios` (un elemento se identifica por carpeta + nombre original + coordenada redondeada), **es de todo el equipo**, solo administradores y editores lo hacen, queda en el historial y se ve igual en modo remoto. El árbol de Lugares muestra **Cambios al KMZ (n)** con la lista y su Deshacer.
- **Lo que todavía no hace:** los cambios **no llegan** a `red_puntos` / `red_lineas`, así que el **presupuesto sigue usando la red como estaba** (queda `publicado = false`; publicar y re-publicar es un paso aparte, pendiente de tu OK). Tampoco se mueven los vértices de una línea del KMZ (solo renombrar o quitar), y la búsqueda del KMZ aún lista el nombre original. Los elementos de la red base (migrados del Visio o creados en el módulo) se editan abriendo su proyecto, como siempre.

**Editar la ruta y presupuesto en vivo (visor v2, fase 4B, primera parte):** `visor_rutas/calculo.py` (`RutaFija`, `calcular_con_ruta`), `web/mapa/editar_ruta.js`. Regla de Jan: **todo cambio recalcula**.

- **Editar la ruta:** en la tarjeta *Ruta* del panel, **✎ Editar ruta** deja la polilínea en blanco con sus puntos: se arrastran, clic en el punto medio de un tramo agrega uno, clic derecho en un punto lo quita. **＋ Poste a mano**: clic en el mapa agrega un poste nuevo (clic en uno suyo lo quita). Unos 0,6 s después del último cambio se recalcula todo **sin pedir nada a Google**: distancia, metraje final y reserva, tipo de cable, postes existentes (PostGIS cerca de la línea), postes nuevos, mufas en ruta y mufas intervenidas; y después el **presupuesto aproximado** con esa misma ruta (una respuesta vieja se descarta). Marcar un poste nuevo como existente sigue bajando el cobro, también sobre la ruta editada (al cambiar la ruta esas marcas se limpian, porque son de los postes anteriores).
- **Ruta a mano:** botón **✎ Ruta a mano** (barra de abajo): clic para cada punto (se pega a postes, mufas y puntos cercanos), doble clic o Enter terminan, Retroceso quita el último, Esc termina. **El presupuesto se va generando mientras se dibuja**; al terminar queda en edición. El cliente es el último punto.
- **Volver a la de Google** rehace la ruta de la coordenada; **Guardar en Mis lugares** guarda la ruta editada como ruta de una carpeta (y de ahí a KMZ).
- **El presupuesto con datos** (☰ → Generar presupuesto) y el aproximado usan la ruta editada y los postes a mano **cuando la coordenada es la del cliente de esa ruta**. `POST /presupuesto` **no cambia** (los dos datos nuevos son opcionales, solo del visor); en modo remoto: `POST /visor/ruta_editada` y `ruta` / `postes_extra` en `/visor/estimacion`.
- **Detalles:** el punto de conexión es el que corresponde a la coordenada del cliente; si la ruta editada empieza a más de 15 m de él, un aviso lo dice (el presupuesto cuenta ese punto de conexión). Un poste a mano se cobra como nuevo y se suma a los calculados.
- **Ruta de fusión editable y su Excel (fase 4B, segunda parte):** `visor_rutas/ruta_fusion_plan.py`, `ruta_fusion_xlsx.py`, `exportar_fusion.py`, `web/mapa/editar_fusion.js`. En la pestaña **Ruta de fusión**, bajo las paradas de los diagramas, el bloque **Ruta para el Excel** trae una caja por mufa, **del cliente hacia la potencia**, con el texto como se escribe en el libro (`En MF X lat°, lon° H# hacia MF A fusionarlo con H# hacia MF B`; la primera: `ingresar la acometida del cliente. H1 del cliente…`). **Mufas aérea y de corte no se tocan** (se reconocen por el nombre en `business_rules.yaml` → `ruta_fusion.no_tocar`; «MF FUERZA AEREA» es un lugar y está en las excepciones; la mufa donde entra el cliente siempre se toca, con un aviso). Los hilos salen del Excel de anillos y donde no hay dato quedan **H__** («hilos por identificar»). Se puede: marcar / desmarcar, cambiar hilos, poner splitter (1x8…), escribir el texto a mano, subir / bajar / quitar, agregar una mufa o una mufa nueva («instalar MF FOSC»), «COMPARTIR POTENCIA DEL SP» y avisos en rojo. Cada cambio rehace los textos (Python), el camino punteado del mapa y el **presupuesto aproximado, que cuenta las mufas que se tocan** (si no editas nada, queda el conteo de siempre).
- **Exportar al Excel:** agrega **una franja nueva al final** de la hoja **«2025 - 2026»** del libro `RUTA_FUSION_XLSX` (por defecto `EjemploRutaFusiones/RUTA DE FUSION - Copia.xlsx`; luego el de la nube): barra verde con la fecha de hoy (la cambias en el libro), **Cliente** (vacío si el presupuesto fue a mano; con ticket, su nombre — el campo del bloque), **Diagramas y Cuadrilla vacíos**, una caja por mufa, avisos en rojo, «COMPARTIR POTENCIA DEL SP» si aplica y **RUTA SUGERIDA** con el mapa de la ruta debajo (opcional). Se escribe **a nivel XML**: lo que ya existe no se toca (comentarios en hilo, dibujos, otras hojas), con los estilos del propio libro; antes se guarda un **respaldo** (`output/ruta_fusion_respaldos`, los últimos 10), se escribe en un archivo temporal que se **verifica** y se reemplaza de una vez. Si el libro está **abierto en Excel** no se escribe y se avisa. Siempre se agrega una franja nueva (no se reutiliza el bloque derecho de una fecha existente) y la franja de mufas en edición se pierde si cambias la ruta del mapa (el plan se rehace).

**Importar un KMZ a la red (visor v2, fase 5):** migración `013_kmz_importaciones.sql`, `visor_rutas/redes/importar_kmz.py`, `web/lugares/importar_kmz.js`. El botón **Importar KMZ** de la barra abre una ventana (solo administradores y editores).

- **Dos modos:** *una ruta o elementos nuevos* (lo que falta en el archivo no se toca) y *actualización de toda la red* (un KMZ completo como `RED DE IDEAY.kmz`; además detecta lo eliminado). El visor **sugiere** uno según cuánto del archivo ya está en la red; se puede cambiar antes de aplicar.
- **Comparar:** cada elemento del archivo se compara con la red en vigor (el KMZ del servidor **con sus cambios** de «Cambios al KMZ» y lo que ya se importó) por carpeta + nombre + cercanía (300 m), y si no hay nombre igual, por el mismo lugar (2 m en puntos, extremos a 3 m en líneas): **nuevo**, **modificado** (nombre, posición, trazo o descripción), **sin cambios** (solo se cuenta) y **eliminado** (solo en actualización). Con la red real, el KMZ contra sí mismo da 35 526 sin cambios en unos 7 s.
- **Revisar:** conteos con color (nuevo verde, modificado naranja, eliminado rojo), lista filtrable por clase, carpeta y nombre, el mapa con los mismos colores (clic en una fila vuela al elemento) y casilla para aceptar o rechazar cada cambio o grupos enteros («Aceptar / Rechazar los mostrados»). Lo **eliminado empieza rechazado**; si el archivo no trae más del 20 % de la red, un aviso lo dice. En el árbol de Lugares el archivo aparece como **Importados (pendientes)** con su nombre.
- **Aplicar a la red:** el archivo KMZ no se modifica. Lo modificado o eliminado de un elemento del KMZ queda en **Cambios al KMZ** (migración 012; se ve en el mapa y se deshace igual) y lo nuevo en la capa **Importados (aplicados)**. Todo guarda lo que había antes: **Revertir** deshace la **última** importación aplicada (las demás, de la más nueva a la más vieja). Queda el historial (archivo, md5, quién, cuándo, conteos).
- **Publicar en el presupuesto** (solo administradores, botón aparte después de aplicar): inserta lo nuevo en `red_puntos` / `red_lineas` con `tabla_origen = 'visor'`, actualiza lo modificado y borra lo eliminado, **en una transacción** y guardando las filas de antes; **Revertir la publicación** las deja exactamente como estaban (con sus ids). La categoría sale del nombre de la carpeta (igual a una que ya existe, en singular o plural; mufas, reservas y postes por sus palabras); lo que no tiene equivalente o no se encuentra en el presupuesto **no se toca** y el reporte lo lista. Hasta publicar, el presupuesto sigue usando la red como estaba.
- **Límites:** el archivo viaja en base64 (hasta 30 MB); en modo remoto un KMZ completo pesa unos 27 MB y la subida por ngrok puede tardar (la fase 7 le da un endpoint de subida propio). Los polígonos se importan y se aplican, pero no se publican. No se comparan los elementos de la red base (proyectos de Visio).

**Modo remoto para todo lo nuevo (visor v2, fase 7):** `VisorRutas.exe` (sin Python ni bases en esa PC) hace lo mismo que el visor local, todo por `/visor/*` con la X-Visor-Key y los permisos de la persona de la clave (un lector solo tiene sus propios lugares; importar KMZ, editar el KMZ, crear proyectos y la ruta de fusión piden ser editor; publicar en el presupuesto, administrador).

- **Medir con total, ruta editada, ruta de fusión y coordenadas masivas** tienen su endpoint (`/visor/medicion`, `/visor/ruta_editada`, `/visor/estimacion` con `ruta`, `postes_extra` y `mufas_tocadas`, `/visor/fusion/*`, `/visor/masivas/*`); Mis lugares, editar el KMZ, importar KMZ, guardar como proyecto y lo de las coordenadas masivas van por `/visor/redes/{metodo}`. Los Excel de los presupuestos masivos y el libro de rutas de fusión **viven en el servidor**: el .exe baja los presupuestos en un .zip.
- **Archivos grandes por partes** (`visor_rutas/subidas.py`, `POST /visor/subidas`, `/visor/subidas/{id}/{n}` con los bytes de la parte, `/visor/subidas/{id}/fin`): un KMZ completo pesa 20 MB; la página lo parte en pedazos de 1,5 MB (con «Subiendo… 40 %»), el servidor los junta en memoria (nada en disco, hasta 40 MB, 8 subidas a la vez, caducan a los 30 min) y «Importar KMZ» / «Coordenadas masivas» usan el id (`subida_id`), que se entrega una sola vez. En modo local la página hace lo mismo contra este mismo módulo.
- **Tareas largas:** el lote de coordenadas masivas corre en segundo plano con seguimiento y cancelar (se consulta cada 1,5 s); comparar un KMZ completo es una sola llamada (unos 10-30 s, con tope de 180 s en el cliente).
- **Para las otras PCs:** regenerar `VisorRutas.zip` (`build_visor.bat`) y reiniciar `start_service.bat` en el servidor cuando cambie algo.

**Modo captura:** el botón **📷 Captura** de la barra de abajo esconde todo menos el mapa (menú, paneles, barras, buscador, controles, leyendas y ventanas) y lo deja a pantalla completa con lo que esté dibujado (ruta, postes, mufas, medidas) para tomar la imagen; **Esc** vuelve. Un aviso de 2,5 s recuerda cómo salir. Además, la lista de resultados del buscador ahora se abre por encima de la barra de herramientas.

**Coordenadas masivas (visor v2, fase 6):** `visor_rutas/masivas.py`, `redes/masivas_red.py`, `web/lugares/masivas.js`. El botón **Coordenadas masivas** de la barra abre una ventana: un presupuesto aproximado por cada coordenada de un archivo.

- **Leer:** Excel (.xlsx), CSV, Word (.docx), texto (.txt) o texto pegado. En Excel y CSV se buscan las columnas por su encabezado (latitud / longitud, o una de «coordenada», nombre o cliente, código; con coma decimal también) y, sin encabezado, las celdas de cada fila. En Word y texto se leen los formatos del buscador (decimal, grados-minutos-segundos y grados-minutos decimales) línea por línea y el resto de la línea es el nombre. Un `.xls` viejo se pide guardarlo como `.xlsx`.
- **Vista previa:** cada punto sale *válida*, *al revés* (latitud y longitud invertidas: botón «Usar» con la sugerida), *fuera de Nicaragua*, *no válida* o *duplicada* (igual a una fila anterior). Se corrige el texto de cada coordenada, el nombre y el código, y se marca cuáles entran. Los puntos se ven en el mapa con su número. Solo las válidas marcadas se calculan.
- **Calcular:** antes avisa cuántos presupuestos y consultas a Google son. Corre **en segundo plano**, un punto tras otro, con el mismo cálculo del presupuesto aproximado (`visor_estimacion`) y las mismas reglas; las rutas de Google se piden con un **límite por minuto** (`visor_masivo.google_por_minuto: 30` en `business_rules.yaml`; `max_puntos: 200` por lote). Barra de progreso, tiempo restante estimado con lo que ya se hizo, y **Cancelar** (termina el punto en curso). Un punto que falla no detiene a los demás. Solo un lote a la vez.
- **Resultados:** tabla ordenable con punto de conexión, distancia por ruta, metraje, cable, postes, mufas, total y avisos; un clic en una fila dibuja su ruta en el mapa. Cada presupuesto queda como Excel en `output/visor/masivo_<fecha>_<archivo>/` junto a un `Resumen.xlsx` (el total sale vacío si LibreOffice no está: se ve al abrir el Excel).
- **Al terminar:** *Abrir carpeta* (modo local) o *Descargar .zip* (modo servidor), **Guardar como proyecto** (un cliente por punto, la mufa de conexión de cada ruta y un cable de acometida FLAT de 2 hilos con el trazo de la ruta; código `MAS-…`) y **Guardar en Mis lugares** (una carpeta con las marcas numeradas y, si se quiere, una subcarpeta «Rutas»).
- **Modo servidor:** `POST /visor/masivas/leer`, `/iniciar`, `GET /visor/masivas/{lote}`, `/cancelar`, `/descargar`: cada punto válido cuenta para el límite por hora de la persona (puede pedir ruta a Google) y se rechaza el lote entero si lo pasa. Un lote vive en la memoria del proceso (si el servicio se reinicia se pierde el seguimiento; los Excel quedan en la carpeta).

**Panel "Lugares": la red del KMZ como en Google Earth** (`visor_rutas/kmz_capas.py`, `web/lugares.js`):

A la izquierda del mapa está el panel **Lugares**, armado desde el archivo KMZ de la red (`KMZ_PATH` del `.env`: el `.kmz` o la carpeta donde está; se usa el más reciente). Tiene la misma jerarquía de carpetas y los mismos estilos que en Google Earth. Es **solo para ver**: el cálculo de ruta y presupuesto sigue usando PostGIS (`red_lineas` / `red_puntos`).

- **Árbol:** flechas para expandir; casillas de tres estados (marcada / desmarcada / parcial) que se propagan a hijos y padres; muestra del estilo y conteo de cada carpeta; las carpetas vacías salen en gris. Al expandir una carpeta se listan sus elementos (lista virtual: miles sin trabarse), cada uno con su casilla.
- **Doble clic:** en un elemento, vuela a él y abre su popup; en una carpeta, la encuadra.
- **Buscador** arriba del árbol: filtra carpetas y elementos por nombre (y por descripción y notas con la casilla *descripción*), resalta lo encontrado; Enter o doble clic vuela al resultado (y enciende su carpeta).
- **Clic derecho en una carpeta:** *Mostrar solo esta*, *Encuadrar*, *Opacidad…* (deslizador) y *Etiquetas de nombre*.
- **Estado inicial:** todo apagado como en el KMZ, **excepto las troncales**: TRUNK GPON, TRUNK METRO, PRINCIPALES y todas las TRONCAL*. ENLACE REDUNDANTE TOLA-RIVAS empieza apagado y se puede encender. Casillas, carpetas expandidas, opacidades, etiquetas, ancho y si el panel está plegado se guardan en `%APPDATA%\VisorRutas\capas.json` y se restauran al abrir. **Restablecer** vuelve al estado inicial. ❮ pliega el panel y *Lugares ❯* lo vuelve a abrir; el ancho se cambia arrastrando su borde derecho.
- **Dibujo:** cada carpeta se carga la primera vez que se enciende y queda en memoria. Las líneas y los postes se dibujan en canvas. **Postes y pozos** son círculos con el color de su estilo, solo desde **zoom 15**, agrupados hasta zoom 16; con menos zoom aparece "Acerque para ver postes". Mufas, reservas y nodos llevan su ícono original y su color.
- **Popup** (clic): nombre, carpeta, descripción limpia (sin scripts ni restos de la app *Map Marker* / `com.exlyo`), notes, descripción, fotos (miniatura; clic para verla en grande) y coordenada con *Copiar*. Al pasar el mouse se ve el nombre.
- **Etiquetas de nombre** por carpeta, desde zoom 14. Arrancan encendidas solo en troncales y nodos.

**Troncales fáciles de distinguir:**
- Se respetan el color y el grosor del KMZ.
- **Colores distintivos para troncales** (casilla del panel, encendida por defecto): donde varias líneas de una misma carpeta comparten color (MANAGUA/TRONCAL y TRONCAL NUEVAS son todas azules), cada una recibe un color de una paleta de alto contraste. El color es siempre el mismo para el mismo nombre. El popup muestra el color original y el distintivo.
- **Estilo por familia:**

  | Familia | Línea |
  |---|---|
  | TRUNK GPON | continua gruesa |
  | TRUNK METRO | con borde oscuro doble |
  | UFINET (red de terceros, por nombre) | punteada |
  | ENLACE REDUNDANTE | guiones cortos |

- Al pasar el mouse sobre una troncal se resalta (más gruesa y con halo) y las demás se atenúan. Con clic, popup con nombre, descripción, familia y **longitud en km**.
- **Leyenda "Troncales"** (abajo a la izquierda, plegable): las troncales visibles con su muestra. Clic en un nombre para encuadrarla y resaltarla.

**Caché del KMZ** (`visor_rutas/datos_kmz/`, se genera sola):

| Archivo | Contenido |
|---|---|
| `arbol.json` | carpetas con id estable (hash de la ruta de carpetas), conteos, bbox, estilo, md5 del KMZ |
| `capas/<id>.geojson` | una capa por carpeta, con el estilo resuelto |
| `indice.json` | nombres y texto de descripciones, para el buscador |
| `iconos/` | íconos de `files/` y los de Google, descargados una vez y teñidos con el color del estilo; sin internet, SVG equivalentes |
| `fotos/` | imágenes de `files/` usadas en las descripciones |

- Se regenera solo cuando cambia el md5 del KMZ: al abrir el visor (con aviso de progreso, ~15 s) o al primer pedido del modo remoto.
- **Cuando llegue un KMZ nuevo:** cópielo en `red_kmz\` (o apunte `KMZ_PATH` a él) y abra el visor. Para regenerarlo a mano:

  ```
  .\.venv\Scripts\python.exe -m visor_rutas.kmz_capas            # usa KMZ_PATH; no hace nada si no cambió
  .\.venv\Scripts\python.exe -m visor_rutas.kmz_capas --kmz "C:\ruta\RED DE IDEAY.kmz" --forzar
  ```

  `--sin-descargar` usa los SVG en vez de descargar los íconos de Google. Si falta el KMZ, se sigue mostrando la última caché, con un aviso.

**Capas Visio** (`visor_rutas/red.py`): en la sección *Capas del visor* del panel Lugares, al final, están las dos casillas de Visio. Empiezan apagadas; al encenderlas se consulta **solo el área visible** del mapa y se vuelve a consultar al moverlo.

| Casilla | Qué muestra | Desde zoom |
|---|---|---|
| Red Visio · nodos | Nodos de los diagramas (mufas en azul; nodo / ODF / mini nodo en morado; borde punteado si la coordenada es estimada). | 12 |
| Red Visio · enlaces | Enlaces lógicos entre nodos de los diagramas, línea azul punteada (más tenue si la confianza es baja). | 12 |

Por debajo del zoom mínimo no se carga nada y un recuadro dice "acerque el mapa"; hay un máximo de elementos por vista. Leen el esquema `red_fibra` de PostgreSQL o, sin conexión, `red_fibra.db`. Los endpoints `/visor/red/kmz_*` (PostGIS) siguen en la API para los `.exe` anteriores, pero la página ya no los usa.

La ventana Tkinter (`--tk`) tiene lo básico: ruta, marcadores, resumen, historial y clic
derecho, con capa *Calles* de OpenStreetMap; no tiene medición.

*Calles* usa Esri y no OpenStreetMap en la ventana web porque WebView2 no envía *Referer*
desde una página `file://` y OpenStreetMap responde cada tesela con una imagen "Access
blocked".

**Diferencias con `POST /presupuesto`** (para que el visor siempre muestre algo):
- Sin Google (falla, sin internet o sin ruta): línea recta conexión → cliente y el aviso
  "Ruta aproximada (sin Google)". El presupuesto respondería 404/502.
- Si la base Visio no responde se sigue solo con el KMZ (igual que el presupuesto); si la
  base KMZ no responde se usa la red Visio y se avisa.
- Si falla la consulta de postes, mufas o cadena de mufas se sigue con un aviso (el
  presupuesto respondería 500).
- Las posiciones de los postes nuevos son aproximadas: cada `spacing_m` sobre la ruta, con
  el mismo recorrido por huecos que `presupuesto.count_new_poles_by_gaps`.

En la ventana Tkinter las teselas se descargan con una sesión propia que carga una sola vez
los certificados de `CURL_CA_BUNDLE`/`REQUESTS_CA_BUNDLE` (el instalador de PostgreSQL define
`CURL_CA_BUNDLE`; sin esto cada tesela recargaba el archivo y el mapa se quedaba en gris). La
ventana web no tiene ese problema: WebView2 descarga las teselas con los certificados de Windows.

Errores: se muestran en la barra inferior; el detalle queda en `logs/visor.log`.
Pruebas:
- `Pruebas/test_visor_rutas.py`: cálculo, con base y Google simulados.
- `Pruebas/test_visor_web.py`: Api de la ventana web y elección web/Tkinter; no necesita pywebview.
- `Pruebas/test_redes_lugares.py` y `test_visor_pagina_fase3.py`: Mis lugares en el servidor (carpetas, geometría y estilo validados, orden manual y ciclos, permisos y compartir, descripciones con imágenes, íconos PNG, KMZ de ida y vuelta, KML de Google Earth, importación todo o nada) y en la página real (barra, menús, ventana flotante, arrastre de vértices con el ratón, casillas, arrastrar y soltar, exportar, importar, compartir, buscador, persistencia en una segunda ventana y la vista de quien recibe una carpeta en solo lectura), con una base de datos desechable.
- `Pruebas/test_coordenadas.py` y `test_visor_pagina_fase2.py`: el intérprete de coordenadas (44 casos, Python y el mismo en JavaScript con los mismos mensajes), el pincho, sus botones, que no se calcule nada, el aviso de invertidas / fuera de Nicaragua y las fuentes del buscador; en Edge sin ventana a 1366×768 y 1920×1080.
- `Pruebas/test_visor_pagina_fase1.py` (con `arnes_pagina.py`): la página real en **Edge sin ventana**, con una `Api` de prueba (sin bases de datos ni Google) a 1366×768 y 1920×1080: un solo panel de capas, capas deshabilitadas con su motivo, zoom abajo a la derecha, ningún control flotante pisa a otro y el panel derecho cerrado hasta tener resultado. Se omite si no hay Edge o la librería `websockets`.
- `Pruebas/test_visor_fusion.py`: ruta de fusión con un SQLite de prueba, claves de `calcular_ruta` y `Api.diagrama`.
- `Pruebas/test_visor_presupuesto.py`: presupuesto del visor = misma función y mismas cantidades que `POST /presupuesto`, archivos solo en `output/visor` (nunca `budget_index.json`), estimación (10 Mbps/GPON, Residencial ≤ 600 m / Empresarial > 600 m, valores de `visor_estimacion`, sin segunda llamada a Google), limpieza, Excel → HTML con valores y no fórmulas, formatos de moneda y resumen.
- `Pruebas/test_seleccion_conexion.py`: punto de conexión elegido por metraje de ruta y descarte de mufas sin hilos (caso real simulado), en el presupuesto y en el visor.
- `Pruebas/test_origen_nombre.py`: emparejamiento por nombre (caso OTTO MUNKEL simulado), normalización, diagnóstico y el eslabón *Por nombre* de la ruta de fusión.

## Visor para otros usuarios

Otras personas usan el mismo visor como programa (`VisorRutas.exe`) **sin acceso a las bases
de datos ni a Google**: su visor llama a la API de esta PC por la URL pública de ngrok y esta PC
hace todos los cálculos con el código que ya existe. No se abren puertos ni se toca el firewall;
el acceso es solo por el túnel de ngrok que abre `start_service.bat`. **Si el servicio está
apagado, el visor de los demás dice "No se pudo conectar con el servidor de presupuestos".**

**Cómo funciona**
- **API** (`visor_api.py`, router incluido en `main.py`; no cambia `/presupuesto`, `/origen`, la
  respuesta de n8n ni `budget_index.json`):

  | Endpoint | Qué hace | Cuenta para el límite |
  |---|---|---|
  | `GET /visor/info` | versión de la API, fecha de la red Visio, mapa base y opciones del formulario | no |
  | `POST /visor/ruta` `{texto}` o `{lat, lon}` | lo mismo que *Generar ruta* (`calculo.calcular_ruta`) | sí |
  | `POST /visor/estimacion` `{lat, lon, metraje_final_m?}` | presupuesto aproximado (`visor_estimacion`) | sí |
  | `POST /visor/presupuesto` `{campos}` | presupuesto completo del formulario; devuelve `id` | sí |
  | `GET /visor/archivo/{id}.xlsx` / `.pdf` | descarga, solo de `output/visor/` | no |
  | `GET /visor/diagrama/{md5}/{pagina}` | imagen del diagrama Visio (SVG o PNG) | no |
  | `GET /visor/red/{capa}`, `/visor/mufas?texto=`, `/visor/mufa/{id}` | capas de red, buscador y detalle de mufa | no |
  | `GET /visor/kmz/arbol`, `/visor/kmz/capa/{id}`, `/visor/kmz/indice`, `/visor/kmz/archivo/{iconos\|fotos}/{nombre}` | panel *Lugares*: árbol, capas, índice de búsqueda, íconos y fotos de la caché del KMZ (JSON con gzip). El `.exe` los guarda en `%APPDATA%\VisorRutas\kmz_cache\<md5>` y los vuelve a pedir solo si cambia el KMZ del servidor | no |

  Todos llaman a la misma clase `Api` del visor local (`ventana_web.py`, modo local), así el
  resultado es idéntico y no hay lógica duplicada. Lo que generan va a `output/visor/` (nunca a
  `budget_index.json`). La API guarda en memoria las rutas de Google ya pedidas (30 min): la
  estimación después de una ruta de la misma coordenada no vuelve a llamar a Google.
- **Seguridad:** header `X-Visor-Key`, una clave por persona, distinta de `SERVICE_API_KEY`
  (que aquí no sirve, ni las claves del visor sirven para `/presupuesto`). Sin clave o con una
  inválida → 401. Con `VISOR_API_KEYS` vacío, todo `/visor/*` responde 404 (desactivado).
- **Límite:** `VISOR_RATE_LIMIT_PER_HOUR` (60) consultas por persona y hora en ruta, estimación y
  presupuesto, para proteger la cuota de Google → 429 "Límite de 60 consultas por hora alcanzado
  para maria; intente de nuevo en N minutos". El contador vive en memoria (se reinicia con el servicio).
- **Log** (`logs/service.log`, logger `visor_api`): persona, endpoint, coordenada, resultado y
  duración de cada consulta; nunca la clave.
- **Visor:** `ventana_web.Api` funciona en modo local (como siempre) o remoto
  (`remoto.ProveedorRemoto`, con `requests`, 1 reintento si falla la conexión, mensajes claros si
  la API está apagada, la clave es mala o se pasó el límite). La página HTML/JS es la misma.
  - Configuración en `%APPDATA%\VisorRutas\config.json`: modo, URL y clave, **cifrada con DPAPI**
    (solo ese usuario de Windows en esa PC puede leerla). Menú ☰ → **Configuración**: URL, clave,
    **Probar conexión** (`GET /visor/info`) y Guardar. En esta PC se puede elegir *Local* o
    *Remoto*; el `.exe` siempre es remoto y la primera vez abre esta pantalla.
  - Barra inferior (derecha): modo, servidor y fecha de la red Visio, p. ej. *Remoto ·
    broken-snowy-credibly.ngrok-free.dev · red Visio 05/10/2026*. Clic: configuración.
  - En remoto los Excel/PDF se descargan a `%TEMP%\VisorRutas\descargas` al verlos; las hojas se
    dibujan en la PC del usuario (`excel_html.py`), y *Abrir en Excel* abre esa copia. *Guardar
    como…* la guarda donde el usuario quiera.
  - Las capas de red también funcionan en remoto: cada movimiento del mapa con una capa
    encendida es una consulta por ngrok (no cuentan para el límite; el plan gratuito de ngrok
    tiene su propio límite mensual de peticiones).

**Agregar o quitar una persona** (en el `.env` de esta PC; no hace falta reiniciar el servicio):
1. Genere una clave: `.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(24))"`
2. Agréguela a `VISOR_API_KEYS`, con el nombre que saldrá en el log:
   `VISOR_API_KEYS=jan:Xy3...,maria:Q9k...`
3. Mándele a esa persona `VisorRutas.zip`, la URL (`https://<NGROK_DOMAIN>`) y **su** clave
   (por un canal privado).
4. Para quitarla, borre su `nombre:clave` de la línea; su visor empieza a recibir 401 de inmediato.
   Para desactivar el visor remoto de todos, deje `VISOR_API_KEYS=` vacío.

**Generar el .exe y el .zip** (en esta PC, sin permisos de administrador):
1. Doble clic en `build_visor.bat` (instala PyInstaller en el `.venv` si falta; unos 2 minutos).
2. Resultado: `dist\VisorRutas\VisorRutas.exe` (modo `--onedir`, sin consola, con ícono) y
   **`VisorRutas.zip`** (≈ 25 MB) en la carpeta del proyecto, con un `LEEME.txt` para la otra persona.
3. Solo empaqueta pywebview, requests, openpyxl/Pillow y el código del visor remoto con
   `visor_rutas\web\` (HTML, CSS, JS y Leaflet). `empaquetar_visor.py` excluye el servicio
   (main, db, config…), FastAPI, psycopg y lo que lee bases o `.env`, y **verifica** al final
   que no haya ningún `.env`, base de datos, plantilla, regla de negocio ni código del servicio.
   Si algo se coló, falla y no genera el `.zip`.
4. Vuelva a generarlo cuando cambie el visor (HTML/JS o `remoto.py`); los cambios de la API o
   de las reglas no lo requieren, porque se calculan en esta PC.

**Instrucciones para la otra persona** (también en `LEEME.txt`):
1. Descomprimir `VisorRutas.zip` en su carpeta de usuario (por ejemplo `C:\Users\<usuario>\VisorRutas`);
   no hace falta ser administrador.
2. Doble clic en `VisorRutas.exe` (opcional: *Enviar a → Escritorio (crear acceso directo)*).
3. La primera vez: escribir la URL y su clave, **Probar conexión** y **Guardar**.
4. Requiere Windows 10/11 con Microsoft Edge WebView2 (ya viene instalado). Si falta, el visor lo
   avisa y ofrece abrir https://go.microsoft.com/fwlink/p/?LinkId=2124703 (se instala sin
   administrador). Registro de errores: `%LOCALAPPDATA%\VisorRutas\visor.log`.

**Probar el modo remoto en esta PC:** ☰ → Configuración → *Remoto*, URL `http://127.0.0.1:8000`
(o la de ngrok) y una clave de `VISOR_API_KEYS`; o `.venv\Scripts\python.exe -m visor_rutas.remoto_main`.

Pruebas: `Pruebas/test_visor_api.py` (401/404, mismo resultado que `calcular_ruta`, 429, archivos
solo de `output/visor`, `ProveedorRemoto` contra la API de prueba = proveedor local, log sin
claves, clave cifrada, `/presupuesto` sin cambios).

## Reporte de emparejamiento (Planta Externa)

`red_fibra/reporte_emparejamiento.py` recorre **todas las mufas del KMZ** (`red_puntos` de tipo mufa) y aplica el mismo emparejamiento que el presupuesto y el visor (casos a–e de *Traffic-origin node*). Solo lee: no modifica ninguna base.

```powershell
.venv\Scripts\python.exe red_fibra\reporte_emparejamiento.py                      # red Visio de PostgreSQL (o red_fibra.db si no responde)
.venv\Scripts\python.exe red_fibra\reporte_emparejamiento.py --sqlite             # forzar red_fibra.db
.venv\Scripts\python.exe red_fibra\reporte_emparejamiento.py --salida output\emparejamiento.xlsx --limite 100
```

Genera `red_fibra/reporte_emparejamiento_AAAAMMDD_HHMM.xlsx` (unos 20 s para ~3100 mufas):
- **Mufas** (con filtros): ID, nombre y coordenada KMZ, resultado (a/b/c/d/e; c y d en naranja, e en rojo), nodo Visio emparejado (o el nombre tal como está dibujado), distancia (en d, a la mufa georreferenciada más cercana de ese diagrama), similitud, archivo del diagrama, mufa desde la que empieza el recorrido, diagnóstico y otros candidatos.
- **Resumen:** cuántas mufas hay por resultado y por caso de diagnóstico.

Sirve para que Planta Externa agregue coordenadas en los diagramas (casos d y `marcada_validar`) o corrija nombres (caso c).

## Piloto de fusiones

Intenta leer automáticamente, de cada diagrama Visio ya convertido (`red_fibra/cache_odg/*.odg`), **qué hilo se fusiona con cuál**, y mide qué tan bien lo hace sobre las mufas que elijas. Todo es local: no usa IA externa ni servicios web. El importador **no** lo usa todavía. El visor solo lo muestra con la casilla *Mostrar fusiones detectadas (piloto)*.

**Cómo están dibujadas las fusiones.** En los diagramas no hay conectores. Cada fusión es una línea suelta, casi siempre un "puente" en ángulo recto con flechas, que une el número de un hilo de un cable con el número de un hilo de otro cable, o con un splitter o cliente. Los números de hilo van en **un** cuadro de texto por cable ("1 2 3 … 24" o "6 / 5 / 4"). El color del trazo es el color del hilo en el **código TIA-598** dentro de su buffer: 1 azul, 2 naranja, 3 verde, 4 café, 5 gris, 6 blanco, 7 rojo, 8 negro, 9 amarillo, 10 violeta, 11 rosa, 12 aqua. Los buffers pueden ser de 12, 6, 2… hilos según la etiqueta del cable ("4BUFFER DE 6H"); si la etiqueta no lo dice, se asume 12.

**`red_fibra/fusiones.py`:**
- Lee las líneas con su color real, resuelto desde los estilos y aplicando `draw:transform`.
- Une las piezas de una misma línea.
- Estima la posición de cada número de hilo.
- Empareja cada punta con el número más cercano o con un texto de splitter o cliente (tolerancias en `TOLERANCIAS`).
- Calcula una **confianza de 0 a 1** con el motivo: cercanía de las puntas, color TIA que coincide con el número de hilo, flechas y si une cables distintos.
- Guarda el resultado en la tabla **`fusiones_piloto`** (`archivo_id`, `pagina`, `entrada`, `salida`, `color`, `color_tia`, `confianza`, `motivo`, extremos en cm). La tabla está en `schema.sql`, `schema_postgres.sql` y `publicar_postgres.py`, que la publica solo si existe.

**Cómo correr el piloto:**

1. Escribe `lista.txt` con las mufas, una por línea: nombre exacto de la mufa, md5 del diagrama o parte de la ruta del archivo. Las líneas con `#` se ignoran.
2. Genera los reportes. Usa LibreOffice (`LIBREOFFICE_PATH`) para las imágenes, con la misma caché que el visor:

   ```powershell
   .\.venv\Scripts\python.exe red_fibra\piloto_fusiones.py --mufas lista.txt
   ```

   Se crean `red_fibra\piloto\index.html` y un reporte por mufa. Cada reporte muestra el diagrama en SVG, nítido con cualquier zoom, con las fusiones detectadas encima (verde ≥ 0.7, naranja 0.4–0.7, rojo < 0.4), con zoom y arrastre, y una tabla con *Correcto / Incorrecto* por fusión.
3. Abre cada reporte en Edge o Chrome:
   - marca cada fusión y anota cuántas **fusiones reales** tiene el diagrama;
   - pulsa *Descargar marcas (CSV)* y mueve los `marcas_<archivo_id>.csv` a `red_fibra\piloto\marcas\`.

   Las marcas se recuerdan en ese navegador aunque vuelvas a generar los reportes.
4. Calcula las métricas:

   ```powershell
   .\.venv\Scripts\python.exe red_fibra\piloto_fusiones.py --metricas red_fibra\piloto\marcas
   ```

   - **Precisión** = correctas / marcadas.
   - **Cobertura** = correctas / reales (también se muestra detectadas / reales).

   Se calculan por mufa, en total y por umbral de confianza (0.3 … 0.8), para decidir desde qué confianza vale la pena mostrarlas.

**Para verlas en el visor:** después de correr el piloto, abre el visor, genera la ruta, entra a la pestaña *Ruta de fusión* y marca *Mostrar fusiones detectadas (piloto)*. Si el visor está conectado a PostgreSQL, primero publica la base con `red_fibra\publicar_postgres.py`. Si no, lee `red_fibra.db`.

**Ojo:** el importador reconstruye `red_fibra.db` completa, así que después de cada importación `fusiones_piloto` queda vacía y hay que volver a correr el piloto. Más detalle en `red_fibra/LEEME.md`. Pruebas: `Pruebas/test_fusiones_piloto.py`.


## Actualizar la red desde el programa (fase 8, administradores)

La ruta y el presupuesto usan `red_puntos` / `red_lineas` (PostGIS), **no** el KMZ del mapa. Al cambiar el KMZ hay que poner esas tablas al día: en el visor, botón **Importar KMZ** → sección **Actualizar la red**: *Subir KMZ nuevo* (reemplaza `KMZ_PATH`, guarda el anterior en `anteriores/`), *Comparar con el presupuesto* (solo lee) y *Poner el presupuesto al día* (inserta lo que falta, opcionalmente quita lo que ya no está; se puede revertir). Regla de postes: entre dos postes existentes se acepta un vano de hasta `poles.max_span_between_existing_m` (100 m) sin postes nuevos, y se buscan postes existentes hasta `existing_pole_search_buffer_m` (25 m) de la ruta.


## Ventana aparte (diagrama Visio y editor de mufa)
En la pestaña *Diagrama*, en el visor a pantalla completa y en el editor de la mufa hay un botón **⧉ Ventana aparte**: abre esa pantalla como ventana propia de Windows, que se puede mover fuera del programa o poner al lado de la otra para llenar la mufa a mano con los datos del Visio. En la ventana de la mufa, *Ver Visio original* abre el diagrama en otra ventana. Cerrar el editor cierra su ventana; cerrar el programa las cierra todas.



## Íconos propios del KMZ (fase 9)
En la ficha de cada elemento del mapa: **Cambiar ícono…** (puntos) o **Cambiar estilo…** (líneas). Para toda una carpeta: clic derecho en el árbol de Lugares → **Ícono / estilo…**. El del elemento gana al de la carpeta; **Quitar estilo** vuelve al del KMZ. Lo ven todos (se guarda en la base, tabla edes.kmz_estilos); no cambia el archivo KMZ ni el presupuesto. Si hay varios elementos en el mismo punto, el clic lista cuáles hay.


## Splitters de los diagramas (se rellenan con cada ruta)
Al generar una ruta de fusión, el visor lee los splitters dibujados en los diagramas de cada mufa: **secundario** (morado) o **principal** (dorado; si el texto es negro, por la palabra SECUNDARIO / PRINCIPAL; si no, «por confirmar»), su relación (1/8, 1/16…) y, cuando el diagrama trae la lista «1- cliente … 8-», los puertos libres. Lo leído se guarda en `redes.splitters_diagrama` (migración 016). Cada parada muestra «Splitters del diagrama» con **Confirmar**: una persona marca la clase y cada puerto libre / ocupado; lo confirmado se guarda y se usa en las rutas siguientes. El plan de fusión usa el primer secundario con puertos libres desde el cliente. Detalle y medición: `docs/modulo_redes/ESTUDIO_SPLITTERS.md`.

## App de campo (técnicos con el teléfono)
Una PWA (página instalable) que sirve esta misma API en `/campo/`: los técnicos registran **postes, mufas, reservas, solitarias, clientes y cables** desde Android o iPhone, con GPS y fotos, y el visor los ve **en tiempo real** para revisarlos, corregirlos y aprobarlos. No toca `/presupuesto` ni n8n.
- **Para el técnico:** `docs/campo/GUIA_TECNICOS.md` (instalar en Android e iPhone, registrar, trazar cables, sin señal, problemas comunes). Es corta; se puede imprimir o mandar por WhatsApp.
- **Interfaz (teléfono y tablet):** inspirada en Map Marker: mapa a pantalla completa, barra flotante (menú, filtro, lista, buscar, compartir), botón **＋** con mira central para ubicar puntos (el GPS se usa si la mira queda sobre él; si no, queda «marcado en el mapa»), cables punto por punto (el punto elegido sigue al centro del mapa; ＋ − ‹ › y guardar) o grabando el recorrido caminando, tarjeta inferior al tocar algo (editar, copiar, cómo llegar, eliminar), lista Explorar/Organizar con filtro, búsqueda por nombre o coordenadas, exportar a KML/KMZ/CSV y pantalla de **Ajustes** (tema, texto, formato de coordenadas, unidades, fotos, grabación). En tablets (≥ 820 px) los formularios salen en un panel lateral. Código en isor_rutas/campo_web/ (captura.js, editor.js, lista.js, menu.js, justes.js, exportar.js). Sin polígonos, círculos ni captura del mapa (no hay dónde guardarlos).
- **Dirección con HTTPS:** sin HTTPS el teléfono no da el GPS ni instala la app. **Hoy se usa la de ngrok** (`CAMPO_URL_PUBLICA=https://<NGROK_DOMAIN>` en `.env`; la primera vez en cada teléfono ngrok muestra un aviso «Visit Site»). El túnel de Cloudflare (`docs/campo/CLOUDFLARE.md`, `iniciar_tunel_cloudflare.bat`) está preparado pero **no se usa hasta que se compre el dominio** `fiberbudget.com`; entonces: `cloudflared tunnel route dns`, `CAMPO_URL_PUBLICA=https://api.fiberbudget.com` y `CLOUDFLARE_ACTIVAR=1` en `.env`. `verificar_campo.py <URL> <clave>` comprueba que todo responda desde cualquier dirección.
- **Dar de alta a un técnico:** (1) agregar `nombre:clave` a `VISOR_API_KEYS` en `.env` (se relee sola, sin reiniciar); (2) que la persona abra la app una vez con su clave (queda como «lector»); (3) en el visor → **Usuarios** → rol **Técnico de campo**. Un técnico solo crea y edita **sus** puntos pendientes; administradores y editores revisan (vista **Campo** del menú, capa «Levantamiento de campo» en Lugares).
- **Revisar:** aprobar un **poste o mufa** lo crea en la red base (o en un proyecto) con historial; un **cable** se aprueba como cable real si empieza y termina a ≤ 20 m de un poste o mufa del proyecto; reservas, solitarias, clientes y otros (y cualquier cable) pueden ir a **Mis lugares**. Rechazar pide un motivo que el técnico lee en su lista.
- **Ajustes** (`business_rules.yaml`, sección `campo`): precisión de GPS que se toma sin preguntar (10 m), distancia de «posible duplicado» (5 m), tamaño y número de fotos, límite de peticiones por hora, largo máximo de un trazo y distancia de los extremos de un cable (20 m).
- **Datos:** migraciones 017 y 018 (esquema `redes`, tablas `campo_*`; las fotos se guardan en `datos_campo/fotos/` o en `CAMPO_FOTOS_DIR`).
- **Pruebas:** `Pruebas/test_campo*.py`, `test_visor_pagina_campo.py` (la PWA y el visor corren en un Edge de verdad con GPS simulado).