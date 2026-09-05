"""
Build per-state county boundary shapes (with vulnerability data attached)
for MapaUS.py's state-level choropleth.

Same purpose as build_zcta_vulnerability_map.py, but keeps the geometry as
vector paths (not a raster) so each county stays individually clickable and
hoverable in the browser, exactly like the national state-outline SVG.

Geometry source: US Census Bureau 2020 cartographic boundary county file
(cb_2020_us_county_500k) -- public domain, already generalized to
1:500,000, then simplified further here (shapely) since county polygons are
far more detailed than state polygons and don't need full resolution for a
state-sized SVG.

One-time setup (shapefile is gitignored):
    curl -o cb_2020_us_county_500k.zip \
        https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_500k.zip
    unzip cb_2020_us_county_500k.zip -d cb_county500k
    pip install pandas pyshp shapely

Run (once, or whenever integrated_data_by_state.csv / map_data.json
changes):
    python3 build_map_data.py   # first, if not already up to date
    python3 build_county_shapes.py

Produces: county_shapes.json
    {
      "TX": {
        "bounds": [[minlon, minlat], [maxlon, maxlat]],
        "counties": [
          {"name": "Dallas County", "center": [lon, lat],
           "geometry": {"type": "Polygon" | "MultiPolygon", "coordinates": [...]},
           "population": <number|null>, "vulnerability": <number|null>,
           "components": {...}|null},
          ...
        ]
      },
      ...
    }

Puerto Rico and the smaller Pacific/Caribbean territories are intentionally
excluded: MapaUS.py's STATES dict only covers the 50 states + DC (PR keeps
its own existing marker-based view; the others aren't in the app at all).
"""
import json
import os
from typing import Any, cast

import shapefile
from shapely.geometry import mapping, shape

SHAPE_FILE = "cb_county500k/cb_2020_us_county_500k.shp"
MAP_DATA_FILE = "map_data.json"
OUTPUT_FILE = "county_shapes.json"
SIMPLIFY_TOLERANCE_DEG = 0.006  # ~650m at mid-latitudes -- plenty for a state-scale SVG
COORD_DECIMALS = 4  # ~11m precision
EXCLUDED_ABBRS = {"PR", "AS", "MP", "VI", "GU"}


def round_coords(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], COORD_DECIMALS), round(coords[1], COORD_DECIMALS)]
    return [round_coords(c) for c in coords]


def _iter_points(coords):
    if isinstance(coords[0], (int, float)):
        yield coords
    else:
        for c in coords:
            yield from _iter_points(c)


def unwrap_lon(coords):
    if isinstance(coords[0], (int, float)):
        lon, lat = coords
        return [lon - 360 if lon > 0 else lon, lat]
    return [unwrap_lon(c) for c in coords]


def main():
    map_data = json.loads(open(MAP_DATA_FILE, encoding="utf-8").read())
    sf = shapefile.Reader(SHAPE_FILE)
    fields = [f[0] for f in sf.fields[1:]]

    out = {}
    for sr in sf.shapeRecords():
        record = sr.record
        if record is None:
            continue
        rec = dict(zip(fields, record))
        abbr = rec["STUSPS"]
        if abbr in EXCLUDED_ABBRS or abbr not in map_data["states"]:
            continue

        geo_interface = getattr(sr.shape, "__geo_interface__", None)
        if not isinstance(geo_interface, dict):
            continue
        geom = shape(cast(dict[str, Any], geo_interface))
        if not geom.is_valid:
            geom = geom.buffer(0)
        simplified = geom.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
        if simplified.is_empty:
            simplified = geom
        centroid = simplified.centroid

        name = rec["NAMELSAD"]
        county_lookup = {c["name"]: c for c in map_data["states"][abbr]["counties"]}
        c_data = county_lookup.get(name)

        geo = mapping(simplified)
        geo["coordinates"] = round_coords(geo["coordinates"])

        out.setdefault(abbr, {"counties": []})["counties"].append(
            {
                "name": name,
                "center": [round(centroid.x, COORD_DECIMALS), round(centroid.y, COORD_DECIMALS)],
                "geometry": geo,
                "population": c_data["population"] if c_data else None,
                "vulnerability": c_data["vulnerability"] if c_data else None,
                "components": c_data["components"] if c_data else None,
            }
        )

    # Alaska's Aleutian islands cross the antimeridian (a few points sit at
    # ~+179 lon right next to the rest of the state at ~-179 lon); a naive
    # min/max would treat that as a ~360-degree-wide state and squash
    # everything else into a sliver. Detect that case and unwrap the
    # eastern-hemisphere points back into the same negative-lon space as
    # the rest of the state before computing bounds.
    for abbr, sdata in out.items():
        all_lons = [pt[0] for c in sdata["counties"] for pt in _iter_points(c["geometry"]["coordinates"])]
        if all_lons and (max(all_lons) - min(all_lons)) > 180:
            for c in sdata["counties"]:
                c["geometry"]["coordinates"] = unwrap_lon(c["geometry"]["coordinates"])
                if c["center"][0] > 0:
                    c["center"][0] = round(c["center"][0] - 360, COORD_DECIMALS)

    for abbr, sdata in out.items():
        lons, lats = [], []
        for c in sdata["counties"]:
            g = shape(c["geometry"])
            minx, miny, maxx, maxy = g.bounds
            lons += [minx, maxx]
            lats += [miny, maxy]
        sdata["bounds"] = [[min(lons), min(lats)], [max(lons), max(lats)]]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))

    total_counties = sum(len(s["counties"]) for s in out.values())
    print(f"States: {len(out)}  Counties: {total_counties}")
    print(f"Wrote {OUTPUT_FILE} ({os.path.getsize(OUTPUT_FILE) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
