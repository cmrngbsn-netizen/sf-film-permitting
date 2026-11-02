"""SF Film Permit helper (beta).

Draw lines along the curbs you need for a shoot. Each line is split into one zone per
block and named the way Film SF names them ("8 spaces on north side 400-490 McAllister St"),
then exported as a one-page parking request PDF.
Run locally with: streamlit run app.py
"""

import sys
from datetime import date
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

from core.curbdata import CurbData  # noqa: E402
from core.curbs import CurbZoner  # noqa: E402
from core.pdf import build_pdf, render_map  # noqa: E402
from core.streets import StreetIndex  # noqa: E402
from core.summary import METERS, PICTURE, USES, WORKING, ZoneRequest, summarize  # noqa: E402

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
    return render_map([(list(pts), rgb, label) for pts, rgb, label in lines])


def hex_color(rgb):
    return "#%02x%02x%02x" % rgb


def base_map(**kwargs):
    return folium.Map(min_zoom=12, max_bounds=True,
                      min_lat=SF_BOUNDS[0][0], min_lon=SF_BOUNDS[0][1],
                      max_lat=SF_BOUNDS[1][0], max_lon=SF_BOUNDS[1][1], **kwargs)


def drawing_map():
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
    every = [p for pts, _, _ in lines for p in pts]
    m.fit_bounds([[min(p[0] for p in every), min(p[1] for p in every)],
                  [max(p[0] for p in every), max(p[1] for p in every)]], padding=(30, 30))
    return m


map_col, side_col = st.columns([3, 2])

with map_col:
    st.caption("Click the line tool on the left of the map, then click along the curb you need. "
               "Click the last point again (or **Finish**) to end the line. Draw one line per "
               "stretch of curb; a line can turn corners.")
    result = st_folium(drawing_map(), height=600, use_container_width=True,
                       returned_objects=["all_drawings"])

drawings = (result or {}).get("all_drawings") or []
lines = [[(lat, lon) for lon, lat in d["geometry"]["coordinates"]]
         for d in drawings if d.get("geometry", {}).get("type") == "LineString"]
zones = [z for line in lines for z in zoner().zones(line)]

with side_col:
    st.text_input("Location", key="location",
                  placeholder="e.g. City Hall, McAllister @ Larkin & Polk")
    st.text_area("Notes", key="notes", height=120,
                 placeholder="Anything the permit office should know")
    if not lines:
        st.write("No curb lines drawn yet.")
    elif not zones:
        st.warning("The line isn't close enough to a street. Draw it along the curb.")
    else:
        st.write(f"{len(zones)} curb zone{'s' if len(zones) != 1 else ''} found. "
                 "Review them below the map.")

if zones:
    st.divider()
    st.subheader("Curb zones")
    st.caption(f"One row per block. **Curb**, **Meters** and **Spaces** are filled in from SFMTA "
               f"meter and color-curb data (updated {curb_data().built}): one space per meter on "
               f"metered curb, otherwise 20 ft per space minus driveways. Change anything you know "
               f"better, then set the use, date and hours for each zone.")

    infos = [curb_data().lookup(z) for z in zones]
    rows = [{
        "Zone": i,
        "Block": z.block,
        "Side": z.side,
        "Between": z.between,
        "Length (ft)": round(z.length_ft),
        "Curb": info.describe(),
        "Meters": "Metered" if info.metered else "Non-metered",
        "Spaces": info.suggested_spaces(z.length_ft),
        "Use": WORKING,
        "Date": None,
        "Start": None,
        "End": None,
    } for i, (z, info) in enumerate(zip(zones, infos), start=1)]

    # New or changed lines get fresh rows instead of old edits.
    edited = st.data_editor(
        rows, key=f"zones-{hash(tuple(map(tuple, lines)))}", hide_index=True,
        use_container_width=True,
        disabled=["Zone", "Block", "Side", "Between", "Length (ft)"],
        column_config={
            "Curb": st.column_config.TextColumn(width="large"),
            "Spaces": st.column_config.NumberColumn(min_value=1, step=1),
            "Use": st.column_config.SelectboxColumn(options=USES, required=True),
            "Meters": st.column_config.SelectboxColumn(options=METERS, required=True),
            "Date": st.column_config.DateColumn(format="ddd MM/DD/YY"),
            "Start": st.column_config.TimeColumn(format="h:mm A", step=900),
            "End": st.column_config.TimeColumn(format="h:mm A", step=900),
        },
    )

    requests = [ZoneRequest(z.block, z.side, int(r["Spaces"] or z.spaces), r["Use"], r["Meters"],
                            r["Date"], r["Start"], r["End"], r["Curb"] or "")
                for z, r in zip(zones, edited)]
    drawn = tuple((tuple(z.points), USE_COLORS[r.use], str(r.spaces)) for z, r in zip(zones, requests))
    summary = summarize(requests)

    map_col2, list_col = st.columns([3, 2])
    with map_col2:
        st_folium(zones_map(drawn), height=450, use_container_width=True,
                  returned_objects=[], key="reviewed")
        st.caption(f":red[■] {WORKING} · :blue[■] {PICTURE}")
    with list_col:
        st.markdown(f"**Location:** {st.session_state.get('location') or '—'}")
        for field, value in summary.items():
            if isinstance(value, list):
                st.markdown(f"**{field}:**" + "".join(f"\n- {v}" for v in value) if value
                            else f"**{field}:** —")
            else:
                st.markdown(f"**{field}:** {value}")

        st.download_button(
            "Download PDF", type="primary", mime="application/pdf",
            file_name=f"sf-parking-request-{date.today():%Y-%m-%d}.pdf",
            data=build_pdf(pdf_map(drawn), st.session_state.get("location", ""), summary,
                           list(USE_COLORS.items()), st.session_state.get("notes", "")),
        )
