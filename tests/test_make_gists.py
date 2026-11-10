"""scripts/make_gists.py and evaluation.render_gists on synthetic run files. Offline."""
import io
import json
import shutil
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from opsmem import evaluation
from opsmem.evaluation import CLOSING_LINE, PRICE_NOTE, load_catalog, render_gists
from tests.helpers import ROOT, load_script

script = load_script("make_gists")
FIXTURES = ROOT / "tests" / "fixtures" / "runs"
CATALOG = load_catalog(ROOT / "models.json")
BY_LABEL = {e.label: e for e in CATALOG}
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def generate(run_dir, gists_dir):
    out, err = io.StringIO(), io.StringIO()
    code = script.main([str(run_dir)], root=ROOT, gists_dir=gists_dir, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def read_all(directory):
    return {p.name: p.read_bytes() for p in sorted(Path(directory).glob("*.md"))}


def test_twice_gives_identical_files(tmp_path):
    generate(FIXTURES, tmp_path / "a")
    generate(FIXTURES, tmp_path / "b")
    assert read_all(tmp_path / "a") == read_all(tmp_path / "b") and len(read_all(tmp_path / "a")) == 3


def test_setup_line_holds_the_commit(tmp_path):
    generate(FIXTURES, tmp_path)
    for name, data in read_all(tmp_path).items():
        setup = next(line for line in data.decode().splitlines() if line.startswith("Setup: "))
        assert COMMIT in setup and "us-east-1" in setup and "PostgreSQL 16 in Docker" in setup, name


def test_fail_safe_gist_only_when_a_model_saved_fewer_than_six(tmp_path):
    generate(FIXTURES, tmp_path / "with")
    assert (tmp_path / "with" / "small-models-fail-safe.md").exists()
    only_full = tmp_path / "full"
    only_full.mkdir()
    shutil.copy(FIXTURES / "nova-micro.json", only_full)
    shutil.copy(FIXTURES / "claude-haiku-4-5.json", only_full)  # a Failed_Run is not a Finished_Model
    code, out, _ = generate(only_full, tmp_path / "without")
    assert code == 0 and not (tmp_path / "without" / "small-models-fail-safe.md").exists()
    assert "Skipped small-models-fail-safe.md" in out


def test_stale_gist_is_removed(tmp_path):
    generate(FIXTURES, tmp_path)
    only_full = tmp_path / "full"
    only_full.mkdir()
    shutil.copy(FIXTURES / "nova-micro.json", only_full)
    generate(only_full, tmp_path)
    assert not (tmp_path / "small-models-fail-safe.md").exists()


def test_mixed_commits_write_nothing(tmp_path):
    runs = tmp_path / "runs"
    shutil.copytree(FIXTURES, runs)
    data = json.loads((runs / "nova-micro.json").read_text())
    data["commit"] = "b" * 40
    (runs / "nova-micro.json").write_text(json.dumps(data))
    code, _, err = generate(runs, tmp_path / "gists")
    assert code != 0 and COMMIT in err and "b" * 40 in err and not (tmp_path / "gists").exists()


def test_no_full_save_model_skips_the_first_gist(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    shutil.copy(FIXTURES / "ministral-3-3b.json", runs)
    code, out, _ = generate(runs, tmp_path / "gists")
    assert code == 0 and "Skipped agent-learns-from-rejections.md" in out
    assert sorted(read_all(tmp_path / "gists")) == ["five-models.md", "small-models-fail-safe.md"]


def test_every_file_ends_with_the_closing_line(tmp_path):
    generate(FIXTURES, tmp_path)
    for data in read_all(tmp_path).values():
        assert data.decode().rstrip("\n").splitlines()[-1] == CLOSING_LINE


def test_empty_directory_is_an_error(tmp_path):
    code, _, err = generate(tmp_path, tmp_path / "gists")
    assert code != 0 and "No run files" in err


# --- Properties ---------------------------------------------------------------------------

SAVED = "Saved as draft: s <- f (u, every 10 s). A person will review it."
REJECTED = "REJECTED (config_field_exists). Not saved. Unknown source_field. Valid source_field: a."
STOPPED = "STOPPED. The same rule rejected 3 times; a person will take over. Stop now."


def saved_entry(i):
    return {"ts": f"2026-01-01T00:00:{i:02d}.000+00:00", "call": {
        "request_id": f"R{i}", "service_id": "s", "signal_name": f"n{i}", "signal_type": "t",
        "source_field": f"f{i}", "unit": "u", "sample_seconds": "10"}, "result": SAVED, "db_message": None}


@st.composite
def run_for(draw, label):
    if draw(st.integers(min_value=0, max_value=6)) == 0:
        return {"label": label, "_label": label, "commit": COMMIT, "started_at": "2026-01-01T00:00:00Z",
                "error": "AccessDeniedException"}
    saved = draw(st.integers(min_value=0, max_value=6))
    trace = [saved_entry(i) for i in range(1, saved + 1)]
    trace += [{"ts": "t", "call": {"request_id": "R9", "note": draw(st.text(max_size=8))}, "result": r,
               "db_message": draw(st.one_of(st.none(), st.text(max_size=10)))}
              for r in draw(st.lists(st.sampled_from([REJECTED, STOPPED]), max_size=4))]
    return {"label": label, "_label": label, "commit": COMMIT, "started_at": "2026-01-01T00:00:00Z",
            "run_id": f"eval-{label}-1", "trace": trace, "tool_calls": len(trace), "follow_ups": 0,
            "escalated": None if saved == 6 else "rule x rejected 3 times",
            "input_tokens": draw(st.integers(min_value=0, max_value=10**6)),
            "output_tokens": draw(st.integers(min_value=0, max_value=10**5))}


run_sets = st.lists(st.sampled_from(list(BY_LABEL)), min_size=1, max_size=5, unique=True).flatmap(
    lambda labels: st.tuples(*[run_for(label) for label in labels]).map(list))
PROPS = settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


def gists_of(runs):
    return render_gists(runs, CATALOG, "Installation: install-07\nRequests:\nR1: x", "Prompt.", "2026-01-01")


def is_finished(run):
    return "trace" in run


def saved(run):
    return sum(e["result"] == SAVED for e in run.get("trace", []))


# Feature: model-evaluation, Property 1: Price note accompanies every cost output (five-models.md part)
# Feature: model-evaluation, Property 14: Deterministic output
@PROPS
@given(run_sets)
def test_property_deterministic_and_price_note(runs):
    first, second = gists_of(runs), gists_of(json.loads(json.dumps(runs)))
    assert first == second and PRICE_NOTE in first["five-models.md"]


# Feature: model-evaluation, Property 15: Gist model selection comes from the data
@PROPS
@given(run_sets)
def test_property_cheapest_full_save_model(runs):
    gists = gists_of(runs)
    full = [r for r in runs if is_finished(r) and saved(r) == 6]
    if not full:
        assert "agent-learns-from-rejections.md" not in gists
        return
    cheapest = min(full, key=lambda r: (evaluation.run_cost(r, BY_LABEL[r["label"]]), r["label"]))
    assert gists["agent-learns-from-rejections.md"].splitlines()[0] == (
        f"# {BY_LABEL[cheapest['label']].name} learns a schema from database rejections")


# Feature: model-evaluation, Property 16: Raw trace round trip
def trace_blocks(text):
    """The text blocks of a gist that hold a raw trace: JSON lines followed by the summary line."""
    blocks = [part.split("\n```", 1)[0] for part in text.split("```text\n")[1:]]
    return [block.splitlines()[:-1] for block in blocks if block.splitlines()[-1:][0:1]
            and block.splitlines()[-1].startswith("run=")]


@PROPS
@given(run_sets)
def test_property_raw_trace_round_trip(runs):
    gists = gists_of(runs)
    expected = []
    full = [r for r in runs if is_finished(r) and saved(r) == 6]
    if full:
        cheapest = min(full, key=lambda r: (evaluation.run_cost(r, BY_LABEL[r["label"]]), r["label"]))
        assert [[json.loads(line) for line in block] for block in trace_blocks(
            gists["agent-learns-from-rejections.md"])] == [cheapest["trace"]]
    partial = [r for r in runs if is_finished(r) and saved(r) < 6]
    partial.sort(key=lambda r: (-evaluation.run_cost(r, BY_LABEL[r["label"]]), r["label"]))
    expected = [r["trace"] for r in partial]
    got = [[json.loads(line) for line in block] for block in trace_blocks(gists.get("small-models-fail-safe.md", ""))]
    assert got == expected


# Feature: model-evaluation, Property 17: Fail-safe gist is conditional
@PROPS
@given(run_sets)
def test_property_fail_safe_conditional(runs):
    gists = gists_of(runs)
    partial = [r for r in runs if is_finished(r) and saved(r) < 6]
    assert ("small-models-fail-safe.md" in gists) == bool(partial)
    for run in partial:
        assert f"Rows kept: {saved(run)} of 6, counted from the trace." in gists["small-models-fail-safe.md"]


# Feature: model-evaluation, Property 18: Gist framing
@PROPS
@given(run_sets)
def test_property_framing(runs):
    for name, text in gists_of(runs).items():
        assert text.rstrip("\n").splitlines()[-1] == CLOSING_LINE, name
        assert COMMIT in next(line for line in text.splitlines() if line.startswith("Setup: "))


# Feature: model-evaluation, Property 19: Mixed commits block generation
@PROPS
@given(st.lists(st.sampled_from(["a" * 40, "b" * 40, "c" * 40]), min_size=2, max_size=4).filter(
    lambda commits: len(set(commits)) > 1))
def test_property_mixed_commits(commits):
    with tempfile.TemporaryDirectory() as tmp:
        runs = Path(tmp) / "runs"
        runs.mkdir()
        for label, commit in zip(BY_LABEL, commits):
            data = json.loads((FIXTURES / "nova-micro.json").read_text())
            data.update(label=label, commit=commit)
            (runs / f"{label}.json").write_text(json.dumps(data))
        code, _, err = generate(runs, Path(tmp) / "gists")
        assert code != 0 and all(c in err for c in set(commits)) and not (Path(tmp) / "gists").exists()
