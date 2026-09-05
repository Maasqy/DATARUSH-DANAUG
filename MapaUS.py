"""
Fifty States, One Territory - atlas interactivo de Estados Unidos
==================================================================
Construido con MapLibre GL (motor open-source, sin llave/API, sin
cuenta ni tarjeta) incrustado en una pagina de Streamlit.

Vista nacional: plana, dibujada con SVG (sin mapas de calle), solo las
divisiones entre estados y sus siglas. Al hacer click en un estado entra
un mapa real de calles con sus ciudades principales; al hacer click en
una ciudad se acerca a nivel de calle:

    Estados Unidos (plano, SVG) -> click en un estado -> mapa real con
    sus ciudades principales -> click en una ciudad -> nivel de calle

Requiere conexion a internet en el navegador solo para el mapa de calles
del segundo y tercer nivel (el contorno de los estados va incluido en
us_states.json, junto a este archivo).

Instalar dependencias:
    pip install streamlit

Ejecutar:
    streamlit run MapaUS.py
"""
import base64
import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Fifty States, One Territory", page_icon="\U0001F5FA", layout="wide")

REGIONS = {
    "NE":   {"label": "Northeast", "color": "#3a7c76"},
    "MW":   {"label": "Midwest",   "color": "#9c7a2e"},
    "S":    {"label": "South",     "color": "#a2503f"},
    "W":    {"label": "West",      "color": "#3f5f92"},
    "TERR": {"label": "Territory", "color": "#7c4f96"},
}

# Bandas de vulnerabilidad social (SDOH) -- mismos cortes y colores que el
# mapa nacional por ZCTA5 (build_zcta_vulnerability_map.py) y que el atlas
# web, para que todo el proyecto use el mismo lenguaje visual.
VULN_BANDS = [
    {"key": "low",      "label": "Baja",      "max": 10,        "color": "#0ca30c"},
    {"key": "moderate", "label": "Moderada",  "max": 15,        "color": "#fab219"},
    {"key": "high",     "label": "Alta",      "max": 20,        "color": "#ec835a"},
    {"key": "severe",   "label": "Severa",    "max": float("inf"), "color": "#d03b3b"},
]
VULN_NO_DATA_COLOR = "#9aa39c"


def vuln_band(v):
    if v is None:
        return None
    for band in VULN_BANDS:
        if v < band["max"]:
            return band
    return VULN_BANDS[-1]


# Mapa nacional a resolucion ZCTA5 (33,300 formas en el area continental),
# coloreado por banda de vulnerabilidad -- generado una vez por
# build_zcta_vulnerability_map.py a partir del mismo integrated_data_by_state.csv
# y del contorno oficial cb_2020_us_zcta520_500k (Census Bureau, dominio
# publico). Se referencia aqui como imagen de fondo, en base64, detras de la
# capa SVG de contornos de estado (que sigue siendo la que recibe los clicks).
_nation_png_path = Path(__file__).parent / "nation_vulnerability.png"
NATION_PNG_B64 = (
    base64.b64encode(_nation_png_path.read_bytes()).decode("ascii")
    if _nation_png_path.exists() else ""
)

# name debe coincidir exactamente con la propiedad "name" del geojson de
# contornos de estados que se descarga en el navegador (ver JS mas abajo).
STATES = {
    "AL": {"name": "Alabama", "capital": "Montgomery", "population": 5074296, "region": "S", "center": [-86.8, 32.8], "zoom": 6.2},
    "AK": {"name": "Alaska", "capital": "Juneau", "population": 733406, "region": "W", "center": [-152.0, 64.0], "zoom": 3.6},
    "AZ": {"name": "Arizona", "capital": "Phoenix", "population": 7359197, "region": "W", "center": [-111.9, 34.2], "zoom": 6.0},
    "AR": {"name": "Arkansas", "capital": "Little Rock", "population": 3045637, "region": "S", "center": [-92.4, 34.9], "zoom": 6.5},
    "CA": {"name": "California", "capital": "Sacramento", "population": 38965193, "region": "W", "center": [-119.7, 37.2], "zoom": 5.5},
    "CO": {"name": "Colorado", "capital": "Denver", "population": 5877610, "region": "W", "center": [-105.5, 39.0], "zoom": 6.2},
    "CT": {"name": "Connecticut", "capital": "Hartford", "population": 3617176, "region": "NE", "center": [-72.7, 41.6], "zoom": 8.3},
    "DE": {"name": "Delaware", "capital": "Dover", "population": 1031890, "region": "S", "center": [-75.5, 39.0], "zoom": 8.3},
    "FL": {"name": "Florida", "capital": "Tallahassee", "population": 22610726, "region": "S", "center": [-82.4, 28.6], "zoom": 5.9},
    "GA": {"name": "Georgia", "capital": "Atlanta", "population": 11029227, "region": "S", "center": [-83.4, 32.6], "zoom": 6.3},
    "HI": {"name": "Hawaii", "capital": "Honolulu", "population": 1435138, "region": "W", "center": [-156.3, 20.5], "zoom": 6.5},
    "ID": {"name": "Idaho", "capital": "Boise", "population": 1964726, "region": "W", "center": [-114.6, 44.4], "zoom": 5.9},
    "IL": {"name": "Illinois", "capital": "Springfield", "population": 12549689, "region": "MW", "center": [-89.2, 40.0], "zoom": 6.2},
    "IN": {"name": "Indiana", "capital": "Indianapolis", "population": 6862199, "region": "MW", "center": [-86.3, 39.9], "zoom": 6.6},
    "IA": {"name": "Iowa", "capital": "Des Moines", "population": 3207004, "region": "MW", "center": [-93.5, 42.0], "zoom": 6.5},
    "KS": {"name": "Kansas", "capital": "Topeka", "population": 2940546, "region": "MW", "center": [-98.4, 38.5], "zoom": 6.2},
    "KY": {"name": "Kentucky", "capital": "Frankfort", "population": 4526154, "region": "S", "center": [-85.3, 37.5], "zoom": 6.5},
    "LA": {"name": "Louisiana", "capital": "Baton Rouge", "population": 4573749, "region": "S", "center": [-92.0, 31.0], "zoom": 6.4},
    "ME": {"name": "Maine", "capital": "Augusta", "population": 1395722, "region": "NE", "center": [-69.2, 45.4], "zoom": 6.5},
    "MD": {"name": "Maryland", "capital": "Annapolis", "population": 6180253, "region": "S", "center": [-76.7, 39.0], "zoom": 7.3},
    "MA": {"name": "Massachusetts", "capital": "Boston", "population": 7001399, "region": "NE", "center": [-71.8, 42.3], "zoom": 7.6},
    "MI": {"name": "Michigan", "capital": "Lansing", "population": 10037261, "region": "MW", "center": [-85.4, 44.3], "zoom": 5.7},
    "MN": {"name": "Minnesota", "capital": "Saint Paul", "population": 5742225, "region": "MW", "center": [-94.3, 46.3], "zoom": 5.8},
    "MS": {"name": "Mississippi", "capital": "Jackson", "population": 2939690, "region": "S", "center": [-89.7, 32.7], "zoom": 6.4},
    "MO": {"name": "Missouri", "capital": "Jefferson City", "population": 6196156, "region": "MW", "center": [-92.5, 38.5], "zoom": 6.1},
    "MT": {"name": "Montana", "capital": "Helena", "population": 1132812, "region": "W", "center": [-109.6, 47.0], "zoom": 5.9},
    "NE": {"name": "Nebraska", "capital": "Lincoln", "population": 1978379, "region": "MW", "center": [-99.8, 41.5], "zoom": 6.2},
    "NV": {"name": "Nevada", "capital": "Carson City", "population": 3194176, "region": "W", "center": [-117.0, 39.5], "zoom": 5.9},
    "NH": {"name": "New Hampshire", "capital": "Concord", "population": 1395231, "region": "NE", "center": [-71.6, 43.7], "zoom": 7.4},
    "NJ": {"name": "New Jersey", "capital": "Trenton", "population": 9290841, "region": "NE", "center": [-74.7, 40.1], "zoom": 7.6},
    "NM": {"name": "New Mexico", "capital": "Santa Fe", "population": 2114371, "region": "W", "center": [-106.1, 34.5], "zoom": 6.0},
    "NY": {"name": "New York", "capital": "Albany", "population": 19571216, "region": "NE", "center": [-75.5, 42.9], "zoom": 6.0},
    "NC": {"name": "North Carolina", "capital": "Raleigh", "population": 10835491, "region": "S", "center": [-79.4, 35.5], "zoom": 6.3},
    "ND": {"name": "North Dakota", "capital": "Bismarck", "population": 783926, "region": "MW", "center": [-100.5, 47.5], "zoom": 6.2},
    "OH": {"name": "Ohio", "capital": "Columbus", "population": 11785935, "region": "MW", "center": [-82.8, 40.3], "zoom": 6.5},
    "OK": {"name": "Oklahoma", "capital": "Oklahoma City", "population": 4053824, "region": "S", "center": [-97.5, 35.5], "zoom": 6.2},
    "OR": {"name": "Oregon", "capital": "Salem", "population": 4233358, "region": "W", "center": [-120.6, 44.1], "zoom": 5.9},
    "PA": {"name": "Pennsylvania", "capital": "Harrisburg", "population": 12961683, "region": "NE", "center": [-77.8, 40.9], "zoom": 6.4},
    "RI": {"name": "Rhode Island", "capital": "Providence", "population": 1095962, "region": "NE", "center": [-71.5, 41.7], "zoom": 9.0},
    "SC": {"name": "South Carolina", "capital": "Columbia", "population": 5373555, "region": "S", "center": [-80.9, 33.9], "zoom": 6.7},
    "SD": {"name": "South Dakota", "capital": "Pierre", "population": 909824, "region": "MW", "center": [-100.2, 44.4], "zoom": 6.2},
    "TN": {"name": "Tennessee", "capital": "Nashville", "population": 7126489, "region": "S", "center": [-86.4, 35.9], "zoom": 6.4},
    "TX": {"name": "Texas", "capital": "Austin", "population": 30503301, "region": "S", "center": [-99.3, 31.5], "zoom": 5.2},
    "UT": {"name": "Utah", "capital": "Salt Lake City", "population": 3417734, "region": "W", "center": [-111.7, 39.3], "zoom": 6.1},
    "VT": {"name": "Vermont", "capital": "Montpelier", "population": 647464, "region": "NE", "center": [-72.7, 44.1], "zoom": 7.4},
    "VA": {"name": "Virginia", "capital": "Richmond", "population": 8715698, "region": "S", "center": [-78.9, 37.5], "zoom": 6.4},
    "WA": {"name": "Washington", "capital": "Olympia", "population": 7812880, "region": "W", "center": [-120.5, 47.4], "zoom": 6.0},
    "WV": {"name": "West Virginia", "capital": "Charleston", "population": 1770071, "region": "S", "center": [-80.6, 38.6], "zoom": 6.8},
    "WI": {"name": "Wisconsin", "capital": "Madison", "population": 5910955, "region": "MW", "center": [-89.7, 44.6], "zoom": 6.1},
    "WY": {"name": "Wyoming", "capital": "Cheyenne", "population": 584057, "region": "W", "center": [-107.5, 43.0], "zoom": 6.2},
    "DC": {"name": "District of Columbia", "capital": None, "population": 678972, "region": "S", "center": [-77.02, 38.90], "zoom": 11.5,
           "status": "Federal district", "note": "Establecido en 1790 como sede del gobierno federal. No es un estado: sus residentes no tienen representacion con voto en el Congreso."},
    "PR": {"name": "Puerto Rico", "capital": "San Juan", "population": 3205691, "region": "TERR", "center": [-66.5, 18.2], "zoom": 9.3,
           "status": "U.S. territory", "note": "Territorio no incorporado de EE. UU. desde 1898. Sus residentes son ciudadanos estadounidenses pero no pueden votar por el presidente ni tienen un escano con voto en el Congreso."},
}

# Lugares dentro de cada estado: condados reales, agregados desde
# integrated_data_by_state.csv (ZCTA5 -> condado), mas los municipios de
# Puerto Rico (ese archivo no trae coordenadas para PR).
CITIES = json.loads((Path(__file__).parent / "county_places.json").read_text(encoding="utf-8"))
for _place in CITIES.get("DC", []):
    _place["kind"] = "Distrito"
for _abbr, _places in CITIES.items():
    if _abbr != "DC":
        for _place in _places:
            _place["kind"] = "Condado"

CITIES["PR"] = [
    {"name": "San Juan", "lat": 18.47, "lon": -66.11, "population": 320000, "capital": True, "kind": "Municipio"},
    {"name": "Bayamon", "lat": 18.40, "lon": -66.15, "population": 180000, "kind": "Municipio"},
    {"name": "Carolina", "lat": 18.38, "lon": -65.96, "population": 150000, "kind": "Municipio"},
    {"name": "Ponce", "lat": 18.01, "lon": -66.61, "population": 133000, "kind": "Municipio"},
]

# Indice real de vulnerabilidad social (media ponderada por poblacion de
# 7 medidas SDOH: pobreza, desempleo, sin diploma, sin banda ancha, costo
# de vivienda, hacinamiento, hogares monoparentales), calculado por
# build_map_data.py a partir del mismo integrated_data_by_state.csv.
_map_data_path = Path(__file__).parent / "map_data.json"
MAP_DATA = json.loads(_map_data_path.read_text(encoding="utf-8")) if _map_data_path.exists() else None

if MAP_DATA:
    for _abbr, _places in CITIES.items():
        _state_data = MAP_DATA["states"].get(_abbr)
        if not _state_data:
            continue
        _by_name = {c["name"]: c for c in _state_data["counties"]}
        for _place in _places:
            _match = _by_name.get(_place["name"])
            if _match and _match.get("vulnerability") is not None:
                _place["v"] = _match["vulnerability"]
                _place["comps"] = _match["components"]

NAME_TO_ABBR = {v["name"]: k for k, v in STATES.items()}

# Contorno real de los 50 estados + D.C., guardado localmente (no se descarga
# en cada carga de la pagina): fuente PublicaMundi/MappingAPI, dominio publico.
STATES_GEOJSON = json.loads((Path(__file__).parent / "us_states.json").read_text(encoding="utf-8"))

# Contorno real de los condados (uno por estado + D.C.; Puerto Rico usa su
# propia vista con marcadores), generado una vez por build_county_shapes.py
# a partir del limite oficial cb_2020_us_county_500k (Census Bureau, dominio
# publico) y coloreado con el mismo indice de vulnerabilidad de
# map_data.json. Reemplaza el mapa de calles + pines al entrar a un estado:
# ahora la vista de estado es un SVG plano igual que la vista de pais, solo
# que dividido por condado en vez de por estado.
_county_shapes_path = Path(__file__).parent / "county_shapes.json"
COUNTY_SHAPES = (
    json.loads(_county_shapes_path.read_text(encoding="utf-8"))
    if _county_shapes_path.exists() else {}
)

st.title("Fifty States, One Territory")
st.caption(
    "Mapa nacional a resolucion ZCTA5 (codigo postal aproximado, ~33,300 formas), coloreado "
    "por banda de vulnerabilidad social. Haz click en un estado para ver sus condados, tambien "
    "coloreados por banda de vulnerabilidad, y en un condado para bajar a un mapa real a nivel "
    "de calle. Alaska, Hawai y Puerto Rico tienen accesos rapidos en las esquinas del mapa."
)

if MAP_DATA:
    _nat = MAP_DATA["national"]
    _c1, _c2, _c3, _c4 = st.columns(4)
    _c1.metric("Vulnerabilidad nacional", _nat["vulnerability"])
    _c2.metric("Poblacion cubierta", f"{int(_nat['population']):,}")
    _c3.metric("Estados y territorios", _nat["state_count"])
    _c4.metric("Condados / areas", sum(s["county_count"] for s in MAP_DATA["states"].values()))

HTML_TEMPLATE = r"""
<div id="app">
  <svg id="nation-svg" viewBox="0 0 1000 520" preserveAspectRatio="xMidYMid meet"></svg>
  <svg id="state-svg" class="view-hidden" preserveAspectRatio="xMidYMid meet"></svg>
  <div id="map" class="view-hidden"></div>
  <div id="control-card">
    <input id="search-input" list="place-list" placeholder="Buscar un estado o territorio..." autocomplete="off" />
    <datalist id="place-list"></datalist>
    <div id="breadcrumb">Estados Unidos</div>
    <button id="back-btn" style="display:none;">Volver</button>
  </div>
  <div id="info-panel" style="display:none;"></div>
  <button class="corner-chip" id="chip-AK" style="left:16px;">AK</button>
  <button class="corner-chip" id="chip-HI" style="left:66px;">HI</button>
  <button class="corner-chip" id="chip-PR" style="right:16px;">PR</button>
  <div id="load-error" style="display:none;"></div>
</div>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<style>
  html, body { margin:0; padding:0; height:100%; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
  #app { position:relative; width:100%; height:720px; }
  #nation-svg {
    position:absolute; inset:0; width:100%; height:100%; transition:opacity .4s ease;
    background-color:#eef2ef; background-image:__NATION_BG_CSS__;
    background-size:100% 100%; background-repeat:no-repeat;
  }
  #state-svg {
    position:absolute; inset:0; width:100%; height:100%; transition:opacity .4s ease;
    background-color:#eef2ef;
  }
  #map { position:absolute; inset:0; z-index:1; transition:opacity .4s ease; }
  .view-hidden { opacity:0; pointer-events:none; }
  #control-card {
    position:absolute; top:14px; left:14px; z-index:5;
    background:rgba(255,255,255,.96); border-radius:10px; padding:10px 12px;
    box-shadow:0 2px 10px rgba(0,0,0,.18); width:250px;
  }
  #search-input { width:100%; box-sizing:border-box; padding:7px 9px; font-size:13px; border:1px solid #c7d0cb; border-radius:6px; }
  #breadcrumb { margin-top:8px; font-size:12px; color:#52646a; }
  #back-btn {
    margin-top:8px; width:100%; box-sizing:border-box; font-size:13px; font-weight:600;
    padding:8px 10px; border-radius:6px; border:1px solid #16232a; background:#16232a;
    color:#fbfbf8; cursor:pointer;
  }
  #back-btn:hover { background:#2a3d45; }
  #info-panel {
    position:absolute; top:14px; right:14px; z-index:5; width:230px;
    background:rgba(255,255,255,.97); border-radius:10px; padding:14px;
    box-shadow:0 2px 10px rgba(0,0,0,.18); font-size:13px; color:#16232a;
  }
  #info-panel h3 { margin:0 0 8px; font-size:16px; }
  #info-panel .note { margin-top:8px; color:#52646a; font-size:11.5px; line-height:1.5; }
  #info-panel .tag {
    display:inline-block; font-size:10.5px; text-transform:uppercase; letter-spacing:.04em;
    padding:2px 8px; border-radius:999px; background:#7c4f96; color:#fbfbf8; margin-bottom:8px;
  }
  .corner-chip {
    position:absolute; bottom:16px; z-index:5; width:44px; height:44px; border-radius:50%;
    border:2px solid white; background:#7c4f96; color:#fbfbf8; font-weight:700; font-size:12px;
    cursor:pointer; box-shadow:0 2px 8px rgba(0,0,0,.25);
  }
  #load-error {
    position:absolute; bottom:14px; left:50%; transform:translateX(-50%); z-index:6;
    background:#a2503f; color:#fff; padding:8px 14px; border-radius:8px; font-size:12.5px;
  }
  .pin-icon { background:none; border:none; }
</style>
<script>
const STATES = __STATES_JSON__;
const CITIES = __CITIES_JSON__;
const REGIONS = __REGIONS_JSON__;
const NAME_TO_ABBR = __NAME_TO_ABBR_JSON__;
const STATES_GEOJSON = __STATES_GEOJSON__;
const COUNTY_SHAPES = __COUNTY_SHAPES_JSON__;
const VULN_BANDS = __VULN_BANDS_JSON__;
const VULN_NO_DATA_COLOR = __VULN_NO_DATA_COLOR_JSON__;
const US_BOUNDS = [[-125.5, 24.0], [-66.5, 49.8]];
const TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const TILE_ATTRIBUTION = '&copy; OpenStreetMap contributors';

function showFatal(msg) {
  const el = document.getElementById('load-error');
  el.style.display = 'block';
  el.textContent = msg;
}
window.onerror = function (msg, src, line, col, err) {
  showFatal('JS error: ' + msg + ' (linea ' + line + ')');
};

let currentLevel = 'nation';
let currentState = null;
let map = null; // el mapa real (MapLibre) se crea recien al entrar a un estado

function regionColor(abbr) {
  return REGIONS[STATES[abbr].region].color;
}

// --------------------------------------------------------------------
// Vista nacional: SVG plano (sin WebGL, sin tiles) -- solo divisiones
// entre estados, coloreadas por region, con sus siglas encima. El mapa
// "real" (calles, ciudades) solo se crea al entrar a un estado.
// --------------------------------------------------------------------
const VB_W = 1000, VB_H = 520;

// Proyeccion lineal lon/lat -> lienzo, parametrizada por limites y tamano de
// viewBox: la nacional usa US_BOUNDS fijo; cada estado arma la suya con sus
// propios limites (ver makeProjector / buildStateSvg mas abajo).
function makeProjector(bounds, vbW, vbH) {
  const [[lonMin, latMin], [lonMax, latMax]] = bounds;
  return ([lon, lat]) => [
    (lon - lonMin) / (lonMax - lonMin) * vbW,
    (latMax - lat) / (latMax - latMin) * vbH,
  ];
}
function padBounds([[lonMin, latMin], [lonMax, latMax]], pad) {
  const lonPad = (lonMax - lonMin) * pad;
  const latPad = (latMax - latMin) * pad;
  return [[lonMin - lonPad, latMin - latPad], [lonMax + lonPad, latMax + latPad]];
}
const project = makeProjector(US_BOUNDS, VB_W, VB_H);
function ringToPath(ring, proj) {
  return ring.map((pt, i) => (i === 0 ? 'M' : 'L') + proj(pt).join(',')).join(' ') + ' Z';
}
function geometryToPathD(geom, proj) {
  if (geom.type === 'Polygon') return geom.coordinates.map(r => ringToPath(r, proj)).join(' ');
  if (geom.type === 'MultiPolygon') return geom.coordinates.map(poly => poly.map(r => ringToPath(r, proj)).join(' ')).join(' ');
  return '';
}

const SVG_NS = 'http://www.w3.org/2000/svg';
function buildNationSvg() {
  const svg = document.getElementById('nation-svg');
  try {
    STATES_GEOJSON.features.forEach(f => {
      const abbr = NAME_TO_ABBR[f.properties.name];
      if (!abbr || abbr === 'PR') return;
      const path = document.createElementNS(SVG_NS, 'path');
      path.setAttribute('d', geometryToPathD(f.geometry, project));
      // El relleno por ZCTA5 ya viene pintado en el fondo (nation_vulnerability.png);
      // esta forma solo dibuja el borde del estado y recibe los clicks.
      path.setAttribute('fill', 'rgba(255,255,255,0)');
      path.setAttribute('pointer-events', 'all');
      path.setAttribute('fill-rule', 'evenodd');
      path.setAttribute('stroke', 'rgba(22,35,42,0.55)');
      path.setAttribute('stroke-width', '1.1');
      path.style.cursor = 'pointer';

      const [cx, cy] = project(STATES[abbr].center);
      const label = document.createElementNS(SVG_NS, 'text');
      label.setAttribute('x', cx);
      label.setAttribute('y', cy);
      label.setAttribute('text-anchor', 'middle');
      label.setAttribute('dominant-baseline', 'middle');
      label.setAttribute('font-size', '13');
      label.setAttribute('font-weight', '700');
      label.setAttribute('fill', '#16232a');
      label.setAttribute('paint-order', 'stroke');
      label.setAttribute('stroke', '#fbfbf8');
      label.setAttribute('stroke-width', '3');
      label.style.pointerEvents = 'none';
      label.style.transition = 'font-size .15s ease';
      label.textContent = abbr;

      function highlight(on) {
        path.setAttribute('stroke-width', on ? '2.4' : '1.1');
        path.setAttribute('stroke', on ? 'rgba(22,35,42,0.9)' : 'rgba(22,35,42,0.55)');
        path.setAttribute('fill', on ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0)');
        label.setAttribute('font-size', on ? '19' : '13');
      }
      path.addEventListener('mouseenter', () => highlight(true));
      path.addEventListener('mouseleave', () => highlight(false));
      path.addEventListener('click', () => enterState(abbr));
      const title = document.createElementNS(SVG_NS, 'title');
      title.textContent = STATES[abbr].name;
      path.appendChild(title);
      svg.appendChild(path);
      svg.appendChild(label);
    });
  } catch (e) {
    showFatal('Error dibujando el mapa: ' + e.message);
  }
}
buildNationSvg();

// --------------------------------------------------------------------
// Vista de estado / ciudad: mapa real con Leaflet (tiles como imagenes
// normales, sin WebGL, sin llave/API/cuenta). Se crea la primera vez
// que hace falta.
// --------------------------------------------------------------------
let cityCluster = null;

function pinIcon(color, big) {
  const w = big ? 34 : 26;
  const h = Math.round(w * 1.33);
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h + '" viewBox="0 0 24 32">' +
    '<path d="M12 0C5.4 0 0 5.4 0 12c0 9 12 20 12 20s12-11 12-20C24 5.4 18.6 0 12 0z" fill="' + color + '" stroke="#fbfbf8" stroke-width="1.5"/>' +
    '<circle cx="12" cy="12" r="4.6" fill="#fbfbf8"/>' +
    '</svg>';
  return L.divIcon({ html: svg, className: 'pin-icon', iconSize: [w, h], iconAnchor: [w / 2, h] });
}

function createMap(initialCenter, initialZoom, onReady) {
  const container = document.getElementById('map');
  // Fuerza un reflow sincrono: el contenedor acaba de pasar de
  // display:none a block, y sin esto el mapa puede medirlo con 0x0.
  void container.offsetHeight;

  try {
    // Sin control de zoom (+/-): las cuatro esquinas ya las usan la
    // tarjeta de busqueda, el panel de info y los accesos AK/HI/PR.
    // El zoom sigue funcionando con la rueda del mouse o pellizcando.
    map = L.map('map', { zoomControl: false }).setView(
      [initialCenter[1], initialCenter[0]], Math.round(initialZoom)
    );
    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, subdomains: 'abc', maxZoom: 19 }).addTo(map);
    cityCluster = L.markerClusterGroup({ maxClusterRadius: 42, spiderfyOnMaxZoom: true });
    map.addLayer(cityCluster);
    setTimeout(() => map.invalidateSize(), 60);
    onReady();
  } catch (e) {
    showFatal('Error creando el mapa: ' + e.message);
  }
}

// Bandas de vulnerabilidad social (indice SDOH real) -- mismos cortes y
// colores que el mapa nacional por ZCTA5 de fondo, para que el pin de un
// condado y el ZCTA5 que lo rodea se lean con el mismo lenguaje de color.
// Los lugares sin dato (p. ej. Puerto Rico) usan el color de su region.
function vulnBand(v) {
  if (v == null) return null;
  for (const band of VULN_BANDS) { if (v < band.max) return band; }
  return VULN_BANDS[VULN_BANDS.length - 1];
}
function placeColor(abbr, c) {
  const band = vulnBand(c.v);
  return band ? band.color : regionColor(abbr);
}

// --------------------------------------------------------------------
// Vista de estado: mismo mecanismo que el mapa nacional (SVG plano, sin
// tiles), pero dividido por condado en vez de por estado, y coloreado por
// banda de vulnerabilidad SDOH en vez de por region. El mapa real
// (Leaflet) solo se crea cuando el usuario entra a un condado en concreto.
// --------------------------------------------------------------------
const builtStateSvg = { abbr: null };

function countyDataFor(abbr, name) {
  const fromCities = (CITIES[abbr] || []).find(c => c.name === name);
  if (fromCities) return fromCities;
  const shapeEntry = COUNTY_SHAPES[abbr] && COUNTY_SHAPES[abbr].counties.find(c => c.name === name);
  if (shapeEntry) {
    return {
      name: shapeEntry.name,
      population: shapeEntry.population,
      v: shapeEntry.vulnerability,
      comps: shapeEntry.components,
      kind: 'Condado',
    };
  }
  return { name, population: null, v: null };
}

function stateVulnerability(abbr) {
  const sd = COUNTY_SHAPES[abbr];
  if (!sd) return null;
  let sum = 0, w = 0;
  sd.counties.forEach(c => {
    if (c.vulnerability != null && c.population) { sum += c.vulnerability * c.population; w += c.population; }
  });
  return w > 0 ? Math.round((sum / w) * 10) / 10 : null;
}

function shortCountyLabel(name) {
  return name.replace(/ (County|Parish|Borough|Municipality|Census Area|city)$/, '');
}

function buildStateSvg(abbr) {
  const svg = document.getElementById('state-svg');
  svg.innerHTML = '';
  const sdata = COUNTY_SHAPES[abbr];
  if (!sdata) return;

  const bounds = padBounds(sdata.bounds, 0.05);
  const lonSpan = bounds[1][0] - bounds[0][0];
  const latSpan = bounds[1][1] - bounds[0][1];
  const vbW = 1000;
  const vbH = Math.max(220, Math.round(vbW * (latSpan / lonSpan)));
  svg.setAttribute('viewBox', '0 0 ' + vbW + ' ' + vbH);
  const proj = makeProjector(bounds, vbW, vbH);

  sdata.counties.forEach(c => {
    const band = vulnBand(c.vulnerability);
    const baseColor = band ? band.color : VULN_NO_DATA_COLOR;

    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', geometryToPathD(c.geometry, proj));
    path.setAttribute('fill', baseColor);
    path.setAttribute('fill-opacity', '0.88');
    path.setAttribute('fill-rule', 'evenodd');
    path.setAttribute('stroke', 'rgba(22,35,42,0.55)');
    path.setAttribute('stroke-width', '1');
    path.style.cursor = 'pointer';

    const [cx, cy] = proj(c.center);
    const label = document.createElementNS(SVG_NS, 'text');
    label.setAttribute('x', cx);
    label.setAttribute('y', cy);
    label.setAttribute('text-anchor', 'middle');
    label.setAttribute('dominant-baseline', 'middle');
    label.setAttribute('font-size', '7.5');
    label.setAttribute('font-weight', '600');
    label.setAttribute('fill', '#16232a');
    label.setAttribute('paint-order', 'stroke');
    label.setAttribute('stroke', '#fbfbf8');
    label.setAttribute('stroke-width', '2.2');
    label.style.pointerEvents = 'none';
    label.style.transition = 'font-size .15s ease';
    label.textContent = shortCountyLabel(c.name);

    function highlight(on) {
      path.setAttribute('stroke-width', on ? '2.2' : '1');
      path.setAttribute('stroke', on ? 'rgba(22,35,42,0.95)' : 'rgba(22,35,42,0.55)');
      path.setAttribute('fill-opacity', on ? '1' : '0.88');
      label.setAttribute('font-size', on ? '12' : '7.5');
    }
    path.addEventListener('mouseenter', () => highlight(true));
    path.addEventListener('mouseleave', () => highlight(false));
    path.addEventListener('click', () => flyToCity(abbr, c.name, c.center));

    const title = document.createElementNS(SVG_NS, 'title');
    title.textContent = c.name + (c.vulnerability != null ? ' — vulnerabilidad ' + c.vulnerability + (band ? ' (' + band.label + ')' : '') : '');
    path.appendChild(title);

    svg.appendChild(path);
    svg.appendChild(label);
  });
}

function showStateSvg(abbr) {
  document.getElementById('state-svg').classList.remove('view-hidden');
  document.getElementById('map').classList.add('view-hidden');
  if (builtStateSvg.abbr !== abbr) {
    buildStateSvg(abbr);
    builtStateSvg.abbr = abbr;
  }
}

function showStateInfo(abbr) {
  const s = STATES[abbr];
  const hasCounties = !!COUNTY_SHAPES[abbr];
  const stateV = stateVulnerability(abbr);
  const band = vulnBand(stateV);
  const rows = [
    { label: 'Capital', value: s.capital || '—' },
    { label: 'Poblacion', value: s.population.toLocaleString('en-US') },
    { label: 'Region', value: REGIONS[s.region].label },
  ];
  if (stateV != null) {
    rows.push({ label: 'Vulnerabilidad (SDOH)', value: stateV + (band ? ' — ' + band.label : '') });
  }
  rows.push({
    label: hasCounties ? 'Condados en el mapa' : 'Lugares en el mapa',
    value: (hasCounties ? COUNTY_SHAPES[abbr].counties.length : (CITIES[abbr] || []).length).toLocaleString('en-US'),
  });
  showInfo(s.name, {
    status: s.status || (REGIONS[s.region].label + ' state'),
    tagColor: regionColor(abbr),
    note: s.note,
    rows: rows,
  });
}

function showCitiesForState(abbr) {
  cityCluster.clearLayers();
  CITIES[abbr].forEach(c => {
    const marker = L.marker([c.lat, c.lon], { icon: pinIcon(placeColor(abbr, c), !!c.capital) });
    const band = vulnBand(c.v);
    const label = band ? c.name + ' — vulnerabilidad ' + c.v + ' (' + band.label + ')' : c.name;
    marker.bindTooltip(label, { direction: 'top', offset: [0, -h_for(c)] });
    marker.on('click', () => flyToCity(abbr, c.name, [c.lon, c.lat]));
    cityCluster.addLayer(marker);
  });
}
function h_for(c) { return Math.round((c.capital ? 34 : 26) * 1.33); }

function showInfo(title, d) {
  const panel = document.getElementById('info-panel');
  panel.style.display = 'block';
  let html = '';
  if (d.status) html += '<div class="tag" style="background:' + (d.tagColor || '#7c4f96') + '">' + d.status + '</div><br>';
  html += '<h3>' + title + '</h3>';
  (d.rows || []).forEach(r => { html += '<div><b>' + r.label + ':</b> ' + r.value + '</div>'; });
  if (d.note) html += '<div class="note">' + d.note + '</div>';
  panel.innerHTML = html;
}

function enterState(abbr) {
  currentLevel = 'state';
  currentState = abbr;
  const s = STATES[abbr];

  document.getElementById('nation-svg').classList.add('view-hidden');

  if (COUNTY_SHAPES[abbr]) {
    // Estado con datos de condado: SVG plano coloreado por vulnerabilidad,
    // sin tiles ni clustering -- el mapa real solo aparece al entrar a un
    // condado especifico (flyToCity).
    document.getElementById('map').classList.add('view-hidden');
    showStateSvg(abbr);
    showStateInfo(abbr);
    finishEnterState(s);
  } else {
    // Sin datos de condado (Puerto Rico): se mantiene el mapa real con
    // marcadores por municipio.
    document.getElementById('state-svg').classList.add('view-hidden');
    document.getElementById('map').classList.remove('view-hidden');
    function focus(justCreated) {
      map.invalidateSize();
      if (!justCreated) map.flyTo([s.center[1], s.center[0]], Math.round(s.zoom), { duration: 1.2 });
      showCitiesForState(abbr);
      showStateInfo(abbr);
      finishEnterState(s);
    }
    if (map) focus(false); else createMap(s.center, s.zoom, () => focus(true));
  }
}

function finishEnterState(s) {
  const back = document.getElementById('back-btn');
  back.style.display = 'inline-block';
  back.textContent = '← Volver a Estados Unidos';
  document.getElementById('breadcrumb').textContent = 'Estados Unidos › ' + s.name;
}

function flyToCity(abbr, cityName, coords) {
  currentLevel = 'city';
  document.getElementById('state-svg').classList.add('view-hidden');
  document.getElementById('map').classList.remove('view-hidden');

  const city = countyDataFor(abbr, cityName);
  function focus(justCreated) {
    map.invalidateSize();
    if (!justCreated) map.flyTo([coords[1], coords[0]], 13, { duration: 1.4 });
    if (COUNTY_SHAPES[abbr]) {
      cityCluster.clearLayers();
      const marker = L.marker([coords[1], coords[0]], { icon: pinIcon(placeColor(abbr, city), true) });
      cityCluster.addLayer(marker);
    }
    const rows = [
      { label: 'Estado', value: STATES[abbr].name },
      { label: 'Poblacion', value: city.population != null ? city.population.toLocaleString('en-US') : '—' },
    ];
    if (city.v != null) {
      const band = vulnBand(city.v);
      rows.push({ label: 'Vulnerabilidad (SDOH)', value: city.v + (band ? ' — ' + band.label : '') });
      if (city.comps) {
        rows.push({ label: 'Pobreza (<150% FPL)', value: city.comps.POV150 + '%' });
        rows.push({ label: 'Desempleo', value: city.comps.UNEMP + '%' });
        rows.push({ label: 'Sin banda ancha', value: city.comps.BROAD + '%' });
      }
    } else {
      rows.push({ label: 'Region', value: REGIONS[STATES[abbr].region].label });
    }
    showInfo(cityName, {
      status: city.kind || 'Lugar',
      tagColor: placeColor(abbr, city),
      rows: rows,
    });
    const back = document.getElementById('back-btn');
    back.textContent = '← Volver a ' + STATES[abbr].name;
    document.getElementById('breadcrumb').textContent = 'Estados Unidos › ' + STATES[abbr].name + ' › ' + cityName;
  }

  if (map) focus(false); else createMap(coords, 13, () => focus(true));
}

function goNation() {
  currentLevel = 'nation';
  currentState = null;
  document.getElementById('back-btn').style.display = 'none';
  document.getElementById('info-panel').style.display = 'none';
  document.getElementById('breadcrumb').textContent = 'Estados Unidos';
  document.getElementById('map').classList.add('view-hidden');
  document.getElementById('state-svg').classList.add('view-hidden');
  document.getElementById('nation-svg').classList.remove('view-hidden');
}

document.getElementById('back-btn').addEventListener('click', () => {
  if (currentLevel === 'city') enterState(currentState);
  else if (currentLevel === 'state') goNation();
});

['AK', 'HI', 'PR'].forEach(abbr => {
  document.getElementById('chip-' + abbr).addEventListener('click', () => enterState(abbr));
});

const searchInput = document.getElementById('search-input');
const searchList = document.getElementById('place-list');
Object.values(STATES).forEach(s => {
  const opt = document.createElement('option');
  opt.value = s.name;
  searchList.appendChild(opt);
});
searchInput.addEventListener('change', () => {
  const match = Object.entries(STATES).find(([, v]) => v.name.toLowerCase() === searchInput.value.toLowerCase());
  if (match) { enterState(match[0]); searchInput.value = ''; searchInput.blur(); }
});
</script>
"""

_nation_bg_css = f"url('data:image/png;base64,{NATION_PNG_B64}')" if NATION_PNG_B64 else "none"

html = (
    HTML_TEMPLATE
    .replace("__STATES_JSON__", json.dumps(STATES))
    .replace("__CITIES_JSON__", json.dumps(CITIES))
    .replace("__REGIONS_JSON__", json.dumps(REGIONS))
    .replace("__NAME_TO_ABBR_JSON__", json.dumps(NAME_TO_ABBR))
    .replace("__STATES_GEOJSON__", json.dumps(STATES_GEOJSON))
    .replace("__COUNTY_SHAPES_JSON__", json.dumps(COUNTY_SHAPES))
    .replace("__VULN_BANDS_JSON__", json.dumps(VULN_BANDS))
    .replace("__VULN_NO_DATA_COLOR_JSON__", json.dumps(VULN_NO_DATA_COLOR))
    .replace("__NATION_BG_CSS__", _nation_bg_css)
)

components.html(html, height=730, scrolling=False)

if not NATION_PNG_B64:
    st.warning(
        "No se encontro nation_vulnerability.png -- corre "
        "`python3 build_zcta_vulnerability_map.py` para generarlo."
    )

legend_html = " &nbsp; ".join(
    f"<span style='display:inline-flex;align-items:center;gap:5px;font-size:12px;color:#666;'>"
    f"<span style='width:10px;height:10px;border-radius:3px;background:{b['color']};display:inline-block;'></span>"
    f"{b['label']}</span>"
    for b in VULN_BANDS
)
legend_html += (
    " &nbsp; <span style='display:inline-flex;align-items:center;gap:5px;font-size:12px;color:#666;'>"
    f"<span style='width:10px;height:10px;border-radius:3px;background:{VULN_NO_DATA_COLOR};display:inline-block;'></span>"
    "Sin dato</span>"
)
st.markdown(
    legend_html + " &nbsp; (mapa nacional por ZCTA5, vulnerabilidad social SDOH)",
    unsafe_allow_html=True,
)

if MAP_DATA:
    st.markdown(
        f"<div style='font-size:12px;color:#666;margin-top:4px;'>Media nacional: "
        f"{MAP_DATA['national']['vulnerability']} &mdash; los pines dentro de un estado usan "
        "las mismas bandas de color.</div>",
        unsafe_allow_html=True,
    )

st.caption(
    "Poblaciones y vulnerabilidad: calculadas desde integrated_data_by_state.csv. El mapa "
    "nacional colorea cada uno de los ~33,300 ZCTA5 del area continental; los pines dentro de "
    "un estado agregan esos mismos ZCTA5 por condado. Vulnerabilidad = media (ponderada por "
    "poblacion, cuando se agrega por condado o a nivel nacional) de 7 medidas SDOH: pobreza, "
    "desempleo, sin diploma, sin banda ancha, costo de vivienda, hacinamiento, hogares "
    "monoparentales."
)
