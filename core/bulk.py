"""Bulk entry: curb zones typed (or pasted from a spreadsheet) as CSV rows instead of drawn.

Each row names a curb side and either a block ("800-890 Grant Ave", or part of one:
"800-850 Grant Ave") or a street and the cross streets it runs between. The row becomes a
curb line along that side, which the app then splits into per-block zones like any drawn
line. Rows with the same Location share a PDF page; rows for the same curb with different
dates become extra time windows."""

import csv
import io
import math
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, time

from core.streets import pretty_street, street_key, to_latlon
from core.summary import USES, WORKING, Window

COLUMNS = ["Location", "Street", "From", "To", "Side", "Use", "Date", "Start", "End", "Block"]
EXAMPLE = """Location, Street, From, To, Side, Use, Date, Start, End
City Hall, McAllister St, Polk St, Van Ness Ave, north, Working vehicles, 11/03/26, 7:00 AM, 11:59 PM
City Hall, Larkin St, McAllister St, Grove St, both, Picture, 11/03/26, 7:00 AM, 11:59 PM
Chinatown, Grant Ave, Clay St, Jackson St, west, Working vehicles, 11/04/26, 6:00 AM, 10:00 PM
Chinatown, Grant Ave, Clay St, Jackson St, west, Working vehicles, 11/05/26, 6:00 AM, 2:00 PM
"""
EXAMPLE_BLOCKS = """Location, Block, Side, Use, Date, Start, End
City Hall, 400-490 McAllister St, north, Working vehicles, 11/03/26, 7:00 AM, 11:59 PM
City Hall, 200-250 Larkin St, west, Picture, 11/03/26, 7:00 AM, 11:59 PM
Chinatown, 800-890 Grant Ave, west, Working vehicles, 11/04/26, 6:00 AM, 10:00 PM
"""

CURB_OFFSET_M = 6   # a curb line runs this far off the street's centerline
END_TRIM_M = 10     # and stops short of each corner, so it doesn't reach the cross street
BLOCK_TEXT = re.compile(r"(\d+)(?:\s*-\s*(\d+))?\s+(?:block\s+of\s+)?(.+)", re.I)  # "800-890 Grant Ave"
COMPASS = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}
SIDE_WORDS = {"n": "north", "s": "south", "e": "east", "w": "west", "north": "north",
              "south": "south", "east": "east", "west": "west", "both": "both", "b": "both"}


@dataclass
class Planned:
    """One curb line to add, from one or more CSV rows for the same curb."""
    location: str
    label: str              # "McAllister St from Polk St to Van Ness Ave, north side"
    side: str
    use: str
    lines: list             # [[(lat, lon), ...], ...], one curb line per block
    windows: list = field(default_factory=list)  # [Window, ...]
    rows: list = field(default_factory=list)     # CSV row numbers it came from


def parse_date(text):
    text = text.strip()
    if not text:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%m-%d-%y", "%m-%d-%Y", "%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(text.replace(",", ""), fmt).date()
        except ValueError:
            pass
    raise ValueError(f'date "{text}" (use 11/03/26)')


def parse_time(text):
    """"7:00 AM", "7am", "19:00", "noon", "midnight" -> time."""
    t = text.strip().lower().replace(".", "")
    if not t:
        return None
    if t == "noon":
        return time(12)
    if t == "midnight":
        return time(0)
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a|p)?", t)
    if not m:
        raise ValueError(f'time "{text}" (use 7:00 AM)')
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ampm:
        if not 1 <= hour <= 12:
            raise ValueError(f'time "{text}"')
        hour = hour % 12 + (12 if ampm.startswith("p") else 0)
    if hour > 23 or minute > 59:
        raise ValueError(f'time "{text}"')
    return time(hour, minute)


def parse_use(text):
    t = text.strip().lower()
    if not t:
        return WORKING
    for use in USES:
        if use.lower().startswith(t) or t.startswith(use.lower().split()[0]):
            return use
    raise ValueError(f'use "{text}" (use {" or ".join(USES)})')


def address_range(seg):
    """A block's lowest and highest address, or None if it has none."""
    numbers = [seg[k] for k in ("lf_fadd", "lf_toadd", "rt_fadd", "rt_toadd") if seg[k]]
    return (min(numbers), max(numbers)) if numbers else None


def same_hundred(a, b):
    """Whether two pieces of a street are one hundred-block (an alley splits it, not a street)."""
    a, b = address_range(a), address_range(b)
    return bool(a and b) and a[0] // 100 == b[0] // 100


class StreetRoutes:
    """Finds a street's centerline between two cross streets."""

    def __init__(self, index):
        self.index = index
        self.by_key = defaultdict(set)             # search key -> full street names
        self.edges = defaultdict(list)             # street name -> [segment index, ...]
        for i, seg in enumerate(index.segments):
            own = " ".join(filter(None, [seg["street"], seg["st_type"]]))
            self.by_key[street_key(own)].add(own)
            self.edges[own].append(i)
        for names in index.node_names.values():
            for n in names:
                self.by_key[street_key(n)].add(n)

    def names(self, text):
        """Full names a typed street could mean: "Grant" -> {"GRANT AVE"}."""
        typed = text.strip()
        if not typed:
            return set()
        found = self.by_key.get(street_key(typed), set())
        # Typed with its type, e.g. "Mission St" vs "Mission Bay Blvd", or "6th St" vs "6th Ave".
        return {n for n in found if pretty_street(n).upper() == pretty_street(typed.upper()).upper()} or found

    def route(self, street, cross_a, cross_b):
        """The street's centerline from where it meets cross_a to where it meets cross_b, as
        one [(x, y), ...] per block (intersection to intersection), plus the names of the
        street and the two cross streets there. Raises ValueError with a reason the user
        can act on."""
        names = self.names(street)
        if not names:
            raise ValueError(f'no street called "{street}"')
        crosses = []
        for cross in (cross_a, cross_b):
            crosses.append(self.names(cross))
            if not crosses[-1]:
                raise ValueError(f'no street called "{cross}"')
        ends = [{cnn for cnn, at in self.index.node_names.items() if set(at) & names and set(at) & c}
                for c in crosses]
        for cross, nodes in zip((cross_a, cross_b), ends):
            if not nodes:
                raise ValueError(f"{street} doesn't meet {cross}")
        path = self._walk(names, *ends)
        if path is None:
            # A stretch can carry another name, e.g. Polk St in front of City Hall is
            # Dr Carlton B Goodlett Pl. Try any other street that meets both corners.
            for alt in ({n for c in ends[0] for n in self.index.node_names[c]}
                        & {n for c in ends[1] for n in self.index.node_names[c]}) - names - crosses[0] - crosses[1]:
                path = self._walk({alt}, *ends)
                if path:
                    break
        if path is None:
            raise ValueError(f"couldn't follow {street} from {cross_a} to {cross_b}")
        if not path:
            raise ValueError(f"{cross_a} and {cross_b} are the same corner of {street}")
        corners = set(self.index.int_cnns)
        segments = self.index.segments
        blocks = [[]]
        for step, (node, i, backwards) in enumerate(path):
            coords = self.index.seg_xy[i][::-1] if backwards else self.index.seg_xy[i]
            blocks[-1] += coords if not blocks[-1] else coords[1:]
            after = path[step + 1][1] if step + 1 < len(path) else None
            if node in corners and not (after is not None and same_hundred(segments[i], segments[after])):
                blocks.append([])
        blocks = [trim(b, END_TRIM_M, END_TRIM_M) for b in blocks
                  if b and sum(map(math.dist, b, b[1:])) > 3 * END_TRIM_M]
        seg = self.index.segments[path[0][1]]
        # "16th" could be 16th St or 16th Ave; name the one that's actually at the corner.
        corner_names = [sorted({n for c in e for n in self.index.node_names[c]} & c)[0]
                        for e, c in zip(ends, crosses)]
        if not blocks:
            raise ValueError(f"{street} from {cross_a} to {cross_b} is too short for a curb line")
        return blocks, " ".join(filter(None, [seg["street"], seg["st_type"]])), *corner_names

    def block(self, text):
        """The curb stretches named by a block or part of one, lowest address first:
        "800-890 Grant Ave", "800-850 Grant Ave", "800 Grant Ave" or "800 block of Grant Ave".
        One [(x, y), ...] per hundred-block, stopped short of the corners and cut to the
        addresses asked for (placed evenly along the block). Raises ValueError with a reason
        the user can act on."""
        found = BLOCK_TEXT.fullmatch(text.strip())
        if not found:
            raise ValueError(f'block "{text}" (use 800-890 Grant Ave)')
        low, high, street = int(found[1]), found[2], found[3]
        names = self.names(street)
        if not names:
            raise ValueError(f'no street called "{street}"')
        low, high = (low // 100 * 100, low // 100 * 100 + 99) if high is None else (low, int(high))
        if high < low:
            raise ValueError(f'block "{text}" runs backwards (use 800-890 Grant Ave)')
        hits = sorted(((address_range(self.index.segments[i]), i) for name in names for i in self.edges[name]
                       if address_range(self.index.segments[i])), key=lambda hit: hit[0])
        hits = [(r, i) for r, i in hits if r[0] <= high and r[1] >= low]
        if not hits:
            raise ValueError(f"no addresses {low}-{high} on {pretty_street(sorted(names)[0])}")
        own = {" ".join(filter(None, [self.index.segments[i]["street"], self.index.segments[i]["st_type"]]))
               for _, i in hits}
        if len(own) > 1:
            raise ValueError(f'"{street}" could be ' + " or ".join(pretty_street(n) for n in sorted(own)))
        # "800-890" is how a whole block is written, though its addresses run on to 898.
        top = max(r[1] for r, _ in hits)
        if high >= top // 10 * 10:
            high = top
        blocks = []  # [points, trim the start?, trim the end?, last segment index]
        for (first, last), i in hits:
            seg = self.index.segments[i]
            pts = self.index.seg_xy[i]
            start, stop = seg["lf_fadd"] or seg["rt_fadd"], seg["lf_toadd"] or seg["rt_toadd"]
            if start > stop:
                pts = pts[::-1]  # lowest address first
            length, span = self.index.seg_length[i], (last - first) or 1
            cut_a = max(0, low - first) / span * length
            cut_b = max(0, last - high) / span * length
            if cut_a + cut_b >= length - 1:
                continue  # only touches the range at its very end
            pts = trim(pts, cut_a, cut_b)
            if blocks and same_hundred(self.index.segments[blocks[-1][3]], seg) and math.dist(blocks[-1][0][-1], pts[0]) < 5:
                blocks[-1][0] += pts[1:]
                blocks[-1][2], blocks[-1][3] = not cut_b, i
            else:
                blocks.append([list(pts), not cut_a, not cut_b, i])
        lines = [trim(p, END_TRIM_M if a else 0, END_TRIM_M if b else 0) for p, a, b, _ in blocks
                 if sum(map(math.dist, p, p[1:])) > (END_TRIM_M if a else 0) + (END_TRIM_M if b else 0) + 3]
        if not lines:
            raise ValueError(f"{low}-{high} {pretty_street(next(iter(own)))} is too short for a curb line")
        return lines, next(iter(own))

    def _walk(self, names, starts, goals):
        """[(node reached, segment, walked backwards), ...] along streets called `names`
        from any start node to any goal node, or None if they don't connect."""
        graph = defaultdict(list)
        for name in names:
            for i in self.edges[name]:
                seg = self.index.segments[i]
                graph[seg["f_node_cnn"]].append((seg["t_node_cnn"], i, False))
                graph[seg["t_node_cnn"]].append((seg["f_node_cnn"], i, True))
        queue, came = deque(starts), {n: None for n in starts}
        while queue:
            node = queue.popleft()
            if node in goals:
                path = []
                while came[node] is not None:
                    prev, i, backwards = came[node]
                    path.append((node, i, backwards))
                    node = prev
                return path[::-1]
            for nxt, i, backwards in graph[node]:
                if nxt not in came:
                    came[nxt] = (node, i, backwards)
                    queue.append(nxt)
        return None


def trim(pts, start_m, end_m):
    """The polyline with start_m cut off its start and end_m off its end."""
    def cut(p, m):
        out = [p[0]]
        for a, b in zip(p, p[1:]):
            d = math.dist(a, b)
            if m >= d:
                m -= d
                out = [b]
                continue
            f = m / d
            out = [(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)] + p[p.index(b):]
            return out
        return out
    return cut(cut(pts, start_m)[::-1], end_m)[::-1]


def offset(pts, side):
    """The polyline shifted CURB_OFFSET_M toward a compass side ("north", ...)."""
    cx, cy = COMPASS[side]
    out = []
    for i, (x, y) in enumerate(pts):
        a, b = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1
        nx, ny = -dy / length, dx / length          # left of the direction of travel
        if nx * cx + ny * cy < 0:
            nx, ny = -nx, -ny
        out.append((x + nx * CURB_OFFSET_M, y + ny * CURB_OFFSET_M))
    return out


def sides_of(blocks):
    """The two curb sides of a street running along blocks: ("north", "south") or ("east", "west")."""
    dx, dy = blocks[-1][-1][0] - blocks[0][0][0], blocks[-1][-1][1] - blocks[0][0][1]
    return ("north", "south") if abs(dx) >= abs(dy) else ("east", "west")


def read_rows(text):
    """CSV text -> [(row number, {column: value})]. The header row can use any case or
    order; a missing header means the columns are in COLUMNS order."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    reader = csv.reader(io.StringIO("\n".join(lines)), skipinitialspace=True)
    rows = [[c.strip() for c in r] for r in reader]
    wanted = {c.lower(): c for c in COLUMNS}
    named = {c.lower() for c in rows[0]} & set(wanted)
    if named >= {"street", "from", "to"} or "block" in named:
        header, body, first = [wanted.get(c.lower(), c) for c in rows[0]], rows[1:], 2
    else:
        header, body, first = COLUMNS, rows, 1
    return [(n, dict(zip(header, r))) for n, r in enumerate(body, start=first)
            if any(r)]


def plan(text, routes):
    """CSV text -> ([Planned, ...], [error message, ...])."""
    planned, errors = {}, []
    for n, row in read_rows(text):
        try:
            by_block = bool(row.get("Block", "").strip())
            required = ["Side"] if by_block else ["Street", "From", "To", "Side"]
            missing = [c for c in required if not row.get(c, "").strip()]
            if missing:
                raise ValueError(f"missing {', '.join(missing)}")
            side = SIDE_WORDS.get(row["Side"].strip().lower())
            if not side:
                raise ValueError(f'side "{row["Side"]}" (use north, south, east, west or both)')
            use = parse_use(row.get("Use", ""))
            day = parse_date(row.get("Date", ""))
            start, end = parse_time(row.get("Start", "")), parse_time(row.get("End", ""))
            if by_block:
                blocks, own = routes.block(row["Block"])
                name = row["Block"].strip()
            else:
                blocks, own, cross_a, cross_b = routes.route(row["Street"], row["From"], row["To"])
                name = f"{pretty_street(own)} from {pretty_street(cross_a)} to {pretty_street(cross_b)}"
            allowed = sides_of(blocks)
            if side == "both":
                sides = list(allowed)
            elif side in allowed:
                sides = [side]
            else:
                raise ValueError(f"{pretty_street(own)} runs {'east-west' if allowed[0] == 'north' else 'north-south'} "
                                 f"there; its sides are {allowed[0]} and {allowed[1]}")
        except ValueError as e:
            errors.append(f"Row {n}: {e}")
            continue
        location = row.get("Location", "").strip()
        for s in sides:
            key = (location.lower(), name.lower(), s, use)
            if key not in planned:
                lines = [[to_latlon(x, y) for x, y in offset(b, s)] for b in blocks]
                planned[key] = Planned(location, f"{name}, {s} side", s, use, lines)
            p = planned[key]
            p.rows.append(n)
            if day or start or end:
                p.windows.append(Window(day, start, end))
    return list(planned.values()), errors
