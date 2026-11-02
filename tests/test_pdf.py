"""PDF builder checks that need no network (the map image is a plain placeholder)."""

import io

from PIL import Image
from pypdf import PdfReader

from core.pdf import Page, build_pdf

FIELDS = {
    "Production": "High Priestess of Souls, LLC",
    "Contact": "Pat Example",
    "Phone": "(415) 555-0100",
    "Location": "City Hall, McAllister @ Larkin & Polk",
    "# of signs": "8 total spaces",
    "Block #": ["400-490 McAllister St"],
    "Street side": ["8 metered spaces on north side 400-490 McAllister St"],
    "Dates & hours": ["MO, 11/02/26 7:00 AM - 11:59 PM"],
    "Curb notes": ["400-490 McAllister St, north side: 6 meters (6 general)"],
}
LEGEND = [("Working vehicles", (214, 39, 40)), ("Picture", (31, 119, 180))]


def placeholder_png():
    out = io.BytesIO()
    Image.new("RGB", (1400, 950), "lightgrey").save(out, format="PNG")
    return out.getvalue()


def test_pdf_builds_with_special_characters():
    pdf = build_pdf([Page(placeholder_png(), FIELDS, "Crew arrives 6am & wraps <8pm>.")], LEGEND,
                    project="Untitled <Project> & Co")
    assert pdf.startswith(b"%PDF")


def test_one_page_per_location():
    pages = [Page(placeholder_png(), FIELDS, "notes"), Page(placeholder_png(), FIELDS),
             Page(placeholder_png(), {})]
    assert len(PdfReader(io.BytesIO(build_pdf(pages, LEGEND))).pages) == 3


def test_empty_fields_are_skipped():
    empty = {"Production": "", "Location": "", "# of signs": "0 total spaces", "Block #": []}
    assert build_pdf([Page(placeholder_png(), empty, "   ")], LEGEND).startswith(b"%PDF")
    assert build_pdf([Page(placeholder_png(), {})], LEGEND).startswith(b"%PDF")


def test_tile_math_and_basemap_urls():
    from core.basemaps import BASEMAPS
    from core.pdf import tile_x, tile_y

    # Zoom 0 is a single tile covering the world; the equator and prime meridian sit mid-tile.
    assert tile_x(0, 0) == 0.5 and abs(tile_y(0, 0) - 0.5) < 1e-12
    # Grant & Washington at zoom 19, per the OpenStreetMap wiki formula: tile 83876, 202611.
    assert int(tile_x(-122.4066, 19)) == 83876 and int(tile_y(37.7948, 19)) == 202611
    for b in BASEMAPS:
        for url in b.layers:
            assert url.format(z=19, x=1, y=2).startswith("https://")
        assert b.credit
