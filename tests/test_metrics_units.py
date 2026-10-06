"""Unit tests for pure helpers in rat.metrics: ancestors, commit sets, floats, CSV."""
from __future__ import annotations

from decimal import Decimal

import pytest

from rat.metrics import (
    REF_COLUMNS,
    _fmt_float,
    _path_sql,
    ancestors,
    parse_commit_set,
    rows_to_csv,
    set_label,
)


# ---- ancestors ----------------------------------------------------------------

def test_ancestors_nested():
    assert ancestors("src/pkg/mod.py") == ["src", "src/pkg"]


def test_ancestors_top_level_file():
    assert ancestors("README.md") == []


def test_ancestors_two_levels():
    assert ancestors("a/b") == ["a"]


# ---- commit sets --------------------------------------------------------------

def test_parse_commit_set_all():
    assert parse_commit_set("all") == ("all",)
    assert parse_commit_set("  all  ") == ("all",)


def test_parse_commit_set_since_range_list():
    assert parse_commit_set("since:1700000000") == ("since", 1700000000)
    assert parse_commit_set("range:100-200") == ("range", 100, 200)
    assert parse_commit_set("list:abc,def") == ("list", ("abc", "def"))
    assert parse_commit_set("list:") == ("list", ())


def test_parse_commit_set_invalid():
    with pytest.raises(ValueError):
        parse_commit_set("nonsense")
    with pytest.raises(ValueError):
        parse_commit_set("since:notanint")


def test_set_labels():
    assert set_label(("all",)) == "all"
    assert set_label(("since", 123)) == "since:123"
    assert set_label(("range", 10, 20)) == "range:10-20"
    assert set_label(("list", ("a", "b", "c"))) == "list:3"


# ---- float rendering ----------------------------------------------------------

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "0.0"),
        (1.0, "1.0"),
        (0.5, "0.5"),
        (-0.5, "-0.5"),
        (4.0, "4.0"),
        (0.00006546537699873979, "0.00006546537699873979"),
        (1e-05, "0.00001"),
        (3.7986055319092363e-06, "3.7986055319092363e-6"),
        (1.5e-07, "1.5e-7"),
    ],
)
def test_fmt_float_rendering(value, expected):
    assert _fmt_float(value) == expected


@pytest.mark.parametrize(
    "value",
    [0.0, 0.6, 1 / 3, 2 / 5, 1e-05, 3.7986055319092363e-06, 123456.789],
)
def test_fmt_float_round_trips(value):
    assert float(_fmt_float(value)) == value


# ---- CSV output ---------------------------------------------------------------

def _row(**over):
    base = dict.fromkeys(REF_COLUMNS, "")
    base.update(
        repo="r",
        ref_sha="abc",
        commit_set="all",
        commit_count=5,
        object_type="repository",
        path="/",
        author="ALL",
        added=7,
        removed=0,
        growth=7,
        churn=7,
        modifications=3,
    )
    base.update(over)
    return base


def test_rows_to_csv_header_and_line_endings():
    text = rows_to_csv([_row()])
    lines = text.split("\n")
    assert lines[0] == ",".join(REF_COLUMNS)
    assert "\r" not in text
    assert text.endswith("\n")
    assert len(lines) == 3  # header + 1 row + trailing empty


def test_rows_to_csv_formats_floats_and_empty_cells():
    row = _row(modification_frequency=3 * (1 / 5), ownership="")
    text = rows_to_csv([row])
    body = text.split("\n")[1]
    cells = body.split(",")
    idx = {name: i for i, name in enumerate(REF_COLUMNS)}
    assert cells[idx["modification_frequency"]] == _fmt_float(3 * (1 / 5))
    assert cells[idx["ownership"]] == ""
    assert cells[idx["churn_rate"]] == ""


def test_rows_to_csv_none_becomes_empty():
    text = rows_to_csv([_row(ownership=None)])
    assert text.split("\n")[1].split(",")[-1] == ""


# ---- path SQL -----------------------------------------------------------------

def test_path_sql_none_is_empty():
    assert _path_sql(None, "fs", {}) == ""


def test_path_sql_escapes_like_wildcards():
    params: dict = {}
    frag = _path_sql("a%b_c", "fs", params)
    assert params["pth"] == "a%b_c"
    assert params["pth_like"] == "a\\%b\\_c/%"
    assert "ESCAPE" in frag


def test_path_sql_escapes_backslash():
    params: dict = {}
    _path_sql("dir\\name", "fs", params)
    assert params["pth_like"] == "dir\\\\name/%"


# ---- decimal helper sanity ----------------------------------------------------

def test_decimal_format_matches_repr_digits():
    v = 0.30000000000000004
    assert _fmt_float(v) == format(Decimal(repr(v)), "f")
