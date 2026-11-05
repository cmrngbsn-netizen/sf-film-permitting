"""CSV bulk entry: rows become curb lines along the right side of the right blocks."""

from datetime import date, time

import pytest

from core.bulk import EXAMPLE, EXAMPLE_BLOCKS, StreetRoutes, parse_date, parse_dates, parse_time, plan
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


def test_alley_does_not_break_the_line(routes, zoner):
    # 800 Washington has alleys across it, but it's one block: one line, zones only on it.
    planned, _ = plan("Street,From,To,Side\nWashington,Stockton,Grant,south\n", routes)
    assert len(planned[0].lines) == 1
    assert {block for block, _ in zones(zoner, planned[0])} == {"800-890 Washington St"}


def test_rows_by_block(routes, zoner):
    planned, errors = plan(EXAMPLE_BLOCKS, routes)
    assert errors == []
    grant = next(p for p in planned if p.location == "Chinatown")
    assert grant.label == "800-890 Grant Ave, west side"
    assert zones(zoner, grant) == [("800-890 Grant Ave", "west")]


def test_part_of_a_block_is_a_shorter_line(routes, zoner):
    def feet(block):
        planned, errors = plan(f"Block,Side\n{block},west\n", routes)
        assert errors == []
        return sum(z.length_ft for line in planned[0].lines for z in zoner.zones(line))
    whole, half = feet("800-890 Grant Ave"), feet("800-850 Grant Ave")
    assert whole > 200 and 0.4 * whole < half < 0.7 * whole
    assert feet("800 Grant") == whole and feet("800 block of Grant Ave") == whole
    # The far half too: addresses count from the low end whichever way the data runs.
    far = plan("Block,Side\n850-890 Grant Ave,west\n", routes)[0][0].lines[0]
    near = plan("Block,Side\n800-850 Grant Ave,west\n", routes)[0][0].lines[0]
    assert far[0][0] > near[0][0]  # Grant addresses climb going north


def test_numbered_streets_with_their_type(routes, zoner):
    # The city data has "06TH ST"; people type "6th St". The type tells it from 6th Ave.
    planned, errors = plan("Block,Side\n400-490 6th St,west\n", routes)
    assert errors == [] and {block for block, _ in zones(zoner, planned[0])} == {"400-490 6th St"}
    planned, errors = plan("Street,From,To,Side\n6th Ave,Clement St,Geary Blvd,west\n", routes)
    assert errors == [] and planned[0].label.startswith("6th Ave")
    # Without the type it's a question.
    assert plan("Block,Side\n400-490 6th,west\n", routes)[1] == ['Row 2: "6th" could be 6th Ave or 6th St']


def test_several_blocks_in_one_row(routes, zoner):
    planned, errors = plan("Block,Side\n800-990 Grant Ave,west\n", routes)
    assert errors == [] and len(planned[0].lines) == 2
    assert zones(zoner, planned[0]) == [("800-890 Grant Ave", "west"), ("900-990 Grant Ave", "west")]


def test_block_errors_name_the_row(routes):
    text = "Block,Side\nGrant Ave,west\n30000-30090 Grant Ave,west\n800-890 Nowhere St,west\n890-800 Grant,west\n800-890 Grant,\n"
    _, errors = plan(text, routes)
    assert errors[0] == 'Row 2: block "Grant Ave" (use 800-890 Grant Ave)'
    assert errors[1] == "Row 3: no addresses 30000-30090 on Grant Ave"
    assert errors[2] == 'Row 4: no street called "Nowhere St"'
    assert errors[3].startswith('Row 5: block "890-800 Grant" runs backwards')
    assert errors[4] == "Row 6: missing Side"


def test_date_ranges(routes):
    assert [d.day for d in parse_dates("11/02/26-11/06/26")] == [2, 3, 4, 5, 6]
    assert [d.day for d in parse_dates("11/02/26 - 11/04/26")] == [2, 3, 4]
    assert [d.day for d in parse_dates("11/02/26 to 11/03/26")] == [2, 3]
    assert [d.day for d in parse_dates("11/02-11/04/26")] == [2, 3, 4]
    assert [d.day for d in parse_dates("2026-11-02-2026-11-03")] == [2, 3]
    assert [d.day for d in parse_dates("11-02-26")] == [2] and parse_dates("") == []
    planned, errors = plan("Block,Side,Date,Start,End\n800-890 Grant Ave,west,11/02/26-11/04/26,7am,7pm\n"
                           "800-890 Grant Ave,east,11/06/26-11/02/26,,\n", routes)
    assert len(planned[0].windows) == 3 and planned[0].windows[2].end == time(19)
    assert errors == ['Row 3: dates "11/06/26-11/02/26" run backwards']


def test_dates_and_times():
    assert parse_date("11/3/26") == parse_date("2026-11-03") == date(2026, 11, 3)
    assert parse_time("7am") == parse_time("7:00 AM") == time(7)
    assert parse_time("11:59 pm") == parse_time("23:59") == time(23, 59)
    assert parse_time("noon") == time(12) and parse_time("") is None
