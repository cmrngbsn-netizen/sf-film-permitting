"""Street lookups for SF: street blocks, intersections, and street names as Film SF writes them.

Distances use a flat local projection in meters, which is accurate to well under
1% across a city the size of San Francisco.
"""

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

M_PER_FT = 0.3048
LAT0 = 37.76  # projection origin, middle of SF
LON0 = -122.44
M_PER_DEG_LAT = 110_540
M_PER_DEG_LON = 111_320 * math.cos(math.radians(LAT0))


def to_xy(lat, lon):
    return (lon - LON0) * M_PER_DEG_LON, (lat - LAT0) * M_PER_DEG_LAT


def to_latlon(x, y):
    return LAT0 + y / M_PER_DEG_LAT, LON0 + x / M_PER_DEG_LON


def pretty_street(name):
    """"VALENCIA ST" -> "Valencia St", "18TH ST" -> "18th St", "O'FARRELL ST" -> "O'Farrell St"."""
    words = []
    for w in name.split():
        if re.fullmatch(r"\d+(ST|ND|RD|TH)", w):
            words.append(w.lower())
        elif w.startswith("MC") and len(w) > 2:
            words.append("Mc" + w[2:].capitalize())  # MCALLISTER -> McAllister
        else:
            words.append("'".join(part.capitalize() for part in w.split("'")))
    return " ".join(words)


# Street type words a search can leave off ("Grant" for "GRANT AVE").
STREET_TYPES = {"ST", "STREET", "AVE", "AVENUE", "BLVD", "BOULEVARD", "DR", "DRIVE", "WAY", "PL",
                "PLACE", "CT", "COURT", "LN", "LANE", "TER", "TERRACE", "RD", "ROAD", "ALY", "ALLEY",
                "CIR", "HWY", "PLZ", "ROW", "WALK"}


def street_key(name):
    """A street name as searched for: "03RD ST" -> "3RD", "O'Farrell St." -> "OFARRELL".
    The map's address search (core.map_tools) normalizes what's typed the same way."""
    words = re.sub(r"\b0+(\d)", r"\1", re.sub(r"[.']", "", name.upper())).split()
    while len(words) > 1 and words[-1] in STREET_TYPES:
        words.pop()
    return " ".join(words)


def join_streets(names):
    return " & ".join(pretty_street(n) for n in names) if names else "unnamed streets"


class StreetIndex:
    def __init__(self, data_dir=DATA_DIR):
        segments = json.loads((data_dir / "segments.geojson").read_text())["features"]
        self.node_names = {int(k): v for k, v in
                           json.loads((data_dir / "nodes.json").read_text()).items()}

        # Node positions come from segment endpoints. A few segments disagree with
        # their neighbors, so take the position most segments agree on.
        ends = defaultdict(Counter)
        for f in segments:
            p, coords = f["properties"], f["geometry"]["coordinates"]
            ends[p["f_node_cnn"]][tuple(coords[0])] += 1
            ends[p["t_node_cnn"]][tuple(coords[-1])] += 1

        # Only nodes where two or more differently named streets meet count as
        # intersections; the rest are dead ends or mid-block breaks in one street.
        self.int_cnns = [c for c, names in self.node_names.items() if len(names) >= 2 and c in ends]
        self.int_xy = np.array([to_xy(*reversed(ends[c].most_common(1)[0][0]))
                                for c in self.int_cnns])

        # Every straight piece of every block, flattened for vectorized distance math.
        self.segments = [f["properties"] for f in segments]
        starts, stops, owner, offset = [], [], [], []
        self.seg_length = []  # meters, per block
        self.seg_xy = []      # [(x, y), ...] per block, from f_node to t_node
        for i, f in enumerate(segments):
            pts = [to_xy(lat, lon) for lon, lat in f["geometry"]["coordinates"]]
            self.seg_xy.append(pts)
            along = 0.0
            for a, b in zip(pts, pts[1:]):
                starts.append(a)
                stops.append(b)
                owner.append(i)
                offset.append(along)  # distance from the block's start to this piece
                along += math.dist(a, b)
            self.seg_length.append(along)
        self.piece_a = np.array(starts)
        self.piece_b = np.array(stops)
        self.piece_owner = np.array(owner)
        self.piece_offset = np.array(offset)

    def nearest_piece(self, x, y):
        """Closest centerline point to (x, y) in meters: (segment index, distance_m,
        closest x, closest y, direction of the piece, distance along the block)."""
        p = np.array((x, y))
        ab = self.piece_b - self.piece_a
        length2 = (ab ** 2).sum(axis=1)
        length2[length2 == 0] = 1e-9
        t = np.clip(((p - self.piece_a) * ab).sum(axis=1) / length2, 0, 1)
        closest = self.piece_a + ab * t[:, None]
        d = np.hypot(*(closest - p).T)
        i = int(d.argmin())
        along = self.piece_offset[i] + t[i] * math.sqrt(length2[i])
        return int(self.piece_owner[i]), float(d[i]), *closest[i], ab[i], float(along)

    def intersection_index(self):
        """Every intersection, for searching "Grant & Washington" on the map:
        {"streets": [[name, search key], ...], "nodes": [[[street, ...], lat, lon], ...]}."""
        names = sorted({n for c in self.int_cnns for n in self.node_names[c]})
        number = {n: i for i, n in enumerate(names)}
        nodes = [[[number[n] for n in self.node_names[c]], *(round(v, 5) for v in to_latlon(x, y))]
                 for c, (x, y) in zip(self.int_cnns, self.int_xy)]
        return {"streets": [[pretty_street(re.sub(r"\b0+(\d)", r"\1", n)), street_key(n)] for n in names],
                "nodes": nodes}

    def cross_streets(self, node_cnn, own_street):
        """Names at a block's end node other than the block's own street."""
        names = self.node_names.get(node_cnn)
        if names is None:
            return "unknown"
        others = [n for n in names if n != own_street]
        return join_streets(others) if others else "mid-block"
