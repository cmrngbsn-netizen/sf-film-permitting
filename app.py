"""SF Film Permit helper (beta).

Step 1: draw the requested permit area on a map of San Francisco and add notes.
Run locally with: streamlit run app.py
"""

import folium
import streamlit as st
from folium.plugins import Draw
from streamlit_folium import st_folium

SF_CENTER = [37.7749, -122.4194]
SF_BOUNDS = [[37.70, -122.53], [37.84, -122.35]]  # keeps the map panned to the city

st.set_page_config(page_title="SF Film Permit Area", layout="wide")
st.title("SF Film Permit Area")
st.info(
    "Beta planning aid, not an official filing. Requests still go through Film SF and SFMTA.",
    icon="ℹ️",
)


def build_map():
    m = folium.Map(location=SF_CENTER, zoom_start=14, min_zoom=12, max_bounds=True,
                   min_lat=SF_BOUNDS[0][0], min_lon=SF_BOUNDS[0][1],
                   max_lat=SF_BOUNDS[1][0], max_lon=SF_BOUNDS[1][1])
    # Only the polygon tool: click to add corners, click the first corner to close.
    Draw(
        draw_options={
            "polygon": {"allowIntersection": False, "showArea": False},
            "polyline": False, "rectangle": False, "circle": False,
            "marker": False, "circlemarker": False,
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(m)
    return m


def polygon_points(drawing):
    """Corner points of a drawn polygon as (lat, lon), without the repeated closing point."""
    if not drawing or drawing.get("geometry", {}).get("type") != "Polygon":
        return []
    ring = drawing["geometry"]["coordinates"][0]
    return [(lat, lon) for lon, lat in ring[:-1]]


map_col, side_col = st.columns([3, 2])

with map_col:
    st.caption("Click the pentagon tool on the left of the map, click each corner of your area, "
               "then click the first corner again to close it.")
    result = st_folium(build_map(), height=600, use_container_width=True,
                       returned_objects=["all_drawings"])

drawings = (result or {}).get("all_drawings") or []
polygons = [d for d in drawings if d.get("geometry", {}).get("type") == "Polygon"]

with side_col:
    st.subheader("Requested area")
    if not polygons:
        st.write("No area drawn yet.")
    else:
        if len(polygons) > 1:
            st.warning("More than one area is drawn. Only the most recent one is used; "
                       "delete the others with the trash tool.")
        points = polygon_points(polygons[-1])
        st.write(f"{len(points)} corner points")
        st.dataframe(
            [{"Point": i + 1, "Latitude": round(lat, 6), "Longitude": round(lon, 6)}
             for i, (lat, lon) in enumerate(points)],
            hide_index=True, use_container_width=True,
        )

    st.subheader("Notes")
    st.text_area("Anything the permit office should know about this area",
                 key="notes", height=150)
