"""The tools of the writer agent, on a fake database (no model, no network)."""
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from opsmem import writer
from opsmem.writer import RunContext, make_tools
from tests.writer_fakes import FakeDatabase, args, rejection_message

SOURCE = Path(writer.__file__).read_text(encoding="utf-8")


def make(mode="instructive", reject=None, **kw):
    fake = FakeDatabase(reject=reject, **kw)
    ctx = RunContext("run-1", "install-07", "model-x", mode, fake)
    propose, flag = make_tools(ctx)
    return ctx, fake, propose, flag


def always(rule):
    return lambda params: rejection_message(rule)


# --- specs and defaults ------------------------------------------------------------------------

def test_tool_specs():
    _, _, propose, flag = make()
    spec = propose.tool_spec
    assert [t.tool_name for t in (propose, flag)] == ["propose_config", "flag_for_review"]
    assert spec["name"] == "propose_config"
    assert spec["description"] == "Propose one signal configuration as a draft."
    schema = spec["inputSchema"]["json"]
    expected = [("request_id", "request id"), ("service_id", "service id"), ("signal_name", "signal name"),
                ("signal_type", "signal type"), ("source_field", "source field"), ("unit", "unit"),
                ("sample_seconds", "sampling interval in seconds")]
    assert list(schema["properties"]) == [n for n, _ in expected]
    for name, text in expected:
        assert schema["properties"][name] == {"description": text, "type": "string"}
    assert schema["required"] == [n for n, _ in expected]
    spec = flag.tool_spec
    assert spec["name"] == "flag_for_review"
    assert spec["description"] == "Ask a person to decide something you cannot."
    schema = spec["inputSchema"]["json"]
    assert schema["properties"] == {"reason": {"description": "what you cannot decide", "type": "string"}}
    assert schema["required"] == ["reason"]


def test_run_context_defaults_and_constants():
    ctx = RunContext("r", "i", "m", "raw", object())
    assert (ctx.run_id, ctx.installation_id, ctx.model_id, ctx.mode) == ("r", "i", "m", "raw")
    assert ctx.rejections == {} and ctx.tool_calls == 0 and ctx.escalation_reason is None
    assert ctx.flagged == [] and ctx.trace == [] and ctx.last_db_message is None
    assert hasattr(ctx.lock, "acquire") and hasattr(ctx.lock, "release")
    assert (writer.MAX_TOOL_CALLS, writer.ESCALATE_AFTER, writer.FOLLOW_UPS) == (40, 3, 2)


def test_system_prompt_literal():
    assert writer.SYSTEM_PROMPT == (
        "Configure one signal per request with propose_config. If a call is rejected, use the valid values "
        "in the rejection and call the tool again. Stop only when every request is saved.")


def test_source_has_no_instruction_copy_and_no_region():
    assert "Unknown source_field" not in SOURCE
    assert "us-east-1" not in SOURCE


def test_writer_imports_the_real_strands():
    import strands
    assert writer.Agent is strands.Agent


# --- behavior ----------------------------------------------------------------------------------

def test_three_rejections_stop_the_run():
    ctx, fake, propose, _ = make(reject=always("config_field_exists"))
    propose(**args("R1", signal_name="first"))
    replies = [propose(**args("R1")) for _ in range(2)]
    assert ctx.rejections == {("R1", "config_field_exists"): 3}
    assert ctx.escalation_reason == "rule config_field_exists rejected 3 times"
    assert replies[-1] == "STOPPED. The same rule rejected 3 times; a person will take over. Stop now."
    moves = fake.of_kind("UPDATE")
    assert len(moves) == 1
    assert "status = 'needs_review'" in moves[0][0] and "status = 'draft'" in moves[0][0]
    assert moves[0][1] == {"run_id": "run-1", "installation_id": "install-07"}


def test_41st_call_stops_the_run_and_sends_nothing():
    ctx, fake, propose, _ = make()
    for i in range(40):
        assert propose(**args("R1", signal_name=f"s{i}")).startswith("Saved as draft")
    before = len(fake.statements)
    reply = propose(**args("R1"))
    assert ctx.escalation_reason == "more than 40 tool calls"
    assert reply == ("STOPPED. This run is waiting for a person (more than 40 tool calls). "
                     "Do not propose more configurations.")
    assert len(fake.statements) == before
    assert ctx.tool_calls == 41


def test_concurrent_calls_are_counted_and_capped():
    ctx, fake, propose, _ = make(delay=0.001)
    n = 60
    barrier = threading.Barrier(n)

    def go(i):
        barrier.wait()
        propose(**args("R1", signal_name=f"s{i}"))

    threads = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert ctx.tool_calls == n
    assert len(fake.of_kind("INSERT")) == 40
    assert len(ctx.trace) == n


def test_raw_mode_sends_no_lookup():
    _, fake, propose, _ = make(mode="raw", reject=always("config_field_exists"))
    reply = propose(**args())
    assert reply.startswith("ERROR: ")
    assert [s for s, _ in fake.statements if s.startswith("SELECT")] == []


def test_instructive_mode_sends_the_lookup_of_the_rule():
    _, fake, propose, _ = make(reject=always("config_field_exists"))
    reply = propose(**args())
    assert reply == "REJECTED (config_field_exists). Not saved. Unknown source_field. Valid source_field: alpha, beta."
    selects = fake.of_kind("SELECT")
    assert len(selects) == 1 and "FROM source_fields" in selects[0][0]


def test_non_numeric_sample_seconds_is_a_database_rejection_classified_integer_input():
    seen = []

    def reject(params):
        seen.append(params["sample_seconds"])
        return rejection_message("integer_input") if not params["sample_seconds"].isdigit() else None

    ctx, fake, propose, _ = make(reject=reject)
    reply = propose(**args(sample_seconds="every minute"))
    assert seen == ["every minute"]
    assert reply == "REJECTED (integer_input). Not saved. sample_seconds must be a whole number of seconds."
    assert ctx.rejections == {("R1", "integer_input"): 1}


def test_trace_timestamp_is_utc_with_milliseconds():
    ctx, _, propose, _ = make()
    propose(**args())
    ts = ctx.trace[0]["ts"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00", ts)
    assert datetime.fromisoformat(ts).utcoffset() == timedelta(0)


def test_flag_for_review_keeps_every_reason_under_threads():
    ctx, _, _, flag = make()
    barrier = threading.Barrier(30)

    def go(i):
        barrier.wait()
        flag(reason=f"reason {i}")

    threads = [threading.Thread(target=go, args=(i,)) for i in range(30)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(ctx.flagged) == sorted(f"reason {i}" for i in range(30))


# Feature: writer-agent, Property 3: Flagging records the reason and gives the fixed reply
@settings(max_examples=100, deadline=None)
@given(reasons=st.lists(st.text(), max_size=20))
def test_property_flagging(reasons):
    ctx, fake, _, flag = make()
    replies = [flag(reason=r) for r in reasons]
    assert ctx.flagged == reasons
    assert replies == ["Noted for a person. Continue with the signals you can configure."] * len(reasons)
    assert fake.statements == []
