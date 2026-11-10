"""The run loop and the result of a run, with a fake agent (no model, no network)."""
from hypothesis import given, settings
from hypothesis import strategies as st

from opsmem.writer import FOLLOW_UPS, MAX_FINAL_TEXT, RunContext, run_writer
from tests.writer_fakes import FakeAgent, FakeDatabase, FakeResult

KEYS = {"tool_calls", "rejections", "follow_ups", "escalated", "flagged", "trace", "input_tokens",
        "output_tokens", "final_text"}


def context(open_ids):
    fake = FakeDatabase(open_ids=open_ids)
    return RunContext("run-1", "install-07", "model-x", "raw", fake), fake


def test_follow_up_text_and_stop_after_two_follow_ups():
    ctx, fake = context(lambda: ["R5", "R2"])
    agent = FakeAgent()
    result = run_writer(ctx, "the task", agent)
    assert agent.messages == [
        "the task",
        "Not configured yet: R2, R5. Call propose_config for each.",
        "Not configured yet: R2, R5. Call propose_config for each.",
    ]
    assert ctx.escalation_reason == "agent stopped with requests not configured: R2, R5"
    assert result["follow_ups"] == 2
    assert result["escalated"] == "agent stopped with requests not configured: R2, R5"


def test_no_follow_up_when_nothing_is_open():
    ctx, _ = context([])
    agent = FakeAgent()
    result = run_writer(ctx, "task", agent)
    assert agent.messages == ["task"] and result["follow_ups"] == 0 and result["escalated"] is None


def test_no_follow_up_when_the_run_is_stopped():
    ctx, _ = context(["R1"])
    agent = FakeAgent(lambda m, i: setattr(ctx, "escalation_reason", "rule x rejected 3 times"))
    result = run_writer(ctx, "task", agent)
    assert agent.messages == ["task"]
    assert result["escalated"] == "rule x rejected 3 times"


def test_open_request_query_is_bound_to_the_run():
    ctx, fake = context([])
    run_writer(ctx, "task", FakeAgent())
    [(sql, params)] = fake.statements
    assert params == {"installation_id": "install-07", "run_id": "run-1"}
    assert "signal_requests" in sql and "collection_configs" in sql


# Feature: writer-agent, Property 10: The run loop sends follow-ups until requests are configured or the budget is spent
@settings(max_examples=100, deadline=None)
@given(
    count=st.integers(min_value=1, max_value=12),
    subsets=st.lists(st.sets(st.integers(min_value=1, max_value=12)), min_size=3, max_size=3),
    stop_at=st.sampled_from([None, 0, 1, 2]),
)
def test_property_run_loop(count, subsets, stop_at):
    everything = {f"R{i}" for i in range(1, count + 1)}
    open_now = set(everything)
    ctx, _ = context(lambda: list(open_now))

    def behavior(message, index):
        open_now.difference_update({f"R{i}" for i in subsets[index]})
        if stop_at == index:
            ctx.escalation_reason = "stopped by the test"

    agent = FakeAgent(behavior)
    result = run_writer(ctx, "task", agent)

    # oracle
    left = set(everything)
    expected, stop = ["task"], None
    for index in range(FOLLOW_UPS + 1):
        left -= {f"R{i}" for i in subsets[index]}
        if stop_at == index:
            stop = "stopped by the test"
            break
        if not left:
            break
        ids = ", ".join(sorted(left))
        if index == FOLLOW_UPS:
            stop = f"agent stopped with requests not configured: {ids}"
            break
        expected.append(f"Not configured yet: {ids}. Call propose_config for each.")
    assert agent.messages == expected
    assert result["follow_ups"] == len(expected) - 1
    assert result["escalated"] == stop


# Feature: writer-agent, Property 11: The result has the fixed keys and bounded text
usage = st.one_of(
    st.none(),
    st.fixed_dictionaries({}, optional={"inputTokens": st.integers(0, 10**6), "outputTokens": st.integers(0, 10**6)}),
)
pairs = st.dictionaries(st.tuples(st.sampled_from(["R1", "R2", "R3"]), st.sampled_from(["rule_a", "rule_b"])),
                        st.integers(1, 3))


@settings(max_examples=100, deadline=None)
@given(text=st.one_of(st.text(max_size=50), st.text(min_size=MAX_FINAL_TEXT, max_size=MAX_FINAL_TEXT + 500)),
       tokens=usage, with_metrics=st.booleans(), rejections=pairs, flagged=st.lists(st.text(max_size=5), max_size=3))
def test_property_result(text, tokens, with_metrics, rejections, flagged):
    ctx, _ = context([])
    ctx.rejections = dict(rejections)
    ctx.flagged = list(flagged)
    result = run_writer(ctx, "task", FakeAgent(result=FakeResult(text, tokens, with_metrics)))
    assert set(result) == KEYS
    assert result["rejections"] == {f"{r}:{rule}": n for (r, rule), n in rejections.items()}
    assert result["flagged"] == flagged and result["trace"] == [] and result["tool_calls"] == 0
    given_tokens = (tokens or {}) if with_metrics else {}
    assert result["input_tokens"] == given_tokens.get("inputTokens", 0)
    assert result["output_tokens"] == given_tokens.get("outputTokens", 0)
    assert result["final_text"] == text[:MAX_FINAL_TEXT]
    assert len(result["final_text"]) <= MAX_FINAL_TEXT
