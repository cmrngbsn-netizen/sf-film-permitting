"""SF Film Permit helper (beta).

Draw lines along the curbs you need for a shoot, at one or more locations. Each line is
split into one zone per block and named the way Film SF names them ("8 spaces on north
side 400-490 McAllister St"), then exported as a parking request PDF with one page per
location. Requests can be saved to a file and reopened.
Run locally with: streamlit run app.py
"""

import re
import sys
from datetime import date, datetime, time
from pathlib import Path

import folium
import streamlit as st
from folium.plugins import Draw
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
from core.curbs import CurbZoner  # noqa: E402
from core.pdf import Page, build_pdf, render_map  # noqa: E402
from core.request import LOCATION_FIELDS, REQUEST_FIELDS, Request  # noqa: E402
from core.streets import StreetIndex  # noqa: E402
from core.summary import METERS, PICTURE, USES, WORKING, Window, ZoneRequest, summarize  # noqa: E402

SF_CENTER = [37.7749, -122.4194]
SF_BOUNDS = [[37.70, -122.53], [37.84, -122.35]]  # keeps the map panned to the city
USE_COLORS = {WORKING: (214, 39, 40), PICTURE: (31, 119, 180)}

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
def pdf_map(lines):
    return render_map([(list(pts), rgb, label) for pts, rgb, label in lines], BASEMAP)


def hex_color(rgb):
    return "#%02x%02x%02x" % rgb


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


def drawing_map(lines):
    """The map to draw on, starting with a location's saved lines, which stay editable."""
    m = base_map(location=SF_CENTER, zoom_start=14)
    saved = folium.FeatureGroup(name="Curb lines").add_to(m)
    for line in lines:
        folium.PolyLine(line, color="#d62728", weight=5).add_to(saved)
    if lines:
        fit(m, [p for line in lines for p in line])
    # Only the line tool: click along the curb, click the last point again to finish.
    Draw(
        feature_group=saved,
        show_geometry_on_click=False,
        draw_options={
            "polyline": {"shapeOptions": {"color": "#d62728", "weight": 5}},
            "polygon": False, "rectangle": False, "circle": False,
            "marker": False, "circlemarker": False,
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(m)
    return m


def zones_map(lines):
    """Reviewed zones: one colored line per zone with its space count."""
    m = base_map()
    for pts, rgb, label in lines:
        folium.PolyLine(pts, color=hex_color(rgb), weight=7, opacity=0.9).add_to(m)
        folium.Marker(pts[len(pts) // 2], icon=folium.DivIcon(
            icon_size=(30, 20), icon_anchor=(15, 10),
            html=f'<div style="background:white;color:black;border:2px solid {hex_color(rgb)};'
                 f'width:30px;text-align:center;font:bold 12px sans-serif">{label}</div>',
        )).add_to(m)
    fit(m, [p for pts, _, _ in lines for p in pts])
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


def bound_text(label, store, name, key, area=False, **kwargs):
    """A text box whose value lives in store[name]."""
    if key not in st.session_state:
        st.session_state[key] = store.get(name, "")
    (st.text_area if area else st.text_input)(label, key=key, **kwargs)
    store[name] = st.session_state[key].strip() if not area else st.session_state[key]


def zone_defaults(z):
    """Curb, meters and spaces filled in from SFMTA data."""
    info = curb_data().lookup(z)
    return {"Curb": info.describe(), "Meters": "Metered" if info.metered else "Non-metered",
            "Spaces": info.suggested_spaces(z.length_ft), "Use": WORKING}


def location_zones(loc):
    """A location's zones, their ids, and their rows (city data plus the user's edits)."""
    zones = [z for line in loc.lines for z in zoner().zones(line)]
    ids = [zone_id(z) for z in zones]
    rows = [{**zone_defaults(z), **loc.zones.get(zid, {})} for z, zid in zip(zones, ids)]
    return zones, ids, rows


def location_page(req, loc):
    """(map lines, table fields) for one location's page, or None if it has no zones."""
    zones, ids, rows = location_zones(loc)
    if not zones:
        return None
    asks = [ZoneRequest(z.block, z.side, int(r["Spaces"] or 1), r["Use"], r["Meters"],
                        loc.windows.get(zid, []), r["Curb"] or "")
            for z, zid, r in zip(zones, ids, rows)]
    drawn = tuple((tuple(z.points), USE_COLORS[a.use], str(a.spaces)) for z, a in zip(zones, asks))
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
    return drawn, fields


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
        st.button(f"{n}. {place.title}", key=f"g{gen}-open-{place.id}", use_container_width=True,
                  type="primary" if place.id == st.session_state.current else "secondary",
                  on_click=open_location, args=(place.id,))
with buttons[-2]:
    st.button("➕ Add location", on_click=add_location, use_container_width=True)
with buttons[-1]:
    with st.popover("Remove", use_container_width=True):
        st.write("Remove the open location and its lines?")
        st.button("Yes, remove it", on_click=remove_location, type="primary")

loc = next(loc for loc in req.locations if loc.id == st.session_state.current)

# Each time a location is opened, its map starts from that location's saved lines. While
# it stays open, the map is left alone (rebuilding it would reset the view) and what the
# user draws comes back through all_drawings.
if st.session_state.get("shown") != (gen, loc.id):
    st.session_state.shown = (gen, loc.id)
    st.session_state.map_opens = st.session_state.get("map_opens", 0) + 1
    st.session_state.map_lines = [list(line) for line in loc.lines]

map_col, side_col = st.columns([3, 2])

with map_col:
    st.caption("Click the line tool on the left of the map, then click along the curb you need. "
               "Click the last point again (or **Finish**) to end the line. Draw one line per "
               "stretch of curb; a line can turn corners. Use the pencil to move a line and the "
               "trash can to delete one.")
    result = st_folium(drawing_map(st.session_state.map_lines), height=600,
                       use_container_width=True, returned_objects=["all_drawings"],
                       key=f"draw-{st.session_state.map_opens}")

drawings = (result or {}).get("all_drawings")
if drawings is not None:  # None until the user draws, edits or deletes on this map
    loc.lines = [[(lat, lon) for lon, lat in d["geometry"]["coordinates"]]
                 for d in drawings if d.get("geometry", {}).get("type") == "LineString"]
zones, ids, base_rows = location_zones(loc)

with side_col:
    for name in LOCATION_FIELDS:
        placeholder = {"Location": "e.g. City Hall, McAllister @ Larkin & Polk",
                       "Scene": "e.g. INT City Hall - SHOOT"}.get(name)
        bound_text(name, loc.info, name, f"g{gen}-{loc.id}-{name}", placeholder=placeholder)
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

    drawn, fields = location_page(req, loc)
    st.divider()
    map_col2, list_col = st.columns([3, 2])
    with map_col2:
        st_folium(zones_map(drawn), height=450, use_container_width=True,
                  returned_objects=[], key="reviewed")
        st.caption(f":red[■] {WORKING} · :blue[■] {PICTURE}")
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
        data=build_pdf([Page(pdf_map(drawn_), fields_, loc_.notes) for loc_, (drawn_, fields_) in pages],
                       list(USE_COLORS.items()), project=project),
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
