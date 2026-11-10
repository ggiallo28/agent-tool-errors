"""scripts/run_writer.py with run_writer and connect replaced (no model, no database)."""
import json
import re

import pytest

from tests.helpers import load_script

script = load_script("run_writer")

TRACE = [{"ts": "2025-01-31T09:15:42.123+00:00", "call": {"request_id": "R1"}, "result": "ok", "db_message": None},
         {"ts": "2025-01-31T09:15:43.001+00:00", "call": {"request_id": "R2"}, "result": "no", "db_message": "bad"}]
RESULT = {"tool_calls": 2, "rejections": {}, "follow_ups": 1, "escalated": None, "flagged": [], "trace": TRACE,
          "input_tokens": 11, "output_tokens": 7, "final_text": "done"}


@pytest.fixture
def rig(monkeypatch):
    order, seen = [], {}
    monkeypatch.setattr(script.db, "check_config", lambda required: order.append(("check", list(required))))

    def connect(role):
        order.append(("connect", role))
        return f"db-{role}"

    def fake_run(ctx, task):
        seen["ctx"], seen["task"] = ctx, task
        return RESULT

    monkeypatch.setattr(script.db, "connect", connect)
    monkeypatch.setattr(script, "run_writer", fake_run)
    return order, seen


def test_check_config_runs_before_connect(rig, tmp_path):
    order, _ = rig
    script.main(["--model", "m"], results_dir=tmp_path)
    assert order == [("check", ["CLUSTER_ARN", "AGENT_WRITER_SECRET_ARN", "AWS_REGION"]), ("connect", "agent_writer")]


def test_invalid_mode_stops_before_connect(rig, tmp_path):
    order, _ = rig
    with pytest.raises(SystemExit) as stop:
        script.main(["--model", "m", "--mode", "other"], results_dir=tmp_path)
    assert stop.value.code != 0 and order == []


def test_model_is_required(rig, tmp_path):
    with pytest.raises(SystemExit):
        script.main([], results_dir=tmp_path)


def test_default_mode_and_context(rig, tmp_path):
    _, seen = rig
    script.main(["--model", "m1"], results_dir=tmp_path)
    ctx = seen["ctx"]
    assert (ctx.mode, ctx.model_id, ctx.installation_id, ctx.db) == ("instructive", "m1", "install-07", "db-agent_writer")
    assert re.fullmatch(r"single-instructive-\d+", ctx.run_id)
    assert seen["task"].startswith("Installation: install-07\nRequests:\nR1: ")


def test_raw_mode_run_id(rig, tmp_path):
    _, seen = rig
    script.main(["--model", "m", "--mode", "raw"], results_dir=tmp_path)
    assert re.fullmatch(r"single-raw-\d+", seen["ctx"].run_id)


def test_prints_trace_lines_then_summary_and_saves_result(rig, tmp_path, capsys):
    _, seen = rig
    assert script.main(["--model", "m"], results_dir=tmp_path) == 0
    lines = capsys.readouterr().out.splitlines()
    run_id = seen["ctx"].run_id
    assert [json.loads(l) for l in lines[:2]] == TRACE
    assert lines[2] == f"run={run_id} calls=2 follow_ups=1 escalated=None input_tokens=11 output_tokens=7"
    assert len(lines) == 3
    assert json.loads((tmp_path / f"{run_id}.json").read_text()) == RESULT
