"""One-time data build: downloads the DataSF street datasets and writes slim
static files into data/. Run with: python scripts/build_data.py [--refresh]

Outputs:
  data/segments.geojson  one feature per street block (intersection to intersection)
  data/nodes.json        intersection node CNN -> street names meeting there
"""

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "scripts" / ".cache"  # raw downloads, not committed

SOURCES = {
    "segments": "https://data.sf.gov/api/v3/views/3psu-pn9h/query.geojson?accessType=DOWNLOAD",
    "intersections": "https://data.sf.gov/api/v3/views/gmfx-8h6i/query.geojson?accessType=DOWNLOAD",
}

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
    """"26132000.0" -> 26132000"""
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


if __name__ == "__main__":
    main()
