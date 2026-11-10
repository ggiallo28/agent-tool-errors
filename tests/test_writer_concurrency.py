"""Concurrent calls of one run behave as if they came one after the other (no model, no network)."""
import threading

from hypothesis import given, settings
from hypothesis import strategies as st

from opsmem.writer import RunContext, make_tools
from tests.writer_fakes import FakeDatabase, args, rejection_message

RULE = "config_field_exists"
ESCALATION_REPLY = "STOPPED. The same rule rejected 3 times; a person will take over. Stop now."
STOPPED = ("STOPPED. This run is waiting for a person (rule config_field_exists rejected 3 times). "
           "Do not propose more configurations.")


def run_concurrently(n):
    fake = FakeDatabase(reject=lambda params: rejection_message(RULE), delay=0.003)
    ctx = RunContext("run-1", "install-07", "model-x", "instructive", fake)
    propose, _ = make_tools(ctx)
    barrier = threading.Barrier(n)
    replies = [None] * n

    def go(i):
        barrier.wait()
        replies[i] = propose(**args("R1", signal_name=f"s{i}"))

    threads = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return ctx, fake, replies


def check(n, ctx, fake, replies):
    kinds = [s.split(None, 1)[0] for s, _ in fake.statements if not s.startswith("SELECT")]
    assert kinds.count("INSERT") == 3
    assert kinds.count("UPDATE") == 1
    assert kinds == ["INSERT", "INSERT", "INSERT", "UPDATE"]  # no insert after the status update
    assert ctx.escalation_reason == f"rule {RULE} rejected 3 times"
    assert replies.count(ESCALATION_REPLY) == 1
    assert replies.count(STOPPED) == n - 3
    assert len(ctx.trace) == n and ctx.tool_calls == n


# Feature: writer-agent, Property 9: No call after the escalation reaches the database
@settings(max_examples=100, deadline=None)
@given(n=st.integers(min_value=4, max_value=12))
def test_property_no_call_after_escalation(n):
    check(n, *run_concurrently(n))


def test_eight_concurrent_calls_one_escalates_and_none_reaches_the_database_after():
    check(8, *run_concurrently(8))
