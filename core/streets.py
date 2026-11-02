"""Street lookups for SF: nearest intersection, nearest block, and plain-English labels.

Distances use a flat local projection in meters, which is accurate to well under
1% across a city the size of San Francisco.
"""

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Tuning knobs. A corner within this distance is suggested as a snap; beyond it the
# point is treated as mid-block and kept where it was drawn.
SNAP_SUGGEST_M = 30
# Closer than this to an intersection's center, the point has no meaningful corner.
CENTER_RADIUS_M = 3

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


def compass(dx, dy):
    """Corner name ("NE", "SW", ...) for an offset from an intersection center."""
    return ("N" if dy >= 0 else "S") + ("E" if dx >= 0 else "W")


@dataclass
class PointLabel:
    kind: str           # "corner" or "mid-block"
    label: str          # what goes on the form
    distance_ft: float  # from the drawn point to the suggested location
    snap_lat: float     # suggested location
    snap_lon: float


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
        for i, f in enumerate(segments):
            pts = [to_xy(lat, lon) for lon, lat in f["geometry"]["coordinates"]]
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

    def nearest_intersection(self, lat, lon):
        """(cnn, distance_m, x, y) of the closest real intersection."""
        x, y = to_xy(lat, lon)
        d = np.hypot(self.int_xy[:, 0] - x, self.int_xy[:, 1] - y)
        i = int(d.argmin())
        return self.int_cnns[i], float(d[i]), *self.int_xy[i]

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

    def nearest_block(self, lat, lon):
        """(segment properties, distance_m, x, y of the closest point on the centerline,
        direction of the piece it lies on)."""
        seg, d, cx, cy, direction, _ = self.nearest_piece(*to_xy(lat, lon))
        return self.segments[seg], d, cx, cy, direction

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

    def label_point(self, lat, lon):
        x, y = to_xy(lat, lon)
        cnn, dist, ix, iy = self.nearest_intersection(lat, lon)
        if dist <= SNAP_SUGGEST_M:
            streets = join_streets(self.node_names[cnn])
            if dist < CENTER_RADIUS_M:
                label = f"Center of {streets}"
            else:
                label = f"{compass(x - ix, y - iy)} corner, {streets}"
            snap_lat, snap_lon = to_latlon(float(ix), float(iy))
            return PointLabel("corner", label, dist / M_PER_FT, snap_lat, snap_lon)

        seg, dist, cx, cy, (dx, dy) = self.nearest_block(lat, lon)
        own = " ".join(filter(None, [seg["street"], seg["st_type"]]))
        # Which side of the street the point is on, named by the street's main direction.
        if abs(dx) >= abs(dy):  # street runs mostly east-west
            side = "north" if y >= cy else "south"
        else:
            side = "east" if x >= cx else "west"
        a = self.cross_streets(seg["f_node_cnn"], own)
        b = self.cross_streets(seg["t_node_cnn"], own)
        label = f"{pretty_street(own)}, {side} side, between {a} and {b}"
        # Mid-block points stay where they were drawn.
        return PointLabel("mid-block", label, 0.0, lat, lon)
