"""Aurora backend with a Fake_Data_API_Client and a replaced _sleep. No network, no AWS."""
import math
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opsmem import db


class DatabaseResumingException(Exception):
    pass


class BadRequestException(Exception):
    pass


class FakeClient:
    """execute_statement plays a script: an exception instance is raised, anything else is returned."""

    def __init__(self, script=()):
        self.script = list(script)
        self.calls = []
        self.exceptions = SimpleNamespace(DatabaseResumingException=DatabaseResumingException,
                                          BadRequestException=BadRequestException)

    def execute_statement(self, **kwargs):
        self.calls.append(kwargs)
        step = self.script.pop(0) if self.script else {"records": []}
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture(autouse=True)
def aurora_env(monkeypatch):
    monkeypatch.delenv("OPSMEM_LOCAL_PG", raising=False)
    monkeypatch.setenv("CLUSTER_ARN", "arn:cluster")
    monkeypatch.setenv("ADMIN_SECRET_ARN", "arn:admin")
    monkeypatch.setenv("AGENT_WRITER_SECRET_ARN", "arn:agent")
    monkeypatch.setenv("APPROVER_SECRET_ARN", "arn:approver")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")


@pytest.fixture
def sleeps(monkeypatch):
    waits = []
    monkeypatch.setattr(db, "_sleep", waits.append)
    return waits


# Feature: catalog-schema, Property 5: Data API value round trip
@settings(max_examples=200)
@given(st.one_of(st.none(), st.booleans(), st.integers(min_value=-2**63, max_value=2**63 - 1),
                 st.floats(allow_nan=False, allow_infinity=False), st.text()))
def test_property_data_api_round_trip(value):
    back = db.from_field(db.to_field(value))
    assert back == value and type(back) is type(value)


def test_bool_is_not_sent_as_long():
    assert db.to_field(True) == {"booleanValue": True}
    assert db.to_field(1) == {"longValue": 1}


# Feature: catalog-schema, Property 6: Retry schedule
@settings(max_examples=50)
@given(st.integers(min_value=0, max_value=10))
def test_property_retry_schedule(k):
    waits = []
    mp = pytest.MonkeyPatch()
    try:
        mp.setenv("CLUSTER_ARN", "arn:cluster")
        mp.setenv("ADMIN_SECRET_ARN", "arn:admin")
        mp.setattr(db, "_sleep", waits.append)
        client = FakeClient([DatabaseResumingException()] * k + [{"records": [[{"longValue": 1}]]}])
        backend = db.AuroraBackend("admin", client=client)
        if k <= 6:
            assert backend.run("SELECT 1") == [[1]]
            assert waits == list(db.RETRY_WAITS[:k])
            assert len(client.calls) == k + 1
        else:
            with pytest.raises(DatabaseResumingException):
                backend.run("SELECT 1")
            assert waits == list(db.RETRY_WAITS)
            assert len(client.calls) == 7
    finally:
        mp.undo()


# Feature: catalog-schema, Property 4: Missing parameters stop execution (Aurora side)
@settings(max_examples=100)
@given(st.lists(st.from_regex(r"[a-z_][a-z0-9_]{0,6}", fullmatch=True), min_size=1, max_size=5, unique=True),
       st.data())
def test_property_missing_parameter_stops_aurora(names, data):
    given_names = data.draw(st.lists(st.sampled_from(names), unique=True, max_size=len(names) - 1))
    sql = "SELECT " + ", ".join(f":{n}" for n in names)
    client = FakeClient()
    mp = pytest.MonkeyPatch()
    try:
        mp.setenv("CLUSTER_ARN", "arn:cluster")
        mp.setenv("ADMIN_SECRET_ARN", "arn:admin")
        with pytest.raises(ValueError, match="Missing parameter: ") as err:
            db.AuroraBackend("admin", client=client).run(sql, **{n: 1 for n in given_names})
    finally:
        mp.undo()
    assert str(err.value).removeprefix("Missing parameter: ") in set(names) - set(given_names)
    assert client.calls == []


@pytest.mark.parametrize("var", ["CLUSTER_ARN", "ADMIN_SECRET_ARN"])
@pytest.mark.parametrize("empty", [True, False])
def test_missing_or_empty_variable_is_named_and_nothing_is_sent(monkeypatch, var, empty):
    if empty:
        monkeypatch.setenv(var, "")
    else:
        monkeypatch.delenv(var)
    client = FakeClient()
    with pytest.raises(db.ConfigError, match=var):
        db.AuroraBackend("admin", client=client).run("SELECT 1")
    assert client.calls == []


@pytest.mark.parametrize("role,secret", [("admin", "arn:admin"), ("agent_writer", "arn:agent"),
                                         ("approver", "arn:approver")])
def test_each_role_uses_only_its_own_secret(role, secret):
    client = FakeClient()
    db.AuroraBackend(role, client=client).run("SELECT 1")
    assert [c["secretArn"] for c in client.calls] == [secret]
    assert client.calls[0]["resourceArn"] == "arn:cluster" and client.calls[0]["database"] == "opsmemory"


def test_parameters_are_typed_and_extra_ones_ignored():
    client = FakeClient([{"records": [[{"stringValue": "a"}, {"isNull": True}]]}])
    rows = db.AuroraBackend("admin", client=client).run("SELECT :a, :b::int", a="x", b=3, unused=1)
    assert rows == [["a", None]]
    assert client.calls[0]["parameters"] == [{"name": "a", "value": {"stringValue": "x"}},
                                             {"name": "b", "value": {"longValue": 3}}]


def test_no_records_gives_empty_list():
    assert db.AuroraBackend("admin", client=FakeClient([{"numberOfRecordsUpdated": 1}])).run("DELETE FROM t") == []


@pytest.mark.parametrize("error", [RuntimeError("throttled"), KeyError("denied")])
def test_other_exceptions_propagate_without_retry(sleeps, error):
    client = FakeClient([error])
    with pytest.raises(type(error)) as err:
        db.AuroraBackend("admin", client=client).run("SELECT 1")
    assert err.value is error and len(client.calls) == 1 and sleeps == []


def test_database_error_keeps_the_native_text():
    text = ('An error occurred (BadRequestException) when calling the ExecuteStatement operation: '
            'ERROR: duplicate key value violates unique constraint "config_one_per_request"\n'
            'DETAIL: Key (run_id, installation_id, request_id)=(r, i, R1) already exists.')
    native = BadRequestException(text)
    backend = db.AuroraBackend("agent_writer", client=FakeClient([native]))
    with pytest.raises(db.DatabaseError) as err:
        backend.run("INSERT INTO t VALUES (1)")
    assert str(err.value) == str(native)
    assert "DETAIL" in str(err.value)
    assert err.value.__cause__ is native
    assert err.value.sqlstate is None and err.value.constraint is None
    assert backend.DatabaseError is db.DatabaseError


def test_database_error_takes_structured_attributes_when_present():
    native = BadRequestException("boom")
    native.sqlstate, native.constraint = "23505", "config_one_per_request"
    with pytest.raises(db.DatabaseError) as err:
        db.AuroraBackend("admin", client=FakeClient([native])).run("SELECT 1")
    assert (err.value.sqlstate, err.value.constraint) == ("23505", "config_one_per_request")
