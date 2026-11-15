"""The Repeats_Table on the synthetic fixtures of tests/fixtures/runs-repeated. Offline."""
import copy
import io

from opsmem import evaluation
from tests.helpers import ROOT, load_script

script = load_script("summarize_runs")
CATALOG = evaluation.load_catalog(ROOT / "models.json")
REPEATED = ROOT / "tests" / "fixtures" / "runs-repeated"
REPEATED_ONLY = ROOT / "tests" / "fixtures" / "runs-repeated-only"
RUNS = evaluation.load_runs(REPEATED)
HEADER = ("| Model | Mode | Runs | Saved 6 of 6 | Same rows as the first complete run "
          "| Tool calls (min to max) | Rejections (min to max) |")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = script.main(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_every_column_of_every_line():
    assert evaluation.render_repeats(RUNS, CATALOG).splitlines()[:5] == [
        HEADER,
        "|---|---|---|---|---|---|---|",
        "| Amazon Nova Micro | instructive | 4 | 4 of 4 | 3 of 4 | 7 to 9 | 1 to 3 |",
        "| Amazon Nova Micro | raw | 2 | 1 of 2 | 1 of 1 | 4 to 10 | 2 to 4 |",
        "| Ministral 3 3B | instructive | 2 | 0 of 2 | none | 4 | 2 |",
    ]


def test_failed_run_counts_in_runs_and_not_in_the_spans():
    group = [r for r in RUNS if r["label"] == "ministral-3-3b"]
    assert [evaluation.is_failed(r) for r in group] == [False, True]
    entry = next(e for e in CATALOG if e.label == "ministral-3-3b")
    assert evaluation.repeats_row(entry, "instructive", group)[2:] == ["2", "0 of 2", "none", "4", "2"]
    assert evaluation.repeats_row(entry, "instructive", group[1:])[2:] == ["1", "0 of 1", "none", "none", "none"]


def test_differing_rows_listing():
    lines = evaluation.render_repeats(RUNS, CATALOG).splitlines()
    start = lines.index("Differing rows:")
    assert lines[start + 1:] == [
        "- Amazon Nova Micro, instructive, nova-micro-04.json, R4: service api, field api_4xx, type count, "
        "unit count, sampling 10 (first complete run nova-micro-01.json: service api, field api_5xx, "
        "type count, unit count, sampling 10)"]


def test_no_listing_when_all_rows_are_equal():
    same = [r for r in RUNS if r["_file"] != "nova-micro-04.json"]
    assert "Differing rows:" not in evaluation.render_repeats(same, CATALOG)


def test_signal_name_is_not_compared_and_the_note_says_so():
    renamed = copy.deepcopy(RUNS)
    for run_ in renamed:
        for entry in run_.get("trace", []):
            entry["call"]["signal_name"] = "x_" + entry["call"]["signal_name"]
    text = evaluation.render_repeats(RUNS, CATALOG)
    assert evaluation.render_repeats(renamed, CATALOG) == text
    assert "The signal name is not compared" in text
    names = [[e["call"]["signal_name"] for e in r["trace"] if e["result"].startswith("Saved")] for r in RUNS if r["_file"] in (
        "nova-micro-01.json", "nova-micro-02.json")]
    assert set(names[0]).isdisjoint(names[1])  # other names, same rows


def test_single_raw_run_is_listed_with_runs_1():
    runs = [r for r in RUNS if r["_file"] in ("nova-micro-raw-01.json", "claude-sonnet-4-6.json")]
    runs = copy.deepcopy(runs)
    for run_ in runs:
        run_.pop("repeat", None), run_.pop("repeat_count", None)
    lines = evaluation.render_repeats(runs, CATALOG).splitlines()
    assert lines[2] == "| Amazon Nova Micro | raw | 1 | 1 of 1 | 1 of 1 | 10 | 4 |" and lines[3] == ""
    assert evaluation.results_runs(runs) == [r for r in runs if r["label"] == "claude-sonnet-4-6"]


def test_raw_rejections_are_counted_and_stopped_replies_are_not():
    raw = next(r for r in RUNS if r["_file"] == "nova-micro-raw-02.json")
    assert evaluation.count_rejections(raw["trace"]) == 0
    assert evaluation.count_rejections_any_mode(raw["trace"]) == 2
    assert sum(e["result"].startswith("STOPPED") for e in raw["trace"]) == 1


def test_no_group_leaves_header_and_note():
    runs = [r for r in RUNS if r["_file"] == "claude-sonnet-4-6.json"]
    assert evaluation.render_repeats(runs, CATALOG).splitlines() == [
        HEADER, "|---|---|---|---|---|---|---|", "", evaluation.REPEATS_NOTE]


def test_summarizer_with_repeats_prints_both_tables():
    code, out, _ = run([str(REPEATED), "--repeats"])
    lines = out.splitlines()
    assert code == 0
    assert lines[2].startswith("| Claude Sonnet 4.6 | 6 of 6 |") and lines[3].startswith("| Claude Haiku 4.5 | 6 of 6 |")
    assert lines[4] == "" and lines[5] == evaluation.PRICE_NOTE and lines[6] == "" and lines[7] == HEADER
    assert out.endswith(evaluation.render_repeats(RUNS, CATALOG))


def test_summarizer_without_repeats_leaves_repeated_and_raw_runs_out():
    code, out, _ = run([str(REPEATED)])
    assert code == 0 and "Nova Micro" not in out and "Ministral" not in out and "| Mode |" not in out
    assert out == evaluation.render_table(evaluation.results_runs(RUNS), CATALOG)


def test_directory_with_only_repeated_runs():
    code, out, err = run([str(REPEATED_ONLY), "--repeats"])
    assert code == 0 and err == "" and out.splitlines()[0] == HEADER
    assert "| Model | Saved |" not in out
    code, out, err = run([str(REPEATED_ONLY)])
    assert code != 0 and out == "" and "--repeats" in err


def test_empty_directory_is_an_error_with_repeats(tmp_path):
    code, out, err = run([str(tmp_path), "--repeats"])
    assert code != 0 and out == "" and "No run files" in err


def test_run_file_without_mode_is_instructive_in_both_tables(tmp_path):
    import json
    import shutil
    runs = tmp_path / "runs"
    shutil.copytree(REPEATED, runs)
    expected = run([str(runs), "--repeats"])
    for path in runs.glob("*.json"):
        data = json.loads(path.read_text())
        if data.get("mode") == "instructive":
            del data["mode"]
            path.write_text(json.dumps(data))
    assert run([str(runs), "--repeats"]) == expected


def test_same_files_twice_same_output():
    assert run([str(REPEATED), "--repeats"]) == run([str(REPEATED), "--repeats"])
    assert run([str(REPEATED), "--rows"]) == run([str(REPEATED), "--rows"])


def test_rejections_column_counts_both_forms_and_no_stopped_reply():
    def item(result):
        return {"ts": "t", "call": {"request_id": "R1"}, "result": result, "db_message": None}
    trace = [item("REJECTED (config_field_exists). Not saved."), item("ERROR: violates foreign key"),
             item("Saved as draft: x"), item("STOPPED. The same rule rejected 3 times.")]
    run_ = {"label": "nova-micro", "mode": "raw", "_file": "nova-micro-raw.json", "tool_calls": 4, "trace": trace}
    entry = next(e for e in CATALOG if e.label == "nova-micro")
    assert evaluation.count_rejections_any_mode(trace) == 2
    assert evaluation.repeats_row(entry, "raw", [run_])[-1] == "2"
    assert evaluation.count_rejections(trace) == 1  # the Results_Table keeps the model-evaluation definition
    assert evaluation.count_rejections_any_mode([item("STOPPED. x")]) == 0


def test_repeated_run_without_numeric_suffix_is_recognised_from_its_fields(tmp_path):
    import json
    import shutil
    runs = tmp_path / "runs"
    shutil.copytree(REPEATED, runs)
    data = json.loads((REPEATED / "nova-micro-04.json").read_text())
    (runs / "nova-micro-extra.json").write_text(json.dumps(data))
    (runs / "nova-micro-04.json").unlink()
    code, out, _ = run([str(runs), "--repeats"])
    assert code == 0 and "| Amazon Nova Micro | instructive | 4 |" in out
    assert "nova-micro-extra.json" in out  # listed as a differing row of a Repeated_Run
    assert "Nova Micro" not in out.split(HEADER)[0]  # and absent from the Results_Table
