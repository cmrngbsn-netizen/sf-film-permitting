"""Free basemaps for the app maps and the PDF. Each is one or more tile layers, bottom
first, with the credit line its terms ask for."""

from dataclasses import dataclass

ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services"
ESRI_CREDIT = "Imagery © Esri, Maxar, Earthstar Geographics; labels © Esri, HERE, Garmin, OpenStreetMap"


@dataclass(frozen=True)
class Basemap:
    name: str
    layers: tuple  # tile URL templates with {z}, {x}, {y}; overlays after the base
    credit: str
    max_zoom: int = 19


BASEMAPS = [
    # Esri's imagery is free to use with attribution; check Esri's terms before
    # commercial use. Road and place labels come as transparent overlays.
    Basemap("Aerial with street names",
            (f"{ESRI}/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",
             f"{ESRI}/Reference/World_Transportation/MapServer/tile/{{z}}/{{y}}/{{x}}",
             f"{ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{{z}}/{{y}}/{{x}}"),
            ESRI_CREDIT),
    Basemap("Aerial",
            (f"{ESRI}/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}",),
            "Imagery © Esri, Maxar, Earthstar Geographics"),
    # OpenStreetMap's tile policy asks for an identifying User-Agent and the credit line.
    Basemap("Street map",
            ("https://tile.openstreetmap.org/{z}/{x}/{y}.png",),
            "Map data © OpenStreetMap contributors"),
]
BY_NAME = {b.name: b for b in BASEMAPS}
DEFAULT = BASEMAPS[0]
