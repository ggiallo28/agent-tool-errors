"""Helpers for the local_pg tests: connections per role, fresh run ids, rejection checks, config rows."""
import uuid

import pytest

from opsmem import db

INSTALLATION = "install-07"
_connections: dict = {}

# Six valid combinations from the shipped catalog, one per request.
VALID = {
    "R1": dict(request_id="R1", service_id="media", signal_type="latency", source_field="mst_wr_lat", unit="ms", sample_s=10),
    "R2": dict(request_id="R2", service_id="encoding", signal_type="latency", source_field="enc_q_wait", unit="s", sample_s=10),
    "R3": dict(request_id="R3", service_id="api", signal_type="latency", source_field="api_p95", unit="s", sample_s=10),
    "R4": dict(request_id="R4", service_id="api", signal_type="count", source_field="api_5xx", unit="count", sample_s=10),
    "R5": dict(request_id="R5", service_id="classes", signal_type="count", source_field="cls_create_fail", unit="count", sample_s=60),
    "R6": dict(request_id="R6", service_id="queue", signal_type="count", source_field="jq_depth", unit="count", sample_s=10),
}


def connect_as(role):
    if role not in _connections:
        _connections[role] = db.connect(role)
    return _connections[role]


def new_run_id():
    return "t" + uuid.uuid4().hex[:12]


def config(run, request="R4", **overrides):
    """A valid configuration row for the request, with the given columns replaced."""
    row = dict(run_id=run, installation_id=INSTALLATION, signal_name=f"sig_{request.lower()}",
               model_id="test-model", **VALID[request])
    row.update(overrides)
    return row


def insert(role, row, returning=True):
    columns = list(row)
    sql = (f"INSERT INTO collection_configs ({', '.join(columns)}) "
           f"VALUES ({', '.join(':' + c for c in columns)})" + (" RETURNING config_id" if returning else ""))
    rows = connect_as(role).run(sql, **row)
    return rows[0][0] if returning else None


def count(where="TRUE", **params):
    return connect_as("admin").run(f"SELECT count(*) FROM collection_configs WHERE {where}", **params)[0][0]


def assert_rejected(call, *, rule, constraint=None, sqlstate=None, message=None):
    """Run call and expect a DatabaseError. Reports the rule, the expected and the actual name."""
    try:
        call()
    except db.DatabaseError as e:
        problems = []
        if constraint is not None and e.constraint != constraint:
            problems.append(f"expected constraint {constraint!r}, got {e.constraint!r}")
        if sqlstate is not None and e.sqlstate != sqlstate:
            problems.append(f"expected SQLSTATE {sqlstate!r}, got {e.sqlstate!r}")
        if message is not None and message not in str(e):
            problems.append(f"expected message {message!r}, got {str(e)!r}")
        if problems:
            pytest.fail(f"rule {rule}: " + "; ".join(problems))
        return e
    pytest.fail(f"rule {rule}: expected a rejection ({constraint or sqlstate}), but the statement succeeded")
