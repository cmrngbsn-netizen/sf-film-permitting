"""PDF export: a summary of the requested permit area with a map and the boundary list."""

import io
from datetime import date
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as PdfImage
from reportlab.platypus import ListFlowable, Paragraph, SimpleDocTemplate, Spacer
from staticmap import StaticMap
from staticmap.staticmap import _lat_to_y, _lon_to_x

# OpenStreetMap's tile policy asks for an identifying User-Agent and the credit line.
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_HEADERS = {"User-Agent": "sf-film-permitting/0.1 (+https://github.com/cmrngbsn-netizen/sf-film-permitting)"}
MAP_CREDIT = "Map data © OpenStreetMap contributors"
MAX_ZOOM = 19  # highest zoom OpenStreetMap serves

MAP_SIZE = (1400, 950)  # pixels; drawn at about 200 dpi on the page
MAP_MARGIN = 150  # pixels kept clear around the area
RED = (214, 39, 40)


def render_map(points):
    """PNG bytes of the area over OpenStreetMap tiles, with numbered points.
    points: [(lat, lon), ...] in boundary order."""
    m = StaticMap(*MAP_SIZE, url_template=TILE_URL, headers=TILE_HEADERS)
    lats, lons = [p[0] for p in points], [p[1] for p in points]
    center = [(min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2]
    # Closest zoom at which the whole area fits with a margin around it.
    zoom = MAX_ZOOM
    while zoom > 12:
        w = (_lon_to_x(max(lons), zoom) - _lon_to_x(min(lons), zoom)) * 256
        h = (_lat_to_y(min(lats), zoom) - _lat_to_y(max(lats), zoom)) * 256
        if w <= MAP_SIZE[0] - 2 * MAP_MARGIN and h <= MAP_SIZE[1] - 2 * MAP_MARGIN:
            break
        zoom -= 1
    base = m.render(zoom=zoom, center=center).convert("RGBA")

    px = [(m._x_to_px(_lon_to_x(lon, zoom)), m._y_to_px(_lat_to_y(lat, zoom))) for lat, lon in points]
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.polygon(px, fill=RED + (45,))
    draw.line(px + [px[0]], fill=RED + (255,), width=6, joint="curve")
    font = ImageFont.load_default(size=26)
    for i, (x, y) in enumerate(px, start=1):
        draw.ellipse([x - 22, y - 22, x + 22, y + 22], fill=RED + (255,), outline="white", width=3)
        draw.text((x, y), str(i), fill="white", font=font, anchor="mm")
    credit_font = ImageFont.load_default(size=20)
    box = draw.textbbox((MAP_SIZE[0] - 12, MAP_SIZE[1] - 10), MAP_CREDIT, font=credit_font, anchor="rd")
    draw.rectangle([box[0] - 8, box[1] - 6, MAP_SIZE[0], MAP_SIZE[1]], fill=(255, 255, 255, 220))
    draw.text((MAP_SIZE[0] - 12, MAP_SIZE[1] - 10), MAP_CREDIT, fill=(60, 60, 60, 255),
              font=credit_font, anchor="rd")

    out = io.BytesIO()
    Image.alpha_composite(base, overlay).convert("RGB").save(out, format="PNG")
    return out.getvalue()


def build_pdf(map_png, boundary, notes, created=None):
    """PDF bytes. boundary: label text per point, in order; notes: free text."""
    created = created or date.today()
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=8, leading=10, textColor=colors.grey)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title="SF Film Permit Area",
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    width = doc.width
    image = Image.open(io.BytesIO(map_png))
    height = width * image.height / image.width

    story = [
        Paragraph("SF Film Permit Area", styles["Title"]),
        Paragraph(f"Created {created:%B %-d, %Y}", styles["BodyText"]),
        Paragraph("Beta planning aid, not an official filing. Requests still go through "
                  "Film SF and SFMTA.", small),
        Spacer(1, 10),
        PdfImage(io.BytesIO(map_png), width=width, height=height),
        Spacer(1, 12),
        Paragraph("Area boundary, in order", styles["Heading2"]),
        ListFlowable([Paragraph(escape(text), styles["BodyText"]) for text in boundary],
                     bulletType="1", leftIndent=18),
        Spacer(1, 8),
        Paragraph("Notes", styles["Heading2"]),
        Paragraph(escape(notes).replace("\n", "<br/>") if notes.strip() else "None.",
                  styles["BodyText"]),
    ]
    doc.build(story)
    return buf.getvalue()
