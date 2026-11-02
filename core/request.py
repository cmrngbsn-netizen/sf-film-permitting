"""A whole parking request: shared shoot info plus one or more locations, each with its
drawn curb lines, arrows, map markers (stars and text boxes), per-zone edits and time windows.
Saved and reopened as JSON."""

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, time

from core.summary import Window

FORMAT_VERSION = 4
# 2: lines carry a color, locations have markers; 3: scene list, marker size;
# 4: arrows, text box size in pixels and a border color

# Line colors to draw with. The first is the default; a blue line starts as "Picture".
LINE_COLORS = {"Red": "#d62728", "Blue": "#1f77b4", "Green": "#2ca02c",
               "Orange": "#ff7f0e", "Purple": "#9467bd", "Black": "#222222"}
DEFAULT_COLOR = LINE_COLORS["Red"]
STAR, TEXT = "Star", "Text box"
MARKER_KINDS = [STAR, TEXT]
TEXT_COLOR = "#2b2b2b"  # default text box border, a soft black
TEXT_PX = {"min": 10, "max": 36, "default": 14}  # text box font size on screen, in pixels
# Version 3 named the sizes.
NAMED_SIZES = {"Small": 11, "Medium": 14, "Large": 18, "X-Large": 24}

# Shared by every page of the request.
REQUEST_FIELDS = ["Production", "Project", "Email", "Film SF permit #"]
# Set per location (the Film SF slides change contact between locations). Scenes are a
# separate list, since one location can serve several scenes.
LOCATION_FIELDS = ["Location", "Contact", "Phone"]


def new_id():
    return uuid.uuid4().hex[:8]


def format_phone(text):
    """"4155550100" or "1-415-555-0100" -> "(415) 555-0100". Anything that isn't a 10-digit
    US number (an extension, a short code) is left as typed."""
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return text.strip()
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


@dataclass
class Line:
    points: list  # [(lat, lon), ...] as drawn
    color: str = DEFAULT_COLOR


@dataclass
class Arrow:
    points: list  # [(lat, lon), ...]; the head is at the last point
    color: str = DEFAULT_COLOR


@dataclass
class Marker:
    point: tuple  # (lat, lon)
    kind: str = STAR
    text: str = ""
    size: int = TEXT_PX["default"]  # text box font size on screen, in pixels
    color: str = TEXT_COLOR         # text box border


@dataclass
class Location:
    id: str = field(default_factory=new_id)
    info: dict = field(default_factory=lambda: {name: "" for name in LOCATION_FIELDS})
    notes: str = ""
    scenes: list = field(default_factory=list)   # ["INT City Hall - SHOOT", ...]
    lines: list = field(default_factory=list)    # [Line, ...] curb lines
    arrows: list = field(default_factory=list)   # [Arrow, ...]
    markers: list = field(default_factory=list)  # [Marker, ...]
    zones: dict = field(default_factory=dict)    # zone id -> edited row (Curb, Meters, Spaces, Use)
    windows: dict = field(default_factory=dict)  # zone id -> [Window, ...]
    # The Location name is filled in from the drawn lines until the user types their own.
    auto_name: bool = True

    @property
    def title(self):
        return self.info.get("Location") or "Untitled location"


@dataclass
class Request:
    info: dict = field(default_factory=lambda: {name: "" for name in REQUEST_FIELDS})
    locations: list = field(default_factory=lambda: [Location()])

    def add_location(self):
        """A new empty location, carrying over the last location's contact."""
        last = self.locations[-1].info if self.locations else {}
        loc = Location()
        loc.info["Contact"] = last.get("Contact", "")
        loc.info["Phone"] = last.get("Phone", "")
        self.locations.append(loc)
        return loc

    def remove_location(self, loc_id):
        self.locations = [loc for loc in self.locations if loc.id != loc_id] or [Location()]

    def to_json(self):
        return json.dumps({
            "format": "sf-film-parking-request",
            "version": FORMAT_VERSION,
            "info": self.info,
            "locations": [{
                "id": loc.id,
                "info": loc.info,
                "notes": loc.notes,
                "scenes": loc.scenes,
                "lines": [{"points": [[lat, lon] for lat, lon in line.points], "color": line.color}
                          for line in loc.lines],
                "arrows": [{"points": [[lat, lon] for lat, lon in a.points], "color": a.color}
                           for a in loc.arrows],
                "markers": [{"point": list(m.point), "kind": m.kind, "text": m.text, "size": m.size,
                             "color": m.color} for m in loc.markers],
                "auto_name": loc.auto_name,
                "zones": loc.zones,
                "windows": {zid: [_window_out(w) for w in ws] for zid, ws in loc.windows.items()},
            } for loc in self.locations],
        }, indent=1)

    @classmethod
    def from_json(cls, text):
        data = json.loads(text)
        if data.get("format") != "sf-film-parking-request":
            raise ValueError("This isn't a saved SF Film Parking Request file.")
        if data.get("version", 0) > FORMAT_VERSION:
            raise ValueError("This file was saved by a newer version of the app.")
        locations = [Location(
            id=raw.get("id") or new_id(),
            info={name: raw.get("info", {}).get(name, "") for name in LOCATION_FIELDS},
            notes=raw.get("notes", ""),
            # Version 2 had one Scene text field.
            scenes=raw.get("scenes") or ([raw["info"]["Scene"]] if raw.get("info", {}).get("Scene") else []),
            lines=[_line_in(line) for line in raw.get("lines", [])],
            arrows=[Arrow([(lat, lon) for lat, lon in a["points"]], a.get("color", DEFAULT_COLOR))
                    for a in raw.get("arrows", [])],
            markers=[Marker(tuple(m["point"]), m.get("kind", STAR), m.get("text", ""),
                            text_size(m.get("size")), m.get("color", TEXT_COLOR))
                     for m in raw.get("markers", [])],
            auto_name=raw.get("auto_name", not raw.get("info", {}).get("Location")),
            zones=raw.get("zones", {}),
            windows={zid: [_window_in(w) for w in ws] for zid, ws in raw.get("windows", {}).items()},
        ) for raw in data.get("locations", [])]
        info = {name: data.get("info", {}).get(name, "") for name in REQUEST_FIELDS}
        return cls(info=info, locations=locations or [Location()])


def text_size(value):
    """A text box size in pixels, from a saved number or a version 3 name ("Large")."""
    if isinstance(value, str):
        return NAMED_SIZES.get(value, TEXT_PX["default"])
    if isinstance(value, (int, float)):
        return int(min(max(value, TEXT_PX["min"]), TEXT_PX["max"]))
    return TEXT_PX["default"]


def _line_in(raw):
    """A saved line: version 1 stored bare point lists, version 2 adds a color."""
    if isinstance(raw, dict):
        return Line([(lat, lon) for lat, lon in raw["points"]], raw.get("color", DEFAULT_COLOR))
    return Line([(lat, lon) for lat, lon in raw])


def _window_out(w):
    return {"date": w.date.isoformat() if w.date else None,
            "start": w.start.strftime("%H:%M") if w.start else None,
            "end": w.end.strftime("%H:%M") if w.end else None}


def _window_in(raw):
    return Window(date.fromisoformat(raw["date"]) if raw.get("date") else None,
                  time.fromisoformat(raw["start"]) if raw.get("start") else None,
                  time.fromisoformat(raw["end"]) if raw.get("end") else None)
