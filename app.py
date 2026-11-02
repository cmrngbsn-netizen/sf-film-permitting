"""SF Film Permit helper (beta).

Draw lines along the curbs you need for a shoot, at one or more locations. Each line is
split into one zone per block and named the way Film SF names them ("8 spaces on north
side 400-490 McAllister St"), then exported as a parking request PDF with one page per
location. Requests can be saved to a file and reopened.
Run locally with: streamlit run app.py
"""

import re
import sys
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path

import folium
import streamlit as st
from folium.plugins import Draw, Geocoder
from streamlit_folium import st_folium


def code_version():
    """Changes whenever the street code or data changes."""
    root = Path(__file__).parent
    files = [*root.glob("core/*.py"), *root.glob("data/*")]
    return max(f.stat().st_mtime for f in files)


# Streamlit Cloud reruns app.py after a push but keeps the old core/ modules loaded.
# When core/ or data/ changed, drop them so the imports below load the new code.
if getattr(sys, "_sf_core_version", None) != code_version():
    for name in [m for m in sys.modules if m == "core" or m.startswith("core.")]:
        del sys.modules[name]
    sys._sf_core_version = code_version()

from core.basemaps import DEFAULT as BASEMAP  # noqa: E402
from core.curbdata import CurbData  # noqa: E402
from core.curbs import CurbZoner, place_name  # noqa: E402
from core.drawings import merge  # noqa: E402
from core.pdf import Page, build_pdf, render_map  # noqa: E402
from core.request import (LINE_COLORS, LOCATION_FIELDS, MARKER_KINDS, REQUEST_FIELDS,  # noqa: E402
                          STAR, Line, Marker, Request, format_phone)
from core.streets import StreetIndex  # noqa: E402
from core.summary import METERS, PICTURE, USES, WORKING, Window, ZoneRequest, summarize  # noqa: E402

SF_CENTER = [37.7749, -122.4194]
SF_BOUNDS = [[37.70, -122.53], [37.84, -122.35]]  # keeps the map panned to the city
# Streamlit's named text colors closest to each line color, for colored labels on screen.
SCREEN_COLORS = {"Red": "red", "Blue": "blue", "Green": "green", "Orange": "orange",
                 "Purple": "violet", "Black": "gray"}
COLOR_NAMES = {hex_: name for name, hex_ in LINE_COLORS.items()}

st.set_page_config(page_title="SF Film Parking Request", layout="wide")
st.title("SF Film Parking Request")


# Cached street objects are keyed on code_version() too, so they're rebuilt with the new code.
@st.cache_resource
def _zoner(version):
    return CurbZoner(StreetIndex())


@st.cache_resource
def _curb_data(version):
    return CurbData()


def zoner():
    return _zoner(code_version())


def curb_data():
    return _curb_data(code_version())


@st.cache_data(show_spinner="Drawing the map for the PDF...")
def pdf_map(lines, markers):
    return render_map([(list(pts), rgb(color), label) for pts, color, label in lines],
                      list(markers), BASEMAP)


def rgb(hex_color):
    """"#d62728" -> (214, 39, 40)."""
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def star_icon():
    return folium.DivIcon(icon_size=(28, 28), icon_anchor=(14, 14),
                          html='<div style="font-size:28px;line-height:28px;color:#ff8c00;'
                               'text-shadow:0 0 2px #5a3200">★</div>')


def text_icon(text):
    """A white box with a dark border, centered on the marker's point."""
    return folium.DivIcon(icon_size=(200, 40), icon_anchor=(100, 20),
                          html='<div style="width:200px;text-align:center"><span style="'
                               'display:inline-block;background:white;color:black;'
                               'border:2px solid #282828;padding:2px 6px;font:bold 12px sans-serif;'
                               f'white-space:pre">{escape_html(text) or "Text box"}</span></div>')


def escape_html(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def add_marker(group, marker):
    icon = star_icon() if marker.kind == STAR else text_icon(marker.text)
    folium.Marker(marker.point, icon=icon).add_to(group)


def add_basemap(m, basemap):
    for i, url in enumerate(basemap.layers):
        folium.TileLayer(url, attr=basemap.credit if i == 0 else " ", max_zoom=20,
                         max_native_zoom=basemap.max_zoom).add_to(m)


def base_map(**kwargs):
    """A map of SF on the basemap."""
    m = folium.Map(tiles=None, min_zoom=12, max_zoom=20, max_bounds=True,
                   min_lat=SF_BOUNDS[0][0], min_lon=SF_BOUNDS[0][1],
                   max_lat=SF_BOUNDS[1][0], max_lon=SF_BOUNDS[1][1], **kwargs)
    add_basemap(m, BASEMAP)
    return m


def fit(m, points):
    m.fit_bounds([[min(p[0] for p in points), min(p[1] for p in points)],
                  [max(p[0] for p in points), max(p[1] for p in points)]], padding=(30, 30))


def drawing_map(lines, markers, color):
    """The map to draw on, starting with a location's saved lines and markers, which stay
    editable. New lines are drawn in `color`."""
    m = base_map(location=SF_CENTER, zoom_start=14)
    saved = folium.FeatureGroup(name="Curb lines").add_to(m)
    for line in lines:
        folium.PolyLine(line.points, color=line.color, weight=5).add_to(saved)
    for marker in markers:
        add_marker(saved, marker)
    every = [p for line in lines for p in line.points] + [mk.point for mk in markers]
    if every:
        fit(m, every)
    # The line tool for curbs and the marker tool for stars and text boxes.
    Draw(
        feature_group=saved,
        show_geometry_on_click=False,
        draw_options={
            "polyline": {"shapeOptions": {"color": color, "weight": 5}},
            "marker": True,
            "polygon": False, "rectangle": False, "circle": False, "circlemarker": False,
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(m)
    # Address search, limited to San Francisco (OpenStreetMap's Nominatim).
    Geocoder(position="topright", add_marker=False, zoom=18, provider_options={
        "geocodingQueryParams": {"viewbox": "-122.53,37.84,-122.35,37.70", "bounded": 1,
                                 "countrycodes": "us"}}).add_to(m)
    return m


def zones_map(lines, markers):
    """Reviewed zones: one colored line per zone with its space count, plus markers."""
    m = base_map()
    for pts, color, label in lines:
        folium.PolyLine(pts, color=color, weight=7, opacity=0.9).add_to(m)
        folium.Marker(pts[len(pts) // 2], icon=folium.DivIcon(
            icon_size=(30, 20), icon_anchor=(15, 10),
            html=f'<div style="background:white;color:black;border:2px solid {color};'
                 f'width:30px;text-align:center;font:bold 12px sans-serif">{label}</div>',
        )).add_to(m)
    for kind, point, text in markers:
        add_marker(m, Marker(point, kind, text))
    fit(m, [p for pts, _, _ in lines for p in pts] + [point for _, point, _ in markers])
    return m


def as_date(v):
    """A table cell as a date: the editor can hand back dates, timestamps or ISO text."""
    if v is None or v == "" or v != v:  # v != v catches NaN/NaT
        return None
    if isinstance(v, str):
        return datetime.fromisoformat(v).date()
    return v.date() if isinstance(v, datetime) or hasattr(v, "to_pydatetime") else v


def as_time(v):
    """A table cell as a time of day, from a time or "HH:MM[:SS]" text."""
    if v is None or v == "" or v != v:
        return None
    return time.fromisoformat(v) if isinstance(v, str) else v


def zone_id(z):
    """Stable name for a zone, so edits survive drawing more lines."""
    return f"{z.cnn}:{z.side_sign}:{round(z.along_m[0] / 5)}"


def snapshot(key, build):
    """The editor's starting rows, fixed while its key stays the same. Streamlit applies a
    data editor's edits to the rows it was first given, so those rows must not change."""
    store = st.session_state.setdefault("snapshots", {})
    if key not in store:
        store[key] = build()
    return store[key]


def bound_text(label, store, name, key, area=False, formatter=None, **kwargs):
    """A text box whose value lives in store[name]; `formatter` tidies what was typed."""
    if key not in st.session_state:
        st.session_state[key] = store.get(name, "")
    if formatter:
        kwargs["on_change"] = lambda: st.session_state.__setitem__(key, formatter(st.session_state[key]))
    (st.text_area if area else st.text_input)(label, key=key, **kwargs)
    store[name] = st.session_state[key].strip() if not area else st.session_state[key]


def zone_defaults(z, color):
    """Curb, meters and spaces filled in from SFMTA data; a blue line starts as Picture."""
    info = curb_data().lookup(z)
    return {"Curb": info.describe(), "Meters": "Metered" if info.metered else "Non-metered",
            "Spaces": info.suggested_spaces(z.length_ft),
            "Use": PICTURE if color == LINE_COLORS["Blue"] else WORKING}


def location_zones(loc):
    """A location's zones, their ids, line colors, and rows (city data plus the user's edits)."""
    pairs = [(z, line.color) for line in loc.lines for z in zoner().zones(line.points)]
    zones = [z for z, _ in pairs]
    colors = [c for _, c in pairs]
    ids = [zone_id(z) for z in zones]
    rows = [{**zone_defaults(z, c), **loc.zones.get(zid, {})} for z, c, zid in zip(zones, colors, ids)]
    return zones, ids, colors, rows


def location_page(req, loc):
    """(map lines, markers, table fields, legend) for one location's page, or None if it
    has no zones."""
    zones, ids, colors, rows = location_zones(loc)
    if not zones:
        return None
    asks = [ZoneRequest(z.block, z.side, int(r["Spaces"] or 1), r["Use"], r["Meters"],
                        loc.windows.get(zid, []), r["Curb"] or "")
            for z, zid, r in zip(zones, ids, rows)]
    drawn = tuple((tuple(z.points), c, str(a.spaces)) for z, c, a in zip(zones, colors, asks))
    markers = tuple((m.kind, tuple(m.point), m.text) for m in loc.markers
                    if m.kind == STAR or m.text.strip())
    # The legend says what each line color was used for on this page.
    legend = {}
    for c, a in zip(colors, asks):
        legend.setdefault(c, [])
        if a.use not in legend[c]:
            legend[c].append(a.use)
    legend = [(" / ".join(uses), c) for c, uses in legend.items()]
    # Same order as the Film SF slides: who, where, then the parking ask.
    fields = {
        "Production": req.info["Production"],
        "Contact": loc.info["Contact"],
        "Phone": loc.info["Phone"],
        "Email": req.info["Email"],
        "Film SF permit #": req.info["Film SF permit #"],
        "Location": loc.info["Location"],
        "Scene": loc.info["Scene"],
        **summarize(asks),
    }
    return drawn, markers, fields, legend


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# The request being worked on. `gen` changes when a saved request is opened, so every
# widget starts fresh from the opened file instead of keeping what was on screen.
if "request" not in st.session_state:
    st.session_state.request = Request()
    st.session_state.gen = 0
req = st.session_state.request
gen = st.session_state.gen

with st.sidebar:
    st.header("Request file")
    upload = st.file_uploader("Open a saved request", type="json", key=f"g{gen}-open")
    if upload is not None:
        try:
            opened = Request.from_json(upload.getvalue().decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            st.error(f"Couldn't open that file: {e}")
        else:
            st.session_state.request = opened
            st.session_state.gen += 1
            st.session_state.snapshots = {}
            st.rerun()

# Which location is open. Kept in plain session state, not in a picker widget: a picker
# resets itself when a location is renamed, which would switch locations mid-edit.
if st.session_state.get("current") not in [loc.id for loc in req.locations]:
    st.session_state.current = req.locations[0].id


def open_location(loc_id):
    st.session_state.current = loc_id


def add_location():
    st.session_state.current = req.add_location().id


def remove_location():
    req.remove_location(st.session_state.current)
    st.session_state.current = req.locations[0].id


with st.expander("Shoot info (shared by all locations)", expanded=True):
    cols = st.columns(len(REQUEST_FIELDS))
    for col, name in zip(cols, REQUEST_FIELDS):
        with col:
            bound_text(name, req.info, name, f"g{gen}-req-{name}")

st.markdown("**Locations** (one PDF page each)")
buttons = st.columns(len(req.locations) + 2)
for col, (n, place) in zip(buttons, enumerate(req.locations, start=1)):
    with col:
        st.button(f"{n} · {place.title}", key=f"g{gen}-open-{place.id}", use_container_width=True,
                  type="primary" if place.id == st.session_state.current else "secondary",
                  on_click=open_location, args=(place.id,))
with buttons[-2]:
    st.button("➕ Add location", on_click=add_location, use_container_width=True)
with buttons[-1]:
    with st.popover("Remove", use_container_width=True):
        st.write("Remove the open location and its lines?")
        st.button("Yes, remove it", on_click=remove_location, type="primary")

loc = next(loc for loc in req.locations if loc.id == st.session_state.current)

map_col, side_col = st.columns([3, 2])

with map_col:
    color_col, kind_col = st.columns([3, 2])
    with color_col:
        color_name = st.radio("Line color", list(LINE_COLORS), horizontal=True, key="line_color",
                              format_func=lambda n: f":{SCREEN_COLORS[n]}[●] {n}")
    with kind_col:
        marker_kind = st.radio("Marker tool adds", MARKER_KINDS, horizontal=True, key="marker_kind",
                               format_func=lambda k: "★ Star" if k == STAR else "▭ Text box")
    color = LINE_COLORS[color_name]

# The map starts from the open location's saved lines and markers. It is only rebuilt when
# a different location is opened or a tool setting changes (rebuilding resets the view);
# otherwise what the user draws comes back through all_drawings.
setup = (gen, loc.id, color, marker_kind)
if st.session_state.get("map_setup") != setup:
    st.session_state.map_setup = setup
    st.session_state.map_opens = st.session_state.get("map_opens", 0) + 1
    st.session_state.map_shapes = (list(loc.lines), list(loc.markers))

with map_col:
    st.caption("**Curbs:** pick a color, click the line tool (left side of the map), click along "
               "the curb, then click the last point again (or **Finish**). A line can turn corners. "
               "**Stars and text boxes:** pick one above, click the marker tool, click the map; "
               "type a text box's words in the table below. Use the pencil to move things and the "
               "trash can to delete them. Search for an address with the magnifier (top right).")
    result = st_folium(drawing_map(*st.session_state.map_shapes, color), height=600,
                       use_container_width=True, returned_objects=["all_drawings"],
                       key=f"draw-{st.session_state.map_opens}")

drawings = (result or {}).get("all_drawings")
if drawings is not None:  # None until the user draws, edits or deletes on this map
    geoms = [d.get("geometry") or {} for d in drawings]
    loc.lines = merge(loc.lines, [[(lat, lon) for lon, lat in g["coordinates"]]
                                  for g in geoms if g.get("type") == "LineString"],
                      lambda line: line.points, lambda line, pts: replace(line, points=pts),
                      lambda pts: Line(pts, color))
    loc.markers = merge(loc.markers, [(g["coordinates"][1], g["coordinates"][0])
                                      for g in geoms if g.get("type") == "Point"],
                        lambda mk: mk.point, lambda mk, pt: replace(mk, point=pt),
                        lambda pt: Marker(pt, marker_kind))
zones, ids, colors, base_rows = location_zones(loc)

# Until the user types their own, the Location name follows the lines ("Grant @ Washington").
suggested = place_name(zones)
name_key = f"g{gen}-{loc.id}-Location"
if loc.auto_name and suggested and st.session_state.get(name_key, loc.info["Location"]) in (
        "", loc.info["Location"]) and loc.info["Location"] != suggested:
    st.session_state[name_key] = loc.info["Location"] = suggested
    st.rerun()  # so the location buttons above show the new name

with side_col:
    for name in LOCATION_FIELDS:
        placeholder = {"Location": "Filled in from the first line you draw",
                       "Scene": "e.g. INT City Hall - SHOOT",
                       "Phone": "(415) 555-0100"}.get(name)
        bound_text(name, loc.info, name, f"g{gen}-{loc.id}-{name}", placeholder=placeholder,
                   formatter=format_phone if name == "Phone" else None)
        if name == "Location" and loc.auto_name and suggested:
            st.caption("Filled in from your lines. Press Enter to keep it, or type your own.")
    if loc.info["Location"] != suggested:
        loc.auto_name = False  # the user typed their own name
    store = {"notes": loc.notes}
    bound_text("Notes", store, "notes", f"g{gen}-{loc.id}-notes", area=True, height=100,
               placeholder="Anything the permit office should know about this location")
    loc.notes = store["notes"]
    if not loc.lines:
        st.write("No curb lines drawn at this location yet.")
    elif not zones:
        st.warning("The line isn't close enough to a street. Draw it along the curb.")
    else:
        st.write(f"{len(zones)} curb zone{'s' if len(zones) != 1 else ''} found. "
                 "Review them below the map.")

if loc.markers:
    st.subheader("Stars & text boxes")
    st.caption("Type the words for each text box (e.g. WORKING VEHICLES, INT City Hall - SHOOT). "
               "Empty text boxes are left off the PDF.")
    marks_key = f"g{gen}-{loc.id}-marks-{len(loc.markers)}"
    marks = st.data_editor(
        snapshot(marks_key, lambda: [{"#": i, "Kind": m.kind, "Text": m.text}
                                     for i, m in enumerate(loc.markers, start=1)]),
        key=marks_key, hide_index=True, use_container_width=True, disabled=["#"],
        column_config={"Kind": st.column_config.SelectboxColumn(options=MARKER_KINDS, required=True),
                       "Text": st.column_config.TextColumn(width="large")},
    )
    loc.markers = [replace(m, kind=row["Kind"], text=row["Text"] or "")
                   for m, row in zip(loc.markers, marks)]

if zones:
    labels = [f"{i} · {z.block} ({z.side})" for i, z in enumerate(zones, start=1)]
    zones_key = f"g{gen}-{loc.id}-{hash(tuple(ids))}"

    st.divider()
    st.subheader("Curb zones")
    st.caption(f"One row per block. **Curb**, **Meters** and **Spaces** are filled in from SFMTA "
               f"meter and color-curb data (updated {curb_data().built}): one space per meter on "
               f"metered curb, otherwise 20 ft per space minus driveways. Change anything you know "
               f"better.")

    def zone_rows():
        return [{"Zone": i, "Block": z.block, "Side": z.side, "Between": z.between,
                 "Length (ft)": round(z.length_ft), **row}
                for i, (z, row) in enumerate(zip(zones, base_rows), start=1)]

    edited = st.data_editor(
        snapshot(f"zones-{zones_key}", zone_rows), key=f"zones-{zones_key}", hide_index=True,
        use_container_width=True,
        column_order=["Zone", "Block", "Side", "Between", "Length (ft)", "Curb", "Meters",
                      "Spaces", "Use"],
        disabled=["Zone", "Block", "Side", "Between", "Length (ft)"],
        column_config={
            "Curb": st.column_config.TextColumn(width="large"),
            "Spaces": st.column_config.NumberColumn(min_value=1, step=1),
            "Use": st.column_config.SelectboxColumn(options=USES, required=True),
            "Meters": st.column_config.SelectboxColumn(options=METERS, required=True),
        },
    )
    for zid, row in zip(ids, edited):
        loc.zones[zid] = {k: row[k] for k in ("Curb", "Meters", "Spaces", "Use")}

    st.subheader("Dates & hours")
    st.caption("One row per zone to start. To book a zone for more than one day or time window, "
               "add a row at the bottom of the table and pick its zone. An end time earlier than "
               "the start means the next day.")

    def schedule_rows():
        return [{"Zone": label, "Date": w.date, "Start": w.start, "End": w.end}
                for label, zid in zip(labels, ids) for w in loc.windows.get(zid) or [Window()]]

    schedule = st.data_editor(
        snapshot(f"schedule-{zones_key}", schedule_rows), key=f"schedule-{zones_key}",
        hide_index=True, use_container_width=True, num_rows="dynamic",
        column_config={
            "Zone": st.column_config.SelectboxColumn(options=labels, required=True, width="large"),
            "Date": st.column_config.DateColumn(format="ddd MM/DD/YY"),
            "Start": st.column_config.TimeColumn(format="h:mm A", step=900),
            "End": st.column_config.TimeColumn(format="h:mm A", step=900),
        },
    )
    for zid in ids:
        loc.windows[zid] = []
    for row in schedule:
        if row.get("Zone") in labels:
            loc.windows[ids[labels.index(row["Zone"])]].append(
                Window(as_date(row.get("Date")), as_time(row.get("Start")), as_time(row.get("End"))))

    drawn, markers, fields, legend = location_page(req, loc)
    st.divider()
    map_col2, list_col = st.columns([3, 2])
    with map_col2:
        st_folium(zones_map(drawn, markers), height=450, use_container_width=True,
                  returned_objects=[], key="reviewed")
        st.caption(" · ".join(f":{SCREEN_COLORS[COLOR_NAMES.get(c, 'Black')]}[■] {label}"
                              for label, c in legend))
    with list_col:
        st.markdown("#### This location's page")
        for name, value in fields.items():
            if not value:
                continue
            if isinstance(value, list):
                st.markdown(f"**{name}:**" + "".join(f"\n- {v}" for v in value))
            else:
                st.markdown(f"**{name}:** {value}")

# The whole request: one PDF page per location that has zones.
st.divider()
pages = [(loc_, page) for loc_ in req.locations if (page := location_page(req, loc_))]
project = req.info["Project"]
if pages:
    st.write(f"**PDF:** {len(pages)} page{'s' if len(pages) != 1 else ''}, one per location: "
             + ", ".join(loc_.title for loc_, _ in pages))
    st.download_button(
        "Download PDF", type="primary", mime="application/pdf",
        file_name=f"{slug(project) or 'sf-parking-request'}-{date.today():%Y-%m-%d}.pdf",
        data=build_pdf([Page(pdf_map(drawn_, markers_), fields_, loc_.notes,
                             [(label, rgb(c)) for label, c in legend_])
                        for loc_, (drawn_, markers_, fields_, legend_) in pages], [], project=project),
    )
else:
    st.write("Draw curb lines at a location to build the PDF.")

with st.sidebar:
    st.download_button("Save request", req.to_json(), mime="application/json",
                       file_name=f"{slug(project) or 'sf-parking-request'}.json",
                       help="Download everything entered so far, to open again later.",
                       use_container_width=True)
    st.caption("Nothing is kept when the page is closed or refreshed, so save the request "
               "to a file to come back to it.")
