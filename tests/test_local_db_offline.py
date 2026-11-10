"""scripts/local_db.sh with a stub docker on PATH. No Docker, no network."""
import os
import subprocess

import pytest

from tests.helpers import ROOT

SCRIPT = str(ROOT / "scripts" / "local_db.sh")

STUB = """#!/bin/sh
echo "$@" >> "$STUB_LOG"
case "$1" in
  rm) [ -n "$STUB_NO_CONTAINER" ] && { echo "Error: No such container: opsmem-pg" >&2; exit 1; }; exit 0 ;;
  run) [ -n "$STUB_RUN_FAIL" ] && { echo "Bind for 0.0.0.0:55432 failed: port is already allocated" >&2; exit 125; }
       echo abc123; exit 0 ;;
  logs) exit 0 ;;
  *) exit 1 ;;
esac
"""


@pytest.fixture
def sh(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(STUB)
    (bin_dir / "docker").chmod(0o755)
    log = tmp_path / "docker.log"

    def run(*args, **env):
        full = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "STUB_LOG": str(log), **env}
        proc = subprocess.run([SCRIPT, *args], capture_output=True, text=True, env=full, timeout=30)
        calls = log.read_text().splitlines() if log.exists() else []
        return proc, calls

    return run


@pytest.mark.parametrize("args", [(), ("restart",), ("up", "extra"), ("",)])
def test_bad_usage_prints_usage_and_touches_nothing(sh, args):
    proc, calls = sh(*args)
    assert proc.returncode != 0
    assert "up" in proc.stderr and "down" in proc.stderr
    assert proc.stdout == "" and calls == []


def test_start_failure_shows_the_cause_and_no_export_line(sh):
    proc, calls = sh("up", STUB_RUN_FAIL="1")
    assert proc.returncode != 0
    assert "port is already allocated" in proc.stderr
    assert proc.stdout == ""


def test_readiness_timeout_keeps_the_container(sh):
    proc, calls = sh("up", OPSMEM_READY_TIMEOUT="2")
    assert proc.returncode != 0
    assert "readiness timeout" in proc.stderr
    assert "export" not in proc.stdout and proc.stdout == ""
    last_run = max(i for i, c in enumerate(calls) if c.startswith("run"))
    assert not any(c.startswith("rm") for c in calls[last_run + 1:])


def test_down_without_a_container_still_succeeds(sh):
    proc, calls = sh("down", STUB_NO_CONTAINER="1")
    assert proc.returncode == 0
    assert calls == ["rm -f opsmem-pg"]
