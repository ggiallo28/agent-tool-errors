# Structure

- `opsmem/`: the package.
  - `db.py`: connections per role.
  - `manual.py`: deterministic parsers of the manual and the OpenAPI schema.
  - `errors.py`: rejection to instruction.
  - `writer.py`: the writer agent and its tools.
  - `diagnosis.py`
- `sql/schema.sql`: the whole schema, applied by `scripts/apply_schema.py`.
- `manuals/`: the installation manual and its OpenAPI schema. Input data, never edited by code.
- `scripts/`: one script per action (local database, schema, single run, experiment, review, cleanup).
- `agentcore/`, `agentcore_app.py`: the AgentCore Runtime entry point and project.
- `iam/`, `template.yaml`: AWS resources.
- `tests/`, `reference/`, `README.md`.

## Public names to keep

Other tools import these. Do not rename them.

- `opsmem.db.connect`
- `opsmem.manual.agent_input`
- `opsmem.writer.RunContext`
- `opsmem.writer.make_tools`
- `opsmem.writer.run_writer`
- `scripts/apply_schema.py`
- Environment variable `OPSMEM_LOCAL_PG`
