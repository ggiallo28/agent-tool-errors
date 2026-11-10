"""The call cap and the stopped run (no model, no network)."""
from hypothesis import given, settings
from hypothesis import strategies as st

from opsmem.writer import MAX_TOOL_CALLS, RunContext, make_tools
from tests.writer_fakes import FakeDatabase, args

STOPPED = "STOPPED. This run is waiting for a person ({}). Do not propose more configurations."


def make(db=None):
    db = db or FakeDatabase()
    ctx = RunContext("run-1", "install-07", "model-x", "instructive", db)
    propose, _ = make_tools(ctx)
    return ctx, db, propose


# Feature: writer-agent, Property 4: Calls are counted and the 41st call stops the run
@settings(max_examples=100, deadline=None)
@given(n=st.integers(min_value=1, max_value=60))
def test_property_call_cap(n):
    ctx, fake, propose = make()
    replies = [propose(**args("R1", signal_name=f"s{i}")) for i in range(n)]
    assert ctx.tool_calls == n
    assert len(fake.of_kind("INSERT")) == min(n, MAX_TOOL_CALLS)
    assert all(r.startswith("Saved as draft") for r in replies[:MAX_TOOL_CALLS])
    for r in replies[MAX_TOOL_CALLS:]:
        assert r == STOPPED.format("more than 40 tool calls")
    assert (ctx.escalation_reason == "more than 40 tool calls") == (n > MAX_TOOL_CALLS)


# Feature: writer-agent, Property 5: A stopped run never reaches the database
@settings(max_examples=100, deadline=None)
@given(reason=st.text(min_size=1), request=st.text(), signal=st.text(), unit=st.text(), seconds=st.text(),
       calls=st.integers(min_value=1, max_value=5))
def test_property_stopped_run_sends_nothing(reason, request, signal, unit, seconds, calls):
    ctx, fake, propose = make()
    ctx.escalation_reason = reason
    for _ in range(calls):
        reply = propose(**args(request, signal_name=signal, unit=unit, sample_seconds=seconds))
        assert reply == STOPPED.format(reason)
    assert fake.statements == []
    assert ctx.escalation_reason == reason
