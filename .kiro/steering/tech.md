# Tech

## Language and tooling

- Python 3.12+, managed with `uv`.
- Dependencies: `boto3`, `strands-agents`, `bedrock-agentcore` (>=1.18.1,<2), `pyyaml`.
- Dependency groups: `dev` (pytest), `local` (`psycopg[binary]`).

## Models

- Only through Amazon Bedrock (Converse API, via Strands `BedrockModel`).
- Region from `AWS_REGION`.
- Region: us-east-1. Code still reads it from AWS_REGION and never hardcodes it.
- `temperature=0`.

## Database

- PostgreSQL 16.
- Two backends with the same interface:
  - Aurora PostgreSQL Serverless v2 through the RDS Data API, with one Secrets Manager secret per role.
  - Local PostgreSQL in Docker (`OPSMEM_LOCAL_PG=host:port`). Only the model calls go to AWS.

## Runtime and infrastructure

- Runtime: Amazon Bedrock AgentCore Runtime, project layout of the AgentCore CLI 1.x.
- Infrastructure: one CloudFormation template for Aurora, IAM policy as a JSON template.

## Rules

- Configuration errors stop the process at startup, before any model call.
- A missing value must never reach the model as tool output.
- Tests use pytest. Unit tests use no network and no AWS.

## Writing rules

Docs and comments in plain English. README in first person. No marketing words.
