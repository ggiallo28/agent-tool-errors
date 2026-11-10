"""Model evaluation core: catalog, cost and dirty-tree helpers. Offline."""
from decimal import Decimal

from opsmem import evaluation
from opsmem.evaluation import (
    ModelEntry,
    cost_upper_bound,
    format_cost,
    is_dirty,
    load_catalog,
)
from tests.helpers import ROOT

# Requirement 1, criteria 1 to 6: label, name, model_id, input, output, source.
EXPECTED = [
    ("claude-sonnet-4-6", "Claude Sonnet 4.6", "us.anthropic.claude-sonnet-4-6",
     "3.00", "15.00", "Bedrock pricing page"),
    ("claude-haiku-4-5", "Claude Haiku 4.5", "us.anthropic.claude-haiku-4-5-20251001-v1:0",
     "1.00", "5.00", "Bedrock pricing page"),
    ("nova-2-lite", "Amazon Nova 2 Lite", "us.amazon.nova-2-lite-v1:0",
     "0.33", "2.75", "AWS Price List API"),
    ("nova-micro", "Amazon Nova Micro", "us.amazon.nova-micro-v1:0",
     "0.035", "0.14", "AWS Price List API"),
    ("ministral-3-3b", "Ministral 3 3B", "mistral.ministral-3-3b-instruct",
     "0.10", "0.10", "AWS Price List API"),
]


def test_catalog_matches_requirement_1():
    got = [
        (e.label, e.name, e.model_id, e.input_usd_per_million,
         e.output_usd_per_million, e.price_source)
        for e in load_catalog(ROOT / "models.json")
    ]
    want = [(a, b, c, Decimal(d), Decimal(e), f) for a, b, c, d, e, f in EXPECTED]
    assert got == want


def test_format_cost_nova_micro_example():
    entry = next(e for e in load_catalog(ROOT / "models.json") if e.label == "nova-micro")
    value = evaluation.cost_usd(51_844, 2_454, entry)
    assert format_cost(value) == "$0.0022"


def test_is_dirty():
    assert not is_dirty("")
    assert not is_dirty("?? new_file\n?? other\n")
    assert is_dirty(" M file")
    assert is_dirty("A  file")
    assert is_dirty("?? new_file\n M file\n")


def test_cost_upper_bound_single_entry_hand_computed():
    entry = ModelEntry("x", "X", "x-id", Decimal("0.035"), Decimal("0.14"), "src")
    # 40 calls * (4,000 * 0.035 + 400 * 0.14) / 1e6 = 40 * 196 / 1e6
    assert cost_upper_bound([entry]) == Decimal("0.00784")


# --- Run analysis on the synthetic fixtures (task 2.3) ------------------------------------

import json  # noqa: E402
from decimal import ROUND_HALF_UP  # noqa: E402

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from opsmem.evaluation import (  # noqa: E402
    PRICE_NOTE,
    count_rejections,
    count_saved,
    cost_usd,
    ended_stopped,
    identical_rows_statement,
    is_failed,
    load_runs,
    render_table,
    row_for,
    saved_rows,
)

FIXTURES = ROOT / "tests" / "fixtures" / "runs"
CATALOG = load_catalog(ROOT / "models.json")
BY_LABEL = {e.label: e for e in CATALOG}


def fixture(label):
    return next(r for r in load_runs(FIXTURES) if r["_label"] == label)


def test_fixture_rows_every_column():
    assert row_for(fixture("nova-micro"), BY_LABEL["nova-micro"]) == [
        "Amazon Nova Micro", "6 of 6", "8", "2", "51,844 / 2,454", "$0.0022", "no"]
    assert row_for(fixture("ministral-3-3b"), BY_LABEL["ministral-3-3b"]) == [
        "Ministral 3 3B", "1 of 6", "4", "2", "15,055 / 2,329", "$0.0017", "yes"]
    assert row_for(fixture("claude-haiku-4-5"), BY_LABEL["claude-haiku-4-5"]) == [
        "Claude Haiku 4.5", "0 of 6", "0", "0", "0 / 0", "$0.0000",
        "AccessDeniedException: You don't have access to the model with the specified model ID."]


def test_stopped_reply_is_not_a_rejection():
    trace = fixture("ministral-3-3b")["trace"]
    assert trace[-1]["result"].startswith("STOPPED")
    assert count_rejections(trace) == 2 and ended_stopped(trace)


def test_failed_run_is_detected():
    assert is_failed(fixture("claude-haiku-4-5")) and not is_failed(fixture("nova-micro"))


def test_rows_ordered_by_cost_descending():
    lines = render_table(load_runs(FIXTURES), CATALOG).splitlines()
    assert [line.split(" | ")[0] for line in lines[2:5]] == [
        "| Amazon Nova Micro", "| Ministral 3 3B", "| Claude Haiku 4.5"]


def test_price_note_below_the_table():
    lines = render_table(load_runs(FIXTURES), CATALOG).splitlines()
    assert lines[-1] == PRICE_NOTE and lines[-2] == "" and lines[-3].startswith("| Claude Haiku 4.5")


def test_identical_rows_statement_on_fixtures():
    assert identical_rows_statement(load_runs(FIXTURES)) == (
        "Only one model saved all 6 configurations, so there is nothing to compare.")


def test_identical_rows_statement_two_models():
    nova = fixture("nova-micro")
    twin = {**nova, "label": "nova-2-lite", "_label": "nova-2-lite"}
    assert identical_rows_statement([nova, twin]) == "The 2 models that saved all 6 configurations saved identical rows."
    other = json.loads(json.dumps(twin))
    other["trace"][-1]["call"]["sample_seconds"] = "30"
    assert identical_rows_statement([nova, other]) == "The 2 models that saved all 6 configurations saved different rows."


def test_saved_rows_from_call_arguments():
    rows = saved_rows(fixture("nova-micro")["trace"])
    assert rows[0] == ("R1", "media", "mst_wr_lat", "latency", "ms", "10") and len(rows) == 6


def test_reading_twice_gives_identical_output():
    assert render_table(load_runs(FIXTURES), CATALOG) == render_table(load_runs(FIXTURES), CATALOG)


# --- Generators for the properties --------------------------------------------------------

SAVED = "Saved as draft: s <- f (u, every 10 s). A person will review it."
REJECTED = "REJECTED (config_field_exists). Not saved. Unknown source_field. Valid source_field: a."
STOPPED = "STOPPED. The same rule rejected 3 times; a person will take over. Stop now."
OTHER = "something else"

calls = st.fixed_dictionaries({k: st.sampled_from(["R1", "R2", "x", "10", "ms"]) for k in (
    "request_id", "service_id", "source_field", "signal_type", "unit", "sample_seconds")})
entries = st.builds(lambda result, call: {"ts": "t", "call": call, "result": result, "db_message": None},
                    st.sampled_from([SAVED, REJECTED, STOPPED, OTHER]), calls)


@st.composite
def runs(draw, label=None):
    label = label or draw(st.sampled_from([e.label for e in CATALOG]))
    if draw(st.integers(min_value=0, max_value=5)) == 0:
        return {"label": label, "_label": label, "commit": "c", "error": draw(st.text(min_size=1, max_size=30).filter(str.strip))}
    trace = draw(st.lists(entries, max_size=12))
    return {"label": label, "_label": label, "commit": "c", "trace": trace,
            "tool_calls": draw(st.integers(min_value=0, max_value=60)),
            "input_tokens": draw(st.integers(min_value=0, max_value=10**7)),
            "output_tokens": draw(st.integers(min_value=0, max_value=10**6))}


run_sets = st.lists(st.sampled_from([e.label for e in CATALOG]), min_size=1, max_size=5, unique=True).flatmap(
    lambda labels: st.tuples(*[runs(label) for label in labels]).map(list))


# Feature: model-evaluation, Property 11: Cost formula and rounding
@settings(max_examples=200)
@given(st.integers(min_value=0, max_value=10**9), st.integers(min_value=0, max_value=10**9),
       st.decimals(min_value=0, max_value=100, places=3), st.decimals(min_value=0, max_value=100, places=3))
def test_property_cost_formula_and_rounding(tin, tout, pin, pout):
    entry = ModelEntry("x", "X", "x", pin, pout, "s")
    expected = ((Decimal(tin) * pin + Decimal(tout) * pout) / Decimal(1_000_000)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    assert format_cost(cost_usd(tin, tout, entry)) == f"${expected}"


# Feature: model-evaluation, Property 1: Price note accompanies every cost output (table part)
@settings(max_examples=100)
@given(run_sets)
def test_property_price_note_below_table(rs):
    lines = render_table(rs, CATALOG).splitlines()
    assert lines[-1] == PRICE_NOTE and lines[-3].startswith("| ")


# Feature: model-evaluation, Property 10: Table row contents
@settings(max_examples=150)
@given(runs())
def test_property_row_contents(run):
    entry = BY_LABEL[run["label"]]
    row = row_for(run, entry)
    assert row[0] == entry.name
    if is_failed(run):
        assert row[1:6] == ["0 of 6", "0", "0", "0 / 0", "$0.0000"] and row[6]
        return
    trace = run["trace"]
    assert row[1] == f"{sum(e['result'] == SAVED for e in trace)} of 6"
    assert row[3] == str(sum(e["result"] == REJECTED for e in trace))
    assert row[2] == str(run["tool_calls"])
    assert row[4] == f"{run['input_tokens']:,} / {run['output_tokens']:,}"
    assert row[6] == ("yes" if trace and trace[-1]["result"] == STOPPED else "no")


# Feature: model-evaluation, Property 12: Row ordering
@settings(max_examples=100)
@given(run_sets)
def test_property_row_ordering(rs):
    lines = render_table(rs, CATALOG).splitlines()
    body = lines[2:2 + len(rs)]
    assert len(body) == len(rs) and lines[2 + len(rs)] == ""
    keyed = sorted(rs, key=lambda r: (-(Decimal(0) if is_failed(r) else cost_usd(
        r["input_tokens"], r["output_tokens"], BY_LABEL[r["label"]])), r["label"]))
    assert [line.split(" | ")[0][2:] for line in body] == [BY_LABEL[r["label"]].name for r in keyed]


full_traces = st.permutations([
    {"ts": "t", "call": {"request_id": f"R{i}", "service_id": "s", "source_field": f"f{i}", "signal_type": "t",
                         "unit": "u", "sample_seconds": "10"}, "result": SAVED, "db_message": None}
    for i in range(1, 7)])


# Feature: model-evaluation, Property 13: Identical rows statement
@settings(max_examples=100)
@given(st.lists(st.tuples(full_traces, st.booleans()), min_size=2, max_size=5))
def test_property_identical_rows_statement(items):
    rs = []
    for i, (trace, change) in enumerate(items):
        trace = json.loads(json.dumps(trace))
        if change and i:
            trace[0]["call"]["unit"] = "other"
        rs.append({"label": f"m{i}", "trace": trace})
    same = len({tuple(saved_rows(r["trace"])) for r in rs}) == 1
    assert identical_rows_statement(rs).endswith("identical rows." if same else "different rows.")
    assert all(count_saved(r["trace"]) == 6 for r in rs)
