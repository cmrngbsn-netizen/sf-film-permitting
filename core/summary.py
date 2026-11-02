"""Film SF parking-request wording, built from the reviewed curb zones."""

from dataclasses import dataclass

WORKING = "Working vehicles"
PICTURE = "Picture"
USES = [WORKING, PICTURE]
METERS = ["Metered", "Non-metered", "Not sure"]


@dataclass
class ZoneRequest:
    """A curb zone plus what the user filled in for it."""
    block: str
    side: str
    spaces: int
    use: str = WORKING
    meters: str = "Not sure"
    date: object = None   # datetime.date
    start: object = None  # datetime.time
    end: object = None    # datetime.time


def clock(t):
    """07:00 -> "7:00 AM"."""
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def dates_and_hours(z):
    """"MO, 11/02/26 7:00 AM - 11:59 PM", or "" when no date is set."""
    if z.date is None:
        return ""
    text = f"{z.date:%a}"[:2].upper() + f", {z.date:%m/%d/%y}"
    if z.start and z.end:
        text += f" {clock(z.start)} - {clock(z.end)}"
        if z.end <= z.start:
            text += " (Next Day)"
    return text


def street_side(z):
    """"8 metered spaces on north side 400-490 McAllister St"."""
    kind = {"Metered": "metered ", "Non-metered": "non-metered "}.get(z.meters, "")
    noun = "space" if z.spaces == 1 else "spaces"
    return f"{z.spaces} {kind}{noun} on {z.side} side {z.block}"


def unique(items):
    return list(dict.fromkeys(i for i in items if i))


def summarize(zones):
    """The table fields of a Film SF parking request, in the order they appear there."""
    return {
        "# of signs": f"{sum(z.spaces for z in zones)} total spaces",
        "Block #": unique(z.block for z in zones),
        "Street side": [street_side(z) for z in zones],
        "Dates & hours": unique(dates_and_hours(z) for z in zones),
    }
