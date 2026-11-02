"""Curb zones: a line drawn along a curb, split into one zone per block, named the way
Film SF and SFMTA name them ("800-890 Grant Ave, west side, 160 ft, 8 spaces")."""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from core.streets import M_PER_FT, pretty_street, to_latlon, to_xy

# Tuning knobs.
SPACE_FT = 20       # one parking space; 160 ft on a Film SF sign is 8 spaces
SAMPLE_M = 2        # the drawn line is checked every this many meters
MAX_OFFSET_M = 25   # a drawn point farther than this from any street is ignored
MIN_ZONE_M = 6      # shorter runs are noise, e.g. a line cutting across an intersection


@dataclass
class CurbZone:
    street: str               # "Grant Ave"
    block: str                # "800-890 Grant Ave", or "Grant Ave" when the block has no addresses
    side: str                 # "north", "south", "east" or "west"
    between: str              # "Clay St and Washington St"
    length_ft: float
    points: list = field(repr=False)  # (lat, lon) of the drawn line on this block
    cnn: int = field(default=0, repr=False)          # the block, for curb data lookups
    side_sign: int = field(default=1, repr=False)    # +1 left of the block, -1 right
    along_m: tuple = field(default=(0, 0), repr=False)  # stretch of the block covered

    @property
    def spaces(self):
        return max(1, round(self.length_ft / SPACE_FT))


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
        runs = [r for r in runs if len(r) * SAMPLE_M >= MIN_ZONE_M]
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
        return CurbZone(
            street=pretty_street(own),
            block=self.block_label(seg),
            side=side,
            between=between,
            length_ft=length_m / M_PER_FT,
            points=[to_latlon(h[2], h[3]) for h in run],
            cnn=seg["cnn"],
            side_sign=Counter(h[8] for h in run).most_common(1)[0][0],
            along_m=(min(alongs), max(alongs)),
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
