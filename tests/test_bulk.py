"""CSV bulk entry: rows become curb lines along the right side of the right blocks."""

from datetime import date, time

import pytest

from core.bulk import EXAMPLE, StreetRoutes, parse_date, parse_time, plan
from core.curbs import CurbZoner
from core.streets import StreetIndex
from core.summary import PICTURE, WORKING


@pytest.fixture(scope="module")
def index():
    return StreetIndex()


@pytest.fixture(scope="module")
def routes(index):
    return StreetRoutes(index)


@pytest.fixture(scope="module")
def zoner(index):
    return CurbZoner(index)


def zones(zoner, p):
    return [(z.block, z.side) for line in p.lines for z in zoner.zones(line)]


def test_example_rows(routes, zoner):
    planned, errors = plan(EXAMPLE, routes)
    assert errors == []
    by_label = {p.label: p for p in planned}
    mca = by_label["McAllister St from Polk St to Van Ness Ave, north side"]
    assert mca.location == "City Hall" and mca.use == WORKING
    assert zones(zoner, mca) == [("400-490 McAllister St", "north")]
    assert mca.windows[0].date == date(2026, 11, 3)
    # "both" makes one line per side.
    larkin = [p for p in planned if p.label.startswith("Larkin St")]
    assert {p.side for p in larkin} == {"east", "west"} and all(p.use == PICTURE for p in larkin)
    # Two rows for the same curb on different days: one line, two time windows.
    grant = by_label["Grant Ave from Clay St to Jackson St, west side"]
    assert grant.rows == [4, 5] and len(grant.windows) == 2
    assert zones(zoner, grant) == [("800-890 Grant Ave", "west"), ("900-990 Grant Ave", "west")]


def test_lines_stay_off_the_cross_streets(routes, zoner):
    planned, _ = plan("Street,From,To,Side\nGrant,Clay,Jackson,w\n", routes)
    assert all("Grant" in block for block, _ in zones(zoner, planned[0]))


def test_no_header_and_short_names(routes, zoner):
    planned, errors = plan(", 24th, Noe, Sanchez, s", routes)
    assert errors == []
    assert zones(zoner, planned[0]) == [("3900-3990 24th St", "south")]


def test_renamed_stretch_is_followed(routes):
    # Polk St in front of City Hall is officially Dr Carlton B Goodlett Pl.
    planned, errors = plan("Street,From,To,Side\nPolk,McAllister,Grove,east\n", routes)
    assert errors == [] and planned[0].label.startswith("Dr Carlton B Goodlett Pl")


def test_cross_street_names_come_from_the_corner(routes):
    planned, _ = plan("Street,From,To,Side\nValencia,16th,20th,west\n", routes)
    assert planned[0].label == "Valencia St from 16th St to 20th St, west side"


def test_errors_name_the_row(routes):
    text = ("Street,From,To,Side,Date\nGrant,Clay,Jackson,north,\nNowhere St,A,B,east,\n"
            "Grant,Clay,Jackson,west,13/45/26\nGrant,Clay,,west,\n")
    planned, errors = plan(text, routes)
    assert planned == []
    assert errors[0] == "Row 2: Grant Ave runs north-south there; its sides are east and west"
    assert errors[1] == 'Row 3: no street called "Nowhere St"'
    assert errors[2].startswith('Row 4: date "13/45/26"')
    assert errors[3] == "Row 5: missing To"


def test_dates_and_times():
    assert parse_date("11/3/26") == parse_date("2026-11-03") == date(2026, 11, 3)
    assert parse_time("7am") == parse_time("7:00 AM") == time(7)
    assert parse_time("11:59 pm") == parse_time("23:59") == time(23, 59)
    assert parse_time("noon") == time(12) and parse_time("") is None
