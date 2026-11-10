"""Catalog loader and password rules with a spy database. Offline."""
import hashlib
import io
import shutil
from pathlib import Path

import pytest

from opsmem import db, manual
from tests.helpers import ROOT, load_script
from tests.spy import SpyDatabase

apply = load_script("apply_schema")
MANUALS = ROOT / "manuals"


def digest():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(MANUALS.iterdir())}


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setenv("OPSMEM_LOCAL_PG", "localhost:55432")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")


def load(spy, root=ROOT):
    out, err = io.StringIO(), io.StringIO()
    rc = apply.load_catalog(spy, root, out, err)
    return rc, out.getvalue(), err.getvalue()


def test_insert_order_counts_and_no_upsert():
    spy = SpyDatabase(probe="installations")
    rc, out, err = load(spy)
    inserts = [s for s in spy.sqls if s.startswith("INSERT")]
    tables = [s.split()[2] for s in inserts]
    assert rc == 0
    assert tables == ["installations"] + ["services"] * 5 + ["source_fields"] * 9 + ["signal_requests"] * 6
    assert not any("ON CONFLICT" in s.upper() for s in spy.sqls)
    assert out.splitlines() == ["installations: 1", "services: 5", "fields: 9", "requests: 6"]
    first = spy.calls[1]
    assert first[1] == {"installation_id": "install-07", "name": "Course platform, installation 07"}


def test_schema_not_applied_writes_nothing():
    spy = SpyDatabase(probe=None)
    rc, out, err = load(spy)
    assert rc != 0 and "schema has not been applied" in err and len(spy.calls) == 1


def test_missing_manual_file_is_named_and_nothing_is_written(tmp_path):
    (tmp_path / "manuals").mkdir()
    shutil.copy(ROOT / manual.OPENAPI, tmp_path / manual.OPENAPI)
    spy = SpyDatabase(probe="installations")
    rc, out, err = load(spy, tmp_path)
    assert rc != 0 and manual.MANUAL in err
    assert not any(s.startswith("INSERT") for s in spy.sqls)


def test_manual_without_heading_writes_nothing(tmp_path):
    (tmp_path / "manuals").mkdir()
    shutil.copy(ROOT / manual.OPENAPI, tmp_path / manual.OPENAPI)
    (tmp_path / manual.MANUAL).write_text("# Manual\n\nNo table.\n")
    spy = SpyDatabase(probe="installations")
    rc, out, err = load(spy, tmp_path)
    assert rc != 0 and "Requests from operations" in err
    assert not any(s.startswith("INSERT") for s in spy.sqls)


def test_manual_files_are_unchanged_by_a_full_run(local, tmp_path):
    before = digest()
    schema = tmp_path / "schema.sql"
    schema.write_text("SELECT 1")
    spy = SpyDatabase(probe=None)
    rc = apply.main(connect=lambda role: spy, schema_path=schema, out=io.StringIO(), err=io.StringIO())
    assert rc == 0 and digest() == before


def test_local_passwords_equal_the_role_names(local, tmp_path):
    schema = tmp_path / "schema.sql"
    schema.write_text("SELECT 1")
    spy = SpyDatabase(probe=None)
    apply.main(connect=lambda role: spy, schema_path=schema, out=io.StringIO(), err=io.StringIO(),
               read_password=lambda role: pytest.fail("local mode must not read secrets"))
    assert "ALTER ROLE agent_writer PASSWORD 'agent_writer'" in spy.sqls
    assert "ALTER ROLE approver PASSWORD 'approver'" in spy.sqls


def test_aurora_passwords_come_from_the_secrets(monkeypatch, tmp_path):
    monkeypatch.delenv("OPSMEM_LOCAL_PG", raising=False)
    for name in apply.AURORA_REQUIRED:
        monkeypatch.setenv(name, "x")
    schema = tmp_path / "schema.sql"
    schema.write_text("SELECT 1")
    spy = SpyDatabase(probe=None)
    rc = apply.main(connect=lambda role: spy, schema_path=schema, out=io.StringIO(), err=io.StringIO(),
                    read_password=lambda role: {"agent_writer": "Aaa111", "approver": "Bbb222"}[role])
    assert rc == 0
    assert "ALTER ROLE agent_writer PASSWORD 'Aaa111'" in spy.sqls
    assert "ALTER ROLE approver PASSWORD 'Bbb222'" in spy.sqls


@pytest.mark.parametrize("password", ["", "a b", "a'b", "a:b", "a%b", "pass-word", "pass;word"])
def test_non_alphanumeric_password_is_refused_before_anything_runs(monkeypatch, tmp_path, password):
    monkeypatch.delenv("OPSMEM_LOCAL_PG", raising=False)
    for name in apply.AURORA_REQUIRED:
        monkeypatch.setenv(name, "x")
    schema = tmp_path / "schema.sql"
    schema.write_text("SELECT 1")
    spy = SpyDatabase(probe=None)
    err = io.StringIO()
    rc = apply.main(connect=lambda role: spy, schema_path=schema, out=io.StringIO(), err=err,
                    read_password=lambda role: password)
    assert rc != 0 and "AGENT_WRITER_SECRET_ARN" in err.getvalue()
    assert spy.sqls == [apply.PROBE]


def test_admin_connection_failure_runs_no_statement(local, tmp_path):
    schema = tmp_path / "schema.sql"
    schema.write_text("SELECT 1")
    spy = SpyDatabase(probe_error=db.ConnectionFailed("cannot connect to localhost:55432 as admin: refused"))
    err = io.StringIO()
    rc = apply.main(connect=lambda role: spy, schema_path=schema, out=io.StringIO(), err=err)
    assert rc != 0 and "cannot connect" in err.getvalue()
    assert spy.sqls == [apply.PROBE]
