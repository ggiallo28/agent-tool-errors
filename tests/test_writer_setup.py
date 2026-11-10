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


# --- build_agent -------------------------------------------------------------------------------

import pytest  # noqa: E402

from opsmem import writer  # noqa: E402


class Recorder:
    def __init__(self, label, log):
        self.label, self.log = label, log

    def __call__(self, *positional, **keywords):
        self.log.append((self.label, positional, keywords))
        return f"<{self.label}>"


def test_build_agent_uses_exactly_the_contract_arguments(monkeypatch):
    log = []
    monkeypatch.setattr(writer, "BedrockModel", Recorder("model", log))
    monkeypatch.setattr(writer, "Agent", Recorder("agent", log))
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    ctx = writer.RunContext("r", "install-07", "some-model", "raw", object())
    writer.build_agent(ctx)
    (_, pos_m, kw_m), (_, pos_a, kw_a) = log
    assert pos_m == () and kw_m == {"model_id": "some-model", "region_name": "eu-west-1", "temperature": 0}
    assert pos_a == () and set(kw_a) == {"model", "tools", "system_prompt", "callback_handler"}
    assert kw_a["model"] == "<model>"
    assert kw_a["system_prompt"] == writer.SYSTEM_PROMPT
    assert kw_a["callback_handler"] is None
    assert [t.tool_name for t in kw_a["tools"]] == ["propose_config", "flag_for_review"]


def test_region_follows_the_environment(monkeypatch):
    log = []
    monkeypatch.setattr(writer, "BedrockModel", Recorder("model", log))
    monkeypatch.setattr(writer, "Agent", Recorder("agent", log))
    ctx = writer.RunContext("r", "install-07", "m", "raw", object())
    for region in ("ap-south-1", "us-west-2"):
        monkeypatch.setenv("AWS_REGION", region)
        writer.build_agent(ctx)
        assert log[-2][2]["region_name"] == region


def test_missing_region_raises_key_error(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setattr(writer, "BedrockModel", Recorder("model", []))
    monkeypatch.setattr(writer, "Agent", Recorder("agent", []))
    with pytest.raises(KeyError):
        writer.build_agent(writer.RunContext("r", "install-07", "m", "raw", object()))
