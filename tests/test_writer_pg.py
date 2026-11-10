"""The writer tools on the local database as agent_writer, with the real grants and triggers (marker local_pg).
No model is called."""
import pytest

from opsmem.writer import RunContext, _open_requests, make_tools
from tests.pghelpers import INSTALLATION, connect_as, new_run_id

pytestmark = pytest.mark.local_pg


def rig():
    ctx = RunContext(new_run_id(), INSTALLATION, "test-model", "instructive", connect_as("agent_writer"))
    propose, _ = make_tools(ctx)
    return ctx, propose


def statuses(run):
    rows = connect_as("admin").run(
        "SELECT request_id, status FROM collection_configs WHERE run_id = :r ORDER BY request_id", r=run)
    return [tuple(r) for r in rows]


R1 = dict(request_id="R1", service_id="media", signal_name="media_write_latency", signal_type="latency",
          source_field="mst_wr_lat", unit="ms")
R4 = dict(request_id="R4", service_id="api", signal_name="api_errors", signal_type="count",
          source_field="api_5xx", unit="count")


def test_valid_proposal_with_text_seconds_is_saved_as_draft():
    ctx, propose = rig()
    reply = propose(**R1, sample_seconds="10")
    assert reply == ("Saved as draft: media_write_latency <- mst_wr_lat (ms, every 10 s). "
                     "A person will review it.")
    assert statuses(ctx.run_id) == [("R1", "draft")]
    assert ctx.trace[0]["db_message"] is None


def test_non_numeric_sample_seconds_is_rejected_as_integer_input():
    ctx, propose = rig()
    reply = propose(**R1, sample_seconds="every minute")
    assert reply == "REJECTED (integer_input). Not saved. sample_seconds must be a whole number of seconds."
    assert ctx.rejections == {("R1", "integer_input"): 1}
    assert "invalid input syntax for type integer" in ctx.trace[0]["db_message"]
    assert statuses(ctx.run_id) == []


def test_unknown_field_reply_lists_valid_values():
    ctx, propose = rig()
    reply = propose(**{**R1, "source_field": "no_such_field"}, sample_seconds="10")
    assert reply.startswith("REJECTED (config_field_exists). Not saved. Unknown source_field. Valid source_field: ")
    assert "mst_wr_lat" in reply


def test_three_rejections_stop_the_run_and_move_the_earlier_draft():
    ctx, propose = rig()
    assert propose(**R4, sample_seconds="10").startswith("Saved as draft")
    bad = {**R1, "source_field": "no_such_field"}
    replies = [propose(**{**bad, "signal_name": f"bad_{i}"}, sample_seconds="10") for i in range(3)]
    assert replies[-1] == "STOPPED. The same rule rejected 3 times; a person will take over. Stop now."
    assert ctx.escalation_reason == "rule config_field_exists rejected 3 times"
    assert statuses(ctx.run_id) == [("R4", "needs_review")]
    after = propose(**R1, sample_seconds="10")
    assert after.startswith("STOPPED. This run is waiting for a person")
    assert statuses(ctx.run_id) == [("R4", "needs_review")]


def test_open_request_query_returns_requests_without_a_row():
    ctx, propose = rig()
    assert _open_requests(ctx) == ["R1", "R2", "R3", "R4", "R5", "R6"]
    propose(**R1, sample_seconds="10")
    propose(**R4, sample_seconds="10")
    propose(**{**R1, "request_id": "R2", "source_field": "no_such_field"}, sample_seconds="10")  # rejected: no row
    assert _open_requests(ctx) == ["R2", "R3", "R5", "R6"]
