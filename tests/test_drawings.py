"""Lines keep their colors and markers their text through draw, edit and delete."""

from dataclasses import replace

from core.drawings import merge
from core.request import STAR, TEXT, Line, Marker

A = [(37.79, -122.40), (37.80, -122.40)]
B = [(37.78, -122.41), (37.78, -122.42)]
C = [(37.77, -122.43), (37.77, -122.44)]


def merge_lines(previous, returned, color="#2ca02c"):
    return merge(previous, returned, lambda l: l.points, lambda l, g: replace(l, points=g),
                 lambda g: Line(g, color))


def merge_markers(previous, returned, kind=STAR):
    return merge(previous, returned, lambda m: m.point, lambda m, g: replace(m, point=tuple(g)),
                 lambda g: Marker(tuple(g), kind))


def test_new_line_gets_the_current_color():
    old = [Line(A, "#d62728")]
    assert merge_lines(old, [A, B]) == [Line(A, "#d62728"), Line(B, "#2ca02c")]


def test_edited_line_keeps_its_color():
    old = [Line(A, "#d62728"), Line(B, "#1f77b4")]
    moved = [(37.785, -122.41), (37.78, -122.425)]
    assert merge_lines(old, [A, moved]) == [Line(A, "#d62728"), Line(moved, "#1f77b4")]


def test_deleting_keeps_the_others_colors():
    old = [Line(A, "#d62728"), Line(B, "#1f77b4"), Line(C, "#222222")]
    assert merge_lines(old, [A, C]) == [Line(A, "#d62728"), Line(C, "#222222")]


def test_markers_keep_kind_and_text():
    old = [Marker((37.79, -122.40), TEXT, "INT City Hall"), Marker((37.78, -122.41), STAR)]
    dragged = [37.791, -122.401]
    assert merge_markers(old, [dragged, [37.78, -122.41]]) == [
        Marker((37.791, -122.401), TEXT, "INT City Hall"), Marker((37.78, -122.41), STAR)]
    assert merge_markers(old, [[37.78, -122.41]]) == [Marker((37.78, -122.41), STAR)]
    assert merge_markers(old, [[37.79, -122.40], [37.78, -122.41], [37.77, -122.42]], TEXT)[2] == \
        Marker((37.77, -122.42), TEXT)
