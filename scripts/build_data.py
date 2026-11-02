"""One-time data build: downloads the DataSF street datasets and writes slim
static files into data/. Run with: python scripts/build_data.py [--refresh]

Outputs:
  data/segments.geojson  one feature per street block (intersection to intersection),
                         with address ranges per side
  data/nodes.json        intersection node CNN -> street names meeting there
  data/curbs.json        active meters and color curbs (driveways, loading zones, ...)
                         placed on their block, side and position along the block,
                         plus the SFMTA parking census (legal spaces per block)
  static/intersections.json  every intersection's streets and position, fetched by the
                         map's address search (served by Streamlit's static file serving)
"""

import json
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "scripts" / ".cache"  # raw downloads, not committed

SOURCES = {
    "segments": "https://data.sf.gov/api/v3/views/3psu-pn9h/query.geojson?accessType=DOWNLOAD",
    "intersections": "https://data.sf.gov/api/v3/views/gmfx-8h6i/query.geojson?accessType=DOWNLOAD",
}

# SFMTA parking layers (ArcGIS). Meters are one point per space; color curbs are one
# point per zone with its length in feet. Both are pulled fresh on every build.
SFMTA = "https://services.sfmta.com/arcgis/rest/services/Parking/parking/MapServer"
METERS_LAYER = 11
CURBS_LAYER = 18
# Legal on-street spaces per block (both sides), counted in the field 2008-2014. It is the
# only source that reflects every driveway: the color curb layer only has driveways
# painted red. 5555 marks a divided street whose count was put on the other roadway.
CENSUS_LAYER = 4
CENSUS_ELSEWHERE = 5555
# Active on-street meters only ("M" or "T", per SFMTA's notes on the layer).
METERS_WHERE = "ON_OFFSTREET_TYPE='ON' AND ACTIVE_METER_FLAG IN ('M','T')"
# A meter or curb point farther than this from any street centerline is skipped.
CURB_MAX_OFFSET_M = 30

# Values of the `layer` field kept as vehicle streets. Everything else is dropped:
# FREEWAYS, PAPER*, PRIVATE*, PSEUDO, STREETS_PEDESTRI (pedestrian-only) and
# UPROW (unimproved right of way).
KEEP_LAYERS = {
    "STREETS",
    "STREETS_TI",          # Treasure Island
    "STREETS_YBI",         # Yerba Buena Island
    "STREETS_HUNTERSP",    # Hunters Point
    "PARKS",               # park roads, e.g. Golden Gate Park drives
    "PARKS_NPS_PRESIDIO",  # Presidio roads (National Park Service)
    "PARKS_NPS_FTMASON",   # Fort Mason roads (National Park Service)
}
# classcode 0 marks non-vehicle or paper segments; drop it even inside kept layers.
DROP_CLASSCODES = {"0"}

COORD_DECIMALS = 6


def to_cnn(value):
    """"26132000.0" -> 26132000 (also used for address numbers)"""
    if value in (None, ""):
        return None
    return round(float(value))


def download(name, url, refresh):
    path = CACHE_DIR / f"{name}.geojson"
    if path.exists() and not refresh:
        print(f"Using cached {name} ({path}); pass --refresh to re-download")
    else:
        print(f"Downloading {name} ...")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url) as res:
            path.write_bytes(res.read())
    return json.loads(path.read_text())


def slim_segments(raw):
    features = []
    for f in raw["features"]:
        p = f["properties"]
        geom = f.get("geometry")
        if p.get("active") is not True:
            continue
        if p.get("layer") not in KEEP_LAYERS or p.get("classcode") in DROP_CLASSCODES:
            continue
        if not geom or geom["type"] != "LineString":
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "cnn": to_cnn(p.get("cnn")),
                "street": p.get("street"),
                "st_type": p.get("st_type"),
                "f_node_cnn": to_cnn(p.get("f_node_cnn")),
                "t_node_cnn": to_cnn(p.get("t_node_cnn")),
                # Address ranges on the left and right side (relative to f_node -> t_node).
                "lf_fadd": to_cnn(p.get("lf_fadd")),
                "lf_toadd": to_cnn(p.get("lf_toadd")),
                "rt_fadd": to_cnn(p.get("rt_fadd")),
                "rt_toadd": to_cnn(p.get("rt_toadd")),
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [[round(x, COORD_DECIMALS), round(y, COORD_DECIMALS)]
                                for x, y in geom["coordinates"]],
            },
        })
    return {"type": "FeatureCollection", "features": features}


def build_nodes(raw, segments):
    """Node CNN -> unique full street names ("MAIN ST"), for nodes the kept segments use."""
    used = set()
    for f in segments["features"]:
        used.add(f["properties"]["f_node_cnn"])
        used.add(f["properties"]["t_node_cnn"])
    nodes = {}
    for f in raw["features"]:
        p = f["properties"]
        cnn = to_cnn(p.get("cnn"))
        if cnn not in used or not p.get("st_name"):
            continue
        name = " ".join(filter(None, [p["st_name"], p.get("st_type")]))
        names = nodes.setdefault(str(cnn), [])
        if name not in names:
            names.append(name)
    return nodes, used


def fetch_arcgis(layer, where, fields):
    """All features of an SFMTA layer in WGS84, fetched in pages."""
    features, offset = [], 0
    while True:
        query = urllib.parse.urlencode({
            "where": where, "outFields": fields, "outSR": 4326, "f": "json",
            "resultOffset": offset, "resultRecordCount": 5000, "orderByFields": "OBJECTID",
        })
        with urllib.request.urlopen(f"{SFMTA}/{layer}/query?{query}") as res:
            page = json.load(res)
        if "error" in page:
            raise RuntimeError(f"SFMTA layer {layer}: {page['error']}")
        features += page["features"]
        if not page.get("exceededTransferLimit"):
            return features
        offset += len(page["features"])


def build_curbs():
    """Block CNN -> [[side, along_m, kind, feet], ...] for meters and color curbs.
    side is +1 for the left of the block (walking from f_node to t_node), -1 for the right."""
    from core.streets import StreetIndex, to_xy

    index = StreetIndex(DATA_DIR)
    print("Downloading SFMTA meters ...")
    meters = fetch_arcgis(METERS_LAYER, METERS_WHERE, "POST_ID,CAP_COLOR")
    print("Downloading SFMTA color curbs ...")
    curbs = fetch_arcgis(CURBS_LAYER, "1=1", "ZONE_TYPE,FEET")

    points = [((f["geometry"]["y"], f["geometry"]["x"]), f"meter:{f['attributes']['CAP_COLOR']}", 0)
              for f in meters if f.get("geometry")]
    for f in curbs:
        kind = (f["attributes"]["ZONE_TYPE"] or "").strip()
        for lon, lat in (f.get("geometry") or {}).get("points", []):
            if kind:
                points.append(((lat, lon), f"curb:{kind}", f["attributes"]["FEET"] or 0))

    by_block, skipped = {}, 0
    for (lat, lon), kind, feet in points:
        x, y = to_xy(lat, lon)
        seg, d, cx, cy, (dx, dy), along = index.nearest_piece(x, y)
        if d > CURB_MAX_OFFSET_M:
            skipped += 1
            continue
        side = 1 if dx * (y - cy) - dy * (x - cx) >= 0 else -1
        cnn = str(index.segments[seg]["cnn"])
        by_block.setdefault(cnn, []).append([side, round(along, 1), kind, feet])

    print("Downloading SFMTA parking census ...")
    census = {}
    for f in fetch_arcgis(CENSUS_LAYER, "1=1", "CNN,PRKG_SPLY,YEAR"):
        a = f["attributes"]
        if a["CNN"] is None or a["PRKG_SPLY"] is None or a["PRKG_SPLY"] == CENSUS_ELSEWHERE:
            continue
        cnn = str(int(a["CNN"]))
        spaces, year = census.get(cnn, (0, 0))
        census[cnn] = [spaces + a["PRKG_SPLY"], max(year, a["YEAR"] or 0)]

    out = DATA_DIR / "curbs.json"
    out.write_text(json.dumps({"built": date.today().isoformat(), "blocks": by_block,
                               "census": census}, separators=(",", ":")))
    print(f"Meters: {len(meters)}  Color curbs: {len(curbs)}  "
          f"Placed: {len(points) - skipped}  Skipped (off street): {skipped}  "
          f"Census blocks: {len(census)}  "
          f"-> {out.stat().st_size // 1024} KB")


def main():
    refresh = "--refresh" in sys.argv
    raw_segments = download("segments", SOURCES["segments"], refresh)
    raw_intersections = download("intersections", SOURCES["intersections"], refresh)

    segments = slim_segments(raw_segments)
    nodes, used = build_nodes(raw_intersections, segments)

    DATA_DIR.mkdir(exist_ok=True)
    seg_file = DATA_DIR / "segments.geojson"
    node_file = DATA_DIR / "nodes.json"
    seg_file.write_text(json.dumps(segments, separators=(",", ":")))
    node_file.write_text(json.dumps(nodes, separators=(",", ":")))

    kb = lambda p: f"{p.stat().st_size // 1024} KB"
    print()
    print(f"Raw segments:        {len(raw_segments['features'])}")
    print(f"Kept segments:       {len(segments['features'])}  -> {kb(seg_file)}")
    print(f"Nodes used:          {len(used)}")
    print(f"Nodes with names:    {len(nodes)}  -> {kb(node_file)}")
    print(f"Nodes without names: {len(used) - len(nodes)}")
    print()
    build_curbs()
    build_intersections()


def build_intersections():
    sys.path.insert(0, str(ROOT))
    from core.streets import StreetIndex

    out = ROOT / "static" / "intersections.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(StreetIndex().intersection_index(), separators=(",", ":")))
    print(f"Intersections for the map search -> {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
