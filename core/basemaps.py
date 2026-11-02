"""The basemap for the app maps and the PDF: OpenStreetMap, with the credit line its tile
policy asks for (it also asks for an identifying User-Agent, sent by core.pdf)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Basemap:
    url: str      # tile URL template with {z}, {x}, {y}
    credit: str
    max_zoom: int = 19


OSM = Basemap("https://tile.openstreetmap.org/{z}/{x}/{y}.png", "Map data © OpenStreetMap contributors")
