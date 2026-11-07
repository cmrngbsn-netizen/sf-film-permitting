"""What the city has on a curb zone: SFMTA meters (by cap color) and color curbs
(driveways, blue/white/yellow/green zones, ...), from data/curbs.json."""

import json
from collections import Counter
from dataclasses import dataclass, field

from core.curbs import SPACE_FT, joined, share_addresses
from core.streets import DATA_DIR

# Curb items this far past either end of a drawn zone still count, so a meter or
# driveway right at the end of the line isn't missed.
END_MARGIN_M = 3

# Meter cap colors, per SFMTA's data dictionary, as short names for the Curb column.
METER_TYPES = {
    "Grey": "general",
    "Yellow": "yellow loading",
    "Red": "red truck loading",
    "Green": "green short-term",
    "Black": "motorcycle",
    "Brown": "tour bus",
    "Purple": "boat trailer",
    "Blue": "blue accessible",
    "White": "white passenger loading",
}
# Motorcycle meters don't hold a car, so they don't count toward car spaces.
NON_CAR_METERS = {"Black"}

# SFMTA color curb zone types, as short names for the Curb column.
CURB_TYPES = {
    "Driveway Red Zone": "red-curb driveway",  # only driveways painted red are mapped
    "Blue Zone/Disabled Parking": "blue zone",
    "White Zone/Passenger Loading": "white zone",
    "Yellow Zone/Commercial Loading": "yellow zone",
    "Commercial Loading Zone": "yellow zone",
    "6-Wheel Commercial Loading Zone": "6-wheel loading zone",
    "Green Zone/Short Term Parking": "green zone",
    "Green Meter": "green zone",
    "Taxi Zone": "taxi zone",
    "Tour Bus Loading Zone": "tour bus zone",
    "School Bus Loading Zone": "school bus zone",
    "Shuttle Bus Loading Zone": "shuttle bus zone",
    "General Loading Zone": "loading zone",
    "Dual-use zone": "dual-use zone",
}


NOTHING_ON_RECORD = "None on record"


def counted(n, thing):
    return f"{n} {thing}{'s' if n != 1 else ''}"


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
        """What's on the curb, in the terms the Spaces column counts:
        "7 general meters, 3 motorcycle meters (not counted), 2 red-curb driveways, blue zone 34 ft"."""
        parts = [counted(n, f"{METER_TYPES.get(color, color.lower())} meter")
                 + (" (not counted)" if color in NON_CAR_METERS else "")
                 for color, n in self.meters.most_common()]
        by_kind, feet = Counter(), Counter()
        for kind, ft in self.zones:
            by_kind[kind] += 1
            feet[kind] += ft
        for kind, n in by_kind.most_common():
            name = counted(n, kind) if n > 1 or kind == "red-curb driveway" else kind
            parts.append(name + (f" {feet[kind]} ft" if feet[kind] and kind != "red-curb driveway" else ""))
        return ", ".join(parts) if parts else NOTHING_ON_RECORD


class CurbData:
    def __init__(self, data_dir=DATA_DIR):
        data = json.loads((data_dir / "curbs.json").read_text())
        self.built = data["built"]
        self.blocks = data["blocks"]
        self.census = data.get("census", {})  # cnn -> [legal spaces, both sides; year]

    def join_pieces(self, zones):
        """A line's zones with neighboring pieces of a block side joined into one, as long as
        they are all metered or all unmetered (the two are written separately on a request)."""
        groups = []
        for z in zones:
            same = groups and (groups[-1][0].block, groups[-1][0].side) == (z.block, z.side)
            if same and self.lookup(groups[-1][0]).metered == self.lookup(z).metered:
                groups[-1].append(z)
            else:
                groups.append([z])
        return share_addresses([joined(g) for g in groups])

    def lookup(self, zone):
        info = CurbInfo()
        shares = []
        for part in zone.parts or [zone]:
            lo, hi = part.along_m
            for side, along, kind, feet in self.blocks.get(str(part.cnn), []):
                if side != part.side_sign or not lo - END_MARGIN_M <= along <= hi + END_MARGIN_M:
                    continue
                source, _, name = kind.partition(":")
                if source == "meter":
                    info.meters[name] += 1
                else:
                    info.zones.append((CURB_TYPES.get(name, name.lower()), feet))
            # The census counts both sides of the whole block; this stretch gets its share.
            if str(part.cnn) in self.census and part.block_ft > 0:
                spaces, info.census_year = self.census[str(part.cnn)]
                shares.append(spaces * min(1.0, part.length_ft / (2 * part.block_ft)))
            else:
                shares.append(None)
        if None not in shares:
            info.census = sum(shares)
        return info
