# SF Film Parking Request (beta)

Plan the street parking a film shoot in San Francisco needs, and export it as a parking
request PDF in the format Film SF expects, with one page per location.

1. **Start**: what the tool does, a sample page, and the shoot info (production, project,
   email and permit number) shared by every page.
2. **Locations & curbs**: draw lines along the curbs you need (or import them from CSV
   under *Add location*). Each line is split into one zone per block and named the way
   Film SF does ("400-490 McAllister St, north side"). Set the location's dates and hours
   once; a zone can have its own.
3. **Review & PDF**: preview every page, then download the PDF.

Work is kept in the browser as it's entered, and offered back when the page is opened again.
Requests can also be saved to and opened from a `.json` file (Save / Open in the top bar).

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

## Tests

```bash
.venv/bin/pip install pytest pypdf
.venv/bin/python -m pytest
```

## Layout

- `app.py`: the Streamlit app (steps, map, tables, PDF preview).
- `core/map_tools.py`: the map's tools, written in JavaScript inside the map.
- `core/curbs.py`, `core/streets.py`: lines to per-block curb zones, street names.
- `core/curbdata.py`: meters, color curbs and the parking census for a zone.
- `core/summary.py`, `core/pdf.py`: Film SF wording and the PDF.
- `core/request.py`: the request and its save file. `core/bulk.py`: CSV import.
- `core/days.py`: shoot days as short groups, and adding many at once.
- `components/autosave/`: keeps the request in the browser's storage.
- `core/methods.py`: the Sources & methods text shown in the app.
- `core/feedback.py`: the Feedback button's email. Its address and password live in Streamlit's
  secrets (format at the top of the file), and the button stays hidden without them.
- `scripts/build_data.py`: rebuilds `data/` and `static/` from city data.

## Street and curb data

- `data/segments.geojson` (street blocks with address ranges) and `data/nodes.json` (street
  names at each intersection) come from DataSF datasets `3psu-pn9h` and `gmfx-8h6i`.
- `data/curbs.json` holds SFMTA's active on-street meters (by cap color), color curbs, and
  the on-street parking census (legal spaces per block, counted 2008-2014). The census
  sets the space count on unmetered curb because it accounts for every driveway; SFMTA's
  color curb data only has driveways painted red.
- `static/intersections.json` is the intersection list the map's search uses.
- `static/sample-page.jpg` is the example page on the start screen, made in the app from a
  made-up shoot (the CSV import example plus invented contact details).

SFMTA updates meters weekly, so rebuild every few weeks to stay current:

```bash
.venv/bin/python scripts/build_data.py --refresh
```

Known gaps: 96 intersections have no names in the city data (mostly Treasure Island,
Yerba Buena Island, Hunters Point and Mission Bay).
