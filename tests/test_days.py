"""Shoot days: grouping, ranges and merging."""

from datetime import date, time

from core.days import date_range, days_between, group_dates, group_days, group_hours, merge_days
from core.request import Location, Request
from core.summary import Window


def day(d, start=time(7), end=time(19)):
    return Window(date(2026, 11, d), start, end)


def test_consecutive_days_with_the_same_hours_group():
    groups = group_days([day(4), day(2), day(3), day(5, time(17), time(7)), day(6, time(17), time(7)), day(9)])
    assert [[w.date.day for w in g] for g in groups] == [[2, 3, 4], [5, 6], [9]]
    assert group_dates(groups[0]) == "Mon 11/02 - Wed 11/04"
    assert group_hours(groups[0]) == "3 days · 7:00 AM - 7:00 PM"
    assert group_hours(groups[1]) == "2 days · 5:00 PM - 7:00 AM (next day)"
    assert group_dates(groups[2]) == "Mon 11/09" and group_hours(groups[2]) == "7:00 AM - 7:00 PM"


def test_a_gap_in_dates_splits_the_group():
    assert len(group_days([day(2), day(4)])) == 2


def test_days_without_dates_or_hours():
    groups = group_days([Window(None, time(7), time(19)), Window(date(2026, 11, 2))])
    assert group_hours(groups[0]) == "Hours not set"
    assert group_dates(groups[1]) == "No date yet"


def test_days_between_keeps_the_weekdays_asked_for():
    assert len(days_between(date(2026, 11, 2), date(2026, 11, 15))) == 14
    weekdays = days_between(date(2026, 11, 2), date(2026, 11, 15), ["M", "Tu", "W", "Th", "F"])
    assert len(weekdays) == 10 and all(d.weekday() < 5 for d in weekdays)
    assert days_between(date(2026, 11, 2), date(2026, 11, 2), ["Su"]) == []


def test_a_new_day_replaces_that_date():
    merged, replaced = merge_days([day(2), day(3)], [day(3, time(9), time(17)), day(4)])
    assert [(w.date.day, w.start.hour) for w in merged] == [(2, 7), (3, 9), (4, 7)]
    assert replaced == 1
    # The same hours again aren't a replacement, and copies don't share windows.
    source = [day(2)]
    merged, replaced = merge_days([day(2)], source)
    assert replaced == 0 and merged[0] is not source[0]


def test_date_range():
    assert date_range([day(9), day(2)]) == "11/02 - 11/09"
    assert date_range([day(2)]) == "11/02" and date_range([Window()]) == ""


def test_has_content():
    req = Request()
    assert not req.has_content()
    req.locations[0].dates = [day(2)]
    assert req.has_content()
    assert Request(info={"Production": "x"}, locations=[Location()]).has_content()
