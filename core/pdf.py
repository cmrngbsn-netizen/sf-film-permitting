"""PDF export: one page laid out like a Film SF parking request, with a map of the
curb zones and the request table."""

import io
from datetime import date
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as PdfImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from staticmap import StaticMap
from staticmap.staticmap import _lat_to_y, _lon_to_x

# OpenStreetMap's tile policy asks for an identifying User-Agent and the credit line.
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_HEADERS = {"User-Agent": "sf-film-permitting/0.1 (+https://github.com/cmrngbsn-netizen/sf-film-permitting)"}
MAP_CREDIT = "Map data © OpenStreetMap contributors"
MAX_ZOOM = 19  # highest zoom OpenStreetMap serves

MAP_SIZE = (1400, 950)  # pixels; drawn at about 200 dpi on the page
MAP_MARGIN = 150  # pixels kept clear around the zones
MAX_MAP_HEIGHT_IN = 4.0  # on the page


def render_map(lines):
    """PNG bytes of curb zones over OpenStreetMap tiles.
    lines: [(points [(lat, lon), ...], (r, g, b), label), ...]"""
    m = StaticMap(*MAP_SIZE, url_template=TILE_URL, headers=TILE_HEADERS)
    every = [p for pts, _, _ in lines for p in pts]
    lats, lons = [p[0] for p in every], [p[1] for p in every]
    center = [(min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2]
    # Closest zoom at which every zone fits with a margin around it.
    zoom = MAX_ZOOM
    while zoom > 12:
        w = (_lon_to_x(max(lons), zoom) - _lon_to_x(min(lons), zoom)) * 256
        h = (_lat_to_y(min(lats), zoom) - _lat_to_y(max(lats), zoom)) * 256
        if w <= MAP_SIZE[0] - 2 * MAP_MARGIN and h <= MAP_SIZE[1] - 2 * MAP_MARGIN:
            break
        zoom -= 1
    base = m.render(zoom=zoom, center=center).convert("RGBA")

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default(size=26)
    for pts, rgb, label in lines:
        px = [(m._x_to_px(_lon_to_x(lon, zoom)), m._y_to_px(_lat_to_y(lat, zoom))) for lat, lon in pts]
        draw.line(px, fill=rgb + (255,), width=9, joint="curve")
        for x, y in (px[0], px[-1]):
            draw.ellipse([x - 9, y - 9, x + 9, y + 9], fill=rgb + (255,))
        # Space count in a white box at the middle of the zone, like the Film SF slides.
        x, y = px[len(px) // 2]
        box = draw.textbbox((x, y), label, font=font, anchor="mm")
        draw.rectangle([box[0] - 8, box[1] - 6, box[2] + 8, box[3] + 6],
                       fill="white", outline=rgb + (255,), width=3)
        draw.text((x, y), label, fill="black", font=font, anchor="mm")
    credit_font = ImageFont.load_default(size=20)
    box = draw.textbbox((MAP_SIZE[0] - 12, MAP_SIZE[1] - 10), MAP_CREDIT, font=credit_font, anchor="rd")
    draw.rectangle([box[0] - 8, box[1] - 6, MAP_SIZE[0], MAP_SIZE[1]], fill=(255, 255, 255, 220))
    draw.text((MAP_SIZE[0] - 12, MAP_SIZE[1] - 10), MAP_CREDIT, fill=(60, 60, 60, 255),
              font=credit_font, anchor="rd")

    out = io.BytesIO()
    Image.alpha_composite(base, overlay).convert("RGB").save(out, format="PNG")
    return out.getvalue()


def build_pdf(map_png, fields, legend, notes, project="", created=None):
    """PDF bytes.
    fields: {label: text or [lines]} in table order (shoot info, location, then the
    core.summary fields); empty values are left out. legend: [(label, (r, g, b)), ...]."""
    created = created or date.today()
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    small = body.clone("small", fontSize=8, leading=10, textColor=colors.grey)
    label = body.clone("label", fontName="Helvetica-Bold")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title="SF Film Parking Request",
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    width = doc.width
    image = Image.open(io.BytesIO(map_png))
    # Shrink the map (keeping its shape) so the request table and notes fit on the page.
    map_h = min(width * image.height / image.width, MAX_MAP_HEIGHT_IN * inch)
    map_w = map_h * image.width / image.height

    def cell(value):
        lines = value if isinstance(value, list) else [value]
        return Paragraph("<br/>".join(escape(v) for v in lines), body)

    rows = [[Paragraph(f"{k.upper()}:", label), cell(v)] for k, v in fields.items() if v]
    key = "&nbsp;&nbsp;&nbsp;".join(
        f'<font color="#{r:02x}{g:02x}{b:02x}">&#9632;</font> {escape(name)}' for name, (r, g, b) in legend)

    story = [Paragraph("Parking Request", styles["Title"])]
    if project:
        story.append(Paragraph(escape(project), styles["Heading2"]))
    story += [
        Paragraph(f"Created {created:%B %-d, %Y}", body),
        Paragraph("Planning aid, not an official filing. Requests still go through "
                  "Film SF and SFMTA.", small),
        Spacer(1, 8),
        PdfImage(io.BytesIO(map_png), width=map_w, height=map_h),
        Paragraph(key, small),
        Spacer(1, 10),
    ]
    if rows:
        table = Table(rows, colWidths=[1.5 * inch, width - 1.5 * inch])
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8e8ec")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
    if notes.strip():
        story += [Spacer(1, 8), Paragraph("Notes", styles["Heading3"]),
                  Paragraph(escape(notes).replace("\n", "<br/>"), body)]
    doc.build(story)
    return buf.getvalue()
