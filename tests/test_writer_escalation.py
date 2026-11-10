"""Escalation after three rejections of one rule on one request, and the trace (no model, no network)."""
import re
from collections import Counter
from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from opsmem import errors
from opsmem.writer import RunContext, make_tools
from tests.writer_fakes import FakeDatabase, args, rejection_message

RULES = sorted(errors.INSTRUCTIONS)
ESCALATION_REPLY = "STOPPED. The same rule rejected 3 times; a person will take over. Stop now."
STOPPED = "STOPPED. This run is waiting for a person ({}). Do not propose more configurations."
TS = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00")

requests = st.sampled_from(["R1", "R2", "R3"])
rule_calls = st.lists(st.tuples(requests, st.sampled_from(RULES)), min_size=1, max_size=30)
mixed_calls = st.lists(st.tuples(requests, st.sampled_from(RULES + [None])), min_size=1, max_size=30)
modes = st.sampled_from(["raw", "instructive"])


def rig(mode):
    """A run whose database rejects by the rule written in signal_name; None in signal_name accepts."""
    def reject(params):
        rule = params["signal_name"]
        return None if rule == "accept" else rejection_message(rule)

    fake = FakeDatabase(reject=reject)
    ctx = RunContext("run-1", "install-07", "model-x", mode, fake)
    return ctx, fake, make_tools(ctx)[0]


def call_args(request, rule):
    return args(request, signal_name="accept" if rule is None else rule)


def expected_render(mode, rule, call):
    valid = []
    if mode == "instructive":
        valid = errors.valid_values(FakeDatabase(), rule, {**call, "sample_s": call["sample_seconds"]},
                                    "install-07")
    return errors.render(rule, valid, mode, rejection_message(rule))


# Feature: writer-agent, Property 7: Escalation happens exactly when one rule is rejected 3 times on one request
@settings(max_examples=100, deadline=None)
@given(calls=rule_calls, mode=modes)
def test_property_escalation(calls, mode):
    ctx, fake, propose = rig(mode)
    counts = Counter()
    stopped = None
    reached = 0
    for request, rule in calls:
        call = call_args(request, rule)
        reply = propose(**call)
        if stopped is not None:
            assert reply == STOPPED.format(stopped)
            continue
        reached += 1
        counts[(request, rule)] += 1
        if counts[(request, rule)] == 3:
            stopped = f"rule {rule} rejected 3 times"
            assert reply == ESCALATION_REPLY
        else:
            assert reply == expected_render(mode, rule, call)
    assert ctx.escalation_reason == stopped
    inserts = fake.of_kind("INSERT")
    updates = fake.of_kind("UPDATE")
    assert len(inserts) == reached
    assert len(updates) == (1 if stopped else 0)
    if stopped:
        kinds = [sql.split(None, 1)[0] for sql, _ in fake.statements]
        assert "INSERT" not in kinds[kinds.index("UPDATE"):]
    if mode == "raw":
        assert fake.of_kind("SELECT") == []
    assert ctx.rejections == dict(counts)


# Feature: writer-agent, Property 8: The trace has one entry per call
@settings(max_examples=100, deadline=None)
@given(calls=mixed_calls, mode=modes)
def test_property_trace(calls, mode):
    ctx, fake, propose = rig(mode)
    replies, sent = [], []
    for request, rule in calls:
        call = call_args(request, rule)
        sent.append(call)
        replies.append(propose(**call))
    assert len(ctx.trace) == len(calls)
    stopped_at = None
    seen = Counter()
    for i, ((request, rule), entry) in enumerate(zip(calls, ctx.trace)):
        assert list(entry) == ["ts", "call", "result", "db_message"]
        assert TS.fullmatch(entry["ts"])
        assert datetime.fromisoformat(entry["ts"]).utcoffset() == timedelta(0)
        assert entry["call"] == sent[i]
        assert entry["result"] == replies[i]
        if stopped_at is not None or rule is None:
            assert entry["db_message"] is None
        else:
            assert entry["db_message"] == rejection_message(rule)
            seen[(request, rule)] += 1
            if seen[(request, rule)] == 3:
                stopped_at = i
    stamps = [e["ts"] for e in ctx.trace]
    assert stamps == sorted(stamps)
