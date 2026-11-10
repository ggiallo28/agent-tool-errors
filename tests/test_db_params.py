"""Parameter scanning and conversion, and OPSMEM_LOCAL_PG parsing. Offline."""
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opsmem import db

word = st.from_regex(r"[a-z]{1,8}", fullmatch=True)
name = st.from_regex(r"[a-z_][a-z0-9_]{0,8}", fullmatch=True)
piece = st.one_of(
    word.map(lambda w: ("text", w)),
    name.map(lambda n: ("param", n)),
    word.map(lambda w: ("cast", f"{w}::int")),
    st.just(("text", "%")),
    word.map(lambda w: ("text", f"100%{w}")),
)


def render(pieces):
    return " ".join(f":{v}" if kind == "param" else v for kind, v in pieces)


def back(converted: str) -> str:
    return re.sub(r"%\((\w+)\)s|%%", lambda m: f":{m.group(1)}" if m.group(1) else "%", converted)


# Feature: catalog-schema, Property 3: Local parameter conversion round trip
@settings(max_examples=100)
@given(st.lists(piece, min_size=1, max_size=12))
def test_property_conversion_round_trip(pieces):
    sql = render(pieces)
    converted = db.to_psycopg(sql)
    assert back(converted) == sql
    assert all(f"{v}" in converted for kind, v in pieces if kind == "cast")
    assert set(db.param_names(sql)) == {v for kind, v in pieces if kind == "param"}


def test_scanner_skips_strings_comments_and_dollar_quotes():
    sql = "SELECT ':a', \":b\", $$ :c $$, $t$ :d $t$ -- :e\n/* :f */ , :g"
    assert db.param_names(sql) == ["g"]


def test_scanner_leaves_casts_alone_and_escapes_percent():
    assert db.to_psycopg("SELECT :x::int, 'a%' LIKE :p") == "SELECT %(x)s::int, 'a%%' LIKE %(p)s"


def test_missing_parameter_is_named():
    with pytest.raises(ValueError, match="Missing parameter: b"):
        db.check_missing("SELECT :a, :b", {"a": 1})
    db.check_missing("SELECT :a", {"a": 1, "extra": 2})


def parse_oracle(value):
    """Written independently of the implementation: split on the colon."""
    parts = value.split(":")
    if len(parts) != 2 or not parts[0] or any(c.isspace() for c in value):
        return None
    host, port = parts
    if not port or not all(c in "0123456789" for c in port) or not 1 <= int(port) <= 65535:
        return None
    return host, int(port)


# Feature: catalog-schema, Property 7: OPSMEM_LOCAL_PG parsing
@settings(max_examples=200)
@given(st.one_of(
    st.text(max_size=20),
    st.builds(lambda h, p: f"{h}:{p}", st.from_regex(r"[a-z0-9.\-]{1,12}", fullmatch=True),
              st.integers(min_value=-5, max_value=70000)),
    st.builds(lambda h, p: f"{h}:{p}", st.sampled_from(["", "a b", "a:b"]), st.integers(min_value=1, max_value=99)),
))
def test_property_parse_local_pg(value):
    expected = parse_oracle(value)
    if expected is None:
        with pytest.raises(db.ConfigError, match="OPSMEM_LOCAL_PG"):
            db.parse_local_pg(value)
    else:
        assert db.parse_local_pg(value) == expected


@pytest.mark.parametrize("value", [None, "", "localhost", "localhost:", ":5432", "h:0", "h:65536", "h:12\n"])
def test_parse_local_pg_rejects(value):
    with pytest.raises(db.ConfigError, match="OPSMEM_LOCAL_PG"):
        db.parse_local_pg(value)
