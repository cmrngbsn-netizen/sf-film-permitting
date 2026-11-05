"""Shoot days: a location's dates and hours as short groups, and adding many at once."""

from datetime import date, timedelta

from core.summary import Window, clock

WEEKDAYS = ["M", "Tu", "W", "Th", "F", "Sa", "Su"]  # in date.weekday() order


def short_day(day):
    """"Mon 11/02"."""
    return f"{day:%a %m/%d}"


def group_days(windows):
    """Runs of consecutive days with the same hours, in date order: [[Window, ...], ...]. A day
    with no date yet is a group of its own."""
    groups = []
    for w in sorted(windows, key=lambda w: (w.date or date.max, str(w.start), str(w.end))):
        last = groups[-1][-1] if groups else None
        if (last and w.date and last.date and w.date - last.date == timedelta(days=1)
                and (w.start, w.end) == (last.start, last.end)):
            groups[-1].append(w)
        else:
            groups.append([w])
    return groups


def group_dates(group):
    """"Mon 11/02 - Fri 11/06", or "Mon 11/02" for one day."""
    if group[0].date is None:
        return "No date yet"
    if len(group) == 1:
        return short_day(group[0].date)
    return f"{short_day(group[0].date)} - {short_day(group[-1].date)}"


def group_hours(group):
    """"5 days · 7:00 AM - 7:00 PM"; hours past midnight say so."""
    w = group[0]
    count = f"{len(group)} days · " if len(group) > 1 else ""
    if not (w.start and w.end):
        return count + (f"{clock(w.start or w.end)} only" if w.start or w.end else "Hours not set")
    return f"{count}{clock(w.start)} - {clock(w.end)}" + (" (next day)" if w.end <= w.start else "")


def date_range(windows):
    """"11/02 - 11/13" across all of a location's days, or "" if none have dates."""
    days = sorted(w.date for w in windows if w.date)
    if not days:
        return ""
    return f"{days[0]:%m/%d}" if days[0] == days[-1] else f"{days[0]:%m/%d} - {days[-1]:%m/%d}"


def days_between(first, last, weekdays=None):
    """The dates from first through last, keeping only `weekdays` (names from WEEKDAYS) if given."""
    keep = None if weekdays is None else {WEEKDAYS.index(d) for d in weekdays}
    return [first + timedelta(days=n) for n in range((last - first).days + 1)
            if keep is None or (first + timedelta(days=n)).weekday() in keep]


def merge_days(windows, new):
    """`windows` plus `new`. A new day replaces what that date had, so a date is never booked
    twice by accident. Returns (the merged list in date order, how many dates had other hours)."""
    dates = {w.date for w in new}
    replaced = {w.date for w in windows for n in new if w.date == n.date and (w.start, w.end) != (n.start, n.end)}
    kept = [w for w in windows if w.date not in dates]
    copies = [Window(w.date, w.start, w.end) for w in new]
    merged = [w for group in group_days(kept + copies) for w in group]
    return merged, len(replaced)
