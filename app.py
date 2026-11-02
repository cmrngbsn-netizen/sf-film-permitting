"""SF Film Permit helper (beta).

Draw lines along the curbs you need for a shoot. Each line is split into one zone per
block and named the way Film SF names them ("8 spaces on north side 400-490 McAllister St"),
then exported as a one-page parking request PDF.
Run locally with: streamlit run app.py
"""

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

from core.basemaps import BASEMAPS, BY_NAME as BASEMAP_BY_NAME, DEFAULT as DEFAULT_BASEMAP  # noqa: E402
from core.curbdata import CurbData  # noqa: E402
from core.curbs import CurbZoner  # noqa: E402
from core.pdf import build_pdf, render_map  # noqa: E402
from core.streets import StreetIndex  # noqa: E402
from core.summary import (METERS, PICTURE, SHOOT_FIELDS, USES, WORKING, Window,  # noqa: E402
                          ZoneRequest, summarize)

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
def pdf_map(lines, basemap_name):
    return render_map([(list(pts), rgb, label) for pts, rgb, label in lines],
                      BASEMAP_BY_NAME[basemap_name])


def hex_color(rgb):
    return "#%02x%02x%02x" % rgb


def add_basemap(m, basemap, show=True):
    """Add a basemap's tile layers as one choice in the map's layer switcher."""
    group = folium.FeatureGroup(name=basemap.name, overlay=False, control=True, show=show)
    for i, url in enumerate(basemap.layers):
        folium.TileLayer(url, attr=basemap.credit if i == 0 else " ", max_zoom=20,
                         max_native_zoom=basemap.max_zoom).add_to(group)
    group.add_to(m)


def base_map(basemap=None, **kwargs):
    """A map of SF. With a basemap it shows only that one; without, it offers all of
    them in a layer switcher (top right)."""
    m = folium.Map(tiles=None, min_zoom=12, max_zoom=20, max_bounds=True,
                   min_lat=SF_BOUNDS[0][0], min_lon=SF_BOUNDS[0][1],
                   max_lat=SF_BOUNDS[1][0], max_lon=SF_BOUNDS[1][1], **kwargs)
    if basemap:
        add_basemap(m, basemap)
    else:
        for b in BASEMAPS:
            add_basemap(m, b, show=b is DEFAULT_BASEMAP)
        folium.LayerControl(collapsed=False).add_to(m)
    return m


def drawing_map():
    # All basemaps in a switcher: changing it happens in the browser, so drawn lines stay.
    m = base_map(location=SF_CENTER, zoom_start=14)
    # Only the line tool: click along the curb, click the last point again to finish.
    Draw(
        draw_options={
            "polyline": {"shapeOptions": {"color": "#d62728", "weight": 5}},
            "polygon": False, "rectangle": False, "circle": False,
            "marker": False, "circlemarker": False,
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(m)
    return m


def zones_map(lines, basemap):
    """Reviewed zones: one colored line per zone with its space count."""
    m = base_map(basemap)
    for pts, rgb, label in lines:
        folium.PolyLine(pts, color=hex_color(rgb), weight=7, opacity=0.9).add_to(m)
        folium.Marker(pts[len(pts) // 2], icon=folium.DivIcon(
            icon_size=(30, 20), icon_anchor=(15, 10),
            html=f'<div style="background:white;color:black;border:2px solid {hex_color(rgb)};'
                 f'width:30px;text-align:center;font:bold 12px sans-serif">{label}</div>',
        )).add_to(m)
    every = [p for pts, _, _ in lines for p in pts]
    m.fit_bounds([[min(p[0] for p in every), min(p[1] for p in every)],
                  [max(p[0] for p in every), max(p[1] for p in every)]], padding=(30, 30))
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


map_col, side_col = st.columns([3, 2])

with map_col:
    st.caption("Click the line tool on the left of the map, then click along the curb you need. "
               "Click the last point again (or **Finish**) to end the line. Draw one line per "
               "stretch of curb; a line can turn corners. Switch between aerial and street map "
               "at the top right of the map.")
    result = st_folium(drawing_map(), height=600, use_container_width=True,
                       returned_objects=["all_drawings"])

drawings = (result or {}).get("all_drawings") or []
lines = [[(lat, lon) for lon, lat in d["geometry"]["coordinates"]]
         for d in drawings if d.get("geometry", {}).get("type") == "LineString"]
zones = [z for line in lines for z in zoner().zones(line)]

with side_col:
    with st.expander("Shoot info", expanded=True):
        for name in SHOOT_FIELDS:
            st.text_input(name, key=f"shoot_{name}")
    st.text_input("Location", key="location",
                  placeholder="e.g. City Hall, McAllister @ Larkin & Polk")
    st.text_area("Notes", key="notes", height=100,
                 placeholder="Anything the permit office should know")
    if not lines:
        st.write("No curb lines drawn yet.")
    elif not zones:
        st.warning("The line isn't close enough to a street. Draw it along the curb.")
    else:
        st.write(f"{len(zones)} curb zone{'s' if len(zones) != 1 else ''} found. "
                 "Review them below the map.")

if zones:
    ids = [zone_id(z) for z in zones]
    labels = [f"{i} · {z.block} ({z.side})" for i, z in enumerate(zones, start=1)]
    zone_edits = st.session_state.setdefault("zone_edits", {})   # zone id -> edited row
    zone_windows = st.session_state.setdefault("zone_windows", {})  # zone id -> [Window]
    zones_key = str(hash(tuple(ids)))

    st.divider()
    st.subheader("Curb zones")
    st.caption(f"One row per block. **Curb**, **Meters** and **Spaces** are filled in from SFMTA "
               f"meter and color-curb data (updated {curb_data().built}): one space per meter on "
               f"metered curb, otherwise 20 ft per space minus driveways. Change anything you know "
               f"better.")

    def zone_rows():
        rows = []
        for i, (z, zid) in enumerate(zip(zones, ids), start=1):
            info = curb_data().lookup(z)
            row = {
                "Zone": i,
                "Block": z.block,
                "Side": z.side,
                "Between": z.between,
                "Length (ft)": round(z.length_ft),
                "Curb": info.describe(),
                "Meters": "Metered" if info.metered else "Non-metered",
                "Spaces": info.suggested_spaces(z.length_ft),
                "Use": WORKING,
            }
            row.update(zone_edits.get(zid, {}))  # earlier edits to this zone win
            rows.append(row)
        return rows

    edited = st.data_editor(
        snapshot(f"zones-{zones_key}", zone_rows), key=f"zones-{zones_key}", hide_index=True,
        use_container_width=True,
        disabled=["Zone", "Block", "Side", "Between", "Length (ft)"],
        column_config={
            "Curb": st.column_config.TextColumn(width="large"),
            "Spaces": st.column_config.NumberColumn(min_value=1, step=1),
            "Use": st.column_config.SelectboxColumn(options=USES, required=True),
            "Meters": st.column_config.SelectboxColumn(options=METERS, required=True),
        },
    )
    for zid, row in zip(ids, edited):
        zone_edits[zid] = {k: row[k] for k in ("Curb", "Meters", "Spaces", "Use")}

    st.subheader("Dates & hours")
    st.caption("One row per zone to start. To book a zone for more than one day or time window, "
               "add a row at the bottom of the table and pick its zone. An end time earlier than "
               "the start means the next day.")

    def schedule_rows():
        rows = []
        for label, zid in zip(labels, ids):
            for w in zone_windows.get(zid) or [Window()]:
                rows.append({"Zone": label, "Date": w.date, "Start": w.start, "End": w.end})
        return rows

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
        zone_windows[zid] = []
    for row in schedule:
        if row.get("Zone") in labels:
            zid = ids[labels.index(row["Zone"])]
            zone_windows[zid].append(Window(as_date(row.get("Date")), as_time(row.get("Start")),
                                            as_time(row.get("End"))))

    requests = [ZoneRequest(z.block, z.side, int(r["Spaces"] or 1), r["Use"], r["Meters"],
                            zone_windows[zid], r["Curb"] or "")
                for z, zid, r in zip(zones, ids, edited)]
    drawn = tuple((tuple(z.points), USE_COLORS[r.use], str(r.spaces)) for z, r in zip(zones, requests))
    shoot = {name: st.session_state.get(f"shoot_{name}", "").strip() for name in SHOOT_FIELDS}
    project = shoot.pop("Project")
    fields = {**shoot, "Location": st.session_state.get("location", "").strip(), **summarize(requests)}

    st.divider()
    style = st.selectbox("Map style for this map and the PDF", [b.name for b in BASEMAPS],
                         key="basemap")
    map_col2, list_col = st.columns([3, 2])
    with map_col2:
        st_folium(zones_map(drawn, BASEMAP_BY_NAME[style]), height=450, use_container_width=True,
                  returned_objects=[], key=f"reviewed-{style}")
        st.caption(f":red[■] {WORKING} · :blue[■] {PICTURE}")
    with list_col:
        if project:
            st.markdown(f"#### {project}")
        for name, value in fields.items():
            if not value:
                continue
            if isinstance(value, list):
                st.markdown(f"**{name}:**" + "".join(f"\n- {v}" for v in value))
            else:
                st.markdown(f"**{name}:** {value}")

        st.download_button(
            "Download PDF", type="primary", mime="application/pdf",
            file_name=f"sf-parking-request-{date.today():%Y-%m-%d}.pdf",
            data=build_pdf(pdf_map(drawn, style), fields, list(USE_COLORS.items()),
                           st.session_state.get("notes", ""), project=project),
        )
