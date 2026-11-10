"""scripts/run_experiment.py with fake model runner, git, clock and config check. Offline."""
import io
import json
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
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
NOW = datetime(2026, 11, 10, 14, 0, 0, tzinfo=timezone.utc)
RESULT = {"tool_calls": 1, "rejections": {}, "follow_ups": 0, "escalated": None, "flagged": [],
          "trace": [{"ts": "t", "call": {}, "result": "Saved as draft: x", "db_message": None}],
          "input_tokens": 10, "output_tokens": 2, "final_text": "done"}


class Rig:
    def __init__(self, porcelain="", fail=(), git_error=None, result=None):
        self.events, self.models = [], []
        self.porcelain, self.fail, self.git_error = porcelain, set(fail), git_error
        self.result = result if result is not None else RESULT

    def run_model(self, entry, task, run_id):
        self.events.append(("model", entry.label))
        self.models.append((entry.label, task, run_id))
        if entry.label in self.fail:
            raise RuntimeError(f"no access to {entry.model_id}")
        return dict(self.result)

    def git(self, args):
        self.events.append(("git", args[0]))
        if self.git_error:
            raise script.GitError(self.git_error)
        return self.porcelain if args[0] == "status" else COMMIT + "\n"

    def check(self, required):
        self.events.append(("check", tuple(required)))

    def main(self, argv, out_dir=None):
        out, err = io.StringIO(), io.StringIO()
        if out_dir is not None:
            argv = [*argv, "--out", str(out_dir)]
        original = out.write

        def write(text):
            if text.strip():
                self.events.append(("print", text.strip().splitlines()[0][:30]))
            return original(text)
        out.write = write
        code = script.main(argv, run_model=self.run_model, git=self.git, now=lambda: NOW,
                           check_config=self.check, root=ROOT, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()


def files(directory):
    return {p.stem: json.loads(p.read_text()) for p in Path(directory).glob("*.json")}


def test_incomplete_configuration_calls_no_model(tmp_path):
    rig = Rig()

    def missing(required):
        raise SystemExit(1)
    rig.check = missing
    with pytest.raises(SystemExit):
        rig.main(["--yes"], tmp_path)
    assert rig.models == [] and not any(e[0] == "git" for e in rig.events)


def test_without_yes_prints_estimate_and_calls_nothing(tmp_path):
    rig = Rig()
    code, out, _ = rig.main([], tmp_path)
    assert code == 0 and rig.models == [] and not any(e[0] == "git" for e in rig.events)
    assert "Cost upper bound: $" in out and evaluation.PRICE_NOTE in out
    assert list(tmp_path.iterdir()) == []


def test_dirty_tree_blocks_the_run(tmp_path):
    rig = Rig(porcelain=" M opsmem/writer.py\n")
    code, _, err = rig.main(["--yes"], tmp_path)
    assert code != 0 and "commit first" in err and rig.models == []


def test_untracked_files_alone_do_not_block(tmp_path):
    rig = Rig(porcelain="?? notes.txt\n?? results/\n")
    code, _, _ = rig.main(["--yes", "--models", "nova-micro"], tmp_path)
    assert code == 0 and [m[0] for m in rig.models] == ["nova-micro"]


def test_order_of_events(tmp_path):
    rig = Rig()
    rig.main(["--yes", "--models", "nova-micro"], tmp_path)
    kinds = [e for e in rig.events if e[0] != "print" or e[1].startswith("Cost upper bound")]
    assert kinds[0][0] == "check"
    assert [k for k in kinds[1:4]] == [("print", "Cost upper bound: $0.0078 (40 "), ("git", "status"),
                                       ("git", "rev-parse")]
    assert kinds[4] == ("model", "nova-micro")


def test_existing_run_file_is_not_overwritten(tmp_path):
    (tmp_path / "nova-micro.json").write_text("keep me")
    rig = Rig()
    code, out, _ = rig.main(["--yes", "--models", "nova-micro,nova-2-lite"], tmp_path)
    assert code == 0 and (tmp_path / "nova-micro.json").read_text() == "keep me"
    assert [m[0] for m in rig.models] == ["nova-2-lite"] and "nova-micro.json" in out


def test_failed_start_is_recorded_and_next_model_runs(tmp_path):
    rig = Rig(fail={"claude-haiku-4-5"})
    code, _, _ = rig.main(["--yes", "--models", "claude-haiku-4-5,nova-micro"], tmp_path)
    got = files(tmp_path)
    assert code == 0 and [m[0] for m in rig.models] == ["claude-haiku-4-5", "nova-micro"]
    assert "no access to" in got["claude-haiku-4-5"]["error"] and "trace" not in got["claude-haiku-4-5"]
    assert got["nova-micro"]["trace"] == RESULT["trace"]


def test_every_run_file_holds_the_commit(tmp_path):
    rig = Rig(fail={"nova-2-lite"})
    rig.main(["--yes"], tmp_path)
    got = files(tmp_path)
    assert set(got) == set(LABELS) and all(f["commit"] == COMMIT for f in got.values())


def test_git_failure_calls_no_model(tmp_path):
    rig = Rig(git_error="fatal: not a git repository")
    code, _, err = rig.main(["--yes"], tmp_path)
    assert code != 0 and "not a git repository" in err and rig.models == []


def test_default_out_uses_utc_date_and_all_models_in_catalog_order():
    with tempfile.TemporaryDirectory() as root:
        root = Path(root)
        (root / "models.json").write_text((ROOT / "models.json").read_text())
        (root / "manuals").mkdir()
        for p in (ROOT / "manuals").iterdir():
            (root / "manuals" / p.name).write_text(p.read_text())
        rig = Rig()
        out = io.StringIO()
        code = script.main(["--yes"], run_model=rig.run_model, git=rig.git, now=lambda: NOW,
                           check_config=rig.check, root=root, stdout=out, stderr=io.StringIO())
        assert code == 0 and [m[0] for m in rig.models] == LABELS
        assert sorted(p.stem for p in (root / "runs" / "2026-11-10").glob("*.json")) == sorted(LABELS)


def test_model_arguments():
    with tempfile.TemporaryDirectory() as out_dir:
        rig = Rig()
        rig.main(["--yes", "--models", "nova-micro"], out_dir)
        label, task, run_id = rig.models[0]
        assert task.startswith("Installation: install-07\nRequests:\nR1: ")
        assert run_id == f"eval-nova-micro-{int(NOW.timestamp())}"
        data = files(out_dir)["nova-micro"]
        assert (data["mode"], data["model_id"], data["started_at"]) == (
            "instructive", "us.amazon.nova-micro-v1:0", "2026-11-10T14:00:00Z")


# --- Properties ---------------------------------------------------------------------------

subsets = st.lists(st.sampled_from(LABELS), min_size=1, max_size=5, unique=True)
FAST = settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


# Feature: model-evaluation, Property 1: Price note accompanies every cost output (runner estimate part)
# Feature: model-evaluation, Property 3: Cost upper bound formula
@FAST
@given(subsets)
def test_property_estimate(labels):
    with tempfile.TemporaryDirectory() as out_dir:
        rig = Rig()
        code, out, _ = rig.main(["--models", ",".join(labels)], out_dir)
        chosen = [e for e in CATALOG if e.label in labels]
        bound = sum((40 * (4_000 * e.input_usd_per_million + 400 * e.output_usd_per_million) / Decimal(1_000_000)
                     for e in chosen), Decimal(0))
        assert evaluation.cost_upper_bound(chosen) == bound
        assert f"Cost upper bound: {evaluation.format_cost(bound)}" in out and evaluation.PRICE_NOTE in out
        assert code == 0 and rig.models == []


# Feature: model-evaluation, Property 2: Unknown labels block the run
@FAST
@given(subsets, st.text(alphabet="abcxyz-0123456789", min_size=1, max_size=12).filter(lambda s: s not in LABELS))
def test_property_unknown_label(labels, bad):
    with tempfile.TemporaryDirectory() as out_dir:
        rig = Rig()
        code, _, err = rig.main(["--yes", "--models", ",".join([*labels, bad])], out_dir)
        assert code != 0 and bad in err and rig.models == []


# Feature: model-evaluation, Property 4: No model call without --yes
@FAST
@given(subsets, st.text(max_size=40))
def test_property_no_model_without_yes(labels, porcelain):
    with tempfile.TemporaryDirectory() as out_dir:
        rig = Rig(porcelain=porcelain)
        rig.main(["--models", ",".join(labels)], out_dir)
        assert rig.models == [] and not any(e[0] == "git" for e in rig.events)


porcelain_lines = st.lists(st.one_of(
    st.builds(lambda p: f"?? {p}", st.text(alphabet="abc/._", min_size=1, max_size=8)),
    st.builds(lambda code, p: f"{code} {p}", st.sampled_from([" M", "M ", "A ", " D", "R ", "MM", "UU"]),
              st.text(alphabet="abc/._", min_size=1, max_size=8))), max_size=5)


# Feature: model-evaluation, Property 5: Dirty tree detection
@FAST
@given(porcelain_lines)
def test_property_dirty_tree(lines):
    porcelain = "\n".join(lines) + ("\n" if lines else "")
    dirty = any(not line.startswith("?? ") for line in lines)
    assert evaluation.is_dirty(porcelain) == dirty
    with tempfile.TemporaryDirectory() as out_dir:
        rig = Rig(porcelain=porcelain)
        code, _, err = rig.main(["--yes", "--models", "nova-micro"], out_dir)
        if dirty:
            assert code != 0 and "commit first" in err and rig.models == []
        else:
            assert code == 0 and [m[0] for m in rig.models] == ["nova-micro"]


# Feature: model-evaluation, Property 6: Commit in every Run_File
# Feature: model-evaluation, Property 9: Failed start is recorded and the run continues
@FAST
@given(subsets.flatmap(lambda labels: st.tuples(st.just(labels), st.lists(st.sampled_from(labels), unique=True))))
def test_property_failures_and_commit(case):
    labels, failing = case
    with tempfile.TemporaryDirectory() as out_dir:
        rig = Rig(fail=failing)
        code, _, _ = rig.main(["--yes", "--models", ",".join(labels)], out_dir)
        got = files(out_dir)
        assert code == 0 and set(got) == set(labels)
        assert sorted(m[0] for m in rig.models) == sorted(labels)
        for label, data in got.items():
            assert data["commit"] == COMMIT
            assert ("error" in data and "trace" not in data) == (label in failing)


results = st.dictionaries(st.text(alphabet="abcdefgh_", min_size=1, max_size=8),
                          st.one_of(st.integers(), st.text(max_size=10), st.none()), max_size=6)


# Feature: model-evaluation, Property 7: Run_File content
@FAST
@given(results)
def test_property_run_file_content(result):
    result = {k: v for k, v in result.items() if k not in ("model_id", "label", "mode", "commit", "started_at", "run_id")}
    with tempfile.TemporaryDirectory() as out_dir:
        rig = Rig(result=result)
        rig.main(["--yes", "--models", "nova-micro"], out_dir)
        data = files(out_dir)["nova-micro"]
        assert all(data[k] == v for k, v in result.items())
        assert {"model_id", "label", "mode", "commit", "started_at"} <= set(data)


# Feature: model-evaluation, Property 8: Existing files are never overwritten
@FAST
@given(st.binary(max_size=64))
def test_property_existing_files_untouched(content):
    with tempfile.TemporaryDirectory() as out_dir:
        path = Path(out_dir) / "nova-micro.json"
        path.write_bytes(content)
        rig = Rig()
        rig.main(["--yes", "--models", "nova-micro"], out_dir)
        assert path.read_bytes() == content and rig.models == []
