# Implementation Plan: aws-deploy

## Overview

The plan adds the SAM template, the two shell scripts, the README steps and their offline tests, in the order: dev dependency, template, env script, cleanup script, README. Python and bash are the implementation languages (the project is Python 3.12 with pytest and hypothesis). File names follow the existing layout: shell scripts in `scripts/` next to `local_db.sh`, and flat `tests/test_*.py` files that import `ROOT` from `tests/helpers.py`.

Delivery rules that apply to every task:

- One task number = one commit, message `feat(aws-deploy): <task number> <task title in lowercase>`, then `git push`, then `git log --oneline -3`, then stop and wait for the user. A task is committed only when its tests pass.
- The agent never runs `sam deploy`, `sam delete`, `scripts/cleanup.sh` or any command that creates or deletes AWS resources. Tests use Fake_Aws and Fake_Sam stubs and never touch AWS.
- Every commit message ends with a blank line and the trailer `Co-Authored-By: Kiro`, with no email.
- Optional tasks (`*`) are not implemented unless the user asks. They are separate commits when done.

## Tasks

- [ ] 1. Add pinned cfn-lint dev dependency and check .gitignore
  - [ ] 1.1 Add `cfn-lint==<exact latest version>` to the `dev` group in `pyproject.toml` and update `uv.lock` with `uv lock`
    - Resolve the latest release first (for example with `uv pip index versions cfn-lint` or the PyPI page) and pin that exact version
    - `.gitignore` already lists `samconfig.toml` in the working tree: confirm the line exists exactly once, add it only if missing, and confirm no `samconfig.toml` is tracked by git
    - Check that the full existing test suite still collects and passes offline (`uv run pytest`, default markers as the project already does)
    - _Requirements: 6.12, 7.1, 7.10_

- [ ] 2. Add the SAM template with its tests
  - [ ] 2.1 Create `template.yaml` and `tests/test_aws_template.py` with the template assertions
    - Write `template.yaml` as in the design: one Cluster, one WriterInstance, `AgentWriterSecret`, `ApproverSecret`, four outputs
    - In the test file, load the template with the CloudFormation-tag aware loader from the pinned `cfn-lint` (confirm the entry point on the pinned version; unwrap the tuple if it returns one)
    - Assert the Cluster properties, the single `db.serverless` instance, `DeletionPolicy` and `UpdateReplacePolicy` `Delete` on both, exactly two secrets with usernames `agent_writer` and `approver`, `PasswordLength` 32, `ExcludePunctuation` true, no `opsadmin` secret, and exactly the four output keys referring to the matching resources
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 7.1, 7.2, 7.3, 7.4_

  - [ ] 2.2 Add the `sam validate --lint` test to `tests/test_aws_template.py`
    - Run `sam validate --lint -t template.yaml` with `subprocess.run` and assert return code 0, with `skipif(shutil.which("sam") is None)`
    - `sam validate` only reads the template and makes no resource changes; if the sam run needs credentials, report it to the user and do not work around it
    - If lint rejects engine version `16.15` or `MinCapacity: 0`, stop and report to the user instead of changing the values
    - _Requirements: 1.7, 7.8, 7.9_

- [ ] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Add the environment script with its tests
  - [ ] 4.1 Create `scripts/env.sh` and `tests/test_aws_scripts.py` with example tests
    - Write `scripts/env.sh` as in the design: `STACK` default `agent-tool-errors`, `AWS_REGION` default `us-east-1` exported, `_opsmem_output` helper, four exports, only the cluster ARN printed, no `exit` and no `set -e`
    - Treat an empty or `None` output value as a failure: message naming the output key on stderr, `return 1`, nothing on stdout
    - In the test file, build Fake_Aws in `tmp_path` (logs arguments, prints `FAKE_<Key>`, fails on any `secretsmanager` call) and prepend it to `PATH`
    - Example tests: five variables exported (read back with `env -0`), stdout equals the cluster ARN plus newline, default stack name, default region, missing output returns 1 with the key name on stderr, `aws` failure returns 1 with empty stdout
    - Make the script file executable-agnostic (it is sourced); `tests/test_aurora_smoke.py` stays unchanged
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 7.5, 7.6, 7.10_

  - [ ]* 4.2 Write property tests for the environment script
    - Add to `tests/test_aws_scripts.py` using `hypothesis` with `@settings(max_examples=100)`, stubs created once at module level, per-example values passed through environment variables
    - **Property 1: Stack name is passed through**
    - **Property 2: Outputs map to exported variables**
    - **Property 3: Only the cluster ARN is printed**
    - **Property 4: Region is exported and preserved**
    - Each test carries the tag comment `# Feature: aws-deploy, Property N: <text>`
    - **Validates: Requirements 4.1, 4.3, 4.4, 4.5, 4.6, 4.7**

- [ ] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Add the cleanup script with its tests
  - [ ] 6.1 Create `scripts/cleanup.sh` and add Cleanup_Script example tests to `tests/test_aws_scripts.py`
    - Write `scripts/cleanup.sh` as in the design (`set -euo pipefail`, `STACK` default, `sam delete --stack-name "$STACK" --no-prompts`, then the two note lines) and make it executable (`chmod +x`), like `scripts/local_db.sh`
    - Add a Fake_Sam stub (logs argv, exits 0) and a failing variant
    - Example tests: `sam` called once with `delete --stack-name agent-tool-errors --no-prompts`, both note lines printed after the call, no notes and non-zero exit when `sam` fails
    - Tests run the script only against Fake_Sam. The agent never runs `scripts/cleanup.sh` for real
    - _Requirements: 5.1, 5.2, 5.3, 7.7_

  - [ ]* 6.2 Write property test for the cleanup script
    - **Property 5: Cleanup deletes the named stack without prompting**
    - Generator for stack names: `[A-Za-z][A-Za-z0-9-]{0,127}`, `max_examples=100`, tag comment `# Feature: aws-deploy, Property 5: ...`
    - **Validates: Requirements 5.1, 5.2, 5.3**

- [ ] 7. README steps for Aurora
  - [ ] 7.1 Write README Part 1 steps 1, 3, 4, 5 and the Cost and operations section, with `tests/test_aws_readme.py`
    - Keep `## Part 1: the database says no` unchanged
    - Add `### 1. Deploy the database` before the existing step 3: `sam deploy --guided --stack-name agent-tool-errors`, then `source scripts/env.sh`, and one bullet per template choice of Requirements 1 and 2 with a one line reason
    - Add the one sentence about Aurora after `source scripts/env.sh` to the existing steps 3 and 4 without changing their other text
    - Add `### 5. Clean up` (`scripts/cleanup.sh` or `sam delete`, and what it deletes) and `### Cost and operations` (storage only cost with `MinCapacity: 0`, ACU-hour and GB-month billing, links to the Aurora and Bedrock pricing pages with no copied prices, `DatabaseResumingException` retried by `opsmem/db.py`)
    - Do not add step 2 here: it needs real output
    - Tests read `README.md`: heading order of the headings present, required strings and commands, pricing links present and no currency amounts in the cost section, `.gitignore` contains `samconfig.toml`, no tracked `samconfig.toml`
    - Do not break `tests/test_evidence_readme.py`
    - _Requirements: 6.1, 6.3, 6.4, 6.6, 6.7, 6.8, 6.9, 6.10, 6.11, 6.12_

  - [ ] 7.2 STOP: ask the user to deploy and paste the real output of step 2
    - The agent does not run `sam deploy` or `scripts/apply_schema.py` against AWS. Ask the user to run `sam deploy --guided --stack-name agent-tool-errors`, `source scripts/env.sh`, and `uv run scripts/apply_schema.py`, then paste the real output of the last command
    - Make no file change and no commit in this task. Wait for the pasted output before starting 7.3
    - _Requirements: 6.5_

  - [ ] 7.3 Write README step 2 with the pasted real output
    - Add `### 2. Apply the schema` between step 1 and step 3: `uv run scripts/apply_schema.py` against Aurora, what the command creates, and the output exactly as the user pasted it
    - Extend `tests/test_aws_readme.py` to assert the full heading order of Requirement 6.2 and that the step 2 command and a non-empty output block are present
    - _Requirements: 6.2, 6.5_

- [ ] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Commit unit: each numbered task with sub-tasks is committed per sub-task number (for example `feat(aws-deploy): 2.1 create template.yaml and ...`); checkpoint tasks make no commit
- Requirement 4.8 and the real output of README step 2 need a real deployment run by the user. The existing `tests/test_aurora_smoke.py` stays unchanged and is not run by the agent
- Property tests validate universal properties of the scripts against Fake_Aws and Fake_Sam. Example tests cover the static files

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["4.2"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["6.2"] },
    { "id": 7, "tasks": ["7.1"] },
    { "id": 8, "tasks": ["7.2"] },
    { "id": 9, "tasks": ["7.3"] }
  ]
}
```
