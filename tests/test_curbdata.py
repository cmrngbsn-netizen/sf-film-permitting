"""Meters and color curbs on a zone. The live-data checks use loose bounds because
SFMTA updates meters weekly."""

from collections import Counter

import pytest

from core.curbdata import CurbData, CurbInfo
from core.curbs import CurbZoner
from core.streets import StreetIndex
from tests.test_curbs import corner, curb_line


@pytest.fixture(scope="module")
def zoner():
    return CurbZoner(StreetIndex())


@pytest.fixture(scope="module")
def curbs():
    return CurbData()


def main_zone(zoner, street, a, b, offset):
    zones = zoner.zones(curb_line(corner(zoner, street, a), corner(zoner, street, b), offset,
                                  frac=(0.05, 0.95)))
    return max(zones, key=lambda z: z.length_ft)


def test_describe_and_spaces():
    info = CurbInfo(Counter({"Grey": 7, "Yellow": 5, "Black": 2}), [("red-curb driveway", 9), ("red-curb driveway", 9)])
    assert info.car_meters == 12
    assert info.metered
    assert info.suggested_spaces(280) == 12
    # The Curb column says which meters the 12 spaces are, and that motorcycle meters aren't.
    assert info.describe() == ("7 general meters, 5 yellow loading meters, 2 motorcycle meters (not counted), "
                               "2 red-curb driveways")


def test_unmetered_spaces_skip_driveways():
    info = CurbInfo(zones=[("red-curb driveway", 10), ("red-curb driveway", 10), ("blue zone", 20)])
    assert not info.metered
    assert info.suggested_spaces(200) == 9  # (200 - 20) / 20
    assert info.describe() == "2 red-curb driveways, blue zone 20 ft"
    assert CurbInfo().describe() == "None on record"


def test_grant_800_west_side_is_metered(zoner, curbs):
    # A real Film SF request asked for "12 metered spaces on west side Grant" here.
    info = curbs.lookup(main_zone(zoner, "GRANT AVE", "CLAY ST", "WASHINGTON ST", 6))
    assert info.metered
    assert 8 <= info.car_meters <= 16


def test_sides_are_kept_apart(zoner, curbs):
    west = curbs.lookup(main_zone(zoner, "GRANT AVE", "CLAY ST", "WASHINGTON ST", 6))
    east = curbs.lookup(main_zone(zoner, "GRANT AVE", "CLAY ST", "WASHINGTON ST", -6))
    assert west.meters != east.meters


def test_curb_data_has_a_build_date(curbs):
    assert len(curbs.built) == 10


def test_census_counts_driveways_on_unmetered_curb(zoner, curbs):
    # 29th Ave in the Sunset has a driveway at nearly every house, but almost none are
    # painted red. The census (about 31 spaces on the block) catches them; 20 ft per space
    # on the 618 ft side would claim about 31 spaces for one side alone.
    zone = main_zone(zoner, "29TH AVE", "JUDAH ST", "KIRKHAM ST", 6)
    info = curbs.lookup(zone)
    assert not info.metered and info.census is not None
    assert 8 <= info.suggested_spaces(zone.length_ft) <= 20
    assert "census" not in info.describe()  # the Curb column lists only what's on the curb


def test_metered_curb_ignores_census():
    info = CurbInfo(Counter({"Grey": 6}), census=3.0, census_year=2010)
    assert info.suggested_spaces(200) == 6
    assert "census" not in info.describe()


def test_pieces_of_a_block_side_join_into_one_zone():
    from core.bulk import StreetRoutes, plan
    from core.curbs import CurbZoner
    from core.streets import StreetIndex

    index = StreetIndex()
    zoner, data, routes = CurbZoner(index), CurbData(), StreetRoutes(index)
    line = plan("Block,Side\n800-890 Washington St,south\n", routes)[0][0].lines[0]
    pieces = zoner.zones(line)
    zones = data.join_pieces(pieces)
    assert len(pieces) > 1 and len(zones) < len(pieces)
    # Joining changes the rows, not what's on the curb.
    assert sum(data.lookup(z).suggested_spaces(z.length_ft) for z in zones) == sum(
        data.lookup(p).suggested_spaces(p.length_ft) for p in pieces)
    assert round(sum(z.length_ft for z in zones)) == round(sum(p.length_ft for p in pieces))
    # Metered and unmetered stay apart: a request writes them separately.
    for z in zones:
        assert len({data.lookup(p).metered for p in z.parts or [z]}) == 1
    if len(zones) == 1:
        assert set(zones[0].between.split(" and ")) == {"Grant Ave", "Stockton St"}
