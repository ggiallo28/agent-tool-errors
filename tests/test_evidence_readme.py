"""README smoke test: the Evidence section."""
from tests.helpers import ROOT

README = (ROOT / "README.md").read_text()


def test_evidence_section():
    section = README.split("\n## Evidence\n", 1)[1]
    assert "Agent learns a schema from database rejections" in section
    assert "Bedrock models, one database" in section
    assert "Models that did not save all six configurations" in section
    assert "scripts/summarize_runs.py" in section and "scripts/make_gists.py" in section


def test_part_1_anchor_unchanged():
    assert "\n## Part 1: the database says no\n" in README
