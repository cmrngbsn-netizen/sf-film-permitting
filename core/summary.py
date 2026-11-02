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
    curb: str = ""  # meters, driveways and color zones on this stretch


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


def street_side(z):
    """"8 metered spaces on north side 400-490 McAllister St"."""
    kind = {"Metered": "metered ", "Non-metered": "non-metered "}.get(z.meters, "")
    noun = "space" if z.spaces == 1 else "spaces"
    return f"{z.spaces} {kind}{noun} on {z.side} side {z.block}"


def unique(items):
    return list(dict.fromkeys(i for i in items if i))


def summarize(zones):
    """The table fields of a Film SF parking request, in the order they appear there."""
    hours = [zone_hours(z) for z in zones]
    if len({tuple(h) for h in hours}) <= 1:
        # Every zone has the same schedule: list it once.
        dates = hours[0] if hours else []
    else:
        # Schedules differ: say which zone each one belongs to.
        dates = [f"{z.block}, {z.side} side: " + "; ".join(h) for z, h in zip(zones, hours) if h]
    return {
        "# of signs": f"{sum(z.spaces for z in zones)} total spaces",
        "Block #": unique(z.block for z in zones),
        "Street side": [street_side(z) for z in zones],
        "Dates & hours": dates,
        "Curb notes": [f"{z.block}, {z.side} side: {z.curb}" for z in zones if z.curb],
    }
