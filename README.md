# SF Film Permit Area (beta)

Draw the area you are requesting film permits for on a map of San Francisco and add notes.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

## Street data

`data/segments.geojson` (street blocks) and `data/nodes.json` (street names at each intersection)
come from DataSF datasets `3psu-pn9h` and `gmfx-8h6i`. To rebuild them from the latest city data:

```bash
.venv/bin/python scripts/build_data.py --refresh
```

Known gaps: 96 intersections have no names in the city data (mostly Treasure Island,
Yerba Buena Island, Hunters Point and Mission Bay).
