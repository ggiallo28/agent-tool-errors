"""Properties of the repeated-runs core (opsmem/evaluation.py) and of the summarizer output. Offline."""
import copy
import io
import json
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from opsmem import evaluation as ev
from tests.helpers import ROOT, load_script

summarize = load_script("summarize_runs")
make_gists = load_script("make_gists")
CATALOG = ev.load_catalog(ROOT / "models.json")
LABELS = [e.label for e in CATALOG]
NAME = {e.label: e.name for e in CATALOG}
COMMIT = "0123456789abcdef0123456789abcdef01234567"
PROPS = settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
REQUESTS = ["R1", "R2", "R3", "R4", "R5", "R6"]
SAVED = "Saved as draft: x"
REJECTED = {"instructive": "REJECTED (config_field_exists). Not saved.", "raw": "ERROR: violates foreign key"}
STOPPED = "STOPPED. The same rule rejected 3 times; a person will take over. Stop now."


def entry(request, field, name, result):
    return {"ts": "t", "call": {"request_id": request, "service_id": "s", "signal_name": name,
                                "signal_type": "count", "source_field": field, "unit": "count",
                                "sample_seconds": "10"}, "result": result, "db_message": None}


@st.composite
def a_run(draw, label, mode, file_name, repeated):
    run = {"label": label, "_label": Path(file_name).stem, "_file": file_name, "commit": COMMIT,
           "started_at": "2026-01-01T00:00:00Z"}
    if draw(st.booleans()):
        run["mode"] = mode
    elif mode != "instructive":
        run["mode"] = mode
    if repeated:
        run.update(repeat=draw(st.integers(1, 20)), repeat_count=draw(st.integers(2, 20)))
    kind = draw(st.sampled_from(["complete", "complete", "partial", "failed"]))
    if kind == "failed":
        return {**run, "error": "AccessDeniedException"}
    saved = REQUESTS if kind == "complete" else REQUESTS[:draw(st.integers(0, 5))]
    fields = draw(st.lists(st.sampled_from(["f1", "f2"]), min_size=len(saved), max_size=len(saved)))
    trace = [entry("R9", "bad", "n", REJECTED[mode]) for _ in range(draw(st.integers(0, 3)))]
    trace += [entry(r, f, draw(st.sampled_from(["a", "b"])) + r, SAVED) for r, f in zip(saved, fields)]
    if kind == "partial":
        trace.append(entry("R9", "bad", "n", STOPPED))
    return {**run, "run_id": f"eval-{file_name}", "trace": trace, "tool_calls": draw(st.integers(0, 40)),
            "follow_ups": 0, "escalated": None, "input_tokens": 10, "output_tokens": 2}


@st.composite
def run_sets(draw):
    runs = []
    for label in draw(st.lists(st.sampled_from(LABELS), min_size=1, max_size=3, unique=True)):
        for mode in draw(st.lists(st.sampled_from(["instructive", "raw"]), min_size=1, max_size=2, unique=True)):
            base = ev.base_name(label, mode)
            if draw(st.booleans()):
                runs.append(draw(a_run(label, mode, f"{base}.json", False)))
            for n in range(1, draw(st.integers(0, 3)) + 1):
                runs.append(draw(a_run(label, mode, f"{base}-{n:02d}.json", True)))
    return sorted(runs, key=lambda r: r["_file"])


def groups_of(runs):
    groups = {}
    for run in runs:
        groups.setdefault((run["label"], run.get("mode", "instructive")), []).append(run)
    return groups


def table_lines(text):
    return [line for line in text.splitlines()[2:] if line.startswith("| ")]


def cells(line):
    return [c.strip() for c in line.strip("|").split("|")]


# Feature: repeated-runs, Property 10: Repeated runs are recognised from the fields
@PROPS
@given(st.sampled_from(LABELS), st.booleans(), st.booleans(),
       st.sampled_from(["{}.json", "{}-01.json", "{}-raw-07.json", "x.json"]))
def test_property_repeated_from_fields(label, has_repeat, has_count, pattern):
    run = {"label": label, "_file": pattern.format(label), "_label": pattern.format(label)[:-5]}
    if has_repeat:
        run["repeat"] = 1
    if has_count:
        run["repeat_count"] = 3
    assert ev.is_repeated(run) == (has_repeat and has_count)


# Feature: repeated-runs, Property 11: Results_Table selection
# Feature: repeated-runs, Property 19: Missing mode is instructive
@PROPS
@given(run_sets())
def test_property_results_selection(runs):
    selected = ev.results_runs(runs)
    assert selected == [r for r in runs if not ("repeat" in r and "repeat_count" in r)
                        and r.get("mode", "instructive") == "instructive"]
    with_mode = [{**r, "mode": r.get("mode", "instructive")} for r in runs]
    assert [r["_file"] for r in ev.results_runs(with_mode)] == [r["_file"] for r in selected]
    assert ev.render_repeats(with_mode, CATALOG) == ev.render_repeats(runs, CATALOG)
    if selected:
        assert ev.render_table(ev.results_runs(selected), CATALOG) == ev.render_table(selected, CATALOG)


# Feature: repeated-runs, Property 12: Repeats_Table line set
@PROPS
@given(run_sets())
def test_property_line_set(runs):
    expected = [(label, mode) for (label, mode), group in groups_of(runs).items()
                if mode == "raw" or any("repeat" in r and "repeat_count" in r for r in group)]
    expected.sort(key=lambda g: (LABELS.index(g[0]), g[1] == "raw"))
    lines = table_lines(ev.render_repeats(runs, CATALOG))
    assert [tuple(cells(line)[:2]) for line in lines] == [(NAME[label], mode) for label, mode in expected]
    text = ev.render_repeats(runs, CATALOG)
    assert text.splitlines()[:2] == [ev.REPEATS_HEADER, ev.REPEATS_RULE] and ev.REPEATS_NOTE in text


# Feature: repeated-runs, Property 13: Repeats_Table counts and spans
# Feature: repeated-runs, Property 14: Same rows
@PROPS
@given(run_sets())
def test_property_counts_spans_and_same_rows(runs):
    lines = {tuple(cells(line)[:2]): cells(line)[2:] for line in table_lines(ev.render_repeats(runs, CATALOG))}
    for (label, mode), group in groups_of(runs).items():
        if (NAME[label], mode) not in lines:
            continue
        runs_cell, saved_cell, same_cell, calls_cell, rejections_cell = lines[(NAME[label], mode)]
        complete = [r for r in group if "trace" in r and sum(e["result"] == SAVED for e in r["trace"]) == 6]
        started = [r for r in group if "trace" in r]
        assert runs_cell == str(len(group)) and saved_cell == f"{len(complete)} of {len(group)}"

        def text(values):
            if not values:
                return "none"
            return str(min(values)) if min(values) == max(values) else f"{min(values)} to {max(values)}"
        assert calls_cell == text([r["tool_calls"] for r in started])
        assert rejections_cell == text([sum(e["result"] == REJECTED[mode] for e in r["trace"]) for r in started])
        if not complete:
            assert same_cell == "none"
        else:
            def key(run):
                return sorted((e["call"]["request_id"], e["call"]["source_field"]) for e in run["trace"]
                              if e["result"] == SAVED)
            assert same_cell == f"{sum(key(r) == key(complete[0]) for r in complete)} of {len(complete)}"
    renamed = copy.deepcopy(runs)
    for run in renamed:
        for item in run.get("trace", []):
            item["call"]["signal_name"] += "_other"
    assert ev.render_repeats(renamed, CATALOG) == ev.render_repeats(runs, CATALOG)


# Feature: repeated-runs, Property 15: Differing rows
@PROPS
@given(run_sets())
def test_property_differing_rows(runs):
    text = ev.render_repeats(runs, CATALOG)
    expected = []
    for entry_, mode, group in ev.repeat_groups(runs, CATALOG):
        complete = [r for r in group if ev.is_complete(r)]
        for run in complete[1:]:
            for request in REQUESTS:
                if ev.row_keys(run)[request] != ev.row_keys(complete[0])[request]:
                    expected.append((entry_.name, mode, run["_file"], request, complete[0]["_file"]))
    if not expected:
        assert ev.DIFFERING_TITLE not in text
        return
    listing = text.split(ev.DIFFERING_TITLE + "\n", 1)[1].splitlines()
    assert len(listing) == len(expected)
    for line, (name, mode, file_name, request, first) in zip(listing, expected):
        assert line.startswith(f"- {name}, {mode}, {file_name}, {request}: ")
        assert f"(first complete run {first}: " in line and "field f" in line


def write_runs(directory, runs):
    for run in runs:
        data = {k: v for k, v in run.items() if not k.startswith("_")}
        (Path(directory) / run["_file"]).write_text(json.dumps(data))


def summarize_main(argv):
    out, err = io.StringIO(), io.StringIO()
    code = summarize.main(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()




# Feature: repeated-runs, Property 18: Gists use only single instructive runs
@PROPS
@given(run_sets())
def test_property_gists_use_only_single_instructive_runs(runs):
    def generate(run_dir, gists_dir):
        code = make_gists.main([str(run_dir)], root=ROOT, gists_dir=gists_dir, stdout=io.StringIO(),
                               stderr=io.StringIO())
        return code, {p.name: p.read_bytes() for p in sorted(Path(gists_dir).glob("*.md"))}
    with tempfile.TemporaryDirectory() as tmp:
        everything, selected = Path(tmp) / "all", Path(tmp) / "selected"
        everything.mkdir(), selected.mkdir()
        write_runs(everything, runs)
        write_runs(selected, ev.results_runs(runs))
        got = generate(everything, Path(tmp) / "g1")
        assert got == generate(selected, Path(tmp) / "g2")
        assert (got[0] == 0) == bool(ev.results_runs(runs))
