"""What the city has on a curb zone: SFMTA meters (by cap color) and color curbs
(driveways, blue/white/yellow/green zones, ...), from data/curbs.json."""

import json
from collections import Counter
from dataclasses import dataclass, field

from core.curbs import SPACE_FT
from core.streets import DATA_DIR

# Curb items this far past either end of a drawn zone still count, so a meter or
# driveway right at the end of the line isn't missed.
END_MARGIN_M = 3

# Meter cap colors, per SFMTA's data dictionary.
METER_TYPES = {
    "Grey": "general",
    "Yellow": "yellow (commercial loading)",
    "Red": "red (truck loading)",
    "Green": "green (short-term)",
    "Black": "black (motorcycle)",
    "Brown": "brown (tour bus)",
    "Purple": "purple (boat trailer)",
    "Blue": "blue (accessible)",
    "White": "white (passenger loading)",
}
# Motorcycle meters don't hold a car, so they don't count toward car spaces.
NON_CAR_METERS = {"Black"}

# SFMTA color curb zone types, shortened for the table.
CURB_TYPES = {
    "Driveway Red Zone": "red-curb driveway",  # only driveways painted red are mapped
    "Blue Zone/Disabled Parking": "blue zone (disabled)",
    "White Zone/Passenger Loading": "white zone (passenger loading)",
    "Yellow Zone/Commercial Loading": "yellow zone (commercial loading)",
    "Commercial Loading Zone": "yellow zone (commercial loading)",
    "6-Wheel Commercial Loading Zone": "6-wheel truck loading zone",
    "Green Zone/Short Term Parking": "green zone (short-term)",
    "Green Meter": "green zone (short-term)",
    "Taxi Zone": "taxi zone",
    "Tour Bus Loading Zone": "tour bus zone",
    "School Bus Loading Zone": "school bus zone",
    "Shuttle Bus Loading Zone": "shuttle bus zone",
    "General Loading Zone": "loading zone",
    "Dual-use zone": "dual-use zone",
}


def plural(kind, n):
    """"blue zone (disabled)" -> "blue zones (disabled)" when n > 1."""
    if n == 1:
        return kind
    head, sep, tail = kind.partition(" (")
    return f"{head}s{sep}{tail}"


@dataclass
class CurbInfo:
    meters: Counter = field(default_factory=Counter)  # cap color -> count
    zones: list = field(default_factory=list)         # [(curb type, feet), ...]
    census: float = None   # legal spaces on this stretch per the SFMTA parking census
    census_year: int = 0

    @property
    def car_meters(self):
        return sum(n for color, n in self.meters.items() if color not in NON_CAR_METERS)

    @property
    def metered(self):
        return self.car_meters > 0

    def suggested_spaces(self, length_ft):
        """Metered curb: one space per meter. Otherwise the parking census, which counts
        around every driveway; failing that, 20 ft per space minus red-curb driveways
        (the only driveways SFMTA maps)."""
        if self.metered:
            return self.car_meters
        if self.census is not None:
            return max(1, round(self.census))
        driveway_ft = sum(ft for kind, ft in self.zones if kind == "red-curb driveway")
        return max(1, round((length_ft - driveway_ft) / SPACE_FT))

    def describe(self):
        """"12 meters (7 general, 5 yellow (commercial loading)); 2 driveways (18 ft)"."""
        parts = []
        if self.meters:
            total = sum(self.meters.values())
            kinds = ", ".join(f"{n} {METER_TYPES.get(c, c.lower())}" for c, n in self.meters.most_common())
            parts.append(f"{total} meter{'s' if total != 1 else ''} ({kinds})")
        by_kind = Counter()
        feet = Counter()
        for kind, ft in self.zones:
            by_kind[kind] += 1
            feet[kind] += ft
        for kind, n in by_kind.most_common():
            parts.append(f"{n} {plural(kind, n)}" + (f" ({feet[kind]} ft)" if feet[kind] else ""))
        if not self.metered and self.census is not None:
            parts.append(f"about {round(self.census)} legal spaces per SFMTA parking census "
                         f"({self.census_year})")
        return "; ".join(parts) if parts else "no meters or color curbs on record"


class CurbData:
    def __init__(self, data_dir=DATA_DIR):
        data = json.loads((data_dir / "curbs.json").read_text())
        self.built = data["built"]
        self.blocks = data["blocks"]
        self.census = data.get("census", {})  # cnn -> [legal spaces, both sides; year]

    def lookup(self, zone):
        info = CurbInfo()
        lo, hi = zone.along_m
        for side, along, kind, feet in self.blocks.get(str(zone.cnn), []):
            if side != zone.side_sign or not lo - END_MARGIN_M <= along <= hi + END_MARGIN_M:
                continue
            source, _, name = kind.partition(":")
            if source == "meter":
                info.meters[name] += 1
            else:
                info.zones.append((CURB_TYPES.get(name, name.lower()), feet))
        # The census counts both sides of the whole block; this zone gets its share.
        if str(zone.cnn) in self.census and zone.block_ft > 0:
            spaces, info.census_year = self.census[str(zone.cnn)]
            info.census = spaces * min(1.0, zone.length_ft / (2 * zone.block_ft))
        return info
