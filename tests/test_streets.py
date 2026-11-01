"""Checks the labels against known SF intersections. Run with: python -m pytest"""

import pytest

from core.streets import StreetIndex, pretty_street, to_latlon, to_xy

VALENCIA_18TH = (37.761701, -122.421578)  # node 24160000


@pytest.fixture(scope="module")
def index():
    return StreetIndex()


def offset(latlon, east_m, north_m):
    x, y = to_xy(*latlon)
    return to_latlon(x + east_m, y + north_m)


def test_pretty_street():
    assert pretty_street("18TH ST") == "18th St"
    assert pretty_street("VALENCIA ST") == "Valencia St"
    assert pretty_street("O'FARRELL ST") == "O'Farrell St"


@pytest.mark.parametrize("east, north, corner", [(8, 8, "NE"), (-8, 8, "NW"), (8, -8, "SE"), (-8, -8, "SW")])
def test_corners(index, east, north, corner):
    result = index.label_point(*offset(VALENCIA_18TH, east, north))
    assert result.kind == "corner"
    assert result.label in (f"{corner} corner, 18th St & Valencia St",
                            f"{corner} corner, Valencia St & 18th St")
    assert result.snap_lat == pytest.approx(VALENCIA_18TH[0], abs=1e-5)
    assert result.snap_lon == pytest.approx(VALENCIA_18TH[1], abs=1e-5)
    assert 30 < result.distance_ft < 45  # about 11 m from the center


def test_center(index):
    assert index.label_point(*VALENCIA_18TH).label.startswith("Center of ")


def test_mid_block(index):
    # About 45 m north of 18th St on Valencia's east side, short of Sycamore St.
    result = index.label_point(*offset(VALENCIA_18TH, 9, 45))
    assert result.kind == "mid-block"
    assert result.label in ("Valencia St, east side, between 18th St and Sycamore St",
                            "Valencia St, east side, between Sycamore St and 18th St")
    assert result.distance_ft == 0


def test_mid_block_east_west_street(index):
    # On 18th St, about 38 m west of Valencia (short of Lapidge St), north side.
    result = index.label_point(*offset(VALENCIA_18TH, -38, 9))
    assert result.kind == "mid-block"
    assert result.label.startswith("18th St, north side, between ")
    assert "Valencia St" in result.label
