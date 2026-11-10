"""Statement splitting and the apply flow with a spy database (Properties 10 to 12).
The local_pg example for a second run is at the end of the file."""
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.helpers import ROOT, load_script
from tests.spy import SpyDatabase

apply = load_script("apply_schema")
SEP = apply.SEPARATOR

middle = st.sampled_from(["", "-- a comment", "a;b", "$$ x; y $$", "  indented", "/* block */"])


@st.composite
def statement(draw):
    tag = draw(st.integers(min_value=0, max_value=10**6))
    lines = [f"SELECT {tag}"] + draw(st.lists(middle, max_size=4)) + [f"FROM t{tag};"]
    return "\n".join(lines)


def joined(statements):
    return ("\n" + SEP + "\n").join(statements)


# Feature: catalog-schema, Property 10: Statement splitting round trip
@settings(max_examples=100)
@given(st.lists(statement(), min_size=1, max_size=8))
def test_property_split_round_trip(statements):
    found = apply.split_statements(joined(statements))
    assert [s.sql for s in found] == statements
    assert [s.index for s in found] == list(range(1, len(statements) + 1))
    line = 1
    for st_, original in zip(found, statements):
        assert st_.start_line == line
        line += original.count("\n") + 1 + 1  # its lines, then the separator line


def test_splitting_drops_comment_only_chunks_and_keeps_line_numbers():
    text = f"-- header\n{SEP}\n\nSELECT 1\n{SEP}\n/* only */\n{SEP}\nSELECT 2\n"
    found = apply.split_statements(text)
    assert [(s.sql, s.index, s.start_line) for s in found] == [("SELECT 1", 1, 4), ("SELECT 2", 2, 8)]


def test_separator_inside_a_line_does_not_split():
    text = f"SELECT '{SEP}'\n-- {SEP} not alone\nFROM t"
    assert len(apply.split_statements(text)) == 1


# --- apply flow ---

@pytest.fixture
def local(monkeypatch):
    monkeypatch.setenv("OPSMEM_LOCAL_PG", "localhost:55432")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")


def run_main(spy, schema_text, **kwargs):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "schema.sql"
        path.write_text(schema_text)
        out, err = io.StringIO(), io.StringIO()
        rc = apply.main(connect=lambda role: spy, schema_path=path, out=out, err=err, **kwargs)
    return rc, out.getvalue(), err.getvalue()


# Feature: catalog-schema, Property 11: Statements run in order and stop at the first failure
@settings(max_examples=60)
@given(st.lists(statement(), min_size=1, max_size=6, unique=True), st.data())
def test_property_order_and_stop_at_first_failure(statements, data):
    fail_at = data.draw(st.one_of(st.none(), st.integers(min_value=0, max_value=len(statements) - 1)))
    spy = SpyDatabase(probe=None, fail_on=None if fail_at is None else statements[fail_at])
    mp = pytest.MonkeyPatch()
    try:
        mp.setenv("OPSMEM_LOCAL_PG", "localhost:55432")
        mp.setenv("AWS_REGION", "eu-west-1")
        rc, out, err = run_main(spy, joined(statements))
    finally:
        mp.undo()
    sent = [s for s in spy.sqls if s in statements]
    if fail_at is None:
        assert rc == 0 and sent == statements
    else:
        assert rc != 0 and sent == statements[:fail_at + 1]
        assert statements[fail_at] in err and f"statement {fail_at + 1} " in err
        assert not any(s.startswith(("ALTER ROLE", "INSERT")) for s in spy.sqls)


# Feature: catalog-schema, Property 12: Existing schema stops the applier
@settings(max_examples=60)
@given(st.lists(statement(), min_size=1, max_size=4), st.one_of(st.none(), st.just("installations")),
       st.booleans())
def test_property_existing_schema_stops_the_applier(statements, probe, is_local):
    spy = SpyDatabase(probe=probe)
    mp = pytest.MonkeyPatch()
    try:
        if is_local:
            mp.setenv("OPSMEM_LOCAL_PG", "localhost:55432")
            mp.setenv("AWS_REGION", "eu-west-1")
        else:
            mp.delenv("OPSMEM_LOCAL_PG", raising=False)
            for name in apply.AURORA_REQUIRED:
                mp.setenv(name, "x")
        rc, out, err = run_main(spy, joined(statements), read_password=lambda role: "Secret1")
    finally:
        mp.undo()
    if probe is None:
        assert rc == 0 and spy.sqls[1] == statements[0]
    else:
        assert rc != 0 and len(spy.calls) == 1
        assert "not empty" in err
        assert ("scripts/local_db.sh up" if is_local else "a new stack") in err


# --- the example on a database that was already applied ---

@pytest.mark.local_pg
def test_second_run_is_refused_and_changes_nothing(applied):
    from opsmem import db

    admin = db.connect("admin")
    objects = "SELECT string_agg(relname, ',' ORDER BY relname) FROM pg_class WHERE relnamespace = 'public'::regnamespace"
    counts = ("SELECT (SELECT count(*) FROM installations), (SELECT count(*) FROM services), "
              "(SELECT count(*) FROM source_fields), (SELECT count(*) FROM signal_requests)")
    before = (admin.run(objects), admin.run(counts))
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "apply_schema.py")], capture_output=True,
                          text=True, env=os.environ.copy())
    assert proc.returncode != 0
    assert "not empty" in proc.stderr and "scripts/local_db.sh up" in proc.stderr
    assert (admin.run(objects), admin.run(counts)) == before


@pytest.mark.local_pg
def test_first_application_loaded_the_expected_counts(applied):
    from opsmem import db

    rows = db.connect("admin").run(
        "SELECT (SELECT count(*) FROM installations), (SELECT count(*) FROM services), "
        "(SELECT count(*) FROM source_fields), (SELECT count(*) FROM signal_requests)")
    assert rows == [[1, 5, 9, 6]]
