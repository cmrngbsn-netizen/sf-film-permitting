"""Saving and reopening a request."""

import json
from datetime import date, time

import pytest

from core.request import STAR, TEXT, Arrow, Line, Marker, Request, format_phone, text_size
from core.summary import Window


def sample():
    req = Request()
    req.info.update({"Production": "Test Productions LLC", "Project": "Untitled Feature"})
    first = req.locations[0]
    first.info.update({"Location": "City Hall, McAllister @ Larkin & Polk",
                       "Contact": "Pat Example", "Phone": "(415) 555-0100"})
    first.scenes = ["INT City Hall - SHOOT", "EXT Polk St - PREP"]
    first.notes = "Crew parking on Grove"
    first.lines = [Line([(37.7806, -122.4180), (37.7807, -122.4170)], "#1f77b4")]
    first.markers = [Marker((37.7795, -122.4189), STAR), Marker((37.7801, -122.4175), TEXT, "INT City Hall", 22, "#2ca02c")]
    first.arrows = [Arrow([(37.7801, -122.4175), (37.7806, -122.4178)])]
    first.auto_name = False
    first.zones = {"123:1:4": {"Curb": "6 meters (6 general)", "Meters": "Metered", "Spaces": 8,
                               "Use": "Working vehicles"}}
    first.dates = [Window(date(2026, 11, 2), time(7), time(23, 59))]
    first.windows = {"123:1:4": [Window(date(2026, 11, 3), time(6), time(20)), Window()]}
    second = req.add_location()
    second.info["Location"] = "800 Block of Grant"
    return req


def test_round_trip_keeps_everything():
    req = sample()
    back = Request.from_json(req.to_json())
    assert back.info == req.info
    assert [loc.info for loc in back.locations] == [loc.info for loc in req.locations]
    assert back.locations[0].lines == req.locations[0].lines
    assert back.locations[0].markers == req.locations[0].markers
    assert back.locations[0].arrows == req.locations[0].arrows
    assert back.locations[0].auto_name is False and back.locations[1].auto_name is True
    assert back.locations[0].zones == req.locations[0].zones
    assert back.locations[0].windows == req.locations[0].windows
    assert back.locations[0].dates == req.locations[0].dates
    assert back.locations[0].notes == "Crew parking on Grove"
    assert back.locations[0].scenes == ["INT City Hall - SHOOT", "EXT Polk St - PREP"]
    assert [loc.id for loc in back.locations] == [loc.id for loc in req.locations]


def test_new_location_copies_contact():
    req = sample()
    assert req.locations[1].info["Contact"] == "Pat Example"
    assert req.locations[1].info["Phone"] == "(415) 555-0100"
    assert req.locations[1].scenes == []


def test_removing_the_last_location_leaves_an_empty_one():
    req = Request()
    req.remove_location(req.locations[0].id)
    assert len(req.locations) == 1 and req.locations[0].lines == []


def test_rejects_other_files():
    with pytest.raises(ValueError):
        Request.from_json('{"type": "FeatureCollection"}')
    with pytest.raises(ValueError):
        Request.from_json('{"format": "sf-film-parking-request", "version": 99}')


def test_opens_version_1_files():
    v1 = ('{"format": "sf-film-parking-request", "version": 1, "info": {}, "locations": ['
          '{"id": "a1", "info": {"Location": "Grant @ Washington"}, "lines": [[[37.79, -122.40], [37.80, -122.41]]]}]}')
    loc = Request.from_json(v1).locations[0]
    assert loc.lines == [Line([(37.79, -122.40), (37.80, -122.41)])]
    assert loc.lines[0].color == "#d62728"
    assert loc.markers == [] and loc.auto_name is False


def test_format_phone():
    for typed in ("4159351007", "415-935-1007", "415.935.1007", "(415)935 1007", "1 415 935 1007"):
        assert format_phone(typed) == "(415) 935-1007"
    # Digits only, formatted as far as they go, the way the field formats while typing.
    assert format_phone("415-935-1007 x12") == "(415) 935-1007"
    assert format_phone("415") == "(415"
    assert format_phone("41593") == "(415) 93"
    assert format_phone("call me") == ""


def test_opens_version_2_scene_field():
    v2 = ('{"format": "sf-film-parking-request", "version": 2, "info": {}, "locations": ['
          '{"id": "a1", "info": {"Location": "City Hall", "Scene": "INT City Hall - SHOOT"}, '
          '"markers": [{"point": [37.78, -122.42], "kind": "Text box", "text": "PICTURE"}]}]}')
    loc = Request.from_json(v2).locations[0]
    assert loc.scenes == ["INT City Hall - SHOOT"]
    assert loc.markers[0].size == 14 and loc.markers[0].color == "#222222"
    assert loc.arrows == []


def test_text_size():
    assert text_size("Large") == 18 and text_size("X-Large") == 24
    assert text_size(20) == 20 and text_size(99) == 36 and text_size(2) == 10
    assert text_size(None) == 14


def test_location_dates_apply_unless_a_zone_has_its_own():
    loc = Request().locations[0]
    loc.dates = [Window(date(2026, 11, 4), time(7), time(22))]
    loc.windows = {"b": [Window(date(2026, 11, 5), time(6), time(14))]}
    assert loc.windows_for("a") == loc.dates
    assert loc.windows_for("b")[0].date == date(2026, 11, 5)


def test_version_4_matching_zone_times_become_location_dates():
    day = {"date": "2026-11-04", "start": "07:00", "end": "22:00"}
    v4 = ('{"format": "sf-film-parking-request", "version": 4, "locations": [{"id": "a1", '
          '"windows": {"z1": [D], "z2": [D]}}, {"id": "a2", "windows": {"z1": [D], "z2": [E]}}]}')
    v4 = v4.replace("D", json.dumps(day)).replace("E", json.dumps({**day, "end": "23:00"}))
    same, different = Request.from_json(v4).locations
    assert same.dates == [Window(date(2026, 11, 4), time(7), time(22))] and same.windows == {}
    assert len(different.windows) == 2 and different.dates == []
