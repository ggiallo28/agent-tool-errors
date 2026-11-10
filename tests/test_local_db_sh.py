"""scripts/local_db.sh against real Docker. Run alone: uv run pytest -m docker_script

These tests remove and recreate the container opsmem-pg, so they must never share a session with
local_pg tests. After this session run `eval "$(scripts/local_db.sh up)"` and the schema applier
again before the next local_pg session.
"""
import subprocess

import pytest

from tests.helpers import ROOT

pytestmark = pytest.mark.docker_script
SCRIPT = str(ROOT / "scripts" / "local_db.sh")
EXPORT = "export OPSMEM_LOCAL_PG=localhost:55432\n"


def sh(*args):
    return subprocess.run([SCRIPT, *args], capture_output=True, text=True, timeout=120)


def container_id():
    out = subprocess.run(["docker", "ps", "-aq", "--filter", "name=^opsmem-pg$"], capture_output=True, text=True)
    return out.stdout.strip()


@pytest.fixture(autouse=True)
def clean():
    sh("down")
    yield
    sh("down")


def test_up_prints_only_the_export_line():
    proc = sh("up")
    assert proc.returncode == 0
    assert proc.stdout == EXPORT


def test_repeated_up_replaces_the_container():
    sh("up")
    first = container_id()
    proc = sh("up")
    assert proc.returncode == 0 and proc.stdout == EXPORT
    assert container_id() and container_id() != first


def test_down_removes_it_and_down_twice_succeeds():
    sh("up")
    assert container_id()
    assert sh("down").returncode == 0 and container_id() == ""
    assert sh("down").returncode == 0


def test_busy_port_fails_with_empty_stdout():
    # another container publishes the port, which is how it is busy in practice
    subprocess.run(["docker", "rm", "-f", "opsmem-busy"], capture_output=True)
    started = subprocess.run(["docker", "run", "-d", "--name", "opsmem-busy", "-e", "POSTGRES_PASSWORD=x",
                              "-p", "55432:5432", "postgres:16"], capture_output=True, text=True)
    assert started.returncode == 0, started.stderr
    try:
        proc = sh("up")
    finally:
        subprocess.run(["docker", "rm", "-f", "opsmem-busy"], capture_output=True)
    assert proc.returncode != 0
    assert proc.stdout == "" and proc.stderr
