"""A whole parking request: shared shoot info plus one or more locations, each with its
drawn curb lines, per-zone edits and time windows. Saved and reopened as JSON."""

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, time

from core.summary import Window

FORMAT_VERSION = 1

# Shared by every page of the request.
REQUEST_FIELDS = ["Production", "Project", "Email", "Film SF permit #"]
# Set per location (the Film SF slides change contact between locations).
LOCATION_FIELDS = ["Location", "Scene", "Contact", "Phone"]


def new_id():
    return uuid.uuid4().hex[:8]


@dataclass
class Location:
    id: str = field(default_factory=new_id)
    info: dict = field(default_factory=lambda: {name: "" for name in LOCATION_FIELDS})
    notes: str = ""
    lines: list = field(default_factory=list)   # [[(lat, lon), ...], ...] as drawn
    zones: dict = field(default_factory=dict)   # zone id -> edited row (Curb, Meters, Spaces, Use)
    windows: dict = field(default_factory=dict)  # zone id -> [Window, ...]

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
                "lines": [[[lat, lon] for lat, lon in line] for line in loc.lines],
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
            lines=[[(lat, lon) for lat, lon in line] for line in raw.get("lines", [])],
            zones=raw.get("zones", {}),
            windows={zid: [_window_in(w) for w in ws] for zid, ws in raw.get("windows", {}).items()},
        ) for raw in data.get("locations", [])]
        info = {name: data.get("info", {}).get(name, "") for name in REQUEST_FIELDS}
        return cls(info=info, locations=locations or [Location()])


def _window_out(w):
    return {"date": w.date.isoformat() if w.date else None,
            "start": w.start.strftime("%H:%M") if w.start else None,
            "end": w.end.strftime("%H:%M") if w.end else None}


def _window_in(raw):
    return Window(date.fromisoformat(raw["date"]) if raw.get("date") else None,
                  time.fromisoformat(raw["start"]) if raw.get("start") else None,
                  time.fromisoformat(raw["end"]) if raw.get("end") else None)
