"""The Sources & methods text, using the same numbers the code does."""

from core.curbdata import END_MARGIN_M
from core.curbs import MAX_OFFSET_M, SAMPLE_M, SPACE_FT
from core.streets import M_PER_FT


def feet(meters):
    return round(meters / M_PER_FT)


def methods(built):
    """Markdown for the Sources & methods section; `built` is when the city data was last pulled."""
    return f"""
Every number here is a starting estimate from public data. Check the curb in person, and change
any value you know better in the zones table. Film SF and SFMTA decide what gets approved.

#### Sources

City data last pulled **{built}**.

| Data | Source | Used for |
|---|---|---|
| Street blocks and address ranges | [DataSF: Streets, Active and Retired](https://data.sf.gov/d/3psu-pn9h) | Block names, sides, lengths |
| Intersections | [DataSF: Street Intersections](https://data.sf.gov/d/gmfx-8h6i) | Cross streets, map search |
| Active on-street meters | [SFMTA: Meters](https://services.sfmta.com/arcgis/rest/services/Parking/parking/MapServer/11) | Metered spaces, meter types |
| Color curbs | [SFMTA: Color curbs](https://services.sfmta.com/arcgis/rest/services/Parking/parking/MapServer/18) | Curb details |
| On-street parking census, counted 2008-2014 | [SFMTA: Parking census](https://services.sfmta.com/arcgis/rest/services/Parking/parking/MapServer/4) | Spaces on unmetered curb |
| Map background | [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors | Map and PDF |

#### From a line to zones

1. A line is checked every {feet(SAMPLE_M)} ft or so and matched to the nearest street within
   {feet(MAX_OFFSET_M)} ft. Parts farther away are ignored.
2. Each block side becomes one zone. Passing an intersection or an alley's mouth doesn't count as
   being on that street. Where an alley splits a block, the pieces are joined, unless one is
   metered and the other isn't.
3. The side (north, south, east or west) comes from which side of the street's centerline the
   line is on, and the direction the street mostly runs.
4. A block is named by its hundred range, like 800-890 Grant Ave. A line covering only part of
   a block is named by the addresses it covers, estimated by spacing them evenly along the block
   and rounded to the nearest 5, like 800-845 Grant Ave. Exact addresses can be typed over it.

#### How spaces are counted

The first of these that applies sets the Spaces value:

1. **Meters:** one space per car meter on that stretch, including meters up to
   {feet(END_MARGIN_M)} ft past its ends. Motorcycle meters aren't counted, because they don't
   hold a car.
2. **Parking census:** the block's legal spaces, which the census gives for both sides together,
   times the zone's share of that curb (zone length ÷ twice the block length). It's the only
   source that accounts for every driveway.
3. **Length:** one space per {SPACE_FT} ft, less any red-curb driveways, where a block has no
   census count.

#### CSV blocks

Partial blocks, like 800-850 Grant Ave, are placed by spacing addresses evenly along the block.
Real buildings aren't evenly spaced, so check the line on the map.

#### Known limits

- **Age:** the census is more than ten years old, so curb changes since then won't show on
  unmetered blocks. Meters and color curbs are as of the date above.
- **Driveways:** the color curb data only includes driveways painted red. That's why it isn't
  used for space counts when there's a census count.
- **Not included:** temporary closures, construction, other permits, and street-cleaning or
  tow-away hours.
- **Unnamed intersections:** some have no names in the city data, mostly on Treasure Island,
  Yerba Buena Island, Hunters Point and Mission Bay.
"""
