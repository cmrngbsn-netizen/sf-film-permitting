"""Curb zones on blocks from a real Film SF parking request. Run with: python -m pytest"""

import pytest

from core.curbs import CurbZoner, block_labels, place_name, place_names, short_street
from core.streets import StreetIndex, to_latlon


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


def test_place_names_for_several_lines(zoner):
    clay, wash = corner(zoner, "GRANT AVE", "CLAY ST"), corner(zoner, "GRANT AVE", "WASHINGTON ST")
    near_wash = zoner.zones(curb_line(clay, wash, 6, frac=(0.45, 0.97)))
    near_clay = zoner.zones(curb_line(clay, wash, -6, frac=(0.03, 0.55)))
    assert place_names([near_wash, near_clay]) == [
        "Grant @ Washington", "Grant @ Clay", "Grant @ Washington & Clay"]
    waverly = corner(zoner, "WASHINGTON ST", "WAVERLY PL")
    on_wash = zoner.zones(curb_line(wash, waverly, 6, frac=(0.1, 0.9)))
    names = place_names([near_wash, on_wash])
    assert names[0] == "Grant @ Washington" and names[-1] == " / ".join(names[:-1])
    assert place_names([near_wash, near_wash]) == ["Grant @ Washington"]
    assert place_names([[]]) == []


def test_crossing_an_alley_is_not_a_zone(zoner):
    # 800 Washington has Spofford, Ross and Waverly opening onto it.
    stockton, grant = corner(zoner, "WASHINGTON ST", "STOCKTON ST"), corner(zoner, "WASHINGTON ST", "GRANT AVE")
    zones = zoner.zones(curb_line(stockton, grant, 6, frac=(0.1, 0.9)))
    assert len(zones) > 1 and {z.block for z in zones} == {"800-890 Washington St"}
    # One count for the block side on the map, however many pieces the alleys make.
    labels = block_labels(zones, [2] * len(zones))
    assert [total for _, total in labels] == [2 * len(zones)]


def test_zone_names_the_addresses_it_covers(zoner):
    from core.bulk import StreetRoutes, plan
    routes = StreetRoutes(zoner.index)

    def stretch(block):
        planned, errors = plan(f"Block,Side\n{block},south\n", routes)
        assert errors == []
        return [z.stretch for z in zoner.zones(planned[0].lines[0])]
    assert stretch("2800-2890 Clay St") == ["2800-2890 Clay St"]
    assert stretch("2800-2845 Clay St") == ["2800-2845 Clay St"]
    assert stretch("2850-2890 Clay St") == ["2850-2890 Clay St"]
    assert stretch("2820-2860 Clay St") == ["2820-2860 Clay St"]


def test_alleys_and_meters_dont_split_the_addresses(zoner):
    from core.bulk import StreetRoutes, plan
    from core.curbdata import CurbData
    routes, data = StreetRoutes(zoner.index), CurbData()

    def stretches(block, side):
        planned, errors = plan(f"Block,Side\n{block},{side}\n", routes)
        assert errors == []
        return {z.stretch for z in data.join_pieces(zoner.zones(planned[0].lines[0]))}
    assert stretches("800-890 Washington St", "south") == {"800-890 Washington St"}
    assert stretches("800-850 Washington St", "south") == {"800-850 Washington St"}
    # Part metered, part not: two zones, one stretch of addresses.
    assert stretches("700-790 Clay St", "north") == {"700-790 Clay St"}
