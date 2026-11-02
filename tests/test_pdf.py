"""PDF builder checks that need no network (the map image is a plain placeholder)."""

import io

from PIL import Image
from pypdf import PdfReader

from core.pdf import Box, Page, build_pdf

WHO = Box([("Production", "High Priestess of Souls, LLC"), ("Dates & hours", ["MO, 11/02/26 7:00 AM - 11:59 PM"]),
           ("Contact", "Pat Example"), ("Phone", "(415) 555-0100")], (214, 39, 40))
WHERE = Box([("# of signs", "8 total spaces"), ("Location", "City Hall, McAllister @ Larkin & Polk"),
             ("Block #", ["400-490 McAllister St"]),
             ("Street side", ["8 metered spaces on north side 400-490 McAllister St"])])
GREEN = Box([("Dates & hours", ["TU, 11/03/26 7:00 AM - 11:59 PM"])], (44, 160, 44), "Picture")


def placeholder_png():
    out = io.BytesIO()
    Image.new("RGB", (1400, 1180), "lightgrey").save(out, format="PNG")
    return out.getvalue()


def test_pdf_builds_with_special_characters():
    page = Page(placeholder_png(), [WHO, WHERE, GREEN], ["INT <Jail> Release", "INT Morgue & Co"],
                "Crew arrives 6am & wraps <8pm>.", [("Working vehicles", (214, 39, 40))])
    assert build_pdf([page], project="Untitled <Project> & Co").startswith(b"%PDF")


def test_one_landscape_page_per_location():
    pages = [Page(placeholder_png(), [WHO, WHERE]), Page(placeholder_png(), [WHERE]),
             Page(placeholder_png(), [])]
    reader = PdfReader(io.BytesIO(build_pdf(pages)))
    assert len(reader.pages) == 3
    box = reader.pages[0].mediabox
    assert box.width > box.height


def test_empty_boxes_are_skipped():
    empty = Box([("Production", ""), ("Block #", [])])
    assert build_pdf([Page(placeholder_png(), [empty], notes="   ")]).startswith(b"%PDF")


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
