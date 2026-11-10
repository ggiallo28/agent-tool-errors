"""The marker guard of conftest.py (Requirement 20), run in an isolated pytester project."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SAMPLE = """
import pytest

@pytest.mark.docker_script
def test_script():
    pass

@pytest.mark.local_pg
def test_db():
    raise AssertionError("a local_pg body must not run in this check")

def test_plain():
    pass
"""


@pytest.fixture
def project(pytester, monkeypatch):
    monkeypatch.delenv("OPSMEM_LOCAL_PG", raising=False)
    pytester.makeconftest((ROOT / "conftest.py").read_text().replace('pytest_plugins = ["pytester"]', ""))
    pytester.makeini("[pytest]\naddopts = --strict-markers\n")
    pytester.makepyfile(test_sample=SAMPLE)
    return pytester


def test_default_run_skips_docker_script(project):
    result = project.runpytest()
    result.assert_outcomes(passed=1, skipped=2)
    result.stdout.no_fnmatch_line("*test_script PASSED*")


def test_docker_script_runs_when_selected(project):
    result = project.runpytest("-m", "docker_script", "-v")
    result.assert_outcomes(passed=1, deselected=2)
    result.stdout.fnmatch_lines(["*test_script PASSED*"])


def test_both_markers_abort_before_any_test(project, monkeypatch):
    monkeypatch.setenv("OPSMEM_LOCAL_PG", "localhost:55432")
    result = project.runpytest("-m", "docker_script or local_pg")
    assert result.ret != 0
    result.stderr.fnmatch_lines(["*docker_script and local_pg*opsmem-pg*"])
    result.stdout.no_fnmatch_line("*AssertionError*")


def test_local_pg_skipped_without_variable(project):
    result = project.runpytest("-m", "local_pg")
    result.assert_outcomes(skipped=1, deselected=2)
