"""SF Film Permit helper (beta).

Draw lines along the curbs you need for a shoot, at one or more locations. Each line is
split into one zone per block and named the way Film SF names them ("400-490 McAllister
St, north side"), then exported as a parking request PDF with one page per
location. Requests can be saved to a file and reopened.
Run locally with: streamlit run app.py
"""

import io
import re
import sys
from datetime import date, datetime, time
from pathlib import Path

import folium
import pandas as pd
import pypdfium2
import streamlit as st
import streamlit.components.v1 as components
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

from core.basemaps import OSM  # noqa: E402
from core.curbdata import CurbData  # noqa: E402
from core.bulk import EXAMPLE_BLOCKS, StreetRoutes, plan  # noqa: E402
from core.curbs import CurbZoner, block_labels, place_name, place_names  # noqa: E402
from core.map_tools import MapTools  # noqa: E402
from core.methods import methods  # noqa: E402
from core.pdf import Box, Page, build_pdf, render_map  # noqa: E402
from core.request import (DEFAULT_COLOR, LINE_COLORS, REQUEST_FIELDS,  # noqa: E402
                          STAR, TEXT, TEXT_COLOR, TEXT_PX, Arrow, Line, Marker, Request,
                          format_phone, text_size)
from core.streets import StreetIndex  # noqa: E402
from core.summary import (METERS, PICTURE, USES, WORKING, Window, ZoneRequest,  # noqa: E402
                          dates_and_hours, summarize)

SF_CENTER = [37.7749, -122.4194]
SF_BOUNDS = [[37.70, -122.53], [37.84, -122.35]]  # keeps the map panned to the city
COLOR_NAMES = {hex_: name for name, hex_ in LINE_COLORS.items()}

st.set_page_config(page_title="SF Film Parking Request", layout="wide", initial_sidebar_state="collapsed")


# Cached street objects are keyed on code_version() too, so they're rebuilt with the new code.
@st.cache_resource
def _zoner(version):
    return CurbZoner(StreetIndex())


@st.cache_resource
def _curb_data(version):
    return CurbData()


def zoner():
    return _zoner(code_version())


@st.cache_resource
def _routes(version):
    return StreetRoutes(zoner().index)


def routes():
    return _routes(code_version())


def curb_data():
    return _curb_data(code_version())


@st.cache_data(show_spinner="Drawing the map for the PDF...")
def pdf_map(lines, labels, arrows, markers):
    return render_map([(list(pts), rgb(color)) for pts, color in lines],
                      [(point, text, rgb(color)) for point, text, color in labels],
                      [(kind, point, text, size, rgb(color)) for kind, point, text, size, color in markers],
                      [(list(pts), rgb(color)) for pts, color in arrows])


@st.cache_data(show_spinner="Drawing the page previews...")
def pdf_pages(pdf):
    """Each PDF page as a PNG, for the preview."""
    doc = pypdfium2.PdfDocument(pdf)
    out = []
    for page in doc:
        buf = io.BytesIO()
        page.render(scale=1.6).to_pil().save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


def rgb(hex_color):
    """"#d62728" -> (214, 39, 40)."""
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def base_map(**kwargs):
    """A map of SF on the basemap."""
    m = folium.Map(tiles=None, min_zoom=12, scroll_wheel_zoom=False, max_zoom=20, max_bounds=True,
                   min_lat=SF_BOUNDS[0][0], min_lon=SF_BOUNDS[0][1],
                   max_lat=SF_BOUNDS[1][0], max_lon=SF_BOUNDS[1][1], **kwargs)
    folium.TileLayer(OSM.url, attr=OSM.credit, max_zoom=20, max_native_zoom=OSM.max_zoom).add_to(m)
    return m


def fit(m, points):
    # Capped at street level, so one short line doesn't fill the whole map.
    m.fit_bounds([[min(p[0] for p in points), min(p[1] for p in points)],
                  [max(p[0] for p in points), max(p[1] for p in points)]], padding=(30, 30), max_zoom=18)


def drawing_map(lines, arrows, markers):
    """The map to draw on, starting with a location's saved lines, arrows and markers, which
    stay editable. Its tools are in a panel beside it (core.map_tools)."""
    # Quarter-step zoom, for the zoom slider beside the map.
    m = base_map(location=SF_CENTER, zoom_start=14, zoom_control=False, zoom_snap=0.25, zoom_delta=0.5)
    saved = folium.FeatureGroup(name="Drawing").add_to(m)
    # Order matters: core.map_tools matches these to their saved details in this order.
    for line in lines:
        folium.PolyLine(line.points, color=line.color, weight=5).add_to(saved)
    for arrow in arrows:
        folium.PolyLine(arrow.points, color=arrow.color, weight=4, line_cap="butt").add_to(saved)
    for marker in markers:
        folium.Marker(marker.point).add_to(saved)  # its look comes from core.map_tools
    every = ([p for line in lines for p in line.points] + [p for a in arrows for p in a.points]
             + [mk.point for mk in markers])
    if every:
        fit(m, every)
    # Leaflet's drawing plugin, for its line and marker tools. Its own toolbar is hidden;
    # core.map_tools starts the tools from the panel beside the map.
    Draw(
        feature_group=saved,
        show_geometry_on_click=False,
        draw_options={"polyline": True, "marker": True, "polygon": False, "rectangle": False,
                      "circle": False, "circlemarker": False},
        edit_options={"edit": False, "remove": False},
    ).add_to(m)
    m.add_child(MapTools(saved, lines, arrows, markers, LINE_COLORS, TEXT_COLOR, TEXT_PX))
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


def window_columns():
    """Date, Start and End columns for a dates-and-hours table."""
    return {"Date": st.column_config.DateColumn(format="ddd MM/DD/YY"),
            "Start": st.column_config.TimeColumn(format="h:mm a", step=900),
            "End": st.column_config.TimeColumn(format="h:mm a", step=900)}


def window_rows(windows):
    """Date, Start and End rows for a table, with its columns even when there are no rows yet."""
    return pd.DataFrame([{"Date": w.date, "Start": w.start, "End": w.end} for w in windows],
                        columns=["Date", "Start", "End"])


def zone_id(z):
    """Stable name for a zone, so edits survive drawing more lines."""
    if z.parts:
        return "+".join(zone_id(p) for p in z.parts)
    return f"{z.cnn}:{z.side_sign}:{round(z.along_m[0] / 5)}"


def line_zones(points):
    """The curb zones along a drawn line, one per block side."""
    return curb_data().join_pieces(zoner().zones(points))


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


def adopt_pieces(loc, z, color, zid):
    """Requests saved before pieces of a block side were joined have edits on each piece; the
    joined zone starts from them."""
    pieces = [(p, zone_id(p)) for p in z.parts]
    if zid in loc.zones or not any(pid in loc.zones for _, pid in pieces):
        return
    rows = [{**zone_defaults(p, color), **loc.zones.get(pid, {})} for p, pid in pieces]
    loc.zones[zid] = {"Meters": rows[0]["Meters"], "Use": rows[0]["Use"],
                      "Spaces": sum(int(r["Spaces"] or 0) for r in rows)}
    times = next((loc.windows[pid] for _, pid in pieces if pid in loc.windows), None)
    if times is not None:
        loc.windows[zid] = times


def location_zones(loc):
    """A location's zones, their ids, line colors, and rows (city data plus the user's edits)."""
    pairs = [(z, line.color) for line in loc.lines for z in line_zones(line.points)]
    zones = [z for z, _ in pairs]
    colors = [c for _, c in pairs]
    ids = [zone_id(z) for z in zones]
    for z, c, zid in zip(zones, colors, ids):
        adopt_pieces(loc, z, c, zid)
    rows = [{**zone_defaults(z, c), **loc.zones.get(zid, {})} for z, c, zid in zip(zones, colors, ids)]
    return zones, ids, colors, rows


WHO_BORDER = (214, 39, 40)     # the red "who" box on the Film SF slides
WHERE_BORDER = (120, 120, 128)  # the grey "where" table


def location_page(req, loc):
    """(map lines, space counts, arrows, markers, info boxes, legend) for one location's page,
    or None if it has no zones."""
    zones, ids, colors, rows = location_zones(loc)
    if not zones:
        return None
    asks = [ZoneRequest(z.block, z.side, int(r["Spaces"] or 1), r["Use"], r["Meters"], loc.windows_for(zid))
            for z, zid, r in zip(zones, ids, rows)]
    # Each line whole, as it was drawn, with one count per block side it runs along.
    drawn, labels, spaces = [], [], iter(a.spaces for a in asks)
    for line in loc.lines:
        on_line = line_zones(line.points)
        if on_line:
            drawn.append((tuple(line.points), line.color))
            labels += [(point, str(total), line.color)
                       for point, total in block_labels(on_line, [next(spaces) for _ in on_line])]
    markers = tuple((m.kind, tuple(m.point), m.text, m.size, m.color) for m in loc.markers
                    if m.kind == STAR or m.text.strip())
    arrows = tuple((tuple(a.points), a.color) for a in loc.arrows)
    # The legend says what each line color was used for on this page.
    legend = {}
    for c, a in zip(colors, asks):
        legend.setdefault(c, [])
        if a.use not in legend[c]:
            legend[c].append(a.use)
    legend = [(" / ".join(uses), c) for c, uses in legend.items()]
    # The boxes from the Film SF slides: who (red), where (grey), then one per line color
    # when the colors have different dates and hours.
    summary = summarize(asks, colors)
    boxes = [
        Box([("Production", req.info["Production"]), ("Dates & hours", summary["Dates & hours"]),
             ("Contact", loc.info["Contact"]), ("Phone", loc.info["Phone"]),
             ("Email", req.info["Email"]), ("Film SF permit #", req.info["Film SF permit #"])],
            WHO_BORDER, width=1.2),
        Box([("# of signs", summary["# of signs"]), ("Location", loc.info["Location"]),
             ("Block & side", summary["Block & side"])], WHERE_BORDER),
    ]
    boxes += [Box([("Dates & hours", dates)], rgb(c), f"{COLOR_NAMES.get(c, '')} lines: {' / '.join(uses)}")
              for c, uses, dates in summary["By color"] if dates]
    return tuple(drawn), tuple(labels), arrows, markers, boxes, legend


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# The request being worked on. `gen` changes when a saved request is opened, so every
# widget starts fresh from the opened file instead of keeping what was on screen.
if "request" not in st.session_state:
    st.session_state.request = Request()
    st.session_state.gen = 0
    st.session_state.step = 0
req = st.session_state.request
gen = st.session_state.gen
project = req.info["Project"]

STEPS = ["1 · Start", "2 · Locations & curbs", "3 · Review & PDF"]


def go(step):
    """Switches steps. Widgets on other steps lose their on-screen state, so the editors and
    the map reload from the request when their step comes back."""
    if step is None or step == st.session_state.step:
        return
    st.session_state.step = step
    st.session_state.snapshots = {}
    st.session_state.map_visits = st.session_state.get("map_visits", 0) + 1


def picked_step():
    go(STEPS.index(st.session_state.step_pick) if st.session_state.step_pick else None)


def open_request(key):
    upload = st.session_state[key]
    if upload is None:
        return
    try:
        st.session_state.request = Request.from_json(upload.getvalue().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        st.session_state.open_error = f"Couldn't open that file: {e}"
        return
    st.session_state.gen += 1
    st.session_state.snapshots = {}


# Top bar: name, steps, open and save.
st.markdown("""<style>
[data-testid="stMainBlockContainer"], .block-container {padding-top: 2.2rem; padding-bottom: 2rem}
[data-testid="stHeaderActionElements"] {display: none}  /* headings' link icons */
[data-testid="InputInstructions"] {display: none}  /* "Press Enter to apply": fields save on leaving them */
</style>""", unsafe_allow_html=True)
brand, steps_col, file_col = st.columns([3, 5, 2], vertical_alignment="center")
with brand:
    st.markdown("**SF Film Parking Request**" + (f"  \n:gray[{project}]" if project else ""))
with steps_col:
    st.session_state.step_pick = STEPS[st.session_state.step]
    st.segmented_control("Step", STEPS, key="step_pick", on_change=picked_step,
                         label_visibility="collapsed")
# A row that keeps both buttons at their own width, wrapping instead of squeezing their labels.
with file_col.container(horizontal=True, horizontal_alignment="right"):
    with st.popover("Open"):
        st.file_uploader("Open a saved request (.json)", type="json", key=f"g{gen}-open",
                         on_change=open_request, args=(f"g{gen}-open",))
    st.download_button("Save", req.to_json(), mime="application/json",
                       file_name=f"{slug(project) or 'sf-parking-request'}.json",
                       help="Download everything entered so far. Nothing is kept when the "
                            "page is closed, so save to come back later.")
if st.session_state.get("open_error"):
    st.error(st.session_state.pop("open_error"))
st.divider()

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


def add_planned(planned, text):
    """Adds CSV-planned curb lines to the request: rows with the same Location go to one
    location (an existing one with that name, the open one if it's still empty, or a new
    one), each with its use and time windows set on the zones it makes."""
    targets, first, timed = {}, None, {}  # timed: location id -> {zone id: windows from the rows}
    for p in planned:
        name = p.location
        loc_ = targets.get(name.lower())
        if loc_ is None:
            loc_ = next((x for x in req.locations if name and x.info["Location"].lower() == name.lower()), None)
        if loc_ is None:
            current = next(x for x in req.locations if x.id == st.session_state.current)
            empty = not (current.lines or current.arrows or current.markers)
            loc_ = current if empty and current not in targets.values() else req.add_location()
        if name:
            loc_.info["Location"], loc_.auto_name = name, False
        targets[name.lower()] = loc_
        first = first or loc_
        color = LINE_COLORS["Blue"] if p.use == PICTURE else DEFAULT_COLOR
        for pts in p.lines:
            loc_.lines.append(Line(pts, color))
            for z in line_zones(pts):
                zid = zone_id(z)
                loc_.zones.setdefault(zid, {})["Use"] = p.use
                if p.windows:
                    timed.setdefault(loc_.id, {}).setdefault(zid, []).extend(p.windows)
    # The times most imported zones share become the location's dates (if it has none yet);
    # zones with other times keep their own.
    for loc_ in targets.values():
        zone_times = timed.get(loc_.id, {})
        schedules = list(zone_times.values())
        if schedules and not any(w.date or w.start or w.end for w in loc_.dates):
            loc_.dates = max(schedules, key=schedules.count)
        loc_.windows.update({zid: ws for zid, ws in zone_times.items() if ws != loc_.dates})
    go(1)  # show the imported curbs on the map
    # Start every widget fresh from the request, as when a file is opened.
    st.session_state.current = first.id
    st.session_state.gen += 1
    st.session_state.snapshots = {}
    st.session_state.csv_done = text
    st.session_state.csv_added = (f"Added {len(planned)} curb{'s' if len(planned) != 1 else ''} to "
                                  + ", ".join(x.title for x in targets.values()) + ".")


@st.dialog("Import curbs from CSV", width="large")
def csv_import():
    st.caption("One row per curb, with its **Side** (north, south, east, west or both) and either "
               "a **Block**, whole or part (`800-890 Grant Ave`, `800-850 Grant Ave`), or a **Street** "
               "with the cross streets it runs **From** and **To**. **Location**, **Use**, **Date**, "
               "**Start** and **End** are optional.")
    upload_csv = st.file_uploader("CSV file", type=["csv", "txt"], key="csv-file",
                                  label_visibility="collapsed")
    if upload_csv is not None and st.session_state.get("csv-file-seen") != upload_csv.file_id:
        st.session_state["csv-file-seen"] = upload_csv.file_id
        st.session_state["csv-text"] = upload_csv.getvalue().decode("utf-8-sig", errors="replace")
    st.session_state.setdefault("csv-text", EXAMPLE_BLOCKS)
    csv_text = st.text_area("Rows", key="csv-text", height=170)
    planned, problems = plan(csv_text, routes())
    for problem in problems:
        st.warning(problem + ". This row will be skipped.")
    if planned:
        st.dataframe([{"Location": p.location or "(open location)", "Curb": p.label, "Use": p.use,
                       "Blocks": ", ".join(dict.fromkeys(z.block for line in p.lines for z in line_zones(line))),
                       "Dates & hours": "; ".join(dates_and_hours(w) for w in p.windows) or "-"}
                      for p in planned], hide_index=True, use_container_width=True)
        again = st.session_state.get("csv_done") == csv_text
        if st.button(f"Add these {len(planned)} curb{'s' if len(planned) != 1 else ''} "
                     f"{'again' if again else 'to the request'}", type="secondary" if again else "primary",
                     help="These rows were already added; adding them again makes copies." if again else None):
            add_planned(planned, csv_text)
            st.rerun()


EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
SAMPLE_PAGE = Path(__file__).parent / "static" / "sample-page.jpg"  # made-up shoot, City Hall
HOW_IT_WORKS = [
    (":material/route:", "Draw your curbs",
     "Click along the curbs you need. Lines can turn corners and run several blocks; each block "
     "becomes a zone named the way Film SF does, with meters and spaces from city data."),
    (":material/calendar_month:", "Set dates and hours",
     "Once for each location, or for a single zone when it differs. Add stars, text boxes and "
     "arrows to point things out."),
    (":material/picture_as_pdf:", "Download the PDF",
     "One page per location, laid out like the requests Film SF already gets. Save the request "
     "to pick it up again later."),
]


@st.dialog("Sources & methods", width="large")
def methods_dialog():
    st.markdown(methods(curb_data().built))


def start_step():
    intro, sample = st.columns([3, 2], gap="large")
    with intro:
        st.title("Plan your shoot's street parking")
        st.markdown("Map the curbs your shoot needs in San Francisco and get a parking request "
                    "PDF ready to send to Film SF.")
        for icon, title, text in HOW_IT_WORKS:
            st.markdown(f"#### {icon} {title}")
            st.caption(text)
    with sample:
        st.image(str(SAMPLE_PAGE), caption="Example request", use_container_width=True)

    with st.container(border=True):
        st.markdown("**Shoot info**")
        st.caption("Goes on every page of the request. Fill it in now or come back to it any time.")
        left, right = st.columns(2)
        for i, name in enumerate(REQUEST_FIELDS):
            with (left if i % 2 == 0 else right):
                bound_text(name, req.info, name, f"g{gen}-req-{name}",
                           placeholder="name@company.com" if name == "Email" else None)
                if name == "Email" and req.info["Email"] and not EMAIL.fullmatch(req.info["Email"]):
                    st.caption(":red[That doesn't look like an email address. Use the form `name@company.com`.]")
        start, opener, importer, _ = st.columns([1.2, 1.2, 1.2, 2])
        start.button("Start mapping curbs", type="primary", icon=":material/arrow_forward:",
                     on_click=go, args=(1,), use_container_width=True)
        with opener.popover("Open a saved request", icon=":material/folder_open:", use_container_width=True):
            st.file_uploader("Saved request (.json)", type="json", key=f"g{gen}-open-start",
                             on_change=open_request, args=(f"g{gen}-open-start",))
        if importer.button("Import curbs from CSV", type="tertiary", icon=":material/upload_file:"):
            csv_import()
    if st.button("Sources & methods", type="tertiary", icon=":material/menu_book:"):
        methods_dialog()


def locations_step():
    if st.session_state.get("csv_added"):
        st.toast(st.session_state.pop("csv_added"))

    # Location strip: one button per location (one PDF page each), add, and more.
    buttons = st.columns([2] * len(req.locations) + [1.2, 0.5])
    for col, (n, place) in zip(buttons, enumerate(req.locations, start=1)):
        col.button(f"{n} · {place.title}", key=f"g{gen}-open-{place.id}", use_container_width=True,
                   type="primary" if place.id == st.session_state.current else "secondary",
                   on_click=open_location, args=(place.id,))
    with buttons[-2].popover("Add location", icon=":material/add:", use_container_width=True):
        st.button("New location", icon=":material/add_location_alt:", on_click=add_location,
                  use_container_width=True)
        if st.button("Import curbs from CSV", icon=":material/upload_file:", use_container_width=True):
            csv_import()
    with buttons[-1].popover("", icon=":material/more_horiz:", use_container_width=True,
                             help="More for this location"):
        st.button("Remove this location", icon=":material/delete:", on_click=remove_location,
                  disabled=len(req.locations) == 1)

    loc = next(loc for loc in req.locations if loc.id == st.session_state.current)

    # The map starts from the open location's saved lines and markers. It is only rebuilt when
    # a different location is opened or the step comes back (rebuilding resets the view);
    # tools switch inside the map, and what the user draws comes back through all_drawings.
    setup = (gen, loc.id, st.session_state.get("map_visits", 0))
    if st.session_state.get("map_setup") != setup:
        st.session_state.map_setup = setup
        st.session_state.map_opens = st.session_state.get("map_opens", 0) + 1
        st.session_state.map_shapes = (list(loc.lines), list(loc.arrows), list(loc.markers))

    map_col, side_col = st.columns([4, 1])
    with map_col:
        result = st_folium(drawing_map(*st.session_state.map_shapes), height=640,
                           use_container_width=True, returned_objects=["all_drawings"],
                           key=f"draw-{st.session_state.map_opens}")

    drawings = (result or {}).get("all_drawings")
    if drawings is not None:  # None until the user draws, edits or deletes on this map
        def latlon(coords):
            return [(lat, lon) for lon, lat in coords]

        lines = [d for d in drawings if (d.get("geometry") or {}).get("type") == "LineString"]
        points = [d for d in drawings if (d.get("geometry") or {}).get("type") == "Point"]
        def details(d):  # the map script keeps each shape's details on the shape (core.map_tools)
            return d.get("properties") or {}

        loc.lines = [Line(latlon(d["geometry"]["coordinates"]), details(d).get("color", DEFAULT_COLOR))
                     for d in lines if details(d).get("kind") != "arrow"]
        loc.arrows = [Arrow(latlon(d["geometry"]["coordinates"]))
                      for d in lines if details(d).get("kind") == "arrow"]
        loc.markers = [Marker(latlon([d["geometry"]["coordinates"]])[0], details(d).get("kind", TEXT),
                              details(d).get("text", ""), text_size(details(d).get("size")),
                              details(d).get("color", TEXT_COLOR)) for d in points]
    zones, ids, colors, base_rows = location_zones(loc)

    # Until the user types their own, the Location name follows the lines ("Grant @ Washington").
    suggested = place_name(zones)
    suggestions = place_names([line_zones(line.points) for line in loc.lines])
    name_key = f"g{gen}-{loc.id}-Location"
    if loc.auto_name and suggested and st.session_state.get(name_key, loc.info["Location"]) in (
            "", loc.info["Location"]) and loc.info["Location"] != suggested:
        st.session_state[name_key] = loc.info["Location"] = suggested
        st.rerun()  # so the location buttons above show the new name

    with side_col:
        bound_text("Location", loc.info, "Location", name_key, placeholder="Named from your first line",
                   help="Filled in from your lines until you type your own.")
        if len(suggestions) > 1:
            def use_suggestion(pick_key=f"g{gen}-{loc.id}-suggest"):
                if st.session_state[pick_key]:
                    st.session_state[name_key] = loc.info["Location"] = st.session_state[pick_key]
                    loc.auto_name = False
                st.session_state[pick_key] = None
            st.selectbox("Suggested names", suggestions, index=None, key=f"g{gen}-{loc.id}-suggest",
                         on_change=use_suggestion, placeholder="Other names from your lines",
                         label_visibility="collapsed")
        if loc.info["Location"] != suggested:
            loc.auto_name = False  # the user typed or picked their own name
        bound_text("Contact", loc.info, "Contact", f"g{gen}-{loc.id}-Contact")
        bound_text("Phone", loc.info, "Phone", f"g{gen}-{loc.id}-Phone", placeholder="(415) 555-0100",
                   formatter=format_phone)
        scenes = {"text": "\n".join(loc.scenes)}
        bound_text("Scenes", scenes, "text", f"g{gen}-{loc.id}-scenes", area=True, height=80,
                   placeholder="INT City Hall - SHOOT", help="One scene per line.")
        loc.scenes = [line.strip() for line in scenes["text"].splitlines() if line.strip()]
        store = {"notes": loc.notes}
        bound_text("Notes", store, "notes", f"g{gen}-{loc.id}-notes", area=True, height=80,
                   placeholder="Anything the permit office should know")
        loc.notes = store["notes"]
        if loc.lines and not zones:
            st.warning("That line isn't on a street. Draw it along the curb.")
        elif zones:
            spaces = sum(int(r["Spaces"] or 0) for r in base_rows)
            st.markdown(f"**{spaces} spaces** · {len(zones)} zone{'s' if len(zones) != 1 else ''}")

    dates_col, _ = st.columns([1, 1])
    with dates_col:
        st.markdown("**Dates & hours**", help="For every zone at this location. Add a row for each "
                    "day. To give one zone different times, tick Own times in the zones table. An "
                    "end time earlier than the start means the next day.")
        dates_key = f"dates-g{gen}-{loc.id}"
        picked = st.data_editor(
            snapshot(dates_key, lambda: window_rows(loc.dates)),
            key=dates_key, hide_index=True, use_container_width=True, num_rows="dynamic",
            column_config=window_columns())
        loc.dates = [Window(as_date(r.get("Date")), as_time(r.get("Start")), as_time(r.get("End")))
                     for r in picked.to_dict("records")]

    if zones:
        labels = [f"{i} · {z.block} ({z.side})" for i, z in enumerate(zones, start=1)]
        zones_key = f"g{gen}-{loc.id}-{hash(tuple(ids))}"

        heading, toggle, sources = st.columns([6, 1.4, 1.4], vertical_alignment="center")
        heading.subheader("Curb zones")
        curb_details = toggle.toggle("Curb details", key="curb_details",
                                     on_change=lambda: st.session_state.update(snapshots={}),
                                     help="Show the meters and color curbs (blue, white, yellow zones, "
                                          "red-curb driveways) on each block.")
        if sources.button("Sources & methods", use_container_width=True):
            methods_dialog()

        def zone_rows():
            return [{"Zone": i, "Block": z.block, "Side": z.side, "Between": z.between,
                     "Length (ft)": round(z.length_ft), **row, "Own times": zid in loc.windows}
                    for i, (z, zid, row) in enumerate(zip(zones, ids, base_rows), start=1)]

        edited = st.data_editor(
            snapshot(f"zones-{zones_key}-{curb_details}", zone_rows), key=f"zones-{zones_key}-{curb_details}",
            hide_index=True, use_container_width=True,
            # What gets edited first; the city's curb details only when asked for.
            column_order=["Zone", "Block", "Side", "Spaces", "Use", "Own times", "Meters",
                          *(["Curb"] if curb_details else []), "Between", "Length (ft)"],
            disabled=["Zone", "Block", "Side", "Between", "Length (ft)"],
            column_config={
                "Curb": st.column_config.TextColumn(width="large"),
                "Spaces": st.column_config.NumberColumn(min_value=1, step=1),
                "Use": st.column_config.SelectboxColumn(options=USES, required=True),
                "Meters": st.column_config.SelectboxColumn(options=METERS, required=True),
                "Own times": st.column_config.CheckboxColumn(
                    help="Give this zone its own dates and hours instead of the location's."),
            },
        )
        # Zones that no longer exist (a line was moved or erased) drop their own times.
        loc.windows = {zid: ws for zid, ws in loc.windows.items() if zid in ids}
        for zid, row in zip(ids, edited):
            loc.zones[zid] = {k: row[k] for k in ("Curb", "Meters", "Spaces", "Use")}
            if row["Own times"] and zid not in loc.windows:
                loc.windows[zid] = list(loc.dates)  # start from the location's times
            elif not row["Own times"]:
                loc.windows.pop(zid, None)

        own = [i for i, zid in enumerate(ids) if zid in loc.windows]
        if own:
            own_labels = [labels[i] for i in own]
            st.markdown("**Zones with their own dates & hours**", help="Add a row and pick its zone "
                        "to book that zone for another day or time.")
            own_key = f"own-{zones_key}-{hash(tuple(ids[i] for i in own))}"
            rows = st.data_editor(
                snapshot(own_key, lambda: [{"Zone": labels[i], "Date": w.date, "Start": w.start, "End": w.end}
                                           for i in own for w in loc.windows[ids[i]]]),
                key=own_key, hide_index=True, use_container_width=True, num_rows="dynamic",
                column_config={"Zone": st.column_config.SelectboxColumn(options=own_labels, required=True,
                                                                        width="large"),
                               **window_columns()})
            times = {ids[i]: [] for i in own}
            for row in rows:
                if row.get("Zone") in own_labels:
                    times[ids[labels.index(row["Zone"])]].append(
                        Window(as_date(row.get("Date")), as_time(row.get("Start")), as_time(row.get("End"))))
            loc.windows.update(times)

    st.button("Next: review and PDF", type="primary", on_click=go, args=(2,))


def review_step():
    # The whole request: one PDF page per location that has zones.
    pages = [(loc_, page) for loc_ in req.locations if (page := location_page(req, loc_))]
    if not pages:
        st.info("Draw curb lines at a location to build the PDF.")
        st.button("Back to locations", on_click=go, args=(1,))
        return
    pdf = build_pdf([Page(pdf_map(drawn_, labels_, arrows_, markers_), boxes_, loc_.scenes, loc_.notes,
                          [(label, rgb(c)) for label, c in legend_])
                     for loc_, (drawn_, labels_, arrows_, markers_, boxes_, legend_) in pages], project=project)
    head, button = st.columns([4, 1], vertical_alignment="center")
    head.subheader(f"{len(pages)} page{'s' if len(pages) != 1 else ''}, one per location")
    button.download_button("Download PDF", type="primary", mime="application/pdf", data=pdf,
                           icon=":material/download:", use_container_width=True,
                           file_name=f"{slug(project) or 'sf-parking-request'}-{date.today():%Y-%m-%d}.pdf")
    for n, (image, (loc_, _)) in enumerate(zip(pdf_pages(pdf), pages), start=1):
        st.image(image, caption=f"Page {n} · {loc_.title}", use_container_width=True)


[start_step, locations_step, review_step][st.session_state.step]()

# Formats the Phone field while it's typed: digits only, "(415) 555-0100" (as format_phone does
# when the field is saved). Streamlit text inputs can't do this, so a script in a hidden frame
# watches the page for Phone fields.
PHONE_JS = """<script>
const page = window.parent.document;
const setValue = Object.getOwnPropertyDescriptor(window.parent.HTMLInputElement.prototype, "value").set;
function format(text) {
  let d = text.replace(/[^0-9]/g, "");
  if (d.length === 11 && d[0] === "1") d = d.slice(1);
  d = d.slice(0, 10);
  if (!d) return "";
  if (d.length <= 3) return "(" + d;
  if (d.length <= 6) return "(" + d.slice(0, 3) + ") " + d.slice(3);
  return "(" + d.slice(0, 3) + ") " + d.slice(3, 6) + "-" + d.slice(6);
}
function watch(input) {
  if (input.dataset.sfPhone) return;
  input.dataset.sfPhone = "1";
  input.setAttribute("inputmode", "tel");
  input.addEventListener("input", function () {
    const formatted = format(input.value);
    if (formatted !== input.value) {
      setValue.call(input, formatted);
      input.dispatchEvent(new Event("input", {bubbles: true}));
    }
  });
}
function scan() { page.querySelectorAll('input[aria-label="Phone"]').forEach(watch); }
new MutationObserver(scan).observe(page.body, {childList: true, subtree: true});
scan();
</script>"""
components.html(PHONE_JS, height=0)
