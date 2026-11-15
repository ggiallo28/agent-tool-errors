"""--repeat and --mode of scripts/run_experiment.py, with fakes for every dependency. Offline."""
import io
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from opsmem import evaluation
from tests.helpers import ROOT, load_script

script = load_script("run_experiment")
CATALOG = evaluation.load_catalog(ROOT / "models.json")
LABELS = [e.label for e in CATALOG]
COMMIT = "f" * 40
NOW = datetime(2026, 11, 15, 9, 0, 0, tzinfo=timezone.utc)  # one fixed second for every run
RESULT = {"tool_calls": 1, "trace": [{"ts": "t", "call": {}, "result": "Saved as draft: x", "db_message": None}],
          "input_tokens": 10, "output_tokens": 2}
FAST = settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


class Rig:
    def __init__(self, fail=()):
        self.calls, self.git_calls, self.fail = [], [], set(fail)

    def run_model(self, entry, task, run_id, mode):
        self.calls.append((entry.label, run_id, mode))
        if len(self.calls) in self.fail or entry.label in self.fail:
            raise RuntimeError(f"no access to {entry.model_id}")
        return dict(RESULT)

    def git(self, args):
        self.git_calls.append(args[0])
        return "" if args[0] == "status" else COMMIT + "\n"

    def main(self, argv, out_dir=None):
        out, err = io.StringIO(), io.StringIO()
        if out_dir is not None:
            argv = [*argv, "--out", str(out_dir)]
        code = script.main(argv, run_model=self.run_model, git=self.git, now=lambda: NOW,
                           check_config=lambda required: None, root=ROOT, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()


def files(directory):
    return {p.name: json.loads(p.read_text()) for p in sorted(Path(directory).glob("*.json"))}


def cost_line(out):
    return next(line for line in out.splitlines() if line.startswith("Cost upper bound"))


def expected_names(labels, mode, count):
    base = [f"{label}-raw" if mode == "raw" else label for label in labels]
    if count == 1:
        return sorted(f"{b}.json" for b in base)
    return sorted(f"{b}-{n:02d}.json" for b in base for n in range(1, count + 1))


def test_file_names_for_repeat_mode_and_both(tmp_path):
    for sub, argv, names in [
        ("a", ["--repeat", "3"], ["nova-micro-01.json", "nova-micro-02.json", "nova-micro-03.json"]),
        ("b", ["--mode", "raw"], ["nova-micro-raw.json"]),
        ("c", ["--repeat", "3", "--mode", "raw"],
         ["nova-micro-raw-01.json", "nova-micro-raw-02.json", "nova-micro-raw-03.json"]),
    ]:
        code, _, _ = Rig().main(["--yes", "--models", "nova-micro", *argv], tmp_path / sub)
        assert code == 0 and list(files(tmp_path / sub)) == names


def test_existing_file_in_the_middle_is_kept_and_the_others_run(tmp_path):
    (tmp_path / "nova-micro-02.json").write_text("keep me")
    rig = Rig()
    code, out, _ = rig.main(["--yes", "--models", "nova-micro", "--repeat", "3"], tmp_path)
    assert code == 0 and (tmp_path / "nova-micro-02.json").read_text() == "keep me"
    assert len(rig.calls) == 2 and "nova-micro-02.json" in out
    assert sorted(p.name for p in tmp_path.glob("*.json")) == [
        "nova-micro-01.json", "nova-micro-02.json", "nova-micro-03.json"]


@pytest.mark.parametrize("argv", [["--repeat", "0"], ["--repeat", "21"], ["--repeat", "x"], ["--repeat", "2.5"],
                                  ["--mode", "other"]])
def test_invalid_repeat_or_mode_is_refused(argv, tmp_path, capsys):
    rig = Rig()
    with pytest.raises(SystemExit) as stop:
        rig.main(["--yes", *argv], tmp_path)
    err = capsys.readouterr().err
    assert stop.value.code != 0 and rig.calls == [] and rig.git_calls == []
    assert ("from 1 to 20" in err) if argv[0] == "--repeat" else ("raw" in err and "instructive" in err)


def test_without_yes_nothing_runs_and_the_bound_is_multiplied(tmp_path):
    rig = Rig()
    code, out, _ = rig.main(["--models", "nova-micro", "--repeat", "5", "--mode", "raw"], tmp_path)
    entry = next(e for e in CATALOG if e.label == "nova-micro")
    bound = evaluation.cost_upper_bound([entry]) * 5
    assert code == 0 and rig.calls == [] and rig.git_calls == [] and list(tmp_path.iterdir()) == []
    assert cost_line(out).startswith(f"Cost upper bound: {evaluation.format_cost(bound)} (")
    assert "for 5 runs of each model. " + evaluation.PRICE_NOTE in cost_line(out)


def test_default_arguments_print_the_line_of_before(tmp_path):
    _, out, _ = Rig().main(["--models", "nova-micro"], tmp_path)
    assert cost_line(out) == (
        "Cost upper bound: $0.0078 (40 tool calls per run, 4,000 input and 400 output tokens per call). "
        + evaluation.PRICE_NOTE)


def test_mode_reaches_the_model_and_every_run_file(tmp_path):
    rig = Rig(fail={2})
    rig.main(["--yes", "--models", "nova-micro", "--repeat", "3", "--mode", "raw"], tmp_path)
    got = files(tmp_path)
    assert [c[2] for c in rig.calls] == ["raw"] * 3
    assert [f["mode"] for f in got.values()] == ["raw"] * 3 and "error" in got["nova-micro-raw-02.json"]
    rig = Rig()
    rig.main(["--yes", "--models", "nova-micro"], tmp_path / "default")
    assert rig.calls[0][2] == "instructive" and files(tmp_path / "default")["nova-micro.json"]["mode"] == "instructive"


def test_run_ids_are_unique_with_a_fixed_clock_and_a_failed_start(tmp_path):
    rig = Rig(fail={1, "claude-haiku-4-5"})
    rig.main(["--yes", "--models", "nova-micro,claude-haiku-4-5", "--repeat", "3"], tmp_path)
    ids = [f["run_id"] for f in files(tmp_path).values()]
    assert len(ids) == 6 and len(set(ids)) == 6
    assert f"eval-nova-micro-instructive-02-{int(NOW.timestamp())}" in ids
    for name, data in files(tmp_path).items():
        assert f"-instructive-{data['repeat']:02d}-" in data["run_id"] and data["label"] in data["run_id"], name


def test_repeat_fields_only_when_repeating(tmp_path):
    rig = Rig(fail={2})
    rig.main(["--yes", "--models", "nova-micro", "--repeat", "3"], tmp_path / "three")
    got = files(tmp_path / "three")
    assert [(f["repeat"], f["repeat_count"]) for f in got.values()] == [(1, 3), (2, 3), (3, 3)]
    assert "error" in got["nova-micro-02.json"] and "trace" not in got["nova-micro-02.json"]
    Rig().main(["--yes", "--models", "nova-micro", "--repeat", "1"], tmp_path / "one")
    single = files(tmp_path / "one")["nova-micro.json"]
    assert "repeat" not in single and "repeat_count" not in single
    assert {"model_id", "label", "mode", "commit", "started_at", "run_id", "trace"} <= set(single)


# --- Properties ---------------------------------------------------------------------------

subsets = st.lists(st.sampled_from(LABELS), min_size=1, max_size=3, unique=True)
modes = st.sampled_from(["raw", "instructive"])
counts = st.integers(min_value=1, max_value=20)
small = st.integers(min_value=1, max_value=4)


def argv_for(labels, mode, count, yes=True):
    return [*(["--yes"] if yes else []), "--models", ",".join(labels), "--repeat", str(count), "--mode", mode]


# Feature: repeated-runs, Property 1: Invalid repeat or mode is refused
@FAST
@given(st.one_of(st.integers(max_value=0), st.integers(min_value=21, max_value=10**6),
                 st.text(alphabet="abcxyz.-+ ", min_size=1, max_size=6)).map(str),
       st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12).filter(
           lambda m: m not in ("raw", "instructive")))
def test_property_invalid_repeat_or_mode(bad_repeat, bad_mode):
    for argv in (["--repeat=" + bad_repeat], ["--mode", bad_mode]):
        with tempfile.TemporaryDirectory() as out_dir:
            rig = Rig()
            with pytest.raises(SystemExit) as stop:
                rig.main(["--yes", *argv], out_dir)
            assert stop.value.code != 0 and rig.calls == [] and list(Path(out_dir).iterdir()) == []


# Feature: repeated-runs, Property 2: Run count and order
# Feature: repeated-runs, Property 3: Unique run identifiers
# Feature: repeated-runs, Property 6: Mode reaches the run and the file
# Feature: repeated-runs, Property 7: File names
@FAST
@given(subsets, modes, small)
def test_property_count_order_ids_mode_and_names(labels, mode, count):
    with tempfile.TemporaryDirectory() as out_dir:
        rig = Rig()
        code, _, _ = rig.main(argv_for(labels, mode, count), out_dir)
        ordered = [e.label for e in CATALOG if e.label in labels]
        assert code == 0 and [c[0] for c in rig.calls] == [label for label in ordered for _ in range(count)]
        ids = [c[1] for c in rig.calls]
        assert len(set(ids)) == len(ids)
        for position, (label, run_id, got_mode) in enumerate(rig.calls):
            assert got_mode == mode and run_id.startswith(f"eval-{label}-{mode}-{position % count + 1:02d}-")
        got = files(out_dir)
        assert list(got) == expected_names(labels, mode, count)
        assert all(data["mode"] == mode for data in got.values())


# Feature: repeated-runs, Property 4: Repetition fields
# Feature: repeated-runs, Property 5: Failed start does not stop the repetitions
@FAST
@given(subsets, modes, small, st.sets(st.integers(min_value=1, max_value=12)))
def test_property_repetition_fields_and_failures(labels, mode, count, failing):
    with tempfile.TemporaryDirectory() as out_dir:
        rig = Rig(fail=failing)
        code, _, _ = rig.main(argv_for(labels, mode, count), out_dir)
        got = files(out_dir)
        assert code == 0 and list(got) == expected_names(labels, mode, count)
        assert len(rig.calls) == len(labels) * count
        failed = {rig.calls[i - 1][1] for i in failing if i <= len(rig.calls)}
        for data in got.values():
            assert ("error" in data and "trace" not in data) == (data["run_id"] in failed)
            assert data["mode"] == mode
            if count > 1:
                assert data["repeat_count"] == count and 1 <= data["repeat"] <= count
                assert f"-{data['repeat']:02d}-" in data["run_id"]
            else:
                assert "repeat" not in data and "repeat_count" not in data


# Feature: repeated-runs, Property 8: Existing files are never overwritten
@FAST
@given(modes, small, st.data(), st.binary(max_size=32))
def test_property_existing_files_untouched(mode, count, data, content):
    names = expected_names(["nova-micro"], mode, count)
    existing = data.draw(st.sets(st.sampled_from(names)))
    with tempfile.TemporaryDirectory() as out_dir:
        for name in existing:
            (Path(out_dir) / name).write_bytes(content)
        rig = Rig()
        code, _, _ = rig.main(argv_for(["nova-micro"], mode, count), out_dir)
        assert code == 0 and len(rig.calls) == count - len(existing)
        assert all((Path(out_dir) / name).read_bytes() == content for name in existing)
        assert sorted(p.name for p in Path(out_dir).glob("*.json")) == names


# Feature: repeated-runs, Property 9: Cost bound scales with the Repeat_Count, and nothing runs without --yes
@FAST
@given(subsets, modes, counts)
def test_property_cost_bound_and_no_run_without_yes(labels, mode, count):
    with tempfile.TemporaryDirectory() as out_dir:
        rig = Rig()
        code, out, _ = rig.main(argv_for(labels, mode, count, yes=False), out_dir)
        chosen = [e for e in CATALOG if e.label in labels]
        bound = evaluation.cost_upper_bound(chosen) * count
        assert code == 0 and rig.calls == [] and rig.git_calls == [] and list(Path(out_dir).iterdir()) == []
        assert cost_line(out).startswith(f"Cost upper bound: {evaluation.format_cost(bound)} (")
        assert (f"for {count} runs of each model" in cost_line(out)) == (count > 1)
        assert evaluation.PRICE_NOTE in cost_line(out)
