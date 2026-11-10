"""Setup checks for the writer agent: pinned dependencies."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_pins_dependencies():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    deps = data["project"]["dependencies"]
    for pin in ("boto3==1.43.127", "pyyaml==6.0.3", "strands-agents==1.64.0"):
        assert pin in deps


def test_lock_records_strands_agents_version():
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    versions = [p["version"] for p in lock["package"] if p["name"] == "strands-agents"]
    assert versions == ["1.64.0"]
