"""README smoke tests for the Aurora section of Part 1 (Requirement 6, adapted to the local five-step path)."""
import re
import subprocess

from tests.helpers import ROOT

README = (ROOT / "README.md").read_text()
PART1 = README.split("\n## Part 1: the database says no\n", 1)[1].split("\n## ", 1)[0]


def test_part1_heading_unchanged():
    assert "\n## Part 1: the database says no\n" in README


def test_local_steps_then_aurora_then_cost():
    headings = re.findall(r"^### (.+)$", PART1, flags=re.M)
    assert headings == ["1. Start the local database", "2. Apply the schema", "3. Verify without spending",
                        "4. One writer run", "5. Clean up", "On Aurora", "Cost and operations"]


def test_deploy_then_env():
    aurora = PART1.split("### On Aurora", 1)[1]
    assert aurora.index("sam deploy --guided --stack-name agent-tool-errors") < aurora.index("source scripts/env.sh")


def test_every_template_choice_is_explained():
    aurora = PART1.split("### On Aurora", 1)[1].split("### Cost and operations", 1)[0]
    for needle in ("16.15", "EnableHttpEndpoint", "MinCapacity: 0", "SecondsUntilAutoPause: 600", "db.serverless",
                   "DeletionPolicy", "UpdateReplacePolicy", "ManageMasterUserPassword", "32 characters",
                   "no punctuation"):
        assert needle in aurora, needle


def test_steps_3_and_4_mention_aurora():
    for step in ("### 3. Verify without spending", "### 4. One writer run"):
        body = PART1.split(step, 1)[1].split("\n### ", 1)[0]
        assert "after `source scripts/env.sh`" in body, step


def test_clean_up_on_aurora():
    aurora = PART1.split("### On Aurora", 1)[1].split("### Cost and operations", 1)[0]
    assert "scripts/cleanup.sh" in aurora and "sam delete --stack-name agent-tool-errors --no-prompts" in aurora
    assert "deletes the cluster, the writer instance and the two role secrets" in aurora


def test_cost_section_links_prices_and_copies_none():
    cost = PART1.split("### Cost and operations", 1)[1]
    assert "https://aws.amazon.com/rds/aurora/pricing/" in cost and "https://aws.amazon.com/bedrock/pricing/" in cost
    assert "ACU-hour" in cost and "GB-month" in cost and "DatabaseResumingException" in cost
    assert not re.search(r"\$\s?\d", cost)


def test_samconfig_ignored_and_not_tracked():
    assert "samconfig.toml" in (ROOT / ".gitignore").read_text().splitlines()
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    assert not any(p.endswith("samconfig.toml") for p in tracked)
