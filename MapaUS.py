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
import re
import time
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from shapely.geometry import shape as shapely_shape
from shapely.strtree import STRtree

import gemini_service

st.set_page_config(page_title="VITA NEX", page_icon="\U0001F5FA", layout="wide")

# Transiciones del panel de Dashboards: st.container(key=...) expone su div
# como clase CSS "st-key-<key>" (API oficial de Streamlit), asi que animamos
# entrada/salida cambiando de key en vez de tocar el DOM a mano. El area de
# graficas usa una key que depende del estado/condado elegido, para que al
# cambiar la seleccion se vuelva a montar (y por lo tanto reanime) solo esa
# parte, sin repetir la animacion de todo el panel.
st.markdown(
    """
    <style>
    @keyframes dashFadeIn {
        from { opacity: 0; transform: translateY(-10px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes dashFadeOut {
        from { opacity: 1; transform: translateY(0); }
        to   { opacity: 0; transform: translateY(-8px); }
    }
    .st-key-dash_section_open { animation: dashFadeIn 0.3s ease-out; }
    [class*="st-key-dash_charts_sel_"] { animation: dashFadeIn 0.28s ease-out; }
    /* Salida: solo las graficas se animan (dashFadeOut) al cerrar. Los
       controles y el mapa NO pueden usar este mismo truco -- cambiarles la
       key para reanimarlos le borra el valor a los widgets que tienen
       adentro (el dropdown de estado/condado, el mapa) -- ver el
       comentario junto a esos containers en el codigo. */
    .st-key-dash_charts_closing { animation: dashFadeOut 0.16s ease-in forwards; }
    /* Rankings: mismo mecanismo que el panel de Dashboards de arriba, pero
       sin necesidad de una key "closing" separada para el contenido interno
       -- Rankings no tiene widgets con estado adentro (son listas armadas
       en cada render a partir de MAP_DATA), asi que el contenedor entero
       puede cambiar de key libremente sin perder nada. */
    .st-key-rankings_section_open { animation: dashFadeIn 0.3s ease-out; }
    .st-key-rankings_section_closing { animation: dashFadeOut 0.16s ease-in forwards; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "x"

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
    {"key": "low",      "label": "Baja",      "max": 10,        "color": "#14532d"},
    {"key": "moderate", "label": "Moderada",  "max": 15,        "color": "#22c55e"},
    {"key": "high",     "label": "Alta",      "max": 20,        "color": "#a3e635"},
    {"key": "severe",   "label": "Severa",    "max": float("inf"), "color": "#fef08a"},
]
VULN_NO_DATA_COLOR = "#fff7ed"


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

if "show_dashboard" not in st.session_state:
    st.session_state.show_dashboard = False
if "dash_closing" not in st.session_state:
    st.session_state.dash_closing = False
if "show_rankings" not in st.session_state:
    st.session_state.show_rankings = False
if "rankings_closing" not in st.session_state:
    st.session_state.rankings_closing = False

# Un click en el mapa (dentro de col_map, mas abajo) no puede escribir
# directo en st.session_state["dash_mode"] / "dash_state_name" / etc: esos
# widgets ya se instanciaron ANTES en ese mismo run (estan mas arriba en el
# layout), y Streamlit prohibe modificar el estado de un widget ya creado en
# el run actual (tira StreamlitWidgetAlreadyInstantiatedError). Por eso ese
# click solo deja "_pending_map_click" y pide un rerun; aqui, arriba de
# todo -- antes de que se cree ningun widget del dashboard -- es donde se
# aplica de verdad.
if "_pending_map_click" in st.session_state:
    _pending_click = st.session_state.pop("_pending_map_click")
    _pending_abbr = _pending_click.get("abbr")
    _pending_county = _pending_click.get("county")
    if _pending_abbr in STATES:
        st.session_state.show_dashboard = True
        st.session_state["dash_mode"] = "Estado y condado" if _pending_county else "Estado completo"
        st.session_state["dash_state_name"] = STATES[_pending_abbr]["name"]
        if _pending_county:
            st.session_state[f"dash_county_name_{_pending_abbr}"] = _pending_county

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

# --------------------------------------------------------------------
# Dashboards: mismos datos de map_data.json (estado completo o un
# condado/municipio dentro de el), mostrados como graficas junto al mapa
# en vez de como pines/tooltips.
# --------------------------------------------------------------------
COMPONENT_LABELS = {
    "POV150": "Pobreza (<150% FPL)",
    "UNEMP": "Desempleo",
    "NOHSDP": "Sin diploma",
    "BROAD": "Sin banda ancha",
    "HCOST": "Costo de vivienda",
    "CROWD": "Hacinamiento",
    "SNGPNT": "Hogares monoparentales",
}
HEALTH_LABELS = {
    "ACCESS2": "Sin seguro medico",
    "OBESITY": "Obesidad",
    "DIABETES": "Diabetes",
    "CSMOKING": "Tabaquismo",
    "CHECKUP": "Chequeo medico anual",
    "DENTAL": "Visita dental anual",
}


def get_state_entry(abbr):
    return MAP_DATA["states"].get(abbr) if MAP_DATA else None


def get_county_entry(abbr, county_name):
    state_entry = get_state_entry(abbr)
    if not state_entry:
        return None
    return next((c for c in state_entry["counties"] if c["name"] == county_name), None)


# Distancia limite (en grados, ~2km) para considerar dos condados "vecinos".
# Los poligonos vienen del contorno cartografico simplificado (500k) que ya
# usa el mapa -- por la simplificacion, dos condados que en la realidad
# comparten borde a veces quedan con un huequito microscopico entre sus
# poligonos, asi que se usa distancia en vez de exigir que se toquen exacto.
_NEIGHBOR_DISTANCE_DEG = 0.02


@st.cache_data(show_spinner=False)
def compute_neighbor_contrasts(abbr):
    """Detecta pares de condados VECINOS (poligonos que se tocan o estan a
    unos pocos km) dentro de un estado donde uno cae en banda Alta/Severa y
    el otro en Baja -- para que el analisis de IA pueda mencionar ese tipo
    de contraste geografico real en vez de inventarlo a partir de un solo
    numero agregado por estado. Se cachea por estado (la geometria no
    cambia durante la sesion) porque calcular todos los pares es el unico
    paso algo pesado de armar el contexto para Gemini.

    Devuelve una lista (posiblemente vacia) de hasta 5 pares, ordenados por
    la diferencia de vulnerabilidad de mayor a menor.
    """
    sdata = COUNTY_SHAPES.get(abbr)
    if not sdata:
        return []

    shapes, valid = [], []
    for c in sdata["counties"]:
        if c.get("vulnerability") is None:
            continue
        try:
            geom = shapely_shape(c["geometry"])
        except Exception:
            continue
        shapes.append(geom)
        valid.append(c)

    if len(valid) < 2:
        return []

    tree = STRtree(shapes)
    seen_pairs = set()
    contrasts = []

    for i, geom in enumerate(shapes):
        c = valid[i]
        band = vuln_band(c["vulnerability"])
        if not band or band["key"] not in ("high", "severe"):
            continue
        for j in tree.query(geom.buffer(_NEIGHBOR_DISTANCE_DEG)):
            j = int(j)
            if j == i:
                continue
            other = valid[j]
            other_band = vuln_band(other["vulnerability"])
            if not other_band or other_band["key"] != "low":
                continue
            if geom.distance(shapes[j]) > _NEIGHBOR_DISTANCE_DEG:
                continue
            pair_key = tuple(sorted((c["name"], other["name"])))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            contrasts.append(
                {
                    "condadoVulnerabilidadAlta": c["name"],
                    "vulnerabilidadAlta": c["vulnerability"],
                    "bandaAlta": band["label"],
                    "condadoVulnerabilidadBaja": other["name"],
                    "vulnerabilidadBaja": other["vulnerability"],
                    "bandaBaja": other_band["label"],
                    "diferencia": round(c["vulnerability"] - other["vulnerability"], 1),
                }
            )

    contrasts.sort(key=lambda x: x["diferencia"], reverse=True)
    return contrasts[:5]


def render_dashboard(abbr, county_name):
    entry = get_county_entry(abbr, county_name) if county_name else get_state_entry(abbr)
    label = county_name or STATES[abbr]["name"]
    kind = "Condado / municipio" if county_name else "Estado completo"

    st.markdown(f"#### {label}")
    st.caption(kind)

    if not entry or entry.get("vulnerability") is None:
        st.info(f"No hay datos SDOH suficientes para **{label}** (comun en Puerto Rico y zonas sin poblacion).")
        return

    band = vuln_band(entry["vulnerability"])
    m1, m2 = st.columns(2)
    m1.metric(
        "Vulnerabilidad (SDOH)",
        entry["vulnerability"],
        (band["label"] if band else None),
        delta_color="off",
    )
    m2.metric("Poblacion", f"{int(entry['population']):,}" if entry.get("population") else "-")

    nat_comp = MAP_DATA["national"]["components"]
    comp = entry["components"]
    df_comp = pd.DataFrame(
        {
            label: [comp.get(k) for k in COMPONENT_LABELS],
            "Media nacional": [nat_comp.get(k) for k in COMPONENT_LABELS],
        },
        index=list(COMPONENT_LABELS.values()),
    )
    st.caption("Componentes de vulnerabilidad social (%)")
    st.bar_chart(df_comp, horizontal=True, height=280)

    health = entry.get("health") or {}
    if any(v is not None for v in health.values()):
        nat_health = MAP_DATA["national"]["health"]
        df_health = pd.DataFrame(
            {
                label: [health.get(k) for k in HEALTH_LABELS],
                "Media nacional": [nat_health.get(k) for k in HEALTH_LABELS],
            },
            index=list(HEALTH_LABELS.values()),
        )
        st.caption("Indicadores de salud (%)")
        st.bar_chart(df_health, horizontal=True, height=250)

    ctx = entry.get("context") or {}
    if ctx.get("REMNRTY") is not None or ctx.get("AGE65") is not None:
        c1, c2 = st.columns(2)
        if ctx.get("REMNRTY") is not None:
            c1.metric("Minoria racial/etnica", f"{ctx['REMNRTY']}%")
        if ctx.get("AGE65") is not None:
            c2.metric("65 anios o mas", f"{ctx['AGE65']}%")


def render_comparison_dashboard(abbrs):
    """Graficas de comparacion para el modo "Comparar estados": una fila
    por estado elegido, mismos indicadores que usa render_dashboard pero
    uno al lado del otro en vez de contra la media nacional."""
    if len(abbrs) < 2:
        st.info("Elige 2 o mas estados en el selector de arriba para compararlos.")
        return

    rows = []
    comp_series = {}
    for abbr in abbrs:
        entry = get_state_entry(abbr)
        if not entry or entry.get("vulnerability") is None:
            continue
        band = vuln_band(entry["vulnerability"])
        name = STATES[abbr]["name"]
        rows.append(
            {
                "Estado": name,
                "Vulnerabilidad SDOH": entry["vulnerability"],
                "Banda": band["label"] if band else "-",
                "Poblacion": int(entry["population"]) if entry.get("population") else None,
            }
        )
        comp = entry.get("components") or {}
        comp_series[name] = [comp.get(k) for k in COMPONENT_LABELS]

    if not rows:
        st.info("No hay datos SDOH suficientes para ninguno de los estados elegidos.")
        return

    st.markdown(f"#### Comparando {len(rows)} estados")
    st.caption("Comparar estados")

    df = pd.DataFrame(rows).set_index("Estado")
    st.caption("Vulnerabilidad SDOH por estado")
    st.bar_chart(df[["Vulnerabilidad SDOH"]], horizontal=True, height=max(120, 60 * len(rows)))
    st.dataframe(df, use_container_width=True)

    if len(comp_series) >= 2:
        df_comp = pd.DataFrame(comp_series, index=list(COMPONENT_LABELS.values()))
        st.caption("Componentes de vulnerabilidad social (%) por estado")
        st.bar_chart(df_comp, horizontal=True, height=280)


# --------------------------------------------------------------------
# Rankings: dos vistas del mismo indicador (vulnerabilidad SDOH promedio
# por estado, el mismo campo "vulnerability" que ya usa el resto de la app)
# -- una lista general ordenada de mayor a menor, y esa misma lista agrupada
# por banda de color. Los territorios sin dato (vulnerability=None: Samoa
# Americana, Guam, Islas Marianas, Puerto Rico, Islas Virgenes en el
# dataset actual) se excluyen de las dos, tal como se pidio.
# --------------------------------------------------------------------
def _ranked_state_vulnerabilities():
    if not MAP_DATA:
        return []
    ranked = [
        (abbr, STATES[abbr]["name"], entry["vulnerability"])
        for abbr, entry in MAP_DATA["states"].items()
        if abbr in STATES and entry.get("vulnerability") is not None
    ]
    ranked.sort(key=lambda row: row[2], reverse=True)
    return ranked


def render_rankings():
    ranked = _ranked_state_vulnerabilities()
    if not ranked:
        st.info("No hay datos suficientes para armar los rankings.")
        return

    col_general, col_bands = st.columns(2, gap="large")

    with col_general:
        st.markdown("**Ranking general (promedio de vulnerabilidad por estado)**")
        rows_html = "".join(
            f"<div style='display:flex;justify-content:space-between;align-items:center;"
            f"padding:5px 10px;background:{'#f7f7f5' if i % 2 else '#ffffff'};font-size:13px;'>"
            f"<span>{i + 1}. {name}</span>"
            f"<span style='display:inline-flex;align-items:center;gap:6px;color:#444;'>"
            f"<span style='width:10px;height:10px;border-radius:3px;"
            f"background:{vuln_band(v)['color']};display:inline-block;'></span>{v:.1f}</span>"
            f"</div>"
            for i, (abbr, name, v) in enumerate(ranked)
        )
        st.markdown(
            f"<div style='border:1px solid #ddd;border-radius:8px;max-height:560px;"
            f"overflow-y:auto;'>{rows_html}</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            f"{len(ranked)} estados/territorios con dato -- orden descendente, del peor "
            f"promedio ({ranked[0][1]}) al mejor ({ranked[-1][1]})."
        )

    with col_bands:
        st.markdown("**Ranking por banda de vulnerabilidad promedio**")
        for band in VULN_BANDS:
            # Dentro de cada banda, de menor a mayor -- menor vulnerabilidad
            # es mejor, asi que ese va primero (al reves del orden del
            # ranking general, que es de mayor a menor).
            band_rows = sorted(
                ((name, v) for _abbr, name, v in ranked if vuln_band(v) is band),
                key=lambda row: row[1],
            )
            if not band_rows:
                continue
            items_html = "".join(
                f"<div style='display:flex;justify-content:space-between;padding:3px 10px;"
                f"font-size:13px;'><span>{i + 1}. {name}</span><span style='color:#555;'>{v:.1f}</span></div>"
                for i, (name, v) in enumerate(band_rows)
            )
            st.markdown(
                f"<div style='border:1px solid #ddd;border-radius:8px;padding:8px 0;margin-bottom:12px;'>"
                f"<div style='display:flex;align-items:center;gap:8px;padding:0 10px 6px;"
                f"border-bottom:1px solid #eee;'>"
                f"<span style='width:14px;height:14px;border-radius:4px;background:{band['color']};"
                f"display:inline-block;border:1px solid rgba(0,0,0,.15);'></span>"
                f"<strong>{band['label']}</strong>"
                f"<span style='color:#888;font-size:12px;'>({len(band_rows)})</span>"
                f"</div>{items_html}</div>",
                unsafe_allow_html=True,
            )


# --------------------------------------------------------------------
# Analisis con IA (Gemini): arma un contexto compacto -- nunca el dataset
# completo -- reutilizando get_state_entry/get_county_entry (los mismos
# que usa render_dashboard) y se lo manda a gemini_service, que vive en su
# propio modulo para no mezclar la llamada al modelo con la UI. La API key
# solo se lee ahi, del lado servidor -- nunca llega al navegador.
# --------------------------------------------------------------------
def _entry_metrics(entry):
    if not entry or entry.get("vulnerability") is None:
        return None
    comp = entry.get("components") or {}
    health = entry.get("health") or {}
    ctx = entry.get("context") or {}
    has_health = any(v is not None for v in health.values())
    band = vuln_band(entry["vulnerability"])
    return {
        "poblacion": entry.get("population"),
        "vulnerabilidadSDOH": entry["vulnerability"],
        "bandaVulnerabilidad": band["label"] if band else None,
        "componentesSDOH_pct": {COMPONENT_LABELS[k]: comp.get(k) for k in COMPONENT_LABELS},
        "indicadoresSalud_pct": (
            {HEALTH_LABELS[k]: health.get(k) for k in HEALTH_LABELS} if has_health else None
        ),
        "minoriaRacialEtnica_pct": ctx.get("REMNRTY"),
        "mayores65_pct": ctx.get("AGE65"),
    }


def build_ai_context(abbr, county_name):
    """Objeto compacto que se le manda a Gemini -- nunca el dataset
    completo, solo los indicadores de la seleccion activa (ver el shape
    pedido: selectionLevel "state"/"county" + dashboardContext)."""
    nat = MAP_DATA["national"] if MAP_DATA else None
    dashboard_context = {
        "dateRange": (
            "Snapshot mas reciente disponible en el proyecto (CDC PLACES + AHRQ SDOH); "
            "no hay serie temporal ni rango de fechas."
        ),
        "activeFilters": {
            "modo": "Estado y condado" if county_name else "Estado completo",
            "estado": STATES[abbr]["name"],
            "condado": county_name,
        },
        "dataSource": "integrated_data_by_state.csv (CDC PLACES + AHRQ SDOH, agregado por condado y estado)",
    }
    national_reference = (
        {
            "vulnerabilidadSDOH": nat["vulnerability"],
            "componentesSDOH_pct": {COMPONENT_LABELS[k]: nat["components"].get(k) for k in COMPONENT_LABELS},
        }
        if nat else None
    )

    context = {
        "selectionLevel": "county" if county_name else "state",
        "state": {"name": STATES[abbr]["name"], "metrics": _entry_metrics(get_state_entry(abbr))},
        "dashboardContext": dashboard_context,
        "nationalReference": national_reference,
        # Pares de condados VECINOS (geometria real, no solo el numero
        # agregado del estado) donde uno cae en banda Alta/Severa y el de
        # al lado en Baja -- calculado en Python (compute_neighbor_contrasts)
        # para que Gemini lo reporte tal cual en vez de inventar geografia.
        # Lista vacia = no se detecto ningun contraste fuerte entre vecinos.
        "contrastesVecinos": compute_neighbor_contrasts(abbr),
    }
    if county_name:
        context["county"] = {
            "name": county_name,
            "metrics": _entry_metrics(get_county_entry(abbr, county_name)),
        }
    return context


def build_ai_comparison_context(abbrs):
    """Igual que build_ai_context, pero para el modo "Comparar estados":
    una lista de estados en vez de un solo estado/condado. Tampoco manda el
    dataset completo -- solo los indicadores ya agregados por estado."""
    nat = MAP_DATA["national"] if MAP_DATA else None
    national_reference = (
        {
            "vulnerabilidadSDOH": nat["vulnerability"],
            "componentesSDOH_pct": {COMPONENT_LABELS[k]: nat["components"].get(k) for k in COMPONENT_LABELS},
        }
        if nat else None
    )
    return {
        "selectionLevel": "comparison",
        "states": [
            {"name": STATES[abbr]["name"], "metrics": _entry_metrics(get_state_entry(abbr))}
            for abbr in abbrs
        ],
        "dashboardContext": {
            "dateRange": (
                "Snapshot mas reciente disponible en el proyecto (CDC PLACES + AHRQ SDOH); "
                "no hay serie temporal ni rango de fechas."
            ),
            "activeFilters": {
                "modo": "Comparar estados",
                "estados": [STATES[abbr]["name"] for abbr in abbrs],
            },
            "dataSource": "integrated_data_by_state.csv (CDC PLACES + AHRQ SDOH, agregado por estado)",
        },
        "nationalReference": national_reference,
    }


_AI_ERROR_ICONS = {
    "no_api_key": "🔑",
    "missing_dependency": "🧩",
    "invalid_key": "🔑",
    "rate_limited": "⏳",
    "server_error": "🌐",
    "network_error": "🌐",
    "invalid_response": "⚠️",
    "client_error": "⚠️",
}


def get_active_selection():
    """Estado/condado activo -- el mismo que usan los dropdowns y el mapa
    del panel de Dashboards, pero leido desde un espejo en claves propias
    (active_state_abbr/active_county_name) que SI persiste aunque ese panel
    este cerrado -- las claves de los widgets (dash_state_name, etc.) se
    borran de session_state en cuanto sus widgets dejan de dibujarse. Asi el
    panel fijo de IA (fuera de Dashboards, ver mas abajo) siempre sabe de
    que estado/condado hablar, sin duplicar la logica de seleccion."""
    abbr = st.session_state.get("active_state_abbr")
    if not abbr or abbr not in STATES:
        return None, None
    return abbr, st.session_state.get("active_county_name")


def render_ai_panel(abbr, county_name):
    if not abbr:
        st.info(
            "Selecciona un estado (buscandolo, o haciendo click en el mapa) para generar un "
            "analisis con IA."
        )
        return

    current_sel = (abbr, county_name)
    for _key, _default in (
        ("ai_loading", False),
        ("ai_pending_selection", None),
        ("ai_result", None),
        ("ai_result_selection", None),
    ):
        if _key not in st.session_state:
            st.session_state[_key] = _default

    # Una solicitud que quedo "cargando" para una seleccion que ya no es la
    # actual (el usuario cambio de estado/condado mientras Gemini
    # generaba) se abandona: no seguimos esperandola ni la mostramos si
    # llega a resolverse despues.
    if st.session_state.ai_loading and st.session_state.ai_pending_selection != current_sel:
        st.session_state.ai_loading = False
        st.session_state.ai_pending_selection = None

    entry = get_county_entry(abbr, county_name) if county_name else get_state_entry(abbr)
    label = county_name or STATES[abbr]["name"]

    if not entry or entry.get("vulnerability") is None:
        st.caption(f"No hay datos SDOH suficientes de **{label}** para pedirle un analisis a Gemini.")
        return

    has_result_for_current = (
        st.session_state.ai_result is not None and st.session_state.ai_result_selection == current_sel
    )

    col_gen, col_regen = st.columns(2)
    generate_clicked = col_gen.button(
        "Generar analisis con IA",
        key="ai_generate_btn",
        icon=":material/auto_awesome:",
        disabled=st.session_state.ai_loading,
        use_container_width=True,
    )
    regenerate_clicked = col_regen.button(
        "Volver a generar",
        key="ai_regenerate_btn",
        icon=":material/refresh:",
        disabled=st.session_state.ai_loading or not has_result_for_current,
        use_container_width=True,
    )

    if (generate_clicked or regenerate_clicked) and not st.session_state.ai_loading:
        st.session_state.ai_loading = True
        st.session_state.ai_pending_selection = current_sel
        st.rerun()

    if st.session_state.ai_loading and st.session_state.ai_pending_selection == current_sel:
        with st.spinner(f"Gemini esta analizando {label}..."):
            context = build_ai_context(abbr, county_name)
            result = gemini_service.generate_analysis(context)
        # Si mientras corria la llamada el usuario ya cambio de seleccion,
        # este resultado quedo obsoleto -- no lo guardamos como "actual".
        if st.session_state.ai_pending_selection == current_sel:
            st.session_state.ai_result = result
            st.session_state.ai_result_selection = current_sel
        st.session_state.ai_loading = False
        st.rerun()

    result = st.session_state.ai_result
    result_sel = st.session_state.ai_result_selection

    if result is None:
        st.caption("Todavia no se genero un analisis para esta seleccion.")
        return

    if result_sel != current_sel:
        if result_sel and result_sel[0] in STATES:
            old_label = STATES[result_sel[0]]["name"] + (f" / {result_sel[1]}" if result_sel[1] else "")
        else:
            old_label = "una seleccion anterior"
        st.info(
            f"El ultimo analisis generado corresponde a **{old_label}**, no a la seleccion actual. "
            "Genera uno nuevo para verlo aqui."
        )
        return

    if not result.get("ok"):
        icon = _AI_ERROR_ICONS.get(result.get("code"), "⚠️")
        st.error(f"{icon} {result.get('message', 'No se pudo generar el analisis.')}")
        return

    if result.get("truncated"):
        st.warning(
            "⚠️ La respuesta se corto antes de terminar las 5 secciones (limite de tokens del "
            "modelo). Puedes darle a **Volver a generar** para intentar de nuevo."
        )
    st.markdown(result["text"])
    st.caption(
        f"🤖 Analisis generado con IA (Gemini, modelo `{result.get('model', '?')}`) para **{label}**"
        + (f", estado **{STATES[abbr]['name']}**" if county_name else "")
        + " -- basado unicamente en los datos mostrados en este dashboard. Verifica cifras "
        "criticas antes de usarlas para tomar decisiones."
    )


def render_ai_comparison_panel(abbrs):
    """Version de render_ai_panel para el modo "Comparar estados" -- usa su
    propio set de claves de session_state (ai_compare_*) para no pisar ni
    mezclarse con el analisis de un solo estado/condado."""
    if len(abbrs) < 2:
        st.info("Elige 2 o mas estados en el selector de arriba para pedirle a Gemini que los compare.")
        return

    current_sel = tuple(sorted(abbrs))
    for _key, _default in (
        ("ai_compare_loading", False),
        ("ai_compare_pending_selection", None),
        ("ai_compare_result", None),
        ("ai_compare_result_selection", None),
    ):
        if _key not in st.session_state:
            st.session_state[_key] = _default

    if st.session_state.ai_compare_loading and st.session_state.ai_compare_pending_selection != current_sel:
        st.session_state.ai_compare_loading = False
        st.session_state.ai_compare_pending_selection = None

    valid_abbrs = [a for a in abbrs if (get_state_entry(a) or {}).get("vulnerability") is not None]
    label = " vs. ".join(STATES[a]["name"] for a in abbrs)

    if not valid_abbrs or len(valid_abbrs) < 2:
        st.caption(
            f"No hay datos SDOH suficientes para al menos dos de los estados elegidos "
            f"({label}) -- no se le puede pedir una comparacion a Gemini."
        )
        return

    has_result_for_current = (
        st.session_state.ai_compare_result is not None
        and st.session_state.ai_compare_result_selection == current_sel
    )

    col_gen, col_regen = st.columns(2)
    generate_clicked = col_gen.button(
        "Generar analisis comparativo con IA",
        key="ai_compare_generate_btn",
        icon=":material/auto_awesome:",
        disabled=st.session_state.ai_compare_loading,
        use_container_width=True,
    )
    regenerate_clicked = col_regen.button(
        "Volver a generar",
        key="ai_compare_regenerate_btn",
        icon=":material/refresh:",
        disabled=st.session_state.ai_compare_loading or not has_result_for_current,
        use_container_width=True,
    )

    if (generate_clicked or regenerate_clicked) and not st.session_state.ai_compare_loading:
        st.session_state.ai_compare_loading = True
        st.session_state.ai_compare_pending_selection = current_sel
        st.rerun()

    if st.session_state.ai_compare_loading and st.session_state.ai_compare_pending_selection == current_sel:
        with st.spinner(f"Gemini esta comparando {label}..."):
            context = build_ai_comparison_context(abbrs)
            result = gemini_service.generate_analysis(context)
        if st.session_state.ai_compare_pending_selection == current_sel:
            st.session_state.ai_compare_result = result
            st.session_state.ai_compare_result_selection = current_sel
        st.session_state.ai_compare_loading = False
        st.rerun()

    result = st.session_state.ai_compare_result
    result_sel = st.session_state.ai_compare_result_selection

    if result is None:
        st.caption("Todavia no se genero un analisis comparativo para esta seleccion.")
        return

    if result_sel != current_sel:
        old_label = (
            " vs. ".join(STATES[a]["name"] for a in result_sel if a in STATES)
            if result_sel else "una seleccion anterior"
        )
        st.info(
            f"El ultimo analisis comparativo corresponde a **{old_label}**, no a la seleccion "
            "actual. Genera uno nuevo para verlo aqui."
        )
        return

    if not result.get("ok"):
        icon = _AI_ERROR_ICONS.get(result.get("code"), "⚠️")
        st.error(f"{icon} {result.get('message', 'No se pudo generar el analisis.')}")
        return

    if result.get("truncated"):
        st.warning(
            "⚠️ La respuesta se corto antes de terminar las 5 secciones (limite de tokens del "
            "modelo). Puedes darle a **Volver a generar** para intentar de nuevo."
        )
    st.markdown(result["text"])
    st.caption(
        f"🤖 Analisis comparativo generado con IA (Gemini, modelo `{result.get('model', '?')}`) "
        f"para **{label}** -- basado unicamente en los datos mostrados en este dashboard. "
        "Verifica cifras criticas antes de usarlas para tomar decisiones."
    )


st.title("VITA NEX")
st.markdown(
    "<div style='font-size:1.05rem;color:#666;font-style:italic;margin-top:-8px;"
    "margin-bottom:8px;'>See the bigger picture, connecting factors that shape health.</div>",
    unsafe_allow_html=True,
)
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
    position:absolute; inset:0; width:100%; height:100%;
    transform-origin:center center; transform:scale(1);
    background-color:#eef2ef; background-image:__NATION_BG_CSS__;
    background-size:contain; background-position:center; background-repeat:no-repeat;
  }
  #state-svg {
    position:absolute; inset:0; width:100%; height:100%;
    transform-origin:center center; transform:scale(1);
    background-color:#eef2ef;
  }
  #map { position:absolute; inset:0; z-index:1; transition:opacity .4s ease; }
  .view-hidden { opacity:0; pointer-events:none; transform:scale(0); }
  /* Animacion de zoom (pais <-> estado), a proposito NO es una simple
     transicion CSS por opacidad+transform en paralelo -- eso se sentia muy
     diluido (los dos SVG cambiando encimados al mismo tiempo). Esto son dos
     animaciones con nombre y en SECUENCIA real (la de salida termina antes
     de que arranque la de entrada -- ver zoomSwap() en el JS). Tiene
     direccion: "forward" (pais -> estado, se siente como avanzar/acercarse:
     lo que se va CRECE y se desvanece, como si pasaramos a traves; lo nuevo
     APARECE CHICO y crece hacia nosotros) y "backward" (estado -> pais, el
     regreso: lo que se va se ENCOGE y se desvanece -- se aleja; lo nuevo
     aparece GRANDE y se encoge a su tamano normal -- como si nos alejaramos
     de donde estabamos). Solo se aplica a las dos vistas SVG (pais/estado)
     -- el mapa real (#map, Leaflet) sigue solo con el fade de arriba, para
     no desincronizar el tamano que Leaflet cree que tiene.
  */
  @keyframes mapPushOut {
    from { opacity:1; transform:scale(1); }
    to   { opacity:0; transform:scale(2.4); }
  }
  @keyframes mapPushIn {
    from { opacity:0; transform:scale(.25); }
    to   { opacity:1; transform:scale(1); }
  }
  @keyframes mapPullOut {
    from { opacity:1; transform:scale(1); }
    to   { opacity:0; transform:scale(.25); }
  }
  @keyframes mapPullIn {
    from { opacity:0; transform:scale(2.4); }
    to   { opacity:1; transform:scale(1); }
  }
  #nation-svg.zoom-fwd-out, #state-svg.zoom-fwd-out {
    animation:mapPushOut .38s cubic-bezier(.55,0,.85,.35) forwards;
  }
  #nation-svg.zoom-fwd-in, #state-svg.zoom-fwd-in {
    animation:mapPushIn .38s cubic-bezier(.15,.65,.45,1) forwards;
  }
  #nation-svg.zoom-back-out, #state-svg.zoom-back-out {
    animation:mapPullOut .38s cubic-bezier(.55,0,.85,.35) forwards;
  }
  #nation-svg.zoom-back-in, #state-svg.zoom-back-in {
    animation:mapPullIn .38s cubic-bezier(.15,.65,.45,1) forwards;
  }
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

// --------------------------------------------------------------------
// Puente de Streamlit Components, escrito a mano (sin streamlit-component-lib,
// sin build/npm): esto es lo que permite que un click en un condado dentro
// de este iframe le devuelva un valor a Python (a diferencia de
// components.html, que es un srcdoc sin canal de vuelta). El protocolo es
// solo postMessage con dos tipos de mensaje, en ambas direcciones:
//   - de aqui hacia Streamlit: streamlit:componentReady, streamlit:setComponentValue
//   - de Streamlit hacia aqui: streamlit:render (trae los args actuales cada
//     vez que Python vuelve a llamar al componente)
const Streamlit = (() => {
  function post(type, payload) {
    window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type }, payload), '*');
  }
  return {
    init: () => post('streamlit:componentReady', { apiVersion: 1 }),
    sendValue: (value) => post('streamlit:setComponentValue', { value, dataType: 'json' }),
    onRender: (callback) => {
      window.addEventListener('message', (event) => {
        if (event.data && event.data.type === 'streamlit:render') callback(event.data);
      });
    },
  };
})();

let currentLevel = 'nation';
let currentState = null;
let map = null; // el mapa real (MapLibre) se crea recien al entrar a un estado
let lastZoomOrigin = '50% 50%'; // punto (transform-origin) del ultimo zoom pais<->estado, para que la salida revierta por el mismo punto de entrada

// Evita que un click viejo (ya procesado del lado de Python) se vuelva a
// aplicar solo porque el componente se re-renderizo por otra razon: cada
// click manda un numero que siempre sube (clickSeq). lastAppliedAbbr/County
// evitan volver a llamar enterState/flyToCity si la vista actual ya es esa
// (por ejemplo cuando el propio click que mandamos vuelve reflejado en el
// siguiente streamlit:render).
let clickSeq = 0;
let lastAppliedAbbr = null;
let lastAppliedCounty = null;

function reportCountyClick(abbr, countyName) {
  lastAppliedAbbr = abbr;
  lastAppliedCounty = countyName;
  clickSeq += 1;
  Streamlit.sendValue({ abbr, county: countyName, seq: clickSeq });
}

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
      path.addEventListener('click', () => {
        enterState(abbr);
        reportCountyClick(abbr, null);
      });
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
// Animacion de zoom pais <-> estado: dos animaciones con nombre EN
// SECUENCIA (no una transicion CSS por opacidad+transform corriendo en
// paralelo en los dos SVG a la vez -- eso se sentia muy diluido). Primero
// el que se ve termina su animacion de salida, y RECIEN CUANDO ESO TERMINA
// arranca el nuevo con su animacion de entrada. direction="forward" (entrar
// a un estado) hace que lo viejo CREZCA y se desvanezca (como si pasaramos
// a traves de el, avanzando) y lo nuevo APAREZCA CHICO y crezca hacia
// nosotros. direction="backward" (volver al pais) es lo opuesto: lo viejo
// se ENCOGE y se desvanece (se aleja) y lo nuevo aparece GRANDE y se encoge
// a su tamano normal. Los nombres de las clases atan a los @keyframes de
// mas arriba.
// --------------------------------------------------------------------
// Punto (en % del viewBox del SVG nacional) donde esta el centro de un
// estado -- el mismo punto se usa como transform-origin al entrar (el pais
// se "hunde" hacia ahi y el estado nace ahi) y al salir (el estado se
// encoge hacia ese mismo punto y el pais crece desde ahi), para que la
// animacion apunte al estado en cuestion en vez de siempre al centro fijo
// del mapa.
function stateOriginPercent(abbr) {
  const [cx, cy] = project(STATES[abbr].center);
  const x = Math.min(100, Math.max(0, (cx / VB_W) * 100));
  const y = Math.min(100, Math.max(0, (cy / VB_H) * 100));
  return x.toFixed(2) + '% ' + y.toFixed(2) + '%';
}

function zoomSwap(hideEl, showEl, direction, origin) {
  const outClass = direction === 'backward' ? 'zoom-back-out' : 'zoom-fwd-out';
  const inClass = direction === 'backward' ? 'zoom-back-in' : 'zoom-fwd-in';
  const ALL_ZOOM_CLASSES = ['zoom-fwd-out', 'zoom-fwd-in', 'zoom-back-out', 'zoom-back-in'];

  // Si habia una animacion a medias (el usuario clickeo dos veces muy
  // rapido), la cortamos limpio antes de arrancar la nueva en vez de
  // dejarla colgada o pisarse entre si.
  [hideEl, showEl].forEach(el => el.classList.remove(...ALL_ZOOM_CLASSES));
  if (origin) {
    hideEl.style.transformOrigin = origin;
    showEl.style.transformOrigin = origin;
  }

  hideEl.classList.remove('view-hidden');
  void hideEl.offsetWidth; // fuerza un reflow: sin esto el navegador a veces no nota que hay que reiniciar la animacion
  hideEl.classList.add(outClass);

  const finishOut = () => {
    hideEl.removeEventListener('animationend', finishOut);
    hideEl.classList.remove(outClass);
    hideEl.classList.add('view-hidden');

    showEl.classList.remove('view-hidden');
    void showEl.offsetWidth;
    showEl.classList.add(inClass);
    const finishIn = () => {
      showEl.removeEventListener('animationend', finishIn);
      showEl.classList.remove(inClass);
    };
    showEl.addEventListener('animationend', finishIn);
  };
  hideEl.addEventListener('animationend', finishOut);
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
    path.addEventListener('click', () => {
      flyToCity(abbr, c.name, c.center);
      reportCountyClick(abbr, c.name);
    });

    const title = document.createElementNS(SVG_NS, 'title');
    title.textContent = c.name + (c.vulnerability != null ? ' — vulnerabilidad ' + c.vulnerability + (band ? ' (' + band.label + ')' : '') : '');
    path.appendChild(title);

    svg.appendChild(path);
    svg.appendChild(label);
  });
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
    marker.on('click', () => {
      flyToCity(abbr, c.name, [c.lon, c.lat]);
      reportCountyClick(abbr, c.name);
    });
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

  if (COUNTY_SHAPES[abbr]) {
    // Estado con datos de condado: SVG plano coloreado por vulnerabilidad,
    // sin tiles ni clustering -- el mapa real solo aparece al entrar a un
    // condado especifico (flyToCity).
    document.getElementById('map').classList.add('view-hidden');
    if (builtStateSvg.abbr !== abbr) {
      buildStateSvg(abbr);
      builtStateSvg.abbr = abbr;
    }
    const nationEl = document.getElementById('nation-svg');
    const stateEl = document.getElementById('state-svg');
    if (!nationEl.classList.contains('view-hidden')) {
      // Veniamos del mapa completo -- esta es la animacion de zoom pedida:
      // el pais se hunde hacia donde esta el estado clickeado y, cuando
      // termina, el estado crece desde ese mismo punto.
      lastZoomOrigin = stateOriginPercent(abbr);
      zoomSwap(nationEl, stateEl, 'forward', lastZoomOrigin);
    } else {
      // Ya estabamos viendo otro estado (p. ej. se cambio de estado por el
      // dropdown de Dashboards sin volver antes al mapa completo) -- no
      // hay "mapa completo" del que salir, asi que el cambio es directo.
      nationEl.classList.add('view-hidden');
      stateEl.classList.remove('view-hidden');
    }
    showStateInfo(abbr);
    finishEnterState(s);
  } else {
    // Sin datos de condado (Puerto Rico): se mantiene el mapa real con
    // marcadores por municipio.
    document.getElementById('nation-svg').classList.add('view-hidden');
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

  const nationEl = document.getElementById('nation-svg');
  const stateEl = document.getElementById('state-svg');
  document.getElementById('map').classList.add('view-hidden');

  if (!stateEl.classList.contains('view-hidden')) {
    // Misma animacion de zoom, ahora al reves: el estado se encoge hacia el
    // mismo punto por el que se entro (lastZoomOrigin) y el pais completo
    // crece desde ahi de vuelta a su tamano normal.
    zoomSwap(stateEl, nationEl, 'backward', lastZoomOrigin);
  } else {
    stateEl.classList.add('view-hidden');
    nationEl.classList.remove('view-hidden');
  }
}

document.getElementById('back-btn').addEventListener('click', () => {
  if (currentLevel === 'city') enterState(currentState);
  else if (currentLevel === 'state') goNation();
});

['AK', 'HI', 'PR'].forEach(abbr => {
  document.getElementById('chip-' + abbr).addEventListener('click', () => {
    enterState(abbr);
    reportCountyClick(abbr, null);
  });
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
  if (match) {
    enterState(match[0]);
    reportCountyClick(match[0], null);
    searchInput.value = '';
    searchInput.blur();
  }
});

// Vista pedida desde el panel de Dashboards (fuera de este iframe): entra
// directo al estado seleccionado y, si tambien se eligio un condado o
// municipio, se acerca a el -- igual que si el usuario hubiera hecho click
// el mismo. A diferencia del viejo mecanismo (una sola vez, al cargar), esto
// corre en cada streamlit:render, asi que tambien reacciona si el usuario
// cambia el dropdown de condado despues de que el mapa ya esta abierto.
function applyRequestedView(abbr, countyName) {
  if (!abbr || !STATES[abbr]) return;
  if (abbr === lastAppliedAbbr && countyName === lastAppliedCounty) return;
  lastAppliedAbbr = abbr;
  lastAppliedCounty = countyName;
  enterState(abbr);
  if (countyName) {
    const shapeEntry = COUNTY_SHAPES[abbr] &&
      COUNTY_SHAPES[abbr].counties.find(c => c.name === countyName);
    if (shapeEntry) {
      flyToCity(abbr, shapeEntry.name, shapeEntry.center);
    } else {
      const place = (CITIES[abbr] || []).find(p => p.name === countyName);
      if (place) flyToCity(abbr, place.name, [place.lon, place.lat]);
    }
  }
}

Streamlit.onRender((data) => {
  const args = data.args || {};
  applyRequestedView(args.initial_abbr || null, args.initial_county || null);
});
Streamlit.init();
</script>
"""

# --------------------------------------------------------------------
# El mapa como custom component real (declare_component), no como
# components.html: asi tiene un canal de vuelta hacia Python (via
# Streamlit.sendValue en el JS de arriba) para que un click en un condado
# dentro del mapa pueda actualizar el dropdown/graficas del dashboard sin
# recargar la pagina. El HTML es estatico (STATES/CITIES/COUNTY_SHAPES no
# cambian durante la sesion) asi que se escribe una sola vez a disco; lo que
# si cambia entre reruns (initial_abbr/initial_county) se manda como args
# del componente, que el JS recibe via streamlit:render sin recargar el
# iframe.
_MAP_COMPONENT_DIR = Path(__file__).parent / "map_component"
_MAP_COMPONENT_DIR.mkdir(exist_ok=True)
_map_component_html_path = _MAP_COMPONENT_DIR / "index.html"
if not _map_component_html_path.exists():
    _nation_bg_css = f"url('data:image/png;base64,{NATION_PNG_B64}')" if NATION_PNG_B64 else "none"
    _map_static_html = (
        "<!doctype html><html><head><meta charset=\"utf-8\"></head><body>"
        + HTML_TEMPLATE
            .replace("__STATES_JSON__", json.dumps(STATES))
            .replace("__CITIES_JSON__", json.dumps(CITIES))
            .replace("__REGIONS_JSON__", json.dumps(REGIONS))
            .replace("__NAME_TO_ABBR_JSON__", json.dumps(NAME_TO_ABBR))
            .replace("__STATES_GEOJSON__", json.dumps(STATES_GEOJSON))
            .replace("__COUNTY_SHAPES_JSON__", json.dumps(COUNTY_SHAPES))
            .replace("__VULN_BANDS_JSON__", json.dumps(VULN_BANDS))
            .replace("__VULN_NO_DATA_COLOR_JSON__", json.dumps(VULN_NO_DATA_COLOR))
            .replace("__NATION_BG_CSS__", _nation_bg_css)
        + "</body></html>"
    )
    _map_component_html_path.write_text(_map_static_html, encoding="utf-8")

_map_component = components.declare_component("map_dashboard", path=str(_MAP_COMPONENT_DIR))


def render_map_component(initial_abbr=None, initial_county=None, key="map_dashboard_widget"):
    return _map_component(
        initial_abbr=initial_abbr,
        initial_county=initial_county,
        height=730,
        key=key,
        default=None,
    )


def process_map_click(map_value):
    """Reacciona al valor que devuelve el componente del mapa cuando el
    usuario hace click en un estado/condado (ver reportCountyClick en el
    JS), sincronizando los dropdowns/graficas de Dashboards con esa
    seleccion. A proposito solo se llama DENTRO del bloque de Dashboards
    (mas abajo) -- Dashboards es opt-in (solo se abre con su boton), asi
    que un click en el mapa hecho desde la vista de afuera NUNCA debe abrir
    el panel por su cuenta; ahi el click solo mueve el mapa (eso ya lo hace
    el JS del lado del cliente).

    "seq" sube en cada click -- sin compararlo contra el ultimo que ya
    procesamos, el mismo valor (que Streamlit sigue devolviendo en cada
    rerun futuro hasta el proximo click) se reaplicaria una y otra vez.
    """
    if not map_value or map_value.get("abbr") not in STATES:
        return
    if map_value.get("seq") == st.session_state.get("_map_click_seq"):
        return
    st.session_state["_map_click_seq"] = map_value.get("seq")
    st.session_state["_pending_map_click"] = {
        "abbr": map_value["abbr"],
        "county": map_value.get("county"),
    }
    st.rerun()


# --------------------------------------------------------------------
# Botones "Dashboards" y "Rankings": fuera del mapa, debajo del
# titulo/metricas, uno al lado del otro. "Dashboards" abre los selectores
# (estado completo, o estado + condado) y parte el mapa con las graficas a
# la izquierda; "Rankings" abre las dos listas de vulnerabilidad de todos
# los estados (mas abajo, ver render_rankings). Los dos son opt-in e
# independientes -- sin tocar ninguno, la pagina se comporta exactamente
# igual que antes (mapa a todo lo ancho, sin listas de rankings).
# --------------------------------------------------------------------
_btn_dash_col, _btn_rank_col, _btn_spacer_col = st.columns([1, 1, 6], gap="small")
with _btn_dash_col:
    if st.button(
        "Ocultar dashboards" if st.session_state.show_dashboard else "Dashboards",
        icon=":material/close:" if st.session_state.show_dashboard else ":material/bar_chart:",
        key="dashboards_toggle_btn",
    ):
        if st.session_state.show_dashboard:
            # No lo ocultamos todavia: en este mismo render se pinta con la
            # clase de "salida" (ver CSS arriba) para que se vea el fade-out, y
            # recien despues de esa animacion lo quitamos de verdad (mas abajo).
            st.session_state.dash_closing = True
            # Streamlit puede acompanar este click con un reporte desactualizado
            # del dropdown de estado (ej. si "Estado" se cargo por un click en
            # el mapa y el usuario nunca toco el widget el mismo), lo que lo
            # hace volver a su default (Alabama) justo al cerrar. Lo reforzamos
            # aqui, desde el espejo que si sobrevive (active_state_abbr), antes
            # de que el dropdown se vuelva a crear mas abajo en este mismo run.
            _mirror_abbr = st.session_state.get("active_state_abbr")
            if _mirror_abbr in STATES:
                st.session_state["dash_state_name"] = STATES[_mirror_abbr]["name"]
                _mirror_county = st.session_state.get("active_county_name")
                st.session_state["dash_mode"] = "Estado y condado" if _mirror_county else "Estado completo"
                if _mirror_county:
                    st.session_state[f"dash_county_name_{_mirror_abbr}"] = _mirror_county
        else:
            st.session_state.show_dashboard = True
        # Sin este rerun explicito el boton se dibuja con la etiqueta vieja en
        # este mismo render (Streamlit ya lo pinto antes de saber que se hizo
        # click) y queda "atrasado" una pulsacion, aunque el panel de abajo si
        # cambia al instante -- forzamos a que la etiqueta tambien se actualice ya.
        st.rerun()
with _btn_rank_col:
    if st.button(
        "Ocultar rankings" if st.session_state.show_rankings else "Rankings",
        icon=":material/close:" if st.session_state.show_rankings else ":material/leaderboard:",
        key="rankings_toggle_btn",
    ):
        if st.session_state.show_rankings:
            st.session_state.rankings_closing = True
        else:
            st.session_state.show_rankings = True
        # Mismo truco que el boton de Dashboards: sin este rerun, la etiqueta
        # del boton queda un click atrasada.
        st.rerun()

_dash_abbr = None
_dash_county = None

if st.session_state.show_dashboard and MAP_DATA:
    _closing = st.session_state.dash_closing
    with st.container(key="dash_section_open"):
        # OJO: este contenedor de controles (y el del mapa, mas abajo) NUNCA
        # deben cambiar de key mientras esten montados -- Streamlit trata un
        # cambio de key en un ANCESTRO como si el widget de adentro
        # (dash_state_name, el selectbox de condado, el propio componente
        # del mapa) fuera uno nuevo, y le borra el valor que tenia. Por eso
        # la key de este container es fija (a diferencia de dash_charts_key
        # de mas abajo, que si puede cambiar porque solo tiene graficas, sin
        # widgets con estado que conservar).
        with st.container(border=True):
            st.markdown("**¿Que quieres visualizar?**")
            _mode = st.radio(
                "Modo", ["Estado completo", "Estado y condado", "Comparar estados"],
                horizontal=True, label_visibility="collapsed", key="dash_mode",
            )
            # Cambiar de modo agrega o quita widgets enteros mas abajo (el
            # selectbox de condado, el multiselect de comparar) en el MISMO
            # render que el click que los dispara -- eso a veces deja al
            # navegador mostrando un estado a medio asentar hasta el
            # siguiente render (por eso hacia falta clickear dos veces).
            # Forzar un rerun apenas se detecta el cambio le da ese segundo
            # render gratis, sin que el usuario tenga que pedirlo con otro
            # click -- mismo truco que ya se uso para el boton de
            # Dashboards y el de Ocultar/Mostrar del panel de IA.
            if st.session_state.get("_last_dash_mode") != _mode:
                st.session_state["_last_dash_mode"] = _mode
                st.rerun()
            _compare_abbrs = []
            if _mode == "Comparar estados":
                _compare_names = st.multiselect(
                    "Estados a comparar (elige 2 o mas)",
                    sorted(s["name"] for s in STATES.values()),
                    key="dash_compare_states",
                )
                _compare_abbrs = [NAME_TO_ABBR[n] for n in _compare_names]
            else:
                _state_name = st.selectbox(
                    "Estado", sorted(s["name"] for s in STATES.values()), key="dash_state_name",
                )
                _dash_abbr = NAME_TO_ABBR[_state_name]
                if _mode == "Estado y condado":
                    if COUNTY_SHAPES.get(_dash_abbr):
                        _county_options = sorted(c["name"] for c in COUNTY_SHAPES[_dash_abbr]["counties"])
                    else:
                        _county_options = sorted(p["name"] for p in CITIES.get(_dash_abbr, []))
                    if _county_options:
                        _dash_county = st.selectbox(
                            "Condado / municipio", _county_options, key=f"dash_county_name_{_dash_abbr}",
                        )
                    else:
                        st.caption("Sin condados o municipios disponibles para este territorio.")

        # Espejo en claves propias (no las del widget): dash_state_name y
        # dash_county_name_* son claves DE WIDGET, y Streamlit las borra de
        # session_state en cuanto ese widget deja de dibujarse (p. ej. al
        # cerrar Dashboards) -- por eso el panel fijo de IA de mas abajo, que
        # debe seguir mostrando la ultima seleccion aunque Dashboards este
        # cerrado, lee estas otras en vez de las del widget directamente
        # (ver get_active_selection).
        if _mode == "Comparar estados":
            st.session_state["active_mode"] = "comparison"
            st.session_state["active_compare_states"] = _compare_abbrs
        else:
            st.session_state["active_mode"] = "single"
            st.session_state["active_state_abbr"] = _dash_abbr
            st.session_state["active_county_name"] = _dash_county

        col_dash, col_map = st.columns([1, 1.7], gap="large")
        with col_dash:
            if _mode == "Comparar estados":
                _charts_key = (
                    "dash_compare_charts_closing" if _closing
                    else f"dash_compare_charts_{_slug('-'.join(sorted(_compare_abbrs)) or 'ninguno')}"
                )
                with st.container(key=_charts_key):
                    render_comparison_dashboard(_compare_abbrs)
            else:
                if _closing:
                    _charts_key = "dash_charts_closing"
                else:
                    # Key con el estado/condado elegido: al cambiar la
                    # seleccion, este bloque se vuelve a montar (en vez de
                    # solo actualizar sus valores) y por lo tanto repite la
                    # animacion de entrada -- asi las graficas tambien
                    # transicionan al cambiar de condado.
                    _charts_key = f"dash_charts_sel_{_slug(_dash_abbr)}_{_slug(_dash_county or 'estado')}"
                with st.container(key=_charts_key):
                    render_dashboard(_dash_abbr, _dash_county)
        with col_map:
            # Key fija -- ver el comentario junto al container de controles;
            # el componente del mapa tambien es un widget con estado (que
            # condado se clickeo) que no debe perderse al cerrar. En modo
            # comparacion no hay un solo estado "activo" para el mapa, asi
            # que se muestra la vista nacional.
            if _mode == "Comparar estados":
                _map_value = render_map_component(None, None)
            else:
                _map_value = render_map_component(_dash_abbr, _dash_county)
            process_map_click(_map_value)

    if st.session_state.dash_closing:
        # Las graficas se alcanzan a ir con su propio fade (0.16s) -- los
        # controles y el mapa ya no pueden re-animarse individualmente (ver
        # comentario arriba), asi que solo hay que esperar esa unica
        # transicion antes de ocultar todo el bloque.
        time.sleep(0.18)
        st.session_state.show_dashboard = False
        st.session_state.dash_closing = False
        st.rerun()
else:
    # OJO: aca NO se llama process_map_click -- Dashboards es opt-in (solo
    # se abre con el boton de arriba), asi que un click en un estado desde
    # esta vista de afuera solo debe navegar el mapa (eso ya lo hace el JS
    # del lado del cliente, adentro del componente) y nunca debe abrir el
    # panel de Dashboards por su cuenta.
    render_map_component()

# La leyenda va pegada al mapa a proposito (antes vivia mas abajo, pero el
# panel de IA -- que puede crecer bastante con la respuesta -- la terminaba
# empujando hasta el fondo de la pagina).
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

if st.session_state.show_rankings and MAP_DATA:
    st.divider()
    st.markdown("### Rankings de vulnerabilidad SDOH")
    _rankings_key = "rankings_section_closing" if st.session_state.rankings_closing else "rankings_section_open"
    with st.container(key=_rankings_key):
        render_rankings()
    if st.session_state.rankings_closing:
        # Misma espera breve que usa el cierre de Dashboards, solo para que
        # se alcance a ver el fade-out (ver CSS arriba) antes de sacar el
        # bloque del todo.
        time.sleep(0.16)
        st.session_state.show_rankings = False
        st.session_state.rankings_closing = False
        st.rerun()

# --------------------------------------------------------------------
# Panel de IA fijo: vive fuera del bloque de arriba a proposito, para que
# aparezca siempre (con Dashboards abierto o cerrado) reflejando el estado
# activo. Tiene su propio boton para ocultar/mostrar el contenido (queda
# solo el titulo + boton, sin el ruido visual del analisis/botones/errores)
# -- get_active_selection y active_mode leen la misma fuente de verdad que
# usan el mapa y los dropdowns.
# --------------------------------------------------------------------
if "ai_panel_visible" not in st.session_state:
    st.session_state.ai_panel_visible = True

st.divider()
_col_ai_title, _col_ai_toggle = st.columns([5, 1.6])
with _col_ai_title:
    st.markdown("### 🤖 Analisis con IA (Gemini)")
with _col_ai_toggle:
    if st.button(
        "Ocultar" if st.session_state.ai_panel_visible else "Mostrar",
        key="ai_panel_visibility_btn",
        icon=":material/visibility_off:" if st.session_state.ai_panel_visible else ":material/visibility:",
        use_container_width=True,
    ):
        st.session_state.ai_panel_visible = not st.session_state.ai_panel_visible
        # Mismo motivo que el boton de Dashboards: sin este rerun la
        # etiqueta queda un click atrasada.
        st.rerun()

if st.session_state.ai_panel_visible:
    if st.session_state.get("active_mode") == "comparison":
        render_ai_comparison_panel(st.session_state.get("active_compare_states") or [])
    else:
        _ai_abbr, _ai_county = get_active_selection()
        render_ai_panel(_ai_abbr, _ai_county)

st.caption(
    "Poblaciones y vulnerabilidad: calculadas desde integrated_data_by_state.csv. El mapa "
    "nacional colorea cada uno de los ~33,300 ZCTA5 del area continental; los pines dentro de "
    "un estado agregan esos mismos ZCTA5 por condado. Vulnerabilidad = media (ponderada por "
    "poblacion, cuando se agrega por condado o a nivel nacional) de 7 medidas SDOH: pobreza, "
    "desempleo, sin diploma, sin banda ancha, costo de vivienda, hacinamiento, hogares "
    "monoparentales."
)
