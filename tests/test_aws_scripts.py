"""scripts/env.sh and scripts/cleanup.sh against fake aws and sam on PATH. No AWS call is made."""
import os
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.helpers import ROOT

KEYS = ["ClusterArn", "AdminSecretArn", "AgentWriterSecretArn", "ApproverSecretArn"]
VARS = ["CLUSTER_ARN", "ADMIN_SECRET_ARN", "AGENT_WRITER_SECRET_ARN", "APPROVER_SECRET_ARN"]

FAKE_AWS = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
if [ "$1" = "secretsmanager" ]; then echo "secretsmanager must never be called" >&2; exit 99; fi
if [ -n "${FAKE_FAIL:-}" ]; then echo "An error occurred (ValidationError): Stack does not exist" >&2; exit 254; fi
query=""; prev=""
for arg in "$@"; do [ "$prev" = "--query" ] && query="$arg"; prev="$arg"; done
key=$(printf '%s' "$query" | sed -n "s/.*OutputKey=='\([A-Za-z]*\)'.*/\1/p")
var="FAKE_$key"
printf '%s\n' "${!var-None}"
"""
FAKE_SAM = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
[ -z "${FAKE_FAIL:-}" ] || { echo "Error: delete failed" >&2; exit 1; }
"""


def make_bin(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, body in (("aws", FAKE_AWS), ("sam", FAKE_SAM)):
        path = directory / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return directory


BIN = make_bin(Path(tempfile.mkdtemp(prefix="fake-aws-")))


def base_env(log: Path, **extra):
    env = {k: v for k, v in os.environ.items() if k not in ("STACK", "AWS_REGION", *VARS, "OPSMEM_LOCAL_PG")}
    env.update(PATH=f"{BIN}{os.pathsep}{os.environ['PATH']}", FAKE_LOG=str(log))
    env.update(extra)
    return env


def source_env(env):
    """Source scripts/env.sh in bash; return (code, stdout, stderr, exported variables)."""
    script = 'source scripts/env.sh > "$OUT_FILE"; code=$?; env -0 > "$ENV_FILE"; exit $code'
    with tempfile.TemporaryDirectory() as tmp:
        out, envf = Path(tmp) / "out", Path(tmp) / "env"
        done = subprocess.run(["bash", "-c", script], cwd=ROOT, capture_output=True, text=True,
                              env={**env, "OUT_FILE": str(out), "ENV_FILE": str(envf)})
        exported = dict(item.split("=", 1) for item in envf.read_text().split("\0") if "=" in item) \
            if envf.exists() else {}
        return done.returncode, out.read_text() if out.exists() else "", done.stderr, exported


def outputs(**values):
    return {f"FAKE_{k}": values.get(k, f"arn:aws:fake:{k}") for k in KEYS}


def test_exports_the_five_variables(tmp_path):
    code, stdout, _, exported = source_env(base_env(tmp_path / "log", **outputs()))
    assert code == 0
    for key, var in zip(KEYS, VARS):
        assert exported[var] == f"arn:aws:fake:{key}"
    assert exported["AWS_REGION"] == "us-east-1"
    assert stdout == "arn:aws:fake:ClusterArn\n"


def test_default_stack_name(tmp_path):
    source_env(base_env(tmp_path / "log", **outputs()))
    calls = (tmp_path / "log").read_text().splitlines()
    assert len(calls) == 4 and all("--stack-name agent-tool-errors" in c for c in calls)
    assert all(c.startswith("cloudformation describe-stacks") for c in calls)


def test_region_is_kept_when_set(tmp_path):
    _, _, _, exported = source_env(base_env(tmp_path / "log", AWS_REGION="eu-west-1", **outputs()))
    assert exported["AWS_REGION"] == "eu-west-1"


def test_missing_output_returns_1_and_names_the_key(tmp_path):
    env = base_env(tmp_path / "log", **outputs())
    del env["FAKE_ApproverSecretArn"]
    code, stdout, stderr, exported = source_env(env)
    assert code == 1 and stdout == "" and "ApproverSecretArn" in stderr
    assert "APPROVER_SECRET_ARN" not in exported


def test_aws_failure_returns_1_with_empty_stdout(tmp_path):
    code, stdout, stderr, _ = source_env(base_env(tmp_path / "log", FAKE_FAIL="1", **outputs()))
    assert code == 1 and stdout == "" and "Stack does not exist" in stderr


def test_never_reads_a_secret(tmp_path):
    source_env(base_env(tmp_path / "log", **outputs()))
    assert "secretsmanager" not in (tmp_path / "log").read_text()


def run_cleanup(env):
    return subprocess.run(["bash", "scripts/cleanup.sh"], cwd=ROOT, capture_output=True, text=True, env=env)


def test_cleanup_deletes_the_stack_without_prompts(tmp_path):
    done = run_cleanup(base_env(tmp_path / "log"))
    assert done.returncode == 0
    assert (tmp_path / "log").read_text().splitlines() == ["delete --stack-name agent-tool-errors --no-prompts"]
    assert done.stdout.splitlines() == [
        "No final snapshot is kept: the database content is gone.",
        "Secrets Manager keeps deleted secrets for a recovery window before removing them."]


def test_cleanup_failure_prints_no_notes(tmp_path):
    done = run_cleanup(base_env(tmp_path / "log", FAKE_FAIL="1"))
    assert done.returncode != 0 and done.stdout == ""


def test_cleanup_is_executable():
    assert os.access(ROOT / "scripts" / "cleanup.sh", os.X_OK)


# --- Properties -----------------------------------------------------------------------------

stacks = st.from_regex(r"[A-Za-z][A-Za-z0-9-]{0,127}", fullmatch=True)
arns = st.from_regex(r"arn:aws:[a-z0-9:/-]{1,40}", fullmatch=True)
regions = st.from_regex(r"[a-z]{2}-[a-z]+-[0-9]", fullmatch=True)
PROPS = settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


# Feature: aws-deploy, Property 1: Stack name is passed through
@PROPS
@given(stacks)
def test_property_stack_name(stack):
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "log"
        source_env(base_env(log, STACK=stack, **outputs()))
        calls = log.read_text().splitlines()
        assert len(calls) == 4 and all(f"--stack-name {stack} " in c for c in calls)


# Feature: aws-deploy, Property 2: Outputs map to exported variables
# Feature: aws-deploy, Property 3: Only the cluster ARN is printed
@PROPS
@given(st.lists(arns, min_size=4, max_size=4, unique=True).filter(
    lambda vs: not any(a != b and a in b for a in vs for b in vs)))  # no ARN inside another
def test_property_outputs_and_stdout(values):
    with tempfile.TemporaryDirectory() as tmp:
        code, stdout, _, exported = source_env(base_env(Path(tmp) / "log", **outputs(**dict(zip(KEYS, values)))))
        assert code == 0
        assert [exported[v] for v in VARS] == values
        assert stdout == values[0] + "\n"
        assert all(other not in stdout for other in values[1:])


# Feature: aws-deploy, Property 4: Region is exported and preserved
@PROPS
@given(st.one_of(st.none(), regions))
def test_property_region(region):
    extra = outputs() if region is None else {**outputs(), "AWS_REGION": region}
    with tempfile.TemporaryDirectory() as tmp:
        _, _, _, exported = source_env(base_env(Path(tmp) / "log", **extra))
        assert exported["AWS_REGION"] == (region or "us-east-1")


# Feature: aws-deploy, Property 5: Cleanup deletes the named stack without prompting
@PROPS
@given(stacks)
def test_property_cleanup(stack):
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "log"
        done = run_cleanup(base_env(log, STACK=stack))
        assert log.read_text().splitlines() == [f"delete --stack-name {stack} --no-prompts"]
        assert done.stdout.splitlines()[0].startswith("No final snapshot")
