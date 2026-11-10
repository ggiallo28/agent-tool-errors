# Implementation Plan: catalog-schema

## Overview

The design uses Python, so all tasks use Python 3 managed with uv. Each top-level task is one unit of work that ends with its tests passing, so it can be committed alone as `feat(catalog-schema): <task number> <task title in lowercase>` (or `test(catalog-schema): ...` when the task only adds tests). Order: project setup, parsers and pure logic with no database, `db.py`, schema SQL, scripts, then Docker-based tests.

Test rules that apply to every task:
- Unit tests use no network, no AWS and no database. Aurora behaviour is tested with a Fake_Data_API_Client and a replaced `_sleep`. psycopg is replaced by a fake in unit tests.
- Properties 1 to 15 use Hypothesis and are tagged `Feature: catalog-schema, Property <n>: <title>`.
- Database rule tests are example tests with the marker `local_pg` on the local Docker database. They never use generated inputs.
- `docker_script` tests are selected only with `-m docker_script` and never run together with `local_pg`.

## Tasks

- [x] 1. Set up project, dependencies and marker guard
  - [x] 1.1 Create `pyproject.toml` and the package skeleton
    - Project managed with uv. Runtime dependencies: `boto3`, `pyyaml`. Dependency group `dev`: `pytest`, `hypothesis`. Dependency group `local`: `psycopg[binary]`
    - Add `[tool.pytest.ini_options]` with the markers `local_pg`, `docker_script`, `aurora` and `addopts = "--strict-markers"`, exactly as in the design
    - Create `opsmem/__init__.py`, `tests/__init__.py` and the empty directories `scripts/` and `sql/`
    - Pin dependency versions exactly and run `uv sync --group dev --group local`
    - _Requirements: 17.1, 20.1_
  - [x] 1.2 Create root `conftest.py` with the marker guard
    - Register the three markers in `pytest_configure`
    - `pytest_collection_modifyitems` (trylast): skip `docker_script` tests unless `docker_script` appears in the `-m` expression; raise `pytest.UsageError` naming both markers and the container `opsmem-pg` when both `docker_script` and `local_pg` items are selected
    - Skip `local_pg` tests when `OPSMEM_LOCAL_PG` is unset or empty, and `aurora` tests when `CLUSTER_ARN` is unset or empty
    - _Requirements: 20.1, 20.2, 20.3_
  - [x] 1.3 Write tests for the marker guard in `tests/test_markers.py`
    - Use the `pytester` plugin: default run skips `docker_script`; `-m docker_script` runs them; `-m "docker_script or local_pg"` aborts before any test body runs with a message naming both markers
    - Run `uv run pytest` and confirm it passes offline
    - _Requirements: 20.1, 20.2, 20.3_

- [x] 2. Implement manual parsers with tests
  - [x] 2.1 Implement `opsmem/manual.py`: types, constants, `parse_services`, `parse_fields`
    - Frozen dataclasses `Service`, `Field`, `Request`, `ManualError`, constants `MANUAL` and `OPENAPI`
    - `parse_services`: one service per tag, in file order, `service_id` from tag name, `name` from tag description; `ManualError("tags missing")` when there are no tags
    - `parse_fields`: GET `/stats` operations, response schema from `responses.200.content.application/json.schema`, local `$ref` resolution with a depth limit, service from `tags[0]`, required `x-unit`, `x-sampling-min-s`, `x-sampling-max-s` (integers, not booleans)
    - Errors name the unresolved `$ref`, the missing element (`tags` or `GET stats responses`), the operation without a tag, or the offending property; no partial result; no file is read
    - _Requirements: 15.2, 15.3, 15.9, 16.1, 16.2, 16.3, 16.4, 16.5, 16.8_
  - [x] 2.2 Implement `parse_requests` in `opsmem/manual.py`
    - Find `## Requests from operations`, read the first pipe table after it, skip header and separator rows, strip cells and backticks, sampling cell must match `^(\d+)\s*s$`
    - Errors: missing heading names the section; no rows names the section and says no rows were found; a row with fewer cells than the header names the row
    - _Requirements: 15.4, 15.8, 15.9, 16.1, 16.3, 16.6, 16.7_
  - [x] 2.3 Write example tests in `tests/test_manual.py`
    - Happy path on the real files in `manuals/`: 5 services in order `media, encoding, api, classes, queue`; 9 fields; `api_p95` unit `s` 10 to 300; `mst_wr_lat` unit `ms`; 6 requests; `R5` sampling 60; every request service is one of the 5 services
    - Inline error cases: missing `$ref` target names the reference, missing section, section without rows, no tags, no GET stats responses
    - Confirm the tests open no database, network or AWS resource
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 17.9, 17.10, 17.11, 17.13_
  - [x] 2.4 Write property test for OpenAPI parse round trip in `tests/test_manual.py`
    - **Property 13: OpenAPI parse round trip**
    - Generate small OpenAPI texts with tags and stats operations (inline and `$ref` schemas); parse twice and compare
    - **Validates: Requirements 15.2, 15.3, 16.3, 16.4**
  - [x] 2.5 Write property test for dangling references in `tests/test_manual.py`
    - **Property 14: Dangling references are reported**
    - **Validates: Requirements 16.5**
  - [x] 2.6 Write property test for requests table round trip in `tests/test_manual.py`
    - **Property 15: Requests table round trip**
    - Include short rows raising an error that names the row
    - **Validates: Requirements 15.4, 16.3**

- [x] 3. Implement db core logic with tests
  - [x] 3.1 Implement the pure parts of `opsmem/db.py`
    - `ROLES`, `DatabaseError(text, *, sqlstate=None, constraint=None)` with `str(err) == text`, `ConfigError`, `ConnectionFailed`, base `Database` class exposing `DatabaseError`
    - `scan_params(sql)` that skips quoted strings, dollar-quoted bodies and comments, leaves `::` alone, and finds `:name` tokens
    - `to_psycopg(sql)` converting `:name` to `%(name)s` and escaping `%` as `%%`; `check_missing(sql, params)` raising `ValueError("Missing parameter: name")`
    - `parse_local_pg(value)` returning `(host, port)` or raising `ConfigError` mentioning `OPSMEM_LOCAL_PG`
    - `check_config(required)` writing `Configuration error, agent not started. Missing: <names>` (names joined by `", "`) to stderr and `SystemExit(1)`; local mode replaces the list with `OPSMEM_LOCAL_PG` and `AWS_REGION`
    - _Requirements: 1.5, 1.6, 1.7, 1.9, 3.2, 3.7, 3.8, 3.9, 4.1, 4.2, 4.3, 4.4, 4.5_
  - [x] 3.2 Write property test for local parameter conversion in `tests/test_db_params.py`
    - **Property 3: Local parameter conversion round trip**
    - **Validates: Requirements 1.6, 3.7, 3.8, 3.9**
  - [x] 3.3 Write property test for `OPSMEM_LOCAL_PG` parsing in `tests/test_db_params.py`
    - **Property 7: OPSMEM_LOCAL_PG parsing**
    - **Validates: Requirements 3.1, 3.2**
  - [x] 3.4 Write property test for the configuration check in `tests/test_check_config.py`
    - **Property 8: Configuration check**
    - **Validates: Requirements 4.1, 4.2, 4.4, 4.5**
  - [x] 3.5 Write property test for local mode required list in `tests/test_check_config.py`
    - **Property 9: Local mode replaces the required list**
    - **Validates: Requirements 4.3**

- [x] 4. Implement Aurora backend with tests
  - [x] 4.1 Implement `AuroraBackend` in `opsmem/db.py`
    - Secret variables `ADMIN_SECRET_ARN`, `AGENT_WRITER_SECRET_ARN`, `APPROVER_SECRET_ARN`, cluster `CLUSTER_ARN`, database `opsmemory`, lazy boto3 client using `AWS_REGION`
    - Missing or empty variable raises `ConfigError` naming it before any Data API call
    - Typed parameter conversion (`bool` tested before `int`) and result cell conversion back to Python values
    - Retry loop with `RETRY_WAITS = (5, 10, 15, 20, 25, 30)` and module-level `_sleep`; re-raise `DatabaseResumingException` unchanged after 6 retries
    - `BadRequestException` wrapped as `DatabaseError(str(e), ...) from e`; `sqlstate` and `constraint` only from structured attributes, else None; other exceptions propagate unchanged with no retry
    - _Requirements: 1.4, 1.5, 1.8, 1.9, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_
  - [x] 4.2 Write property test for Data API value round trip in `tests/test_db_aurora.py`
    - **Property 5: Data API value round trip**
    - **Validates: Requirements 1.6**
  - [x] 4.3 Write property test for the retry schedule in `tests/test_db_aurora.py`
    - **Property 6: Retry schedule**
    - Use a Fake_Data_API_Client and a replaced `_sleep`
    - **Validates: Requirements 2.4, 2.5**
  - [x] 4.4 Write property test for missing parameters on Aurora in `tests/test_db_aurora.py`
    - **Property 4: Missing parameters stop execution** (Aurora side)
    - **Validates: Requirements 1.7**
  - [x] 4.5 Write example tests in `tests/test_db_aurora.py`
    - Missing or empty secret and `CLUSTER_ARN` variables name the variable and send nothing; each role uses only its own secret; non-resuming exceptions are not retried
    - DatabaseError text: the fake client raises a `BadRequestException` with a DETAIL line; assert `str(err) == str(native)`, `err.__cause__ is native`, `sqlstate` and `constraint` None
    - _Requirements: 1.9, 2.1, 2.3, 2.6, 2.7, 18.3, 18.4_

- [x] 5. Implement local backend and `connect` with tests
  - [x] 5.1 Implement `LocalBackend` and `connect(role)` in `opsmem/db.py`
    - `connect`: exact-type role check (`type(role) is str and role in ROLES`) raising `ValueError` containing the value before any I/O; `LocalBackend` when `OPSMEM_LOCAL_PG` is non-empty, else `AuroraBackend`
    - `LocalBackend`: parse `host:port` before opening a socket, credentials per role (`postgres/postgres`, `agent_writer/agent_writer`, `approver/approver`), database `opsmemory`, `autocommit=True`, `connect_timeout=10`, `ConnectionFailed` naming host, port and role with no retry, lazy `psycopg` import
    - `psycopg.Error` wrapped as `DatabaseError(str(e), sqlstate=e.diag.sqlstate, constraint=e.diag.constraint_name) from e`
    - Module docstring states the Local_Backend is for local Docker only
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.8, 1.9, 1.10, 3.1, 3.3, 3.4, 3.5, 3.6, 3.10, 3.11_
  - [x] 5.2 Write property test for backend selection in `tests/test_db_connect.py`
    - **Property 1: Backend selection follows OPSMEM_LOCAL_PG**
    - Replace both backend constructors with fakes; no connection is made
    - **Validates: Requirements 1.2, 1.3**
  - [x] 5.3 Write property test for invalid roles in `tests/test_db_connect.py`
    - **Property 2: Invalid roles are rejected before any connection**
    - **Validates: Requirements 1.10**
  - [x] 5.4 Write local backend unit tests in `tests/test_db_local.py` with a fake psycopg
    - Property 4 for the local side (**Property 4: Missing parameters stop execution**, **Validates: Requirements 1.7**)
    - Credentials per role, `autocommit=True`, timeout 10, error naming host, port and role, malformed `OPSMEM_LOCAL_PG` opens no connection
    - Fake `psycopg.Error` with a DETAIL line is wrapped with `str(err) == str(native)` and `__cause__` set
    - _Requirements: 1.7, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.10_

- [x] 6. Write schema SQL for tables
  - [x] 6.1 Create `sql/schema.sql` with roles and catalog tables
    - Statement separator line `-- @@ --`, used only as a whole line
    - `CREATE ROLE agent_writer LOGIN` and `CREATE ROLE approver LOGIN` with no PASSWORD clause
    - Tables `installations`, `services`, `source_fields`, `signal_requests`, `allowed_units` with the keys, UNIQUE constraints and foreign keys of the design
    - Five `allowed_units` rows: `latency/ms`, `latency/s`, `ratio/percent`, `count/count`, `age/s`
    - Plain statements only; no `::` casts, no colon followed by a letter in comments or literals
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 13.1, 13.2, 14.4_
  - [x] 6.2 Add `collection_configs`, `review_log` and `signals` to `sql/schema.sql`
    - `collection_configs` exactly as in the design: column order, defaults, three named CHECKs, three UNIQUE constraints in order, eight foreign keys in order
    - `review_log` with defaults, verdict and bait_expected CHECKs; `signals` with the composite primary key
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.7, 7.9, 7.10, 7.11, 7.12, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 8.13, 8.14, 9.2, 9.3_
  - [x] 6.3 Write offline schema text tests in `tests/test_schema_text.py`
    - The separator appears only as a whole line; no statement is empty; the file has no `PASSWORD` and no `::`
    - The eight foreign key names appear in the order of Requirement 8.1 to 8.8 and the three UNIQUE names in the order of 8.9 to 8.11; the column list of `collection_configs` matches Requirement 7.1
    - Exactly five `allowed_units` inserts
    - _Requirements: 6.10, 7.1, 8.1, 8.9, 9.2, 9.3, 13.2, 14.4_

- [x] 7. Write schema SQL for triggers, roles and grants
  - [x] 7.1 Add functions and triggers to `sql/schema.sql`
    - `check_sampling()` as SECURITY DEFINER with `SET search_path = public`, inclusive bounds, NULL and unknown field pass, exact message, ERRCODE `23514`, CONSTRAINT `config_sampling_supported`; trigger `config_sampling` BEFORE INSERT OR UPDATE OF `source_field`, `sample_s`, FOR EACH ROW
    - `check_transition()` with the ordered rules and exact messages, ERRCODEs and constraint names of Requirement 11; trigger `config_transition` BEFORE UPDATE
    - `check_signal_active()` with exact message, ERRCODE `23503`, CONSTRAINT `signal_needs_active_config`; trigger `signal_active` BEFORE INSERT on `signals`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 12.1, 12.2, 12.3, 12.4_
  - [x] 7.2 Add grants to `sql/schema.sql`
    - `agent_writer`: SELECT on the six catalog and signal tables; INSERT on the ten listed columns of `collection_configs`; SELECT on it; UPDATE (`status`); USAGE on `collection_configs_config_id_seq`
    - `approver`: SELECT on `collection_configs`; UPDATE (`status`, `approved_by`); INSERT and SELECT on `review_log`; nothing on the other tables
    - _Requirements: 13.3, 13.4, 13.5, 13.6, 13.7, 13.8_
  - [x] 7.3 Extend `tests/test_schema_text.py` with trigger and grant checks
    - Messages, ERRCODEs and constraint names appear exactly as in Requirements 10 to 12; `SECURITY DEFINER` and `SET search_path = public` are present on `check_sampling`; grant statements list the exact columns; `approver` has no GRANT on the six tables
    - _Requirements: 10.2, 10.3, 10.4, 11.3, 11.4, 11.5, 12.2, 13.4, 13.5, 13.6, 13.7, 13.8_

- [x] 8. Implement schema applier and catalog loader with tests
  - [x] 8.1 Implement `split_statements` in `scripts/apply_schema.py`
    - `Statement(sql, index, start_line)`; split only on the whole-line separator `-- @@ --`; drop chunks with only comments or whitespace
    - _Requirements: 14.3, 14.4_
  - [x] 8.2 Implement the apply flow in `scripts/apply_schema.py`
    - `check_config` for the backend in use; `connect("admin")`; first statement `SELECT to_regclass('public.installations')`; connection failure runs no statement and exits non-zero; a non-NULL result prints the not-empty message with the recreate hint (`scripts/local_db.sh up` or a new stack) and exits non-zero
    - Run statements one per call in file order; on failure print statement text, index, start line and database error, run nothing later, exit non-zero
    - Set passwords with `ALTER ROLE`: local passwords equal role names; Aurora passwords from the role secrets, accepted only if `[A-Za-z0-9]+`
    - _Requirements: 14.1, 14.2, 14.5, 14.6, 14.7, 14.8, 14.9_
  - [x] 8.3 Implement the Catalog_Loader in `scripts/apply_schema.py`
    - Read `OPENAPI` and `MANUAL` as text (read-only), parse everything before writing, report missing files and parser errors by name with a failure exit
    - Plain INSERTs without `ON CONFLICT`, in order: installation `install-07` named `Course platform, installation 07`, services, fields, requests
    - Print `installations: 1`, `services: 5`, `fields: 9`, `requests: 6` style lines and exit 0; run as part of the first successful apply
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8, 15.9_
  - [x] 8.4 Write property test for statement splitting in `tests/test_apply_schema.py`
    - **Property 10: Statement splitting round trip**
    - **Validates: Requirements 14.3, 14.4**
  - [x] 8.5 Write property test for order and stop at first failure in `tests/test_apply_schema.py`
    - **Property 11: Statements run in order and stop at the first failure**
    - Use a spy Database_Object
    - **Validates: Requirements 14.5, 14.8**
  - [x] 8.6 Write property test for the existing schema refusal in `tests/test_apply_schema.py`
    - **Property 12: Existing schema stops the applier**
    - **Validates: Requirements 14.9**
  - [x] 8.7 Write loader unit tests in `tests/test_catalog_loader.py` with a spy database
    - Insert order and counts 1, 5, 9, 6; no `ON CONFLICT`; missing file and missing heading write nothing; hashes of the two files in `manuals/` are unchanged; password rules and local versus Aurora password source; admin connection failure runs no statement
    - _Requirements: 14.1, 14.2, 14.6, 14.7, 15.1, 15.5, 15.6, 15.7, 15.8, 15.9_

- [x] 9. Implement local database script with offline tests
  - [x] 9.1 Create `scripts/local_db.sh`
    - `up`: `docker rm -f opsmem-pg` with output discarded, `docker run -d --name opsmem-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=opsmemory -p 55432:5432 postgres:16`; wait at 1-second polls, 60 seconds in total, first for the log line `PostgreSQL init process complete; ready for start up.`, then for `pg_isready` over TCP (fall back to `docker exec` when the host has no `pg_isready`); success prints only `export OPSMEM_LOCAL_PG=localhost:55432` and exits 0
    - Start failure and readiness timeout print the cause to stderr, print no `export` line, exit non-zero, and keep the container on timeout; the timeout is read from `OPSMEM_READY_TIMEOUT` with default 60 so it can be tested
    - `down`: `docker rm -f opsmem-pg`, always exit 0; other arguments print a usage line with `up` and `down` to stderr, touch nothing, exit non-zero
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_
  - [x] 9.2 Write offline tests in `tests/test_local_db_offline.py` with a stub `docker` on PATH
    - No argument and a bad argument: usage on stderr, stub `docker` never called, non-zero exit
    - Stub `docker run` fails: stderr has the cause, stdout is empty, non-zero exit
    - Stub never logs the init line with `OPSMEM_READY_TIMEOUT=2`: stderr mentions readiness timeout, no `export` line, container not removed
    - `down` with a stub that reports no container exits 0
    - _Requirements: 5.5, 5.6, 5.7, 5.8_

- [x] 10. Add Docker script tests
  - [x] 10.1 Write `tests/test_local_db_sh.py` with the marker `docker_script`
    - Real Docker: `up` prints only the `export` line on stdout; repeated `up` replaces the container; `down` removes it and `down` twice exits 0; a busy port 55432 fails with empty stdout
    - Run with `uv run pytest -m docker_script`, alone; document that `local_pg` tests must be run in a separate session
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.7, 20.1, 20.2, 20.3_

- [x] 11. Add local database fixtures, smoke tests and error text test
  - [x] 11.1 Create `tests/conftest.py` fixtures for `local_pg`
    - Session fixture that checks the container is reachable as `admin` and, when `to_regclass('public.installations')` is NULL, runs the applier once; helpers `connect_as(role)`, `new_run_id()` and `assert_rejected(call, expect)` that reports the rule, expected and actual constraint name
    - _Requirements: 19.4, 19.5_
  - [x] 11.2 Write `tests/test_schema_pg.py` (marker `local_pg`)
    - Compare `information_schema` and `pg_constraint` with the expected columns, constraint names and creation order of the eight foreign keys and three UNIQUE constraints; check trigger definitions
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 7.1, 7.2, 8.1, 8.9_
  - [x] 11.3 Extend `tests/test_apply_schema.py` with `local_pg` tests
    - Row counts 1, 5, 9, 6 after the first application; a second run exits non-zero, prints the not-empty message with the `scripts/local_db.sh up` hint, and leaves object names and row counts unchanged
    - _Requirements: 14.9, 15.1, 15.5, 15.7_
  - [x] 11.4 Write `tests/test_db_error_pg.py` (marker `local_pg`)
    - As `agent_writer`, repeat a configuration for the same `(run_id, installation_id, request_id)`; assert `__cause__` is a `psycopg.Error`, `str(err) == str(err.__cause__)`, the text contains `DETAIL`, `sqlstate == "23505"`, `constraint == "config_one_per_request"`
    - _Requirements: 18.1, 18.2_

- [x] 12. Add database rule tests for tables and constraints
  - [x] 12.1 Write rule tests in `tests/test_rules_pg.py` (marker `local_pg`): catalog, defaults and status
    - `test_catalog_constraints`, `test_allowed_units_content`, `test_config_defaults`, `test_status_values` with the cases of the design table (valid values, `''`, `Draft`, `archived`, trailing space, on INSERT and UPDATE)
    - _Requirements: 6.10, 6.11, 7.2, 7.3, 7.4, 7.5, 7.6, 8.14, 19.1, 19.2, 19.4_
  - [x] 12.2 Add `test_review_log` and `test_signals_primary_key` to `tests/test_rules_pg.py`
    - Cases from the design table, `approver` for review_log and `admin` for signals; a rejected statement is followed by a count showing the table is unchanged
    - _Requirements: 7.7, 7.8, 7.9, 7.10, 7.11, 7.12, 7.13, 19.2, 19.4_
  - [x] 12.3 Add the eight `test_config_foreign_key_<name>` tests to `tests/test_rules_pg.py`
    - Each foreign key violated alone as `agent_writer`; the reported CONSTRAINT equals the name; use the data examples of the design (`api_p95` with unit `ms`, `R4` with a queue field, `R4` with service `media` and field `api_5xx`)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.15, 19.2, 19.4_
  - [x] 12.4 Add `test_config_unique_<name>` (3 tests) and `test_approval_signed` to `tests/test_rules_pg.py`
    - Repeat of request, signal name and source field; same value in another `run_id` passes; `approved` and `active` with NULL `approved_by` fail, other statuses pass
    - _Requirements: 8.9, 8.10, 8.11, 8.12, 8.15, 19.2, 19.4_
  - [x] 12.5 Add `test_signal_name_pattern` to `tests/test_rules_pg.py`
    - Lengths 2 (fail), 3 (pass), 41 (pass), 42 (fail); leading digit, uppercase, `_`, `-`, space and trailing newline fail; `a_1` passes; expected results written by hand, not from a Python regex
    - _Requirements: 8.13, 8.15, 19.2, 19.3_

- [x] 13. Add database rule tests for triggers, precedence and grants
  - [x] 13.1 Add `test_precedence_matrix` to `tests/test_rules_pg.py`
    - Each foreign key alone, every adjacent pair of foreign keys, CHECK with UNIQUE, UNIQUE with FK, sampling with CHECK, UNIQUE and FK; the earlier rule is reported
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 19.2_
  - [x] 13.2 Add sampling tests to `tests/test_rules_pg.py`
    - `test_sampling_bounds` on `api_p95` (9 fails, 10, 11, 299, 300 pass, 301 fails; exact message and SQLSTATE `23514`; same bounds on UPDATE of `sample_s` and of `source_field`)
    - `test_sampling_passthrough` (unknown field reports `config_field_exists`, NULL reports the NOT NULL error)
    - `test_sampling_trigger_definition` (`pg_trigger`, `prosecdef`, `search_path`, `approver` has no SELECT on `source_fields`)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 19.2, 19.3, 19.4_
  - [x] 13.3 Add `test_transitions` to `tests/test_rules_pg.py`
    - Parametrised table written from Requirement 11: same status passes for every role; allowed and forbidden agent moves with `42501`; approver promote cases; bait case; precedence cases; every failure leaves the row unchanged
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 19.2, 19.4_
  - [x] 13.4 Add `test_signal_admission` to `tests/test_rules_pg.py`
    - No configuration and each non-active status fail; `active` passes; other name or installation fails; draft plus active passes; exact message and SQLSTATE `23503`; no row stored on failure
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 19.2, 19.4_
  - [x] 13.5 Add `test_role_grants` and `test_forbidden_statements` to `tests/test_rules_pg.py`
    - `has_column_privilege` for every column and role; LOGIN on both roles; `approver` has nothing on the six tables; forbidden INSERT columns, UPDATE columns, INSERT and DELETE for `approver` fail with `42501` and leave the table unchanged; allowed updates pass
    - _Requirements: 13.1, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 13.10, 13.11, 19.2, 19.4_

- [x] 14. Add Aurora smoke test
  - [x] 14.1 Write `tests/test_aurora_smoke.py` (marker `aurora`)
    - Skipped unless `CLUSTER_ARN` is set; applies nothing by itself beyond a connection check and one rejected insert to record what the Data API error text contains
    - _Requirements: 1.9, 2.1, 2.2_

- [x] 15. Write README.md, first version
  - Docs task, committed as `docs(catalog-schema): 15 write readme.md, first version`. Write in first person, plain English, no marketing words. Describe only what is implemented in this spec: no agent, no tool layer, no AgentCore, no experiments, no cleanup script, no CloudFormation.
  - [x] 15.1 Create `README.md` with the title, summary and prerequisites
    - Title `agent-tool-errors`, followed by two sentences saying what the repository shows: an agent writes configuration rows, the rules live in PostgreSQL, and rejections tell the agent what to change
    - Section `## Prerequisites`: Python 3.12+, uv, Docker; say that AWS is needed only for Bedrock and Aurora, which are covered in later sections
    - _Requirements: 5.4_
  - [x] 15.2 Add the section `## Run it locally, paying only for the model`
    - The intro states that this step only starts the database and applies the schema, and that no model is called at this point; the section must not claim a model call
    - Document, in order: `scripts/local_db.sh up`, `eval` of the printed export line, `uv run scripts/apply_schema.py`
    - Actually run each command in a clean state (run `scripts/local_db.sh down` first, then `scripts/local_db.sh up` first in the sequence) and paste the real output of each command under it. Do not invent output; remove or mark nothing that was not run
    - Note that applying the schema a second time is refused with a message pointing to `scripts/local_db.sh up`
    - _Requirements: 5.4, 14.9, 15.5_
  - [x] 15.3 Add a short section on what the database enforces
    - List the named rules: the 14 named constraints (eight foreign keys, three UNIQUE constraints, three CHECK constraints on `collection_configs`) and the three triggers (`config_sampling`, `config_transition`, `signal_active`), using the exact names from `sql/schema.sql`
    - Describe the roles and what each may do: `admin`, `agent_writer`, `approver`
    - Describe the rule precedence: sampling trigger, then CHECK, then UNIQUE, then foreign keys in declared order
    - Mention test commands only as implemented: `uv run pytest`, `uv run pytest -m local_pg`, and `uv run pytest -m docker_script` run alone in its own session
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 8.13, 8.14, 8.15, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 13.10, 13.11_
  - [x] 15.4 Verify the README against the repository
    - Check that every constraint, trigger, role and message named in the README matches `sql/schema.sql` exactly
    - Follow the README commands from a fresh clone (new checkout, `uv sync --group dev --group local`) and confirm they work as written
    - Confirm that the README mentions nothing that is not implemented yet and that the pasted outputs come from real runs
    - _Requirements: 5.4, 14.9, 15.5, 8.1, 9.1, 13.1_

- [x] 16. Final checkpoint - Ensure all tests pass
  - Run `uv run pytest` (offline), then `eval "$(scripts/local_db.sh up)"`, apply the schema, run `uv run pytest -m local_pg`, and run `uv run pytest -m docker_script` as a separate session. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are property tests. They are optional per the workflow, but the plan assumes they are run so each commit ends with its tests passing. Skip them only if you accept a commit without that coverage.
- Example tests are not marked optional because each task must end with its tests passing.
- Database rule tests are example tests only. Hypothesis is used for Properties 1 to 15 on pure logic.
- `local_pg` and `docker_script` tests use the same container `opsmem-pg`, so run them in separate sessions. After a `docker_script` session, run `local_db.sh up` and the applier again.
- `OPSMEM_READY_TIMEOUT` (default 60) is a small addition to `local_db.sh` so the timeout path can be tested; it does not change the 60 second contract.
- The applier tests import `scripts/apply_schema.py` with `importlib`; `scripts/` is not a package.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "2.1"] },
    { "id": 3, "tasks": ["2.2"] },
    { "id": 4, "tasks": ["2.3"] },
    { "id": 5, "tasks": ["2.4"] },
    { "id": 6, "tasks": ["2.5"] },
    { "id": 7, "tasks": ["2.6"] },
    { "id": 8, "tasks": ["3.1"] },
    { "id": 9, "tasks": ["3.2", "3.4"] },
    { "id": 10, "tasks": ["3.3", "3.5"] },
    { "id": 11, "tasks": ["4.1"] },
    { "id": 12, "tasks": ["4.2"] },
    { "id": 13, "tasks": ["4.3"] },
    { "id": 14, "tasks": ["4.4"] },
    { "id": 15, "tasks": ["4.5"] },
    { "id": 16, "tasks": ["5.1"] },
    { "id": 17, "tasks": ["5.2", "5.4"] },
    { "id": 18, "tasks": ["5.3"] },
    { "id": 19, "tasks": ["6.1"] },
    { "id": 20, "tasks": ["6.2"] },
    { "id": 21, "tasks": ["6.3"] },
    { "id": 22, "tasks": ["7.1"] },
    { "id": 23, "tasks": ["7.2"] },
    { "id": 24, "tasks": ["7.3"] },
    { "id": 25, "tasks": ["8.1"] },
    { "id": 26, "tasks": ["8.2"] },
    { "id": 27, "tasks": ["8.3"] },
    { "id": 28, "tasks": ["8.4", "8.7"] },
    { "id": 29, "tasks": ["8.5"] },
    { "id": 30, "tasks": ["8.6"] },
    { "id": 31, "tasks": ["9.1"] },
    { "id": 32, "tasks": ["9.2"] },
    { "id": 33, "tasks": ["10.1"] },
    { "id": 34, "tasks": ["11.1"] },
    { "id": 35, "tasks": ["11.2", "11.3", "11.4"] },
    { "id": 36, "tasks": ["12.1"] },
    { "id": 37, "tasks": ["12.2"] },
    { "id": 38, "tasks": ["12.3"] },
    { "id": 39, "tasks": ["12.4"] },
    { "id": 40, "tasks": ["12.5"] },
    { "id": 41, "tasks": ["13.1"] },
    { "id": 42, "tasks": ["13.2"] },
    { "id": 43, "tasks": ["13.3"] },
    { "id": 44, "tasks": ["13.4"] },
    { "id": 45, "tasks": ["13.5"] },
    { "id": 46, "tasks": ["14.1"] },
    { "id": 47, "tasks": ["15.1"] },
    { "id": 48, "tasks": ["15.2"] },
    { "id": 49, "tasks": ["15.3"] },
    { "id": 50, "tasks": ["15.4"] }
  ]
}
```
