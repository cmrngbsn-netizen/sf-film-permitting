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
    info = CurbInfo(Counter({"Grey": 7, "Yellow": 5, "Black": 2}), [("driveway", 9), ("driveway", 9)])
    assert info.car_meters == 12
    assert info.metered
    assert info.suggested_spaces(280) == 12
    assert info.describe() == ("14 meters (7 general, 5 yellow (commercial loading), 2 black (motorcycle)); "
                               "2 driveways (18 ft)")


def test_unmetered_spaces_skip_driveways():
    info = CurbInfo(zones=[("driveway", 10), ("driveway", 10), ("blue zone (disabled)", 20)])
    assert not info.metered
    assert info.suggested_spaces(200) == 9  # (200 - 20) / 20
    assert info.describe() == "2 driveways (20 ft); 1 blue zone (disabled) (20 ft)"
    assert CurbInfo().describe() == "no meters or color curbs on record"


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
