"""scripts/summarize_runs.py on the synthetic fixtures. Offline."""
import io

from tests.helpers import ROOT, load_script

script = load_script("summarize_runs")
FIXTURES = ROOT / "tests" / "fixtures" / "runs"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = script.main(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_table_on_fixtures():
    code, out, _ = run([str(FIXTURES)])
    assert code == 0
    assert out.splitlines()[:5] == [
        "| Model | Saved | Tool calls | Rejections | Tokens in / out | Cost | Escalated |",
        "|---|---|---|---|---|---|---|",
        "| Amazon Nova Micro | 6 of 6 | 8 | 2 | 51,844 / 2,454 | $0.0022 | no |",
        "| Ministral 3 3B | 1 of 6 | 4 | 2 | 15,055 / 2,329 | $0.0017 | yes |",
        "| Claude Haiku 4.5 | 0 of 6 | 0 | 0 | 0 / 0 | $0.0000 | AccessDeniedException: You don't have access "
        "to the model with the specified model ID. |",
    ]
    assert "US cross-region inference profiles can be billed slightly higher than the list price." in out
    assert "### " not in out


def test_rows_option():
    code, out, _ = run([str(FIXTURES), "--rows"])
    assert code == 0
    assert "### Amazon Nova Micro" in out and "### Ministral 3 3B" not in out
    assert "| R5 | classes | cls_create_fail | count | count | 60 |" in out
    assert out.rstrip().endswith("Only one model saved all 6 configurations, so there is nothing to compare.")


def test_empty_directory_is_an_error(tmp_path):
    code, out, err = run([str(tmp_path)])
    assert code != 0 and out == "" and "No run files" in err


def test_same_input_twice_same_output():
    assert run([str(FIXTURES), "--rows"]) == run([str(FIXTURES), "--rows"])
