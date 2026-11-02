"""Street names as Film SF writes them, and as the map search matches them."""

from core.streets import pretty_street, street_key


def test_pretty_street():
    assert pretty_street("18TH ST") == "18th St"
    assert pretty_street("VALENCIA ST") == "Valencia St"
    assert pretty_street("O'FARRELL ST") == "O'Farrell St"
    assert pretty_street("MCALLISTER ST") == "McAllister St"


def test_street_key():
    assert street_key("03RD ST") == "3RD"
    assert street_key("O'Farrell St.") == "OFARRELL"
    assert street_key("Grant Avenue") == "GRANT"
    assert street_key("BROADWAY") == "BROADWAY"
