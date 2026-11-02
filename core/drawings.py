"""Keeping what the map doesn't know (a line's color, a marker's kind and text) when the
drawing map reports its shapes back.

The map sends back plain geometry, in the order the shapes were added, after each single
action: drawing one shape, editing (moving points, never adding or removing shapes), or
deleting. So:
  - same count as before: an edit; shapes line up with the previous ones in order
  - more than before: the earlier ones are unchanged and in order; the extras are new
  - fewer than before: a delete; the remaining ones are unchanged, so match exact positions
"""


def _key(geometry):
    """Rounded coordinates, so an unchanged shape matches itself after the round trip."""
    if geometry and isinstance(geometry[0], (list, tuple)):
        return tuple((round(lat, 7), round(lon, 7)) for lat, lon in geometry)
    return (round(geometry[0], 7), round(geometry[1], 7))


def merge(previous, returned, geometry_of, with_geometry, new):
    """The updated list of shapes.
    previous: shapes from before; returned: geometries from the map, in map order;
    geometry_of(shape) -> its geometry; with_geometry(shape, geometry) -> a copy moved there;
    new(geometry) -> a shape drawn just now."""
    if len(returned) >= len(previous):
        kept = [with_geometry(old, geo) for old, geo in zip(previous, returned)]
        return kept + [new(geo) for geo in returned[len(previous):]]
    by_position = {}
    for old in previous:
        by_position.setdefault(_key(geometry_of(old)), []).append(old)
    out = []
    for geo in returned:
        matches = by_position.get(_key(geo))
        out.append(with_geometry(matches.pop(0), geo) if matches else new(geo))
    return out
