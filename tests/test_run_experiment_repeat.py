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
