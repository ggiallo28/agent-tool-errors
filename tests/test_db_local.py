"""Local backend with a fake psycopg. No database, no network."""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opsmem import db


class FakeError(Exception):
    def __init__(self, text, sqlstate=None, constraint_name=None):
        super().__init__(text)
        self.diag = type("Diag", (), {"sqlstate": sqlstate, "constraint_name": constraint_name})()


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.description, self.closed = conn, None, False

    def execute(self, query, params):
        self.conn.executed.append((query, params))
        if self.conn.fail:
            raise self.conn.fail
        self.description = [("c",)] if self.conn.rows is not None else None

    def fetchall(self):
        return self.conn.rows

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, rows=None, fail=None):
        self.rows, self.fail, self.executed = rows, fail, []

    def cursor(self):
        return FakeCursor(self)


class FakePsycopg:
    Error = FakeError

    def __init__(self, conn=None, connect_error=None):
        self.conn, self.connect_error, self.connects = conn or FakeConn(), connect_error, []

    def connect(self, **kwargs):
        self.connects.append(kwargs)
        if self.connect_error:
            raise self.connect_error
        return self.conn


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("OPSMEM_LOCAL_PG", "dbhost:55432")
    fake = FakePsycopg()
    monkeypatch.setattr(db, "_psycopg", lambda: fake)
    return fake


@pytest.mark.parametrize("role,login", [("admin", "postgres"), ("agent_writer", "agent_writer"),
                                        ("approver", "approver")])
def test_credentials_autocommit_and_timeout(pg, role, login):
    db.connect(role).run("SELECT 1")
    assert pg.connects == [dict(host="dbhost", port=55432, dbname="opsmemory", user=login, password=login,
                                autocommit=True, connect_timeout=10)]


def test_rows_are_lists_and_empty_when_no_result(pg):
    pg.conn.rows = [(1, "a"), (2, "b")]
    assert db.connect("admin").run("SELECT 1") == [[1, "a"], [2, "b"]]
    pg.conn.rows = None
    assert db.connect("admin").run("DELETE FROM t") == []


def test_query_is_converted_and_always_has_a_params_dict(pg):
    db.connect("admin").run("SELECT :a::int, 'x%'", a=1, unused=2)
    assert pg.conn.executed == [("SELECT %(a)s::int, 'x%%'", {"a": 1})]


# Feature: catalog-schema, Property 4: Missing parameters stop execution (local side)
@settings(max_examples=100)
@given(st.lists(st.from_regex(r"[a-z_][a-z0-9_]{0,6}", fullmatch=True), min_size=1, max_size=5, unique=True),
       st.data())
def test_property_missing_parameter_stops_local(names, data):
    given_names = data.draw(st.lists(st.sampled_from(names), unique=True, max_size=len(names) - 1))
    mp = pytest.MonkeyPatch()
    try:
        mp.setenv("OPSMEM_LOCAL_PG", "dbhost:55432")
        fake = FakePsycopg()
        mp.setattr(db, "_psycopg", lambda: fake)
        with pytest.raises(ValueError, match="Missing parameter: ") as err:
            db.connect("admin").run("SELECT " + ", ".join(f":{n}" for n in names),
                                    **{n: 1 for n in given_names})
    finally:
        mp.undo()
    assert str(err.value).removeprefix("Missing parameter: ") in set(names) - set(given_names)
    assert fake.conn.executed == []


@pytest.mark.parametrize("value", ["nohost", "h:99999", "h:x", "h:"])
def test_malformed_variable_opens_no_connection(monkeypatch, value):
    fake = FakePsycopg()
    monkeypatch.setattr(db, "_psycopg", lambda: fake)
    monkeypatch.setenv("OPSMEM_LOCAL_PG", value)
    with pytest.raises(db.ConfigError, match="OPSMEM_LOCAL_PG"):
        db.connect("admin").run("SELECT 1")
    assert fake.connects == []


def test_connection_failure_names_host_port_and_role_without_retry(monkeypatch):
    monkeypatch.setenv("OPSMEM_LOCAL_PG", "dbhost:55432")
    fake = FakePsycopg(connect_error=FakeError("connection refused"))
    monkeypatch.setattr(db, "_psycopg", lambda: fake)
    with pytest.raises(db.ConnectionFailed, match=r"dbhost.*55432.*approver"):
        db.connect("approver").run("SELECT 1")
    assert len(fake.connects) == 1


def test_database_error_keeps_native_text_and_cause(monkeypatch, pg):
    text = ('ERROR:  duplicate key value violates unique constraint "config_one_per_request"\n'
            "DETAIL:  Key (run_id)=(r) already exists.")
    native = FakeError(text, "23505", "config_one_per_request")
    pg.conn.fail = native
    with pytest.raises(db.DatabaseError) as err:
        db.connect("agent_writer").run("INSERT INTO t VALUES (1)")
    assert str(err.value) == str(native) and "DETAIL" in str(err.value)
    assert err.value.__cause__ is native
    assert (err.value.sqlstate, err.value.constraint) == ("23505", "config_one_per_request")


def test_cursor_is_closed(pg):
    pg.conn.rows = [(1,)]
    cursors = []
    original = pg.conn.cursor
    pg.conn.cursor = lambda: cursors.append(original()) or cursors[-1]
    db.connect("admin").run("SELECT 1")
    assert [c.closed for c in cursors] == [True]
