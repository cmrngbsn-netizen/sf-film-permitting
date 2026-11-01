"""PDF builder checks that need no network (the map image is a plain placeholder)."""

import io

from PIL import Image

from core.pdf import build_pdf


def placeholder_png():
    out = io.BytesIO()
    Image.new("RGB", (1400, 950), "lightgrey").save(out, format="PNG")
    return out.getvalue()


def test_pdf_is_one_page_with_text():
    pdf = build_pdf(placeholder_png(),
                    ["NE corner, 18th St & Valencia St", "Valencia St, east side, between Sycamore St and 18th St"],
                    "Crew arrives 6am & wraps <8pm>.")
    assert pdf.startswith(b"%PDF")
    assert pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") >= 1


def test_empty_notes():
    assert build_pdf(placeholder_png(), ["Point"], "   ").startswith(b"%PDF")
