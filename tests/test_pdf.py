"""PDF builder checks that need no network (the map image is a plain placeholder)."""

import io

from PIL import Image

from core.pdf import build_pdf

SUMMARY = {
    "# of signs": "8 total spaces",
    "Block #": ["400-490 McAllister St"],
    "Street side": ["8 metered spaces on north side 400-490 McAllister St"],
    "Dates & hours": ["MO, 11/02/26 7:00 AM - 11:59 PM"],
}
LEGEND = [("Working vehicles", (214, 39, 40)), ("Picture", (31, 119, 180))]


def placeholder_png():
    out = io.BytesIO()
    Image.new("RGB", (1400, 950), "lightgrey").save(out, format="PNG")
    return out.getvalue()


def test_pdf_builds_with_special_characters():
    pdf = build_pdf(placeholder_png(), "City Hall, McAllister @ Larkin & Polk", SUMMARY, LEGEND,
                    "Crew arrives 6am & wraps <8pm>.")
    assert pdf.startswith(b"%PDF")


def test_empty_fields():
    empty = {"# of signs": "0 total spaces", "Block #": [], "Street side": [], "Dates & hours": []}
    assert build_pdf(placeholder_png(), "", empty, LEGEND, "   ").startswith(b"%PDF")
