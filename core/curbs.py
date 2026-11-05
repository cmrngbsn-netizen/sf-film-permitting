"""Curb zones: a line drawn along a curb, split into one zone per block, named the way
Film SF and SFMTA name them ("800-890 Grant Ave, west side, 160 ft, 8 spaces")."""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace

from core.streets import M_PER_FT, pretty_street, to_latlon, to_xy

# Tuning knobs.
SPACE_FT = 20       # one parking space; 160 ft on a Film SF sign is 8 spaces
SAMPLE_M = 2        # the drawn line is checked every this many meters
MAX_OFFSET_M = 25   # a drawn point farther than this from any street is ignored
MIN_ZONE_M = 6      # shorter runs are noise, e.g. a line crossing an intersection or alley


@dataclass
class CurbZone:
    street: str               # "Grant Ave"
    block: str                # "800-890 Grant Ave", or "Grant Ave" when the block has no addresses
    side: str                 # "north", "south", "east" or "west"
    between: str              # "Clay St and Washington St"
    length_ft: float
    points: list = field(repr=False)  # (lat, lon) of the drawn line on this block
    near_cross: str = ""                              # cross street at the end the zone is nearer
    cnn: int = field(default=0, repr=False)          # the block, for curb data lookups
    side_sign: int = field(default=1, repr=False)    # +1 left of the block, -1 right
    along_m: tuple = field(default=(0, 0), repr=False)  # stretch of the block covered
    block_ft: float = field(default=0, repr=False)      # whole block, intersection to intersection
    corners: tuple = field(default=("", ""), repr=False)  # cross streets at the block's two ends
    parts: list = field(default_factory=list, repr=False)  # the pieces, when several were joined


class CurbZoner:
    def __init__(self, index):
        self.index = index
        # Highest address on each hundred-block of each street. Film SF names a block by
        # its hundred range ("700-790 Grant Ave") even where an alley splits it in two.
        self.block_end = defaultdict(int)
        for seg in index.segments:
            for a, b in self._ranges(seg):
                self.block_end[(self._own(seg), a // 100)] = max(self.block_end[(self._own(seg), a // 100)], b)

    @staticmethod
    def _own(seg):
        return " ".join(filter(None, [seg["street"], seg["st_type"]]))

    @staticmethod
    def _ranges(seg):
        return [(min(a, b), max(a, b)) for a, b in
                ((seg["lf_fadd"], seg["lf_toadd"]), (seg["rt_fadd"], seg["rt_toadd"]))
                if a and b]

    def block_label(self, seg):
        own = self._own(seg)
        ranges = self._ranges(seg)
        if not ranges:
            return pretty_street(own)
        start = min(a for a, _ in ranges) // 100 * 100
        end = self.block_end[(own, start // 100)] // 10 * 10
        return f"{start}-{end} {pretty_street(own)}"

    def zones(self, line):
        """Curb zones for a drawn line [(lat, lon), ...], in drawing order."""
        samples = self._sample([to_xy(lat, lon) for lat, lon in line])
        hits = []  # (segment, along, x, y, piece direction, closest centerline point, side)
        for x, y in samples:
            seg, d, cx, cy, (dx, dy), along = self.index.nearest_piece(x, y)
            if d <= MAX_OFFSET_M:
                side = 1 if dx * (y - cy) - dy * (x - cx) >= 0 else -1
                hits.append((seg, along, x, y, dx, dy, cx, cy, side))

        # Consecutive samples on the same block form a run; drop short runs (noise from
        # crossing an intersection), then join runs that end up next to each other.
        runs = []
        for h in hits:
            if runs and runs[-1][0][0] == h[0]:
                runs[-1].append(h)
            else:
                runs.append([h])
        # A run counts by how far it goes along its block: a line passing the mouth of an alley
        # is briefly closest to the alley, but doesn't travel along it.
        runs = [r for r in runs if max(h[1] for h in r) - min(h[1] for h in r) + SAMPLE_M >= MIN_ZONE_M]
        merged = []
        for r in runs:
            if merged and merged[-1][0][0] == r[0][0]:
                merged[-1].extend(r)
            else:
                merged.append(r)
        return [self._zone(r) for r in merged]

    def _zone(self, run):
        seg = self.index.segments[run[0][0]]
        alongs = [h[1] for h in run]
        # Name the side by the street's main direction, from the middle sample.
        _, _, x, y, dx, dy, cx, cy, _ = run[len(run) // 2]
        if abs(dx) >= abs(dy):  # street runs mostly east-west
            side = "north" if y >= cy else "south"
        else:
            side = "east" if x >= cx else "west"
        own = self._own(seg)
        between = (f"{self.index.cross_streets(seg['f_node_cnn'], own)} and "
                   f"{self.index.cross_streets(seg['t_node_cnn'], own)}")
        length_m = max(alongs) - min(alongs) + SAMPLE_M  # each sample stands for SAMPLE_M of curb
        # The cross street at whichever end of the block the zone sits closer to; a dead
        # end or mid-block break doesn't name a place, so use the other end then.
        ends = [self.index.cross_streets(seg[f"{e}_node_cnn"], own) for e in ("f", "t")]
        nearer = 0 if sum(alongs) / len(alongs) < self.index.seg_length[run[0][0]] / 2 else 1
        near_cross = next((c for c in (ends[nearer], ends[1 - nearer])
                           if c not in ("mid-block", "unknown")), "")
        return CurbZone(
            street=pretty_street(own),
            block=self.block_label(seg),
            side=side,
            between=between,
            length_ft=length_m / M_PER_FT,
            points=[to_latlon(h[2], h[3]) for h in run],
            near_cross=near_cross,
            cnn=seg["cnn"],
            side_sign=Counter(h[8] for h in run).most_common(1)[0][0],
            along_m=(min(alongs), max(alongs)),
            block_ft=self.index.seg_length[run[0][0]] / M_PER_FT,
            corners=tuple(ends),
        )

    @staticmethod
    def _sample(pts):
        """Points every SAMPLE_M along a polyline in meters."""
        out = []
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            n = max(1, math.ceil(math.dist((ax, ay), (bx, by)) / SAMPLE_M))
            out.extend((ax + (bx - ax) * k / n, ay + (by - ay) * k / n) for k in range(n))
        out.append(pts[-1])
        return out


def joined(parts):
    """One zone from neighboring pieces of a block side, e.g. where an alley splits it."""
    if len(parts) == 1:
        return parts[0]
    first, last = parts[0], parts[-1]
    # The cross streets at the outer ends, not the alleys in between.
    start = next((c for c in first.corners if c not in parts[1].corners), first.corners[0])
    end = next((c for c in last.corners if c not in parts[-2].corners), last.corners[1])
    longest = max(parts, key=lambda p: p.length_ft)
    return replace(first, between=f"{start} and {end}", length_ft=sum(p.length_ft for p in parts),
                   points=[pt for p in parts for pt in p.points], near_cross=longest.near_cross, parts=parts)


def block_labels(zones, spaces):
    """Where a drawn line's space counts go on a map: [(point, total), ...], one per block side
    it runs along, at the middle of that stretch."""
    groups = {}
    for z, n in zip(zones, spaces):
        points, total = groups.get((z.block, z.side), ([], 0))
        groups[(z.block, z.side)] = (points + z.points, total + n)
    return [(points[len(points) // 2], total) for points, total in groups.values()]


# Street types left off in a short place name ("Grant @ Washington"), as on the Film SF slides.
SHORT_DROP = {"St", "Ave", "Blvd", "Pl", "Dr", "Ct", "Ln", "Ter", "Rd", "Aly", "Way", "Hwy"}


def short_street(name):
    """"Grant Ave" -> "Grant", "Walter U Lum Pl" -> "Walter U Lum"."""
    words = name.split()
    return " ".join(words[:-1]) if len(words) > 1 and words[-1] in SHORT_DROP else name


def place_name(zones):
    """A location name like "Grant @ Washington", from the longest zone's street and the
    cross street it is nearest. Empty when there are no zones."""
    if not zones:
        return ""
    z = max(zones, key=lambda z: z.length_ft)
    cross = " & ".join(short_street(c) for c in z.near_cross.split(" & ")) if z.near_cross else ""
    return f"{short_street(z.street)} @ {cross}" if cross else short_street(z.street)


def place_names(zones_by_line):
    """Name suggestions for a location with several lines: one per line, then a combined
    one ("Grant @ Washington & Clay" when they share a street, else "A / B")."""
    names = list(dict.fromkeys(n for n in (place_name(zs) for zs in zones_by_line) if n))
    if len(names) > 1:
        streets = {n.split(" @ ")[0] for n in names}
        if len(streets) == 1 and all(" @ " in n for n in names):
            crosses = list(dict.fromkeys(n.split(" @ ", 1)[1] for n in names))
            names.append(f"{streets.pop()} @ {' & '.join(crosses)}")
        else:
            names.append(" / ".join(names))
    return names
