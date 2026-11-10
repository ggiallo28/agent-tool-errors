"""Unit tests for the valid-values lookup: failure and rules without lookup."""
import pytest

from opsmem import db
from opsmem.errors import INSTRUCTIONS, NONE_LISTED, UNKNOWN, render, valid_values

INSTALLATION = "install-07"
PROPOSAL = {
    "request_id": "R1",
    "service_id": "api",
    "signal_type": "latency",
    "source_field": "p95",
    "sample_s": "30",
}
NO_LOOKUP = (
    "config_one_per_request",
    "config_one_per_signal",
    "config_one_per_field",
    "signal_name_check",
    "integer_input",
)
WITH_LOOKUP = sorted(set(INSTRUCTIONS) - set(NO_LOOKUP) - {"unknown"})


class RecordingDb:
    DatabaseError = db.DatabaseError

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def run(self, sql, **params):
        self.calls.append((sql, params))
        if self.error is not None:
            raise self.error
        return []


def test_rule_sets_cover_the_table():
    assert len(WITH_LOOKUP) == 9
    assert len(NO_LOOKUP) + len(WITH_LOOKUP) == len(INSTRUCTIONS)


@pytest.mark.parametrize("rule", WITH_LOOKUP)
def test_database_error_gives_empty_list_and_none_listed(rule):
    stand_in = RecordingDb(error=db.DatabaseError("boom"))
    assert valid_values(stand_in, rule, PROPOSAL, INSTALLATION) == []
    assert len(stand_in.calls) == 1
    text = render(rule, [], "instructive", "raw")
    assert NONE_LISTED in text


@pytest.mark.parametrize("rule", WITH_LOOKUP)
def test_only_database_error_is_caught(rule):
    stand_in = RecordingDb(error=RuntimeError("not a sql error"))
    with pytest.raises(RuntimeError):
        valid_values(stand_in, rule, PROPOSAL, INSTALLATION)


@pytest.mark.parametrize("rule", [*NO_LOOKUP, UNKNOWN])
def test_rules_without_lookup_send_no_statement(rule):
    stand_in = RecordingDb()
    assert valid_values(stand_in, rule, PROPOSAL, INSTALLATION) == []
    assert stand_in.calls == []


# ---------------------------------------------------------------------------
# Property 10: lookups send SELECT statements only, scoped to the installation
# ---------------------------------------------------------------------------
import re  # noqa: E402
import sqlite3  # noqa: E402
from pathlib import Path  # noqa: E402

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

SCHEMA = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
CATALOG = ("installations", "services", "source_fields", "signal_requests", "allowed_units")
INSTALLATIONS = ("inst-a", "inst-b")
SAMPLE_BASE = {"inst-a": 0, "inst-b": 1000}


def schema_columns():
    """table -> column names, read from the CREATE TABLE blocks of sql/schema.sql."""
    text = SCHEMA.read_text()
    tables = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\)", text, re.S):
        cols = re.findall(r"^\s+(\w+)\s+(?:text|integer|SERIAL)\b", m.group(2), re.M)
        tables[m.group(1)] = cols
    return tables


COLUMNS = schema_columns()
SCOPED = {t for t, cols in COLUMNS.items() if "installation_id" in cols}


class SqliteRecordingDb:
    """In-memory sqlite stand-in with the schema column names; records (sql, params)."""

    DatabaseError = db.DatabaseError

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        for table in CATALOG:
            self.conn.execute(f"CREATE TABLE {table} ({', '.join(COLUMNS[table])})")
        self.calls = []

    def insert(self, table, row):
        marks = ", ".join("?" for _ in COLUMNS[table])
        self.conn.execute(f"INSERT INTO {table} VALUES ({marks})", row)

    def run(self, sql, **params):
        self.calls.append((sql, params))
        return [list(r) for r in self.conn.execute(sql, params).fetchall()]


names = st.sampled_from(["x", "y", "z", "w"])


@st.composite
def catalogs(draw):
    """Rows for both installations, every installation-owned value tagged with its owner."""
    rows = {"signal_requests": [], "source_fields": []}
    cells = {inst: set() for inst in INSTALLATIONS}
    for inst in INSTALLATIONS:
        base = SAMPLE_BASE[inst]
        for n in draw(st.sets(names, max_size=4)):
            row = (inst, f"{inst}:r{n}", f"{inst}:s{n}", f"{inst}:t{n}",
                   base + draw(st.integers(1, 100)), "text")
            rows["signal_requests"].append(row)
            cells[inst].update(str(c) for c in row[1:5])
        for n in draw(st.sets(names, max_size=4)):
            lo = base + draw(st.integers(1, 50))
            row = (inst, f"{inst}:s{n}", f"{inst}:f{n}", f"{inst}:u{n}", lo, lo + draw(st.integers(0, 50)))
            rows["source_fields"].append(row)
            cells[inst].update(str(c) for c in row[1:])
    units = draw(st.lists(st.tuples(names, names), max_size=4))
    return rows, units, cells


@st.composite
def proposals(draw):
    def tagged(letter):
        return f"{draw(st.sampled_from(INSTALLATIONS))}:{letter}{draw(names)}"

    return {"request_id": tagged("r"), "service_id": tagged("s"), "signal_type": tagged("t"),
            "source_field": tagged("f"), "sample_s": "30"}


# Feature: instructive-rejections, Property 10: Lookups send SELECT statements only, scoped to the installation
@settings(max_examples=100, deadline=None)
@given(
    rule=st.sampled_from(sorted(INSTRUCTIONS)),
    installation_id=st.sampled_from(INSTALLATIONS),
    catalog=catalogs(),
    proposal=proposals(),
)
def test_lookup_sends_select_only_scoped_to_installation(rule, installation_id, catalog, proposal):
    """**Validates: Requirements 4.1, 4.2, 4.13**"""
    rows, units, cells = catalog
    stand_in = SqliteRecordingDb()
    for table, table_rows in rows.items():
        for row in table_rows:
            stand_in.insert(table, row)
    for signal_type, unit in units:
        stand_in.insert("allowed_units", (signal_type, unit))
    proposal = {**proposal, "signal_type": units[0][0] if units else "x"}

    result = valid_values(stand_in, rule, proposal, installation_id)

    if rule in NO_LOOKUP or rule == UNKNOWN:
        assert stand_in.calls == []
        assert result == []
        return
    other = next(i for i in INSTALLATIONS if i != installation_id)
    for sql, params in stand_in.calls:
        assert sql.lstrip().upper().startswith("SELECT")
        used = set(re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql, re.I))
        assert used <= set(CATALOG)
        if used & SCOPED:
            assert params["installation_id"] == installation_id
    leaked = {tok for text in result for tok in text.split()} & cells[other]
    assert not leaked


# ---------------------------------------------------------------------------
# Property 11: lookup results match the catalog
# ---------------------------------------------------------------------------
def oracle(rule, proposal, installation_id, rows, units):
    """Plain Python answer for each lookup rule, computed from the generated catalog."""
    reqs = [r for r in rows["signal_requests"] if r[0] == installation_id]
    fields = [r for r in rows["source_fields"] if r[0] == installation_id]
    request = [r for r in reqs if r[1] == proposal["request_id"]]
    if rule == "config_answers_request":
        return sorted(r[1] for r in reqs)
    if rule == "config_service_matches_request":
        return [str(r[2]) for r in request]
    if rule == "config_type_matches_request":
        return [str(r[3]) for r in request]
    if rule == "config_sampling_requested":
        return [str(r[4]) for r in request]
    if rule == "config_field_in_service":
        return sorted(f[2] for f in fields if f[1] == proposal["service_id"])
    if rule == "config_field_exists":
        return sorted(f[2] for f in fields)
    if rule == "config_unit_matches_source":
        return [str(f[3]) for f in fields if f[2] == proposal["source_field"]]
    if rule == "config_unit_allowed_for_type":
        return sorted(u for t, u in units if t == proposal["signal_type"])
    if rule == "config_sampling_supported":
        return [f"{f[4]} to {f[5]} seconds" for f in fields if f[2] == proposal["source_field"]][:1]
    raise AssertionError(rule)


# Feature: instructive-rejections, Property 11: Lookup results match the catalog
@settings(max_examples=100, deadline=None)
@given(
    rule=st.sampled_from(WITH_LOOKUP),
    installation_id=st.sampled_from(INSTALLATIONS),
    catalog=catalogs(),
    proposal=proposals(),
    signal_type=st.sampled_from(["x", "y", "z", "w", "missing"]),
)
def test_lookup_results_match_the_catalog(rule, installation_id, catalog, proposal, signal_type):
    """**Validates: Requirements 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 4.14**"""
    rows, units, _cells = catalog
    stand_in = SqliteRecordingDb()
    for table, table_rows in rows.items():
        for row in table_rows:
            stand_in.insert(table, row)
    for unit_type, unit in units:
        stand_in.insert("allowed_units", (unit_type, unit))
    proposal = {**proposal, "signal_type": signal_type}

    result = valid_values(stand_in, rule, proposal, installation_id)

    assert isinstance(result, list)
    assert all(isinstance(v, str) for v in result)
    assert result == oracle(rule, proposal, installation_id, rows, units)
