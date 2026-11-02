"""PDF export: one page laid out like a Film SF parking request, with a map of the
curb zones and the request table."""

import io
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as PdfImage
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.basemaps import DEFAULT

# Tile servers ask apps to identify themselves.
TILE_HEADERS = {"User-Agent": "sf-film-permitting/0.1 (+https://github.com/cmrngbsn-netizen/sf-film-permitting)"}

MAP_SIZE = (1400, 950)  # pixels; drawn at about 200 dpi on the page
MAP_MARGIN = 150  # pixels kept clear around the zones
MAX_MAP_HEIGHT_IN = 4.0  # on the page
TILE = 256  # pixels per map tile


def tile_x(lon, zoom):
    """Web Mercator tile coordinate (fractional) for a longitude."""
    return (lon + 180) / 360 * 2 ** zoom


def tile_y(lat, zoom):
    return (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** zoom


def fetch_tile(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=TILE_HEADERS), timeout=20) as res:
        return Image.open(io.BytesIO(res.read())).convert("RGBA")


def render_tiles(url, zoom, cx, cy):
    """One tile layer as a transparent RGBA image of MAP_SIZE centered on tile coords
    (cx, cy); overlay layers keep their transparency."""
    w, h = MAP_SIZE
    left, top = cx * TILE - w / 2, cy * TILE - h / 2
    xs = range(math.floor(left / TILE), math.floor((left + w) / TILE) + 1)
    ys = range(math.floor(top / TILE), math.floor((top + h) / TILE) + 1)
    spots = [(x, y) for x in xs for y in ys]
    with ThreadPoolExecutor(max_workers=4) as pool:
        tiles = pool.map(lambda xy: fetch_tile(url.format(z=zoom, x=xy[0], y=xy[1])), spots)
    image = Image.new("RGBA", MAP_SIZE, (0, 0, 0, 0))
    for (x, y), tile in zip(spots, tiles):
        image.alpha_composite(tile, (round(x * TILE - left), round(y * TILE - top)))
    return image


STAR_COLOR = (255, 140, 0)  # the orange star on the Film SF slides


def star_points(x, y, r):
    """Corners of a five-pointed star centered on (x, y)."""
    pts = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        radius = r if i % 2 == 0 else r * 0.42
        pts.append((x + radius * math.cos(angle), y - radius * math.sin(angle)))
    return pts


def render_map(lines, markers=(), basemap=DEFAULT):
    """PNG bytes of curb zones and markers over a basemap (core.basemaps).
    lines: [(points [(lat, lon), ...], (r, g, b), label), ...]
    markers: [(kind "Star" or "Text box", (lat, lon), text), ...]"""
    every = [p for pts, _, _ in lines for p in pts] + [point for _, point, _ in markers]
    lats, lons = [p[0] for p in every], [p[1] for p in every]
    center = [(min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2]
    # Closest zoom at which every zone fits with a margin around it.
    zoom = basemap.max_zoom
    while zoom > 12:
        w = (tile_x(max(lons), zoom) - tile_x(min(lons), zoom)) * TILE
        h = (tile_y(min(lats), zoom) - tile_y(max(lats), zoom)) * TILE
        if w <= MAP_SIZE[0] - 2 * MAP_MARGIN and h <= MAP_SIZE[1] - 2 * MAP_MARGIN:
            break
        zoom -= 1
    cx, cy = tile_x(center[0], zoom), tile_y(center[1], zoom)
    # Tile layers stacked bottom first: imagery, then label overlays.
    base = Image.new("RGBA", MAP_SIZE, (255, 255, 255, 255))
    for url in basemap.layers:
        base.alpha_composite(render_tiles(url, zoom, cx, cy))

    def to_px(lat, lon):
        return ((tile_x(lon, zoom) - cx) * TILE + MAP_SIZE[0] / 2,
                (tile_y(lat, zoom) - cy) * TILE + MAP_SIZE[1] / 2)

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default(size=26)
    for pts, rgb, label in lines:
        px = [to_px(lat, lon) for lat, lon in pts]
        draw.line(px, fill=rgb + (255,), width=9, joint="curve")
        for x, y in (px[0], px[-1]):
            draw.ellipse([x - 9, y - 9, x + 9, y + 9], fill=rgb + (255,))
        # Space count in a white box at the middle of the zone, like the Film SF slides.
        x, y = px[len(px) // 2]
        box = draw.textbbox((x, y), label, font=font, anchor="mm")
        draw.rectangle([box[0] - 8, box[1] - 6, box[2] + 8, box[3] + 6],
                       fill="white", outline=rgb + (255,), width=3)
        draw.text((x, y), label, fill="black", font=font, anchor="mm")
    bold = ImageFont.load_default(size=28)
    for kind, (lat, lon), text in markers:
        x, y = to_px(lat, lon)
        if kind == "Star":
            draw.polygon(star_points(x, y, 26), fill=STAR_COLOR + (255,), outline=(90, 50, 0, 255), width=2)
        elif text.strip():
            # A white text box with a dark border, like "WORKING VEHICLES" on the slides.
            box = draw.multiline_textbbox((x, y), text.strip(), font=bold, anchor="mm", align="center")
            draw.rectangle([box[0] - 12, box[1] - 10, box[2] + 12, box[3] + 10],
                           fill=(255, 255, 255, 240), outline=(40, 40, 40, 255), width=3)
            draw.multiline_text((x, y), text.strip(), fill="black", font=bold, anchor="mm", align="center")
    credit_font = ImageFont.load_default(size=20)
    box = draw.textbbox((MAP_SIZE[0] - 12, MAP_SIZE[1] - 10), basemap.credit, font=credit_font, anchor="rd")
    draw.rectangle([box[0] - 8, box[1] - 6, MAP_SIZE[0], MAP_SIZE[1]], fill=(255, 255, 255, 220))
    draw.text((MAP_SIZE[0] - 12, MAP_SIZE[1] - 10), basemap.credit, fill=(60, 60, 60, 255),
              font=credit_font, anchor="rd")

    out = io.BytesIO()
    Image.alpha_composite(base, overlay).convert("RGB").save(out, format="PNG")
    return out.getvalue()


@dataclass
class Page:
    """One location of the request: its map, table fields and notes."""
    map_png: bytes
    fields: dict  # {label: text or [lines]} in table order; empty values are left out
    notes: str = ""
    legend: list = None  # [(label, (r, g, b)), ...]; the document legend when not set


def build_pdf(pages, legend, project="", created=None):
    """PDF bytes with one page per location, laid out like the Film SF slides.
    legend: [(label, (r, g, b)), ...]."""
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

    def cell(value):
        lines = value if isinstance(value, list) else [value]
        return Paragraph("<br/>".join(escape(v) for v in lines), body)

    def key(entries):
        return "&nbsp;&nbsp;&nbsp;".join(
            f'<font color="#{r:02x}{g:02x}{b:02x}">&#9632;</font> {escape(name)}'
            for name, (r, g, b) in entries)

    heading = "Parking Request" + (f" - {escape(project)}" if project else "")

    story = []
    for n, page in enumerate(pages, start=1):
        if n > 1:
            story.append(PageBreak())
        image = Image.open(io.BytesIO(page.map_png))
        # Shrink the map (keeping its shape) so the request table and notes fit on the page.
        map_h = min(width * image.height / image.width, MAX_MAP_HEIGHT_IN * inch)
        map_w = map_h * image.width / image.height
        story += [
            Paragraph(heading, styles["Heading1"]),
            Paragraph(f"Created {created:%B %-d, %Y}"
                      + (f" &nbsp;·&nbsp; Page {n} of {len(pages)}" if len(pages) > 1 else ""), body),
            Paragraph("Planning aid, not an official filing. Requests still go through "
                      "Film SF and SFMTA.", small),
            Spacer(1, 8),
            PdfImage(io.BytesIO(page.map_png), width=map_w, height=map_h),
            Paragraph(key(page.legend if page.legend is not None else legend), small),
            Spacer(1, 10),
        ]
        rows = [[Paragraph(f"{k.upper()}:", label), cell(v)] for k, v in page.fields.items() if v]
        if rows:
            table = Table(rows, colWidths=[1.5 * inch, width - 1.5 * inch])
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8e8ec")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(table)
        if page.notes.strip():
            story += [Spacer(1, 8), Paragraph("Notes", styles["Heading3"]),
                      Paragraph(escape(page.notes).replace("\n", "<br/>"), body)]
    doc.build(story)
    return buf.getvalue()
