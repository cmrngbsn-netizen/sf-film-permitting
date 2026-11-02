"""Basemaps for the app maps and the PDF. Each is one or more tile layers, bottom first,
with the credit line its terms ask for. Only OpenStreetMap for now; aerial options were
tried and set aside (see git history)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Basemap:
    name: str
    layers: tuple  # tile URL templates with {z}, {x}, {y}; overlays after the base
    credit: str
    max_zoom: int = 19


BASEMAPS = [
    # OpenStreetMap's tile policy asks for an identifying User-Agent and the credit line.
    Basemap("Street map",
            ("https://tile.openstreetmap.org/{z}/{x}/{y}.png",),
            "Map data © OpenStreetMap contributors"),
]
DEFAULT = BASEMAPS[0]
