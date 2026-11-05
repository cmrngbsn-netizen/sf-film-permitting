"""PDF export: one page laid out like a Film SF parking request, with a map of the
curb zones and the request table."""

import io
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as PdfImage
from reportlab.platypus import (BaseDocTemplate, Frame, FrameBreak, KeepInFrame, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

from core.basemaps import OSM

# Tile servers ask apps to identify themselves.
TILE_HEADERS = {"User-Agent": "sf-film-permitting/0.1 (+https://github.com/cmrngbsn-netizen/sf-film-permitting)"}

MAP_SIZE = (1400, 1180)  # pixels; drawn at about 220 dpi in the page's map column
MAP_MARGIN = 150  # pixels kept clear around the zones
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
    """The basemap's tiles as an RGBA image of MAP_SIZE centered on tile coords (cx, cy)."""
    w, h = MAP_SIZE
    left, top = cx * TILE - w / 2, cy * TILE - h / 2
    xs = range(math.floor(left / TILE), math.floor((left + w) / TILE) + 1)
    ys = range(math.floor(top / TILE), math.floor((top + h) / TILE) + 1)
    spots = [(x, y) for x in xs for y in ys]
    with ThreadPoolExecutor(max_workers=4) as pool:
        tiles = pool.map(lambda xy: fetch_tile(url.format(z=zoom, x=xy[0], y=xy[1])), spots)
    image = Image.new("RGBA", MAP_SIZE, (255, 255, 255, 255))
    for (x, y), tile in zip(spots, tiles):
        image.alpha_composite(tile, (round(x * TILE - left), round(y * TILE - top)))
    return image


STAR_COLOR = (255, 140, 0)  # the orange star on the Film SF slides
SCREEN_TO_MAP = 2  # a text box's on-screen font size times this is its size on the PDF map


def star_points(x, y, r):
    """Corners of a five-pointed star centered on (x, y)."""
    pts = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        radius = r if i % 2 == 0 else r * 0.42
        pts.append((x + radius * math.cos(angle), y - radius * math.sin(angle)))
    return pts


def arrow_head(tip, tail, length=34, width=28):
    """Corners of a triangle pointing from tail to tip, with its point at tip."""
    (tx, ty), (bx, by) = tip, tail
    d = math.hypot(tx - bx, ty - by) or 1
    ux, uy = (tx - bx) / d, (ty - by) / d
    baseX, baseY = tx - ux * length, ty - uy * length
    return [(tx, ty), (baseX - uy * width / 2, baseY + ux * width / 2),
            (baseX + uy * width / 2, baseY - ux * width / 2)]


def text_box(overlay, x, y, text, font_px, border):
    """A text box like the app's: white, rounded, a soft drop shadow, centered on (x, y)."""
    font = ImageFont.load_default(size=font_px)
    draw = ImageDraw.Draw(overlay)
    box = draw.multiline_textbbox((x, y), text, font=font, anchor="mm", align="center", stroke_width=1)
    pad_x, pad_y = font_px * 0.75, font_px * 0.4
    rect = [box[0] - pad_x, box[1] - pad_y, box[2] + pad_x, box[3] + pad_y]
    radius = font_px * 0.45
    shadow = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([rect[0], rect[1] + 6, rect[2], rect[3] + 6], radius,
                                             fill=(0, 0, 0, 90))
    overlay.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(8)))
    draw.rounded_rectangle(rect, radius, fill=(255, 255, 255, 255), outline=border + (255,), width=4)
    # A thin stroke in the text color reads as semi-bold.
    draw.multiline_text((x, y), text, fill=(29, 29, 31, 255), font=font, anchor="mm", align="center",
                        stroke_width=1, stroke_fill=(29, 29, 31, 255))


def render_map(lines, labels=(), markers=(), arrows=(), basemap=OSM):
    """PNG bytes of curb lines, space counts, arrows and markers over a basemap (core.basemaps).
    lines: [(points [(lat, lon), ...], (r, g, b)), ...], each drawn whole, as it was drawn
    labels: [((lat, lon), text, (r, g, b)), ...]
    markers: [(kind "Star" or "Text box", (lat, lon), text, size_px, (r, g, b) border), ...]
    arrows: [(points, (r, g, b)), ...] with the head at the last point"""
    every = ([p for pts, _ in lines for p in pts] + [m[1] for m in markers]
             + [p for pts, _ in arrows for p in pts])
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
    base = render_tiles(basemap.url, zoom, cx, cy)

    def to_px(lat, lon):
        return ((tile_x(lon, zoom) - cx) * TILE + MAP_SIZE[0] / 2,
                (tile_y(lat, zoom) - cy) * TILE + MAP_SIZE[1] / 2)

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default(size=26)
    for pts, rgb in lines:
        px = [to_px(lat, lon) for lat, lon in pts]
        draw.line(px, fill=rgb + (255,), width=9, joint="curve")
        for x, y in (px[0], px[-1]):
            draw.ellipse([x - 9, y - 9, x + 9, y + 9], fill=rgb + (255,))
    # Space counts in white boxes along the lines, like the Film SF slides.
    for (lat, lon), label, rgb in labels:
        x, y = to_px(lat, lon)
        box = draw.textbbox((x, y), label, font=font, anchor="mm")
        draw.rectangle([box[0] - 8, box[1] - 6, box[2] + 8, box[3] + 6],
                       fill="white", outline=rgb + (255,), width=3)
        draw.text((x, y), label, fill="black", font=font, anchor="mm")
    for pts, rgb in arrows:
        px = [to_px(lat, lon) for lat, lon in pts]
        head = arrow_head(px[-1], px[-2])
        # Stop the shaft inside the head so its square end doesn't poke past the point.
        shaft_end = ((head[1][0] + head[2][0]) / 2, (head[1][1] + head[2][1]) / 2)
        draw.line(px[:-1] + [shaft_end], fill=rgb + (255,), width=7, joint="curve")
        draw.polygon(head, fill=rgb + (255,))
    for kind, (lat, lon), text, size, border in markers:
        x, y = to_px(lat, lon)
        if kind == "Star":
            draw.polygon(star_points(x, y, 26), fill=STAR_COLOR + (255,), outline=(90, 50, 0, 255), width=2)
        elif text.strip():
            text_box(overlay, x, y, text.strip(), int(size * SCREEN_TO_MAP), border)
    credit_font = ImageFont.load_default(size=20)
    box = draw.textbbox((MAP_SIZE[0] - 12, MAP_SIZE[1] - 10), basemap.credit, font=credit_font, anchor="rd")
    draw.rectangle([box[0] - 8, box[1] - 6, MAP_SIZE[0], MAP_SIZE[1]], fill=(255, 255, 255, 220))
    draw.text((MAP_SIZE[0] - 12, MAP_SIZE[1] - 10), basemap.credit, fill=(60, 60, 60, 255),
              font=credit_font, anchor="rd")

    out = io.BytesIO()
    Image.alpha_composite(base, overlay).convert("RGB").save(out, format="PNG")
    return out.getvalue()


@dataclass
class Box:
    """One info box in a page's side column, like the boxes on the Film SF slides."""
    rows: list           # [(label, text or [lines]), ...]; rows with no value are left out
    border: tuple = (120, 120, 128)  # (r, g, b)
    title: str = ""      # shown above the rows, in the border color
    width: float = 1


@dataclass
class Page:
    """One location of the request."""
    map_png: bytes
    boxes: list          # [Box, ...] down the side column
    scenes: list = field(default_factory=list)
    notes: str = ""
    legend: list = field(default_factory=list)  # [(label, (r, g, b)), ...] under the map


PAGE = landscape(letter)
MARGIN = 0.4 * inch
HEADER_H = 0.62 * inch
GAP = 0.18 * inch
MAP_COL_W = 6.35 * inch


def build_pdf(pages, project="", created=None):
    """PDF bytes, one landscape page per location: the map on the left and the info boxes
    down the right, like the Film SF slides."""
    created = created or date.today()
    styles = getSampleStyleSheet()
    body = styles["BodyText"].clone("body", fontSize=8.5, leading=10.5)
    small = body.clone("small", fontSize=7.5, leading=9, textColor=colors.grey)
    label = body.clone("label", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5)
    title = body.clone("title", fontName="Helvetica-Bold", fontSize=9.5, leading=12)
    scene = body.clone("scene", fontName="Helvetica-Bold", fontSize=12, leading=15)
    heading = styles["Heading2"].clone("heading", spaceBefore=0, spaceAfter=2)

    buf = io.BytesIO()
    width, height = PAGE
    inner_w, inner_h = width - 2 * MARGIN, height - 2 * MARGIN
    side_w = inner_w - MAP_COL_W - GAP
    body_h = inner_h - HEADER_H
    frames = [
        Frame(MARGIN, height - MARGIN - HEADER_H, inner_w, HEADER_H, id="header", showBoundary=0,
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
        Frame(MARGIN, MARGIN, MAP_COL_W, body_h, id="map", leftPadding=0, rightPadding=0,
              topPadding=0, bottomPadding=0),
        Frame(MARGIN + MAP_COL_W + GAP, MARGIN, side_w, body_h, id="side", leftPadding=0,
              rightPadding=0, topPadding=0, bottomPadding=0),
    ]
    doc = BaseDocTemplate(buf, pagesize=PAGE, title="SF Film Parking Request",
                          leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN)
    doc.addPageTemplates([PageTemplate(id="slide", frames=frames)])

    def hexcolor(rgb):
        return "#%02x%02x%02x" % rgb

    def cell(value):
        lines = value if isinstance(value, list) else [value]
        return Paragraph("<br/>".join(escape(v) for v in lines), body)

    def box_flowable(box):
        rows = [[Paragraph(f"{k.upper()}:", label), cell(v)] for k, v in box.rows if v]
        if box.title:
            rows.insert(0, [Paragraph(f'<font color="{hexcolor(box.border)}">{escape(box.title)}</font>',
                                      title), ""])
        if not rows:
            return None
        table = Table(rows, colWidths=[0.95 * inch, side_w - 0.95 * inch])
        style = [
            ("BOX", (0, 0), (-1, -1), 2 * box.width, colors.Color(*[c / 255 for c in box.border])),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c7c7cc")),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f2f5")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if box.title:
            style += [("SPAN", (0, 0), (-1, 0)), ("BACKGROUND", (0, 0), (-1, 0), colors.white)]
        table.setStyle(TableStyle(style))
        return table

    def key(entries):
        return "&nbsp;&nbsp;&nbsp;".join(
            f'<font color="{hexcolor(rgb)}">&#9632;</font> {escape(name)}' for name, rgb in entries)

    story = []
    for n, page in enumerate(pages, start=1):
        if n > 1:
            story.append(PageBreak())
        story += [
            Paragraph("Parking Request" + (f" &nbsp;&middot;&nbsp; {escape(project)}" if project else ""),
                      heading),
            Paragraph(f"Created {created:%B %-d, %Y}"
                      + (f" &nbsp;&middot;&nbsp; Page {n} of {len(pages)}" if len(pages) > 1 else ""), small),
            FrameBreak(),
        ]
        image = Image.open(io.BytesIO(page.map_png))
        left = [PdfImage(io.BytesIO(page.map_png), width=MAP_COL_W,
                         height=MAP_COL_W * image.height / image.width)]
        if page.legend:
            left += [Spacer(1, 3), Paragraph(key(page.legend), small)]
        if page.notes.strip():
            left += [Spacer(1, 6), Paragraph("<b>Notes:</b> " + escape(page.notes).replace("\n", "<br/>"), body)]
        story += [KeepInFrame(MAP_COL_W, body_h, left, mode="shrink"), FrameBreak()]

        right = []
        if page.scenes:
            scenes = Table([[Paragraph("<br/>".join(escape(s) for s in page.scenes), scene)]],
                           colWidths=[side_w])
            scenes.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor("#2b2b2b")),
                                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            right += [scenes, Spacer(1, 8)]
        for box in page.boxes:
            table = box_flowable(box)
            if table is not None:
                right += [table, Spacer(1, 8)]
        story.append(KeepInFrame(side_w, body_h, right or [Spacer(1, 1)], mode="shrink"))
    doc.build(story)
    return buf.getvalue()
