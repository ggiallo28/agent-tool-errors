"""scripts/publish_gists.sh with a fake gh first on PATH. The real gh is never called."""
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tests.helpers import ROOT

FAKE_GH = """#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
if [ -n "${GH_FAIL:-}" ]; then echo "gh: HTTP 401: Bad credentials" >&2; exit 1; fi
if [ "$1 $2" = "gist create" ]; then
  echo "- Creating gist $4" >&2
  echo "https://gist.github.com/someone/$(basename "$4" .md)1234"
fi
"""


@pytest.fixture
def rig(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "publish_gists.sh", repo / "scripts")
    (repo / "gists").mkdir()
    (repo / "gists" / "a.md").write_text("# A\n")
    (repo / "gists" / "b.md").write_text("# B\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "gh.log"
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_LOG": str(log)}

    def run(**extra):
        return subprocess.run(["bash", str(repo / "scripts" / "publish_gists.sh")], capture_output=True,
                              text=True, env={**env, **extra}, cwd=tmp_path)
    return repo, log, run


def test_creates_public_gists_and_writes_the_index(rig):
    repo, log, run = rig
    done = run()
    assert done.returncode == 0, done.stderr
    assert log.read_text().splitlines() == ["gist create --public gists/a.md", "gist create --public gists/b.md"]
    assert json.loads((repo / "gists" / "index.json").read_text()) == {
        "a.md": "https://gist.github.com/someone/a1234", "b.md": "https://gist.github.com/someone/b1234"}


def test_edits_when_the_index_has_a_url(rig):
    repo, log, run = rig
    (repo / "gists" / "index.json").write_text(json.dumps({"a.md": "https://gist.github.com/someone/abc123"}))
    done = run()
    assert done.returncode == 0, done.stderr
    assert log.read_text().splitlines() == ["gist edit abc123 --filename a.md gists/a.md",
                                            "gist create --public gists/b.md"]
    assert json.loads((repo / "gists" / "index.json").read_text())["a.md"] == "https://gist.github.com/someone/abc123"


def test_gh_failure_exits_non_zero(rig):
    _, _, run = rig
    done = run(GH_FAIL="1")
    assert done.returncode != 0 and "Bad credentials" in done.stderr


def test_no_gists_is_an_error(rig):
    repo, log, run = rig
    for p in (repo / "gists").glob("*.md"):
        p.unlink()
    done = run()
    assert done.returncode != 0 and "No gists" in done.stderr and not log.exists()


def test_script_is_executable():
    assert os.access(ROOT / "scripts" / "publish_gists.sh", os.X_OK)
