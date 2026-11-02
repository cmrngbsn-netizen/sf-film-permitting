"""Saving and reopening a request."""

from datetime import date, time

import pytest

from core.request import Request
from core.summary import Window


def sample():
    req = Request()
    req.info.update({"Production": "Test Productions LLC", "Project": "Untitled Feature"})
    first = req.locations[0]
    first.info.update({"Location": "City Hall, McAllister @ Larkin & Polk", "Scene": "INT City Hall - SHOOT",
                       "Contact": "Pat Example", "Phone": "(415) 555-0100"})
    first.notes = "Crew parking on Grove"
    first.lines = [[(37.7806, -122.4180), (37.7807, -122.4170)]]
    first.zones = {"123:1:4": {"Curb": "6 meters (6 general)", "Meters": "Metered", "Spaces": 8,
                               "Use": "Working vehicles"}}
    first.windows = {"123:1:4": [Window(date(2026, 11, 2), time(7), time(23, 59)), Window()]}
    second = req.add_location()
    second.info["Location"] = "800 Block of Grant"
    return req


def test_round_trip_keeps_everything():
    req = sample()
    back = Request.from_json(req.to_json())
    assert back.info == req.info
    assert [loc.info for loc in back.locations] == [loc.info for loc in req.locations]
    assert back.locations[0].lines == req.locations[0].lines
    assert back.locations[0].zones == req.locations[0].zones
    assert back.locations[0].windows == req.locations[0].windows
    assert back.locations[0].notes == "Crew parking on Grove"
    assert [loc.id for loc in back.locations] == [loc.id for loc in req.locations]


def test_new_location_copies_contact():
    req = sample()
    assert req.locations[1].info["Contact"] == "Pat Example"
    assert req.locations[1].info["Phone"] == "(415) 555-0100"
    assert req.locations[1].info["Scene"] == ""


def test_removing_the_last_location_leaves_an_empty_one():
    req = Request()
    req.remove_location(req.locations[0].id)
    assert len(req.locations) == 1 and req.locations[0].lines == []


def test_rejects_other_files():
    with pytest.raises(ValueError):
        Request.from_json('{"type": "FeatureCollection"}')
    with pytest.raises(ValueError):
        Request.from_json('{"format": "sf-film-parking-request", "version": 99}')
