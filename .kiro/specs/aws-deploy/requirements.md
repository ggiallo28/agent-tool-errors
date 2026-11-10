# Requirements Document

## Introduction

This feature deploys the opsmem database on AWS, runs the existing scripts against it, and removes everything afterwards. The code already supports Aurora through the RDS Data API (`opsmem/db.py`, one secret per role). This feature adds the infrastructure template, the environment script, the clean up script and the README steps. The region is `us-east-1`, always taken from `AWS_REGION`.

Out of scope: AgentCore Runtime, review with baits, incident replay.

Delivery constraints (not product behavior):
- No `samconfig.toml` is committed; it is listed in `.gitignore`.
- Commit and push after each step, one commit per step. Every message ends with a blank line and the trailer `Co-Authored-By: Kiro`, with no email. After each push, `git log --oneline -3` is shown.
- When the user approves `tasks.md`: one commit with the three documents, `docs(aws-deploy): requirements, design and tasks`, then `git push`.
- After each task, when its tests pass: one commit for that task only, `feat(aws-deploy): <task number> <task title in lowercase>`, then push, then stop and wait for the user.
- The agent never runs `sam deploy`, `sam delete`, `scripts/cleanup.sh` or any command that creates or deletes AWS resources. The agent stops and asks the user, who runs them.
- When a README step needs the output of a real deployment, the agent stops and asks the user to paste it. Only real output is documented.

## Glossary

- **Template**: The AWS SAM file `template.yaml` at the repository root.
- **Stack**: The CloudFormation stack created from the Template, named by `STACK` (default `agent-tool-errors`).
- **Cluster**: The Aurora PostgreSQL Serverless v2 DB cluster defined in the Template.
- **Writer_Instance**: The single `db.serverless` DB instance of the Cluster.
- **Data_API**: The RDS Data API, reached over HTTPS with IAM, requiring no VPC networking from the scripts.
- **Admin_Secret**: The Secrets Manager secret that RDS manages for the master user `opsadmin`, exposed as the output `AdminSecretArn`.
- **Role_Secrets**: The two Secrets Manager secrets defined in the Template, for the roles `agent_writer` and `approver`.
- **Env_Script**: The file `scripts/env.sh`, intended to be sourced.
- **Cleanup_Script**: The file `scripts/cleanup.sh`.
- **Readme**: The file `README.md`.
- **Part_1_Section**: The Readme section with the heading `## Part 1: the database says no`.
- **Schema_Applier**: The script `scripts/apply_schema.py`, which refuses passwords containing punctuation.
- **Test_Suite**: The pytest tests added by this feature, which use no AWS account.
- **Fake_Aws**: A stand-in `aws` executable placed first on `PATH` by a test.
- **Fake_Sam**: A stand-in `sam` executable placed first on `PATH` by a test.
- **Aurora_Smoke_Test**: The existing test `tests/test_aurora_smoke.py`.

## Requirements

### Requirement 1: Aurora cluster template

**User Story:** As a developer, I want a SAM template that creates the Aurora cluster, so that the scripts can use a real Aurora database.

#### Acceptance Criteria

1. THE Template SHALL define one Cluster with engine `aurora-postgresql`, engine version `16.15`, and database name `opsmemory`.
2. THE Template SHALL define the Cluster master user as `opsadmin` with `ManageMasterUserPassword` set to `true`.
3. THE Template SHALL set `EnableHttpEndpoint` to `true` on the Cluster.
4. THE Template SHALL set `ServerlessV2ScalingConfiguration` on the Cluster with `MinCapacity` 0, `MaxCapacity` 2, and `SecondsUntilAutoPause` 600.
5. THE Template SHALL define exactly one Writer_Instance with instance class `db.serverless`.
6. THE Template SHALL set `DeletionPolicy` to `Delete` and `UpdateReplacePolicy` to `Delete` on the Cluster and on the Writer_Instance.
7. WHEN `sam validate --lint` is run on the Template, THE Template SHALL pass validation.

### Requirement 2: Role secrets

**User Story:** As a developer, I want one generated secret per database role, so that the scripts connect with the correct role.

#### Acceptance Criteria

1. THE Template SHALL define exactly two Secrets Manager secrets, Role_Secrets, for the usernames `agent_writer` and `approver`.
2. THE Template SHALL set the username of each Role_Secret in the Template text.
3. THE Template SHALL generate the password of each Role_Secret with a length of 32 characters.
4. THE Template SHALL generate the password of each Role_Secret without punctuation characters.
5. THE Template SHALL NOT define a secret for the master user `opsadmin`, because the Admin_Secret is managed by RDS.

### Requirement 3: Stack outputs

**User Story:** As a developer, I want the stack to output the ARNs the scripts need, so that the environment can be configured from the Stack.

#### Acceptance Criteria

1. THE Template SHALL define exactly four outputs: `ClusterArn`, `AdminSecretArn`, `AgentWriterSecretArn`, and `ApproverSecretArn`.
2. THE Template SHALL set `AdminSecretArn` to the ARN of the Admin_Secret.
3. THE Template SHALL set `AgentWriterSecretArn` and `ApproverSecretArn` to the ARNs of the matching Role_Secrets.

### Requirement 4: Environment script

**User Story:** As a developer, I want to source one file to configure my shell, so that the existing scripts run against Aurora.

#### Acceptance Criteria

1. WHEN the Env_Script is sourced, THE Env_Script SHALL read the four outputs of the Stack named by the variable `STACK`.
2. WHERE `STACK` is unset, THE Env_Script SHALL use the stack name `agent-tool-errors`.
3. WHEN the Env_Script is sourced, THE Env_Script SHALL export `CLUSTER_ARN`, `ADMIN_SECRET_ARN`, `AGENT_WRITER_SECRET_ARN`, and `APPROVER_SECRET_ARN` from the outputs `ClusterArn`, `AdminSecretArn`, `AgentWriterSecretArn`, and `ApproverSecretArn`.
4. WHEN the Env_Script is sourced, THE Env_Script SHALL export `AWS_REGION`.
5. WHERE `AWS_REGION` is unset, THE Env_Script SHALL set `AWS_REGION` to `us-east-1`.
6. WHEN the Env_Script is sourced, THE Env_Script SHALL print the cluster ARN and no other value.
7. THE Env_Script SHALL print no secret value, no secret content, and no password.
8. WHILE the five variables are exported and `OPSMEM_LOCAL_PG` is unset, THE Schema_Applier, `scripts/run_writer.py`, and `scripts/run_experiment.py` SHALL work against Aurora with no code change.

### Requirement 5: Clean up script

**User Story:** As a developer, I want a clean up command, so that everything is removed after the demo.

#### Acceptance Criteria

1. WHEN the Cleanup_Script is run, THE Cleanup_Script SHALL run `sam delete --stack-name "$STACK" --no-prompts` without a confirmation prompt.
2. WHEN the `sam delete` command completes, THE Cleanup_Script SHALL print one line stating that no final snapshot is kept.
3. WHEN the `sam delete` command completes, THE Cleanup_Script SHALL print one line stating that Secrets Manager keeps deleted secrets for a recovery window.

### Requirement 6: README steps

**User Story:** As a reader of the article, I want README steps for Aurora, so that I can reproduce the demo.

#### Acceptance Criteria

1. THE Readme SHALL keep the heading `## Part 1: the database says no` unchanged.
2. THE Part_1_Section SHALL contain, in this order, the headings `### 1. Deploy the database`, `### 2. Apply the schema`, `### 3. Verify without spending`, `### 4. One writer run`, `### 5. Clean up`, and `### Cost and operations`.
3. THE section `### 1. Deploy the database` SHALL show `sam deploy --guided --stack-name agent-tool-errors` followed by `source scripts/env.sh`.
4. THE section `### 1. Deploy the database` SHALL state each template choice of Requirements 1 and 2, with one line of reason for each.
5. THE section `### 2. Apply the schema` SHALL show `uv run scripts/apply_schema.py` against Aurora, state what the command creates, and show its real output.
6. THE sections `### 3. Verify without spending` and `### 4. One writer run` SHALL keep their existing text and SHALL each gain one sentence stating that the same command works on Aurora after `source scripts/env.sh`.
7. THE section `### 5. Clean up` SHALL show `scripts/cleanup.sh` or the `sam delete` command, and state what the command deletes.
8. THE section `### Cost and operations` SHALL state that with `MinCapacity: 0` storage is the only cost between runs.
9. THE section `### Cost and operations` SHALL state that Serverless v2 is billed per ACU-hour and storage per GB-month, and SHALL link the Aurora pricing page and the Bedrock pricing page without prices copied by hand.
10. THE section `### Cost and operations` SHALL state that the first call after a pause can raise `DatabaseResumingException`, which `opsmem/db.py` retries.
11. THE Readme SHALL keep the command `sam deploy --guided --stack-name agent-tool-errors`, with no committed `samconfig.toml`.
12. THE `.gitignore` SHALL list `samconfig.toml`.

### Requirement 7: Offline tests

**User Story:** As a developer, I want tests that need no AWS account, so that I can verify the files offline.

#### Acceptance Criteria

1. THE Test_Suite SHALL parse the Template as YAML using a loader that supports the CloudFormation tags, provided by the pinned dev dependency `cfn-lint`.
2. THE Test_Suite SHALL assert every property listed in Requirements 1 and 2 on the parsed Template.
3. THE Test_Suite SHALL assert the four outputs of Requirement 3 on the parsed Template.
4. THE Test_Suite SHALL assert that each Role_Secret password configuration excludes punctuation.
5. THE Test_Suite SHALL run the Env_Script with a Fake_Aws on `PATH` and assert that the five variables of Requirement 4 are exported.
6. THE Test_Suite SHALL assert that the Env_Script output contains the cluster ARN and no secret value.
7. THE Test_Suite SHALL run the Cleanup_Script with a Fake_Sam on `PATH` and assert that `sam delete` is called with the stack name and `--no-prompts`.
8. THE Test_Suite SHALL include a test that runs `sam validate --lint` on the Template.
9. IF `sam` is absent from `PATH`, THEN THE `sam validate --lint` test SHALL be skipped.
10. THE Aurora_Smoke_Test SHALL remain unchanged.
