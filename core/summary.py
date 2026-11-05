"""Film SF parking-request wording, built from the reviewed curb zones."""

from dataclasses import dataclass, field
from datetime import time

WORKING = "Working vehicles"
PICTURE = "Picture"
USES = [WORKING, PICTURE]
METERS = ["Metered", "Non-metered", "Not sure"]

@dataclass
class Window:
    """One stretch of time a zone is occupied."""
    date: object = None   # datetime.date
    start: object = None  # datetime.time
    end: object = None    # datetime.time


@dataclass
class ZoneRequest:
    """A curb zone plus what the user filled in for it."""
    block: str
    side: str
    spaces: int
    use: str = WORKING
    meters: str = "Not sure"
    windows: list = field(default_factory=list)  # [Window, ...]


def clock(t):
    """07:00 -> "7:00 AM"."""
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def dates_and_hours(w):
    """"MO, 11/02/26 7:00 AM - 11:59 PM", or "" when no date is set."""
    if w.date is None:
        return ""
    text = f"{w.date:%a}"[:2].upper() + f", {w.date:%m/%d/%y}"
    if w.start and w.end:
        text += f" {clock(w.start)} - {clock(w.end)}"
        if w.end <= w.start:
            text += " (Next Day)"
    return text


def zone_hours(z):
    """All of a zone's windows, in date order, as text lines."""
    timed = sorted((w for w in z.windows if w.date), key=lambda w: (w.date, w.start or time.min))
    return [dates_and_hours(w) for w in timed]


def unique(items):
    return list(dict.fromkeys(i for i in items if i))


def block_sides(zones):
    """One line per block, with what's asked for on each side:
    "800-890 Washington St: 6 metered north, 10 metered south". Pieces of a block side (an
    alley can split a block in two) are added up."""
    totals = {}
    for z in zones:
        sides = totals.setdefault(z.block, {}).setdefault(z.side, {})
        sides[z.meters] = sides.get(z.meters, 0) + z.spaces
    def kind(meters, n):
        return f"{n} " + {"Metered": "metered", "Non-metered": "non-metered"}.get(
            meters, "space" if n == 1 else "spaces")
    return [block + ": " + ", ".join(" + ".join(kind(m, n) for m, n in kinds.items()) + f" {side}"
                                     for side, kinds in sides.items())
            for block, sides in totals.items()]


def schedules(zones):
    """{(dates & hours lines): [zones with that schedule]}, in first-seen order."""
    out = {}
    for z in zones:
        out.setdefault(tuple(zone_hours(z)), []).append(z)
    return out


def summarize(zones, colors=None):
    """The table fields of a Film SF parking request, in the order they appear there, plus
    "By color": [(color, uses, dates & hours lines), ...] for the color-matched boxes on the
    Film SF slides, when line colors tell the schedules apart."""
    groups = {k: v for k, v in schedules(zones).items() if k}
    by_color = []
    if len(groups) <= 1:
        dates = list(next(iter(groups), []))
    else:
        per_color = {}
        for z, c in zip(zones, colors or []):
            per_color.setdefault(c, []).append(z)
        if colors and all(len(schedules(zs)) == 1 for zs in per_color.values()):
            # Each line color has one schedule: list the schedules once, and the colored
            # boxes say which goes with which lines.
            dates = unique(line for s in groups for line in s)
            by_color = [(c, unique(z.use for z in zs), zone_hours(zs[0])) for c, zs in per_color.items()]
        else:
            dates = [", ".join(unique(f"{z.block} ({z.side})" for z in zs)) + ": " + "; ".join(s)
                     for s, zs in groups.items()]
    return {
        "# of signs": f"{sum(z.spaces for z in zones)} total spaces",
        "Block & side": block_sides(zones),
        "Dates & hours": dates,
        "By color": by_color,
    }
