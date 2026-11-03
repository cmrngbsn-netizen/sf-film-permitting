"""Film SF wording, checked against lines from a real parking request."""

from datetime import date, time

from core.summary import PICTURE, Window, ZoneRequest, dates_and_hours, street_side, summarize


def test_street_side_matches_film_sf_wording():
    z = ZoneRequest("400-490 McAllister St", "north", 8, meters="Metered")
    assert street_side(z) == "8 metered spaces on north side 400-490 McAllister St"
    z = ZoneRequest("200-290 Harriet St", "west", 2, meters="Non-metered")
    assert street_side(z) == "2 non-metered spaces on west side 200-290 Harriet St"
    assert street_side(ZoneRequest("800-890 Grant Ave", "west", 1)) == "1 space on west side 800-890 Grant Ave"


def test_dates_and_hours():
    assert dates_and_hours(Window(date(2026, 11, 2), time(7), time(23, 59))) == "MO, 11/02/26 7:00 AM - 11:59 PM"
    assert dates_and_hours(Window(date(2026, 11, 4), time(7), time(2))) == "WE, 11/04/26 7:00 AM - 2:00 AM (Next Day)"
    assert dates_and_hours(Window()) == ""


def test_shared_schedule_listed_once():
    day = [Window(date(2026, 11, 4), time(7), time(22))]
    zones = [
        ZoneRequest("800-890 Grant Ave", "west", 12, windows=day),
        ZoneRequest("800-890 Grant Ave", "west", 11, windows=day),
        ZoneRequest("700-790 Clay St", "north", 6, windows=day),
    ]
    s = summarize(zones)
    assert s["# of signs"] == "29 total spaces"
    assert s["Block #"] == ["800-890 Grant Ave", "700-790 Clay St"]
    assert s["Dates & hours"] == ["WE, 11/04/26 7:00 AM - 10:00 PM"]
    # Two pieces of one block side (split by an alley) are one line, as Film SF writes it.
    assert s["Street side"] == ["23 spaces on west side 800-890 Grant Ave", "6 spaces on north side 700-790 Clay St"]
    assert s["By color"] == []


def test_several_windows_and_different_schedules():
    # Like the Harriet St slide: prep, shoot and wrap on three days for one zone.
    prep_shoot_wrap = [Window(date(2026, 11, 3), time(7), time(23, 59)),
                       Window(date(2026, 11, 2), time(7), time(19)),
                       Window(date(2026, 11, 4), time(7), time(19))]
    zones = [ZoneRequest("200-290 Harriet St", "west", 2, windows=prep_shoot_wrap),
             ZoneRequest("400-450 6th St", "west", 8, windows=[Window(date(2026, 11, 3), time(7), time(23, 59))])]
    # Same line color: each schedule says which blocks it is for.
    assert summarize(zones, ["red", "red"])["Dates & hours"] == [
        "200-290 Harriet St (west): MO, 11/02/26 7:00 AM - 7:00 PM; "
        "TU, 11/03/26 7:00 AM - 11:59 PM; WE, 11/04/26 7:00 AM - 7:00 PM",
        "400-450 6th St (west): TU, 11/03/26 7:00 AM - 11:59 PM",
    ]
    # Line colors tell them apart: each line once, and a box per color, like the slides.
    s = summarize(zones, ["green", "red"])
    assert s["Dates & hours"] == ["MO, 11/02/26 7:00 AM - 7:00 PM", "TU, 11/03/26 7:00 AM - 11:59 PM",
                                  "WE, 11/04/26 7:00 AM - 7:00 PM"]
    assert [(c, len(d)) for c, _, d in s["By color"]] == [("green", 3), ("red", 1)]


def test_no_dates_yet():
    assert summarize([ZoneRequest("x", "north", 1, windows=[Window()])])["Dates & hours"] == []


def test_same_schedule_needs_no_color_boxes():
    wed = [Window(date(2026, 11, 4), time(7), time(22))]
    zones = [ZoneRequest("800-890 Grant Ave", "west", 12, windows=wed),
             ZoneRequest("800-890 Washington St", "south", 4, use=PICTURE, windows=wed)]
    s = summarize(zones, ["#d62728", "#1f77b4"])
    assert s["Dates & hours"] == ["WE, 11/04/26 7:00 AM - 10:00 PM"] and s["By color"] == []
