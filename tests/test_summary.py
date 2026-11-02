"""Film SF wording, checked against lines from a real parking request."""

from datetime import date, time

from core.summary import ZoneRequest, dates_and_hours, street_side, summarize


def test_street_side_matches_film_sf_wording():
    z = ZoneRequest("400-490 McAllister St", "north", 8, meters="Metered")
    assert street_side(z) == "8 metered spaces on north side 400-490 McAllister St"
    z = ZoneRequest("200-290 Harriet St", "west", 2, meters="Non-metered")
    assert street_side(z) == "2 non-metered spaces on west side 200-290 Harriet St"
    assert street_side(ZoneRequest("800-890 Grant Ave", "west", 1)) == "1 space on west side 800-890 Grant Ave"


def test_dates_and_hours():
    z = ZoneRequest("x", "north", 1, date=date(2026, 11, 2), start=time(7), end=time(23, 59))
    assert dates_and_hours(z) == "MO, 11/02/26 7:00 AM - 11:59 PM"
    z = ZoneRequest("x", "north", 1, date=date(2026, 11, 4), start=time(7), end=time(2))
    assert dates_and_hours(z) == "WE, 11/04/26 7:00 AM - 2:00 AM (Next Day)"
    assert dates_and_hours(ZoneRequest("x", "north", 1)) == ""


def test_summary_totals_and_dedupes():
    day = dict(date=date(2026, 11, 4), start=time(7), end=time(22))
    zones = [
        ZoneRequest("800-890 Grant Ave", "west", 12, **day),
        ZoneRequest("800-890 Grant Ave", "west", 11, **day),
        ZoneRequest("700-790 Clay St", "north", 6, **day),
    ]
    s = summarize(zones)
    assert s["# of signs"] == "29 total spaces"
    assert s["Block #"] == ["800-890 Grant Ave", "700-790 Clay St"]
    assert s["Dates & hours"] == ["WE, 11/04/26 7:00 AM - 10:00 PM"]
    assert len(s["Street side"]) == 3
    assert s["Curb notes"] == []


def test_curb_notes():
    z = ZoneRequest("800-890 Grant Ave", "west", 12, curb="12 meters (7 general, 5 yellow (commercial loading))")
    assert summarize([z])["Curb notes"] == [
        "800-890 Grant Ave, west side: 12 meters (7 general, 5 yellow (commercial loading))"]
