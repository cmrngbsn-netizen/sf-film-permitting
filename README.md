# SF Film Parking Request (beta)

Draw lines along the curbs you need for a film shoot in San Francisco. Each line is split
into one zone per block and named the way Film SF does ("8 metered spaces on north side
400-490 McAllister St"). Set each zone's use, meters, date and hours, then download a
one-page parking request PDF.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

## Street data

`data/segments.geojson` (street blocks with address ranges) and `data/nodes.json` (street names at each intersection)
come from DataSF datasets `3psu-pn9h` and `gmfx-8h6i`. To rebuild them from the latest city data:

```bash
.venv/bin/python scripts/build_data.py --refresh
```

Known gaps: 96 intersections have no names in the city data (mostly Treasure Island,
Yerba Buena Island, Hunters Point and Mission Bay).
