# agent-tool-errors

This repository shows an agent that writes configuration rows into a database. The rules for those rows live in PostgreSQL, not in the prompt, and every rejection names the rule that failed so the agent knows what to change.

What exists so far is the database layer: the schema, the connection code for Aurora and for local Docker, and the parsers that load the catalog from the manual in `manuals/`.

## Prerequisites

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- Docker

AWS is needed only for Bedrock and for Aurora. Neither is used in the steps below. When you do use Bedrock, model access must be enabled in us-east-1, the region this project uses.

Install the dependencies once:

```
uv sync --group dev --group local
```

## Run it locally, paying only for the model

This step only starts the database and applies the schema. No model is called at this point, so it costs nothing.

Start PostgreSQL 16 in Docker. The script prints one line, and `eval` puts it in your shell:

```
$ eval "$(scripts/local_db.sh up)"
$ echo $OPSMEM_LOCAL_PG
localhost:55432
```

Without `eval`, the script prints only this line and nothing else:

```
$ scripts/local_db.sh up
export OPSMEM_LOCAL_PG=localhost:55432
```

The applier also wants `AWS_REGION` to be set, even in local mode, because the later steps call Bedrock. Without it the applier stops before it touches the database:

```
$ AWS_REGION= uv run scripts/apply_schema.py
Configuration error, agent not started. Missing: AWS_REGION
```

Set it to `us-east-1` and apply the schema. This creates the tables, the rules, the two roles and their passwords, and loads the catalog from `manuals/`:

```
$ export AWS_REGION=us-east-1
$ uv run scripts/apply_schema.py
installations: 1
services: 5
fields: 9
requests: 6
```

The schema is written for an empty database, so a second run is refused and changes nothing. The message tells you how to start again:

```
$ uv run scripts/apply_schema.py
Error: the database is not empty, the schema already exists. Nothing was applied. To start again, recreate the database with scripts/local_db.sh up.
```

`scripts/local_db.sh down` removes the container.

## What the database enforces

All rules are in `sql/schema.sql`. Each one has a fixed name, and that name is what a rejection reports.

**Constraints on `collection_configs`** (14, all named):

- Foreign keys, in the order the database checks them: `config_field_exists`, `config_unit_matches_source`, `config_answers_request`, `config_service_matches_request`, `config_field_in_service`, `config_type_matches_request`, `config_sampling_requested`, `config_unit_allowed_for_type`
- UNIQUE constraints: `config_one_per_request`, `config_one_per_signal`, `config_one_per_field`
- CHECK constraints: `collection_configs_signal_name_check`, `collection_configs_status_check`, `config_approval_signed`

**Triggers:**

- `config_sampling` checks that `sample_s` is inside the range of the source field. It reports `config_sampling_supported`.
- `config_transition` limits status changes by role and by state. It reports `config_agent_cannot_approve`, `config_promote_only_approved` or `config_bait_never_active`.
- `signal_active` accepts a row in `signals` only when an active configuration exists for that signal. It reports `signal_needs_active_config`.

**Roles:**

- `admin` applies the schema and reads everything. It is the `postgres` user locally.
- `agent_writer` can read the catalog and the signals, insert a configuration with ten named columns, and change `status`. The only status change it may make is `draft` to `needs_review`.
- `approver` can read configurations, change `status` and `approved_by`, and write to `review_log`. It has no access to the catalog tables and cannot insert or delete configurations.

**Precedence.** When one insert breaks several rules, the database reports one of them, in this order: the sampling trigger, then the CHECK constraints, then the UNIQUE constraints, then the foreign keys in the order listed above. I did not write this order as code. It follows from how PostgreSQL checks rows, and `tests/test_rules_pg.py` covers it.

## Tests

```
uv run pytest                    # offline: no network, no AWS, no database
uv run pytest -m local_pg        # needs the container from above, with the schema applied
uv run pytest -m docker_script   # tests of scripts/local_db.sh, run alone
```

The `docker_script` tests remove and recreate the container `opsmem-pg`, which the `local_pg` tests use. Run them in a separate session and never together. If you select both, pytest stops before running any test. After a `docker_script` session, run `eval "$(scripts/local_db.sh up)"` and the applier again before the next `local_pg` session.

## Part 1: the database says no

### 3. Verify without spending

Here I check what the agent will read when the database rejects a row, without calling a model. The script below connects as `agent_writer` to the local database from the previous step, inserts a configuration whose `source_field` does not exist, and prints the rejection twice: once in raw mode and once in instructive mode.

```python
from opsmem import db, errors

agent = db.connect("agent_writer")
proposal = {"request_id": "R1", "service_id": "api", "signal_type": "latency",
            "source_field": "no_such_field", "sample_s": 60}
try:
    agent.run(
        "INSERT INTO collection_configs (run_id, installation_id, request_id, service_id, signal_name,"
        " signal_type, source_field, unit, sample_s, model_id)"
        " VALUES ('demo', 'install-07', :request_id, :service_id, 'demo_signal', :signal_type,"
        " :source_field, 'ms', :sample_s, 'demo')", **proposal)
except agent.DatabaseError as err:
    rule = errors.classify(str(err))
    valid = errors.valid_values(agent, rule, proposal, "install-07")
    print(errors.render(rule, [], "raw", str(err)))
    print(errors.render(rule, valid, "instructive", str(err)))
```

I saved it as a file and ran it with `uv run python`, with `OPSMEM_LOCAL_PG` and `AWS_REGION` set as before. This is the output, unedited:

```
ERROR: insert or update on table "collection_configs" violates foreign key constraint "config_field_exists"
DETAIL:  Key (installation_id, source_field)=(install-07, no_such_field) is not present in table "source_fields".
REJECTED (config_field_exists). Not saved. Unknown source_field. Valid source_field: api_5xx, api_p95, cls_create_fail, enc_active, enc_q_wait, jq_depth, jq_oldest, mst_free_pct, mst_wr_lat.
```

The first two lines are the raw mode: the message PostgreSQL produced, passed through as it is. The third line is the instructive mode. `classify` reads the rule name from the message (`config_field_exists`). `valid_values` asks the database, as `agent_writer`, for the nine field names of `install-07`. `render` puts the rule, the parameter to change (`source_field`) and those values in one line.

The instruction names the parameter to change and never a tool. I did this on purpose. A tool name in a rejection tells the model which action to repeat, and I want the experiment to measure what the model learns from the rule and the valid values alone. If the line said which tool to call, I could not tell whether the model understood the rule or only followed the hint.

The lookup of valid values must run with the `agent_writer` connection, as in the script. With a role that cannot read the catalog, the list comes back empty.
