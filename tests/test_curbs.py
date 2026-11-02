"""Curb zones on blocks from a real Film SF parking request. Run with: python -m pytest"""

import pytest

from core.curbs import CurbZoner, place_name, short_street
from core.streets import StreetIndex, to_latlon, to_xy


@pytest.fixture(scope="module")
def zoner():
    return CurbZoner(StreetIndex())


def corner(zoner, a, b):
    """(x, y) in meters of the intersection of streets a and b."""
    ix = zoner.index
    for cnn, xy in zip(ix.int_cnns, ix.int_xy):
        if {a, b} <= set(ix.node_names[cnn]):
            return xy
    raise LookupError(f"{a} & {b}")


def curb_line(start, end, offset_m, frac=(0.2, 0.8)):
    """A drawn line between two corners, shifted sideways off the centerline.
    Positive offset is to the left when walking from start to end."""
    (ax, ay), (bx, by) = start, end
    length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
    nx, ny = -(by - ay) / length * offset_m, (bx - ax) / length * offset_m
    return [to_latlon(ax + (bx - ax) * f + nx, ay + (by - ay) * f + ny) for f in frac]


def test_grant_800_block_west_side(zoner):
    # Grant Ave runs north from Clay to Washington; west is to the left.
    clay, wash = corner(zoner, "GRANT AVE", "CLAY ST"), corner(zoner, "GRANT AVE", "WASHINGTON ST")
    zones = zoner.zones(curb_line(clay, wash, 6))
    assert len(zones) == 1
    z = zones[0]
    assert z.block == "800-890 Grant Ave"
    assert z.side == "west"
    assert z.between in ("Clay St and Washington St", "Washington St and Clay St")
    block_ft = ((wash[0] - clay[0]) ** 2 + (wash[1] - clay[1]) ** 2) ** 0.5 / 0.3048
    assert z.length_ft == pytest.approx(block_ft * 0.6, rel=0.08)
    assert z.spaces == round(z.length_ft / 20)


def test_mcallister_400_block_north_side(zoner):
    # McAllister runs west from Polk to Van Ness; north is to the right, so negative offset.
    polk, van_ness = corner(zoner, "MCALLISTER ST", "POLK ST"), corner(zoner, "MCALLISTER ST", "VAN NESS AVE")
    zones = zoner.zones(curb_line(polk, van_ness, -7))
    assert [(z.block, z.side) for z in zones] == [("400-490 McAllister St", "north")]


def test_line_around_a_corner_gives_two_zones(zoner):
    # West curb of Grant going north to Washington, then the south curb of Washington going west.
    clay = corner(zoner, "GRANT AVE", "CLAY ST")
    wash = corner(zoner, "GRANT AVE", "WASHINGTON ST")
    waverly = corner(zoner, "WASHINGTON ST", "WAVERLY PL")
    up = curb_line(clay, wash, 6, frac=(0.5, 0.97))
    across = curb_line(wash, waverly, 6, frac=(0.1, 0.9))
    zones = zoner.zones(up + across)
    assert [z.street for z in zones] == ["Grant Ave", "Washington St"]
    assert zones[0].side == "west" and zones[1].side == "south"


def test_line_far_from_streets_gives_no_zones(zoner):
    # Middle of the Golden Gate Park polo field.
    assert zoner.zones([(37.7678, -122.4925), (37.7680, -122.4915)]) == []


def test_place_name_uses_the_nearer_cross_street(zoner):
    clay, wash = corner(zoner, "GRANT AVE", "CLAY ST"), corner(zoner, "GRANT AVE", "WASHINGTON ST")
    # Mostly the Washington end of the block.
    assert place_name(zoner.zones(curb_line(clay, wash, 6, frac=(0.45, 0.97)))) == "Grant @ Washington"
    # Mostly the Clay end.
    assert place_name(zoner.zones(curb_line(clay, wash, 6, frac=(0.03, 0.55)))) == "Grant @ Clay"
    assert place_name([]) == ""


def test_short_street():
    assert short_street("Grant Ave") == "Grant"
    assert short_street("Walter U Lum Pl") == "Walter U Lum"
    assert short_street("Broadway") == "Broadway"
    assert short_street("The Embarcadero") == "The Embarcadero"
