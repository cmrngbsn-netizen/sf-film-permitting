"""SF Film Permit helper (beta).

Draw the requested permit area on a map of San Francisco, review each corner point
against the nearest cross streets, and add notes.
Run locally with: streamlit run app.py
"""

import folium
import streamlit as st
from folium.plugins import Draw
from streamlit_folium import st_folium

from core.streets import StreetIndex

SF_CENTER = [37.7749, -122.4194]
SF_BOUNDS = [[37.70, -122.53], [37.84, -122.35]]  # keeps the map panned to the city

SNAP = "Snap to corner"
KEEP = "Keep as drawn"

st.set_page_config(page_title="SF Film Permit Area", layout="wide")
st.title("SF Film Permit Area")
st.info(
    "Beta planning aid, not an official filing. Requests still go through Film SF and SFMTA.",
    icon="ℹ️",
)


@st.cache_resource
def street_index():
    return StreetIndex()


def base_map(**kwargs):
    return folium.Map(min_zoom=12, max_bounds=True,
                      min_lat=SF_BOUNDS[0][0], min_lon=SF_BOUNDS[0][1],
                      max_lat=SF_BOUNDS[1][0], max_lon=SF_BOUNDS[1][1], **kwargs)


def drawing_map():
    m = base_map(location=SF_CENTER, zoom_start=14)
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


def reviewed_map(drawn, final):
    """Final area with numbered points; grey dots show where snapped points were drawn."""
    m = base_map()
    folium.Polygon(final, color="#d62728", weight=3, fill=True, fill_opacity=0.15).add_to(m)
    for i, (orig, new) in enumerate(zip(drawn, final), start=1):
        if orig != new:
            folium.PolyLine([orig, new], color="grey", weight=1, dash_array="4").add_to(m)
            folium.CircleMarker(orig, radius=3, color="grey", fill=True).add_to(m)
        folium.Marker(new, icon=folium.DivIcon(
            icon_size=(22, 22), icon_anchor=(11, 11),
            html=f'<div style="background:#d62728;color:white;border-radius:11px;width:22px;'
                 f'height:22px;line-height:22px;text-align:center;font:bold 12px sans-serif">{i}</div>',
        )).add_to(m)
    m.fit_bounds([[min(p[0] for p in final), min(p[1] for p in final)],
                  [max(p[0] for p in final), max(p[1] for p in final)]], padding=(30, 30))
    return m


def polygon_points(drawing):
    """Corner points of a drawn polygon as (lat, lon), without the repeated closing point."""
    ring = drawing["geometry"]["coordinates"][0]
    return [(lat, lon) for lon, lat in ring[:-1]]


map_col, side_col = st.columns([3, 2])

with map_col:
    st.caption("Click the pentagon tool on the left of the map, click each corner of your area, "
               "then click the first corner again to close it.")
    result = st_folium(drawing_map(), height=600, use_container_width=True,
                       returned_objects=["all_drawings"])

drawings = (result or {}).get("all_drawings") or []
polygons = [d for d in drawings if d.get("geometry", {}).get("type") == "Polygon"]
points = polygon_points(polygons[-1]) if polygons else []

with side_col:
    st.subheader("Requested area")
    if not points:
        st.write("No area drawn yet.")
    else:
        if len(polygons) > 1:
            st.warning("More than one area is drawn. Only the most recent one is used; "
                       "delete the others with the trash tool.")
        st.write(f"{len(points)} corner points. Review them below the map.")

    st.subheader("Notes")
    st.text_area("Anything the permit office should know about this area",
                 key="notes", height=150)

if points:
    st.divider()
    st.subheader("Review points")
    st.caption("Each point is matched to the nearest cross streets. Points near an intersection "
               f"can snap to it; mid-block points stay where you drew them. Change the "
               f"**Action** column to choose.")

    labels = [street_index().label_point(lat, lon) for lat, lon in points]
    rows = [{
        "Point": i,
        "Location": lab.label,
        "Distance to corner (ft)": str(round(lab.distance_ft)) if lab.kind == "corner" else "—",
        "Action": SNAP if lab.kind == "corner" else KEEP,
    } for i, lab in enumerate(labels, start=1)]

    # A new or edited polygon gets fresh suggestions instead of old choices.
    edited = st.data_editor(
        rows, key=f"review-{hash(tuple(points))}", hide_index=True, use_container_width=True,
        disabled=["Point", "Location", "Distance to corner (ft)"],
        column_config={"Action": st.column_config.SelectboxColumn(options=[SNAP, KEEP], required=True)},
    )

    final, listing = [], []
    for lab, drawn, row in zip(labels, points, edited):
        if row["Action"] == SNAP and lab.kind == "corner":
            final.append((lab.snap_lat, lab.snap_lon))
            listing.append(lab.label)
        else:
            final.append(drawn)
            # A kept point near a corner is still described by that corner.
            listing.append(lab.label if lab.kind == "mid-block" else f"Near {lab.label}")
        if row["Action"] == SNAP and lab.kind == "mid-block":
            st.warning(f"Point {row['Point']} is mid-block, so there is no corner to snap to; "
                       "it stays where it was drawn.")

    map_col2, list_col = st.columns([3, 2])
    with map_col2:
        st_folium(reviewed_map(points, final), height=450, use_container_width=True,
                  returned_objects=[], key="reviewed")
    with list_col:
        st.markdown("**Area boundary, in order**")
        st.markdown("\n".join(f"{i}. {text}" for i, text in enumerate(listing, start=1)))
