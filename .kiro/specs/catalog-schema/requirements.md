# Requirements Document

## Introduction

This spec covers the PostgreSQL database that holds the rules for collection configurations, the connections per role, and the loading of the catalog from the manual. PostgreSQL enforces every rule with named constraints, foreign keys, triggers, column-level grants and roles. Names, messages and orders in this document are an external contract. The model reads these strings, so changing one changes what the agent learns: keep them exactly.

Out of scope: the tool layer, the agent, the experiment scripts and AWS deployment.

## Glossary

- **Db_Connector**: The module `opsmem/db.py` that provides `connect` and `check_config`.
- **Database_Object**: The object returned by `connect(role)`, exposing `run(sql, **params) -> list[list]` and the attribute `DatabaseError`.
- **Aurora_Backend**: The Database_Object implementation that uses Aurora PostgreSQL through the RDS Data API.
- **Local_Backend**: The Database_Object implementation that uses local PostgreSQL in Docker through psycopg.
- **Native_Exception**: The exception raised by the underlying driver: `psycopg.Error` on the Local_Backend, `BadRequestException` of the Data API client on the Aurora_Backend.
- **Fake_Data_API_Client**: A test double of the Data API client that raises a configured exception and makes no network call.
- **Rule_Test**: A test of one database rule (sampling, name pattern, status values, transitions, signal admission, rule precedence, grants) run against the local Database.
- **Role**: One of `admin`, `agent_writer` or `approver`.
- **Local_DB_Script**: The script `scripts/local_db.sh`.
- **Schema_File**: The file `sql/schema.sql` containing the whole schema.
- **Schema_Applier**: The script `scripts/apply_schema.py`, run as the `admin` Role.
- **Catalog_Loader**: The part of the Schema_Applier that loads the catalog from `manuals/`.
- **Manual_Parser**: The module `opsmem/manual.py` with `parse_services(openapi_text)`, `parse_fields(openapi_text)` and `parse_requests(manual_text)`, each taking the text of a file as input and returning a list.
- **Manual**: The file `manuals/course-platform-install-07.md`, referenced by the constant `MANUAL`.
- **OpenAPI_Schema**: The file `manuals/course-platform-install-07.openapi.yaml`, referenced by the constant `OPENAPI`.
- **Config_Table**: The table `collection_configs`.
- **Sampling_Trigger**: The trigger `config_sampling` and its function `check_sampling()`.
- **Transition_Trigger**: The trigger `config_transition` and its function `check_transition()`.
- **Signal_Trigger**: The trigger `signal_active` and its function `check_signal_active()`.
- **Bait**: A row of the Config_Table with `is_bait` equal to true.
- **Database**: The PostgreSQL database named `opsmemory`.
- **Rule_Precedence**: The order in which PostgreSQL reports a violated rule when one insert violates several: Sampling_Trigger, CHECK constraints, UNIQUE constraints in the order of the constraint table, foreign keys in the order of the constraint table.

## Requirements

### Requirement 1: Connection by role

**User Story:** As a builder, I want one `connect(role)` function that works on Aurora and on local PostgreSQL, and that raises database errors carrying the native error text, so that the same code runs in both places and the tool layer can show the text to the model in raw mode, read the constraint name from it in instructive mode, and store it in the trace.

#### Acceptance Criteria

1. WHEN `connect(role)` is called with the string `admin`, `agent_writer` or `approver` (case-sensitive), THE Db_Connector SHALL return a Database_Object bound to that Role.
2. WHERE the environment variable `OPSMEM_LOCAL_PG` is set to a non-empty value, THE Db_Connector SHALL return a Local_Backend.
3. WHERE the environment variable `OPSMEM_LOCAL_PG` is unset or set to an empty string, THE Db_Connector SHALL return an Aurora_Backend.
4. WHEN `run(sql, **params)` is called with valid SQL, THE Database_Object SHALL return a list of rows, each row being a list of column values in SELECT order, and SHALL return an empty list IF the statement produces no rows.
5. THE Database_Object SHALL expose the attribute `DatabaseError` holding the exception class raised on a database error, and the class SHALL be the same for Local_Backend and Aurora_Backend.
6. WHEN `run` is called with SQL containing Data API style named parameters written as `:name`, THE Database_Object SHALL bind each `:name` to the keyword argument of the same name, on both Local_Backend and Aurora_Backend.
7. IF `run` is called with SQL containing a `:name` parameter for which no keyword argument is supplied, THEN THE Database_Object SHALL raise an error naming the missing parameter and SHALL NOT execute the statement.
8. IF a database error occurs during `run`, THEN THE Database_Object SHALL raise an exception of the class held in `DatabaseError`.
9. WHEN `run` raises the exception held in `DatabaseError`, THE Database_Object SHALL set `str(err)` equal, character for character and including any DETAIL lines, to `str()` of the Native_Exception (`str(psycopg.Error)` on the Local_Backend, `str(BadRequestException)` on the Aurora_Backend), SHALL expose the attributes `sqlstate` and `constraint` on `err` with the value None for each one that the backend does not report, and SHALL chain the Native_Exception as `err.__cause__`.
10. IF `connect` is called with a value that is not one of the three Roles (including `None`, an empty string, a non-string value, or a different letter case), THEN THE Db_Connector SHALL raise an error whose message contains the invalid value, and SHALL NOT open any database connection.

### Requirement 2: Aurora backend

**User Story:** As a builder with an AWS account, I want the Aurora backend to use one secret per role, so that each Role connects with its own credentials.

#### Acceptance Criteria

1. THE Aurora_Backend SHALL use one Secrets Manager secret per Role, read from `ADMIN_SECRET_ARN` for `admin`, `AGENT_WRITER_SECRET_ARN` for `agent_writer` and `APPROVER_SECRET_ARN` for `approver`.
2. THE Aurora_Backend SHALL use the cluster given by `CLUSTER_ARN` and the database `opsmemory`.
3. WHEN the Aurora_Backend executes a statement for a Role, THE Aurora_Backend SHALL send the statement to the Data API using only the secret mapped to that Role in criterion 1.
4. IF the Data API raises `DatabaseResumingException`, THEN THE Aurora_Backend SHALL retry the same statement, waiting 5 seconds before the first retry and increasing the wait by 5 seconds before each following retry (5, 10, 15, 20, 25 and 30 seconds for retries 1 to 6).
5. IF the Data API still raises `DatabaseResumingException` after 6 retries, THEN THE Aurora_Backend SHALL stop retrying and raise the `DatabaseResumingException` to the caller without altering its type.
6. IF the environment variable for a Role's secret, or `CLUSTER_ARN`, is unset or empty when the Aurora_Backend needs it, THEN THE Aurora_Backend SHALL raise an error to the caller that names the missing variable and SHALL NOT send any statement to the Data API.
7. IF the Data API raises an exception other than `DatabaseResumingException`, THEN THE Aurora_Backend SHALL raise that exception to the caller without retrying.

### Requirement 3: Local backend

**User Story:** As a builder, I want to run the database in local Docker, so that I can verify the rules without Aurora.

#### Acceptance Criteria

1. WHEN the Local_Backend opens a connection, THE Local_Backend SHALL connect to the host and port parsed from `OPSMEM_LOCAL_PG` in the format `host:port` and to the database `opsmemory`.
2. IF `OPSMEM_LOCAL_PG` is unset, empty, not in the format `host:port`, or has a port outside 1 to 65535, THEN THE Local_Backend SHALL refuse to connect, SHALL raise an error indicating the variable is missing or malformed, and SHALL open no database connection.
3. WHEN the Local_Backend opens a connection for the `admin` Role, THE Local_Backend SHALL log in as `postgres` with password `postgres`.
4. WHEN the Local_Backend opens a connection for the `agent_writer` Role, THE Local_Backend SHALL log in as `agent_writer` with password `agent_writer`.
5. WHEN the Local_Backend opens a connection for the `approver` Role, THE Local_Backend SHALL log in as `approver` with password `approver`.
6. THE Local_Backend SHALL run every connection with autocommit enabled, so that each statement is committed immediately and no explicit commit is required.
7. WHEN `run` receives SQL with `:name` parameters, THE Local_Backend SHALL convert each `:name` parameter to the psycopg `%(name)s` format and bind its value from the supplied parameters.
8. WHEN `run` receives SQL containing `::` casts, THE Local_Backend SHALL keep each cast unchanged and SHALL NOT treat it as a parameter.
9. WHEN `run` receives SQL containing a literal `%`, THE Local_Backend SHALL escape the `%` so that it is sent to the database as a literal `%` character.
10. IF the database is unreachable or rejects the login within 10 seconds of a connection attempt, THEN THE Local_Backend SHALL raise an error that identifies the failed host, port and Role and SHALL NOT retry.
11. THE Local_Backend SHALL be intended for local Docker only and SHALL NOT be used against Aurora.

### Requirement 4: Configuration check

**User Story:** As a builder, I want the process to stop at startup when configuration is missing, so that no model call happens with a broken setup.

#### Acceptance Criteria

1. WHEN `check_config(required)` is called and one or more variables listed in `required` are absent from the environment, THE Db_Connector SHALL stop the process before any model call is made, and SHALL write the message `Configuration error, agent not started. Missing: <names>` to the error output, where `<names>` is a comma-separated list of every missing variable name, in the order they appear in `required`.
2. IF a variable listed in `required` is present in the environment with an empty string value, THEN THE Db_Connector SHALL treat that variable as missing and include its name in `<names>`.
3. WHERE the environment variable `OPSMEM_LOCAL_PG` is set to a non-empty value, THE Db_Connector SHALL use exactly `OPSMEM_LOCAL_PG` and `AWS_REGION` as the required variables, replacing the `required` list passed by the caller.
4. WHEN all required variables are present and non-empty, THE Db_Connector SHALL return to the caller without stopping the process and without writing a configuration error message.
5. IF `required` is an empty list, THEN THE Db_Connector SHALL return to the caller without stopping the process.

### Requirement 5: Local database script

**User Story:** As a builder, I want one script to start and stop the local database, so that the setup is repeatable and removable.

#### Acceptance Criteria

1. WHEN `scripts/local_db.sh up` is run, THE Local_DB_Script SHALL remove any existing container named `opsmem-pg`, and the removal SHALL complete without error when no such container exists.
2. WHEN `scripts/local_db.sh up` is run and the removal of any existing container has completed, THE Local_DB_Script SHALL start a container named `opsmem-pg` from the image `postgres:16` with host port `55432` published to the container's PostgreSQL port.
3. WHEN the container has started, THE Local_DB_Script SHALL wait until the container log contains the database init completion line, and then wait until `pg_isready` succeeds over TCP on `localhost:55432`, polling at 1-second intervals.
4. WHEN `pg_isready` succeeds over TCP, THE Local_DB_Script SHALL print `export OPSMEM_LOCAL_PG=localhost:55432` to standard output and exit with status 0.
5. WHEN `scripts/local_db.sh down` is run, THE Local_DB_Script SHALL remove the container `opsmem-pg` and exit with status 0, including when the container does not exist.
6. IF the database is not ready within 60 seconds of container start, THEN THE Local_DB_Script SHALL print an error message indicating a readiness timeout to standard error, SHALL leave the container `opsmem-pg` in place for inspection, SHALL NOT print the `export` line, and SHALL exit with a non-zero status.
7. IF the container cannot be started (for example, port `55432` is already in use or the container runtime is unavailable), THEN THE Local_DB_Script SHALL print an error message indicating the cause to standard error, SHALL NOT print the `export` line, and SHALL exit with a non-zero status.
8. IF `scripts/local_db.sh` is run with no argument or an argument other than `up` or `down`, THEN THE Local_DB_Script SHALL print a usage message listing `up` and `down` to standard error, leave existing containers unchanged, and exit with a non-zero status.

### Requirement 6: Catalog tables

**User Story:** As a builder, I want the catalog and request tables, so that the database knows the installation, its services, its fields and the requests.

#### Acceptance Criteria

1. THE Schema_File SHALL define the table `installations(installation_id, name)` with primary key `installation_id`, and with `name` declared NOT NULL.
2. THE Schema_File SHALL define the table `services(installation_id, service_id, name)` with primary key `(installation_id, service_id)`, a foreign key from `installation_id` to `installations`, and `name` declared NOT NULL.
3. THE Schema_File SHALL define the table `source_fields(installation_id, service_id, field_name, unit, min_sample_s, max_sample_s)` with primary key `(installation_id, field_name)`, and with `service_id`, `unit`, `min_sample_s` and `max_sample_s` declared NOT NULL.
4. THE Schema_File SHALL define on `source_fields` a UNIQUE constraint on `(installation_id, field_name, unit)` and a UNIQUE constraint on `(installation_id, service_id, field_name)`.
5. THE Schema_File SHALL define on `source_fields` a foreign key from `(installation_id, service_id)` to `services`.
6. THE Schema_File SHALL define the table `signal_requests(installation_id, request_id, service_id, signal_type, sample_s, request_text)` with primary key `(installation_id, request_id)`, and with `service_id`, `signal_type`, `sample_s` and `request_text` declared NOT NULL.
7. THE Schema_File SHALL define on `signal_requests` a UNIQUE constraint on each of `(installation_id, request_id, service_id)`, `(installation_id, request_id, signal_type)` and `(installation_id, request_id, sample_s)`.
8. THE Schema_File SHALL define on `signal_requests` a foreign key from `(installation_id, service_id)` to `services`.
9. THE Schema_File SHALL define the table `allowed_units(signal_type, unit)` with primary key `(signal_type, unit)`.
10. WHEN the Schema_File is executed, THE Schema_File SHALL load `allowed_units` with exactly five rows, the pairs `latency/ms`, `latency/s`, `ratio/percent`, `count/count` and `age/s`, each written as `signal_type/unit`.
11. IF a statement violates a primary key, UNIQUE, foreign key or NOT NULL constraint defined in this requirement, THEN THE database SHALL reject the statement with a constraint-violation error and SHALL leave the affected tables unchanged.
12. THE Schema_File SHALL define on `source_fields` a foreign key from `installation_id` to `installations`, with the default constraint name `source_fields_installation_id_fkey`, in addition to the foreign key of criterion 5.

### Requirement 7: Configuration, review and signal tables

**User Story:** As a builder, I want the table for configuration drafts, the review log and the signals, so that the agent can propose rows and a person can review them.

#### Acceptance Criteria

1. THE Schema_File SHALL define the Config_Table with exactly the columns `config_id`, `run_id`, `installation_id`, `request_id`, `service_id`, `signal_name`, `signal_type`, `source_field`, `unit`, `sample_s`, `model_id`, `status`, `created_by`, `approved_by` and `is_bait`.
2. THE Config_Table SHALL use `config_id` of type SERIAL as primary key and `sample_s` of type INTEGER.
3. THE Config_Table SHALL declare every column NOT NULL except `approved_by`, which SHALL accept NULL.
4. THE Config_Table SHALL default `status` to `draft`, `created_by` to `current_user` and `is_bait` to false, with `is_bait` of type BOOLEAN.
5. THE Config_Table SHALL accept for `status` only the values `draft`, `needs_review`, `approved`, `rejected` and `active`.
6. IF an INSERT or UPDATE on the Config_Table sets `status` to a value outside the set in criterion 5, THEN THE Config_Table SHALL reject the statement with a constraint violation error and leave the table unchanged.
7. THE Schema_File SHALL define the table `review_log` with exactly the columns `config_id`, `reviewer`, `verdict`, `bait_expected` and `reviewed_at`, and with a foreign key from `config_id` to `config_id` of the Config_Table.
8. IF an INSERT into `review_log` references a `config_id` that does not exist in the Config_Table, THEN THE `review_log` table SHALL reject the statement with a foreign key violation error and leave the table unchanged.
9. THE `review_log` table SHALL default `reviewer` to `current_user` and `reviewed_at` to `now()`, and SHALL declare `config_id`, `reviewer`, `verdict` and `reviewed_at` NOT NULL.
10. THE `review_log` table SHALL accept for `verdict` only the values `approved` and `rejected`.
11. THE `review_log` table SHALL accept for `bait_expected` only the values `approved` and `rejected`, or NULL.
12. THE Schema_File SHALL define the table `signals` with exactly the columns `installation_id`, `signal_name`, `ts` and `value`, with `value` of type DOUBLE PRECISION, all four columns NOT NULL, and primary key `(installation_id, signal_name, ts)`.
13. IF an INSERT into `signals` repeats an existing `(installation_id, signal_name, ts)` combination, THEN THE `signals` table SHALL reject the statement with a primary key violation error and leave the table unchanged.

### Requirement 8: Named rules on the configuration table

**User Story:** As a builder, I want every rule to have a stable name, so that the tool layer can turn each rejection into an instruction.

#### Acceptance Criteria

1. THE Config_Table SHALL define the foreign key `config_field_exists` on `(installation_id, source_field)` referencing `source_fields`.
2. THE Config_Table SHALL define the foreign key `config_unit_matches_source` on `(installation_id, source_field, unit)` referencing `source_fields`.
3. THE Config_Table SHALL define the foreign key `config_answers_request` on `(installation_id, request_id)` referencing `signal_requests`.
4. THE Config_Table SHALL define the foreign key `config_service_matches_request` on `(installation_id, request_id, service_id)` referencing `signal_requests`.
5. THE Config_Table SHALL define the foreign key `config_field_in_service` on `(installation_id, service_id, source_field)` referencing `source_fields`.
6. THE Config_Table SHALL define the foreign key `config_type_matches_request` on `(installation_id, request_id, signal_type)` referencing `signal_requests`.
7. THE Config_Table SHALL define the foreign key `config_sampling_requested` on `(installation_id, request_id, sample_s)` referencing `signal_requests`.
8. THE Config_Table SHALL define the foreign key `config_unit_allowed_for_type` on `(signal_type, unit)` referencing `allowed_units`.
9. THE Config_Table SHALL define the UNIQUE constraint `config_one_per_request` on `(run_id, installation_id, request_id)`.
10. THE Config_Table SHALL define the UNIQUE constraint `config_one_per_signal` on `(run_id, installation_id, signal_name)`.
11. THE Config_Table SHALL define the UNIQUE constraint `config_one_per_field` on `(run_id, installation_id, source_field)`.
12. THE Config_Table SHALL define the CHECK constraint `config_approval_signed` requiring `approved_by` to be not null when `status` is `approved` or `active`.
13. THE Config_Table SHALL define the CHECK constraint `collection_configs_signal_name_check` requiring `signal_name` to match the pattern `^[a-z][a-z0-9_]{2,40}$`, which allows a length of 3 to 41 characters.
14. THE Config_Table SHALL define the CHECK constraint `collection_configs_status_check` requiring `status` to be one of `draft`, `needs_review`, `approved`, `rejected` or `active`.
15. IF an insert or update of the Config_Table violates one of the named constraints in criteria 1 to 14, THEN THE Database SHALL reject the statement, report the name of the violated constraint as the CONSTRAINT of the error, and leave the table unchanged by that statement.

### Requirement 9: Rule precedence

**User Story:** As a builder, I want a predictable rule reported when an insert breaks several rules, so that the agent receives the same instruction on every run.

#### Acceptance Criteria

1. WHEN one insert into the Config_Table violates two or more rules, THE Database SHALL reject the insert with one error that names only the violated rule that comes first in the Rule_Precedence, using the constraint name of that rule.
2. THE Config_Table SHALL declare the foreign keys in the order of Requirement 8, criteria 1 to 8, so that WHEN an insert violates several foreign keys, PostgreSQL reports the one that comes first in that order.
3. THE Config_Table SHALL declare the UNIQUE constraints in the order of Requirement 8, criteria 9 to 11, so that WHEN an insert violates several UNIQUE constraints, PostgreSQL reports the one that comes first in that order.
4. WHEN an insert violates both a CHECK constraint and a UNIQUE constraint, THE Database SHALL report the CHECK constraint.
5. WHEN an insert violates both a UNIQUE constraint and a foreign key, THE Database SHALL report the UNIQUE constraint.
6. WHEN an insert violates both the Sampling_Trigger rule and any constraint, THE Database SHALL report the Sampling_Trigger rule with CONSTRAINT `config_sampling_supported`.

### Requirement 10: Sampling trigger

**User Story:** As a builder, I want the sampling interval checked against the range of the source field, so that out-of-range values are rejected with a clear message.

#### Acceptance Criteria

1. THE Sampling_Trigger SHALL fire BEFORE INSERT OR UPDATE OF `source_field`, `sample_s` on the Config_Table, once for each affected row.
2. THE function `check_sampling()` SHALL be declared SECURITY DEFINER with `SET search_path = public`.
3. IF the source field exists in `source_fields` and `sample_s` is less than `min_sample_s` or greater than `max_sample_s` of that field, THEN THE Sampling_Trigger SHALL raise an exception with the message `config_sampling_supported: sample_s % outside % to % for %`, filled with `sample_s`, the minimum, the maximum and the field name in this order, and THE Config_Table SHALL keep the row unchanged. The bounds `min_sample_s` and `max_sample_s` are inclusive, so a value equal to either bound is accepted.
4. WHEN the Sampling_Trigger raises its exception, THE Sampling_Trigger SHALL set ERRCODE to `23514` and CONSTRAINT to `config_sampling_supported`.
5. IF the source field does not exist in `source_fields`, THEN THE Sampling_Trigger SHALL let the row pass without raising an exception so that the foreign keys report the error.
6. WHEN the `approver` Role executes an INSERT or UPDATE that fires the Sampling_Trigger, THE Sampling_Trigger SHALL read `source_fields` with the rights of the function owner, because the `approver` Role cannot read `source_fields`.
7. IF `sample_s` is NULL, THEN THE Sampling_Trigger SHALL let the row pass without raising an exception so that column constraints on the Config_Table report the error.

### Requirement 11: Transition trigger

**User Story:** As an operator, I want status changes limited by role and by state, so that the agent cannot approve and a bait never becomes active.

#### Acceptance Criteria

1. THE Transition_Trigger SHALL fire BEFORE UPDATE on the Config_Table, once for each row updated, using the function `check_transition()`.
2. WHEN an update does not change `status` (old status equals new status), THE Transition_Trigger SHALL let the row pass unchanged and SHALL NOT raise an exception.
3. IF the current user is `agent_writer` and the status change is anything other than `draft` to `needs_review`, THEN THE Transition_Trigger SHALL raise an exception with the message `config_agent_cannot_approve: agent cannot move a configuration from % to %`, filled with the old status and the new status, ERRCODE `42501` and CONSTRAINT `config_agent_cannot_approve`, AND the row SHALL keep its previous values.
4. IF the new status is `active` and the old status is not `approved`, THEN THE Transition_Trigger SHALL raise an exception with the message `config_promote_only_approved: only approved configurations become active`, ERRCODE `23514` and CONSTRAINT `config_promote_only_approved`, AND the row SHALL keep its previous values.
5. IF the new status is `active` and `is_bait` is true, THEN THE Transition_Trigger SHALL raise an exception with the message `config_bait_never_active: bait configurations never become active`, ERRCODE `23514` and CONSTRAINT `config_bait_never_active`, AND the row SHALL keep its previous values.
6. IF more than one of the conditions in criteria 3, 4 and 5 applies to the same update, THEN THE Transition_Trigger SHALL raise only the exception of the lowest-numbered applicable criterion.
7. WHEN the current user is `agent_writer` and the status change is `draft` to `needs_review`, THE Transition_Trigger SHALL let the row pass unchanged and SHALL NOT raise an exception.

### Requirement 12: Signal trigger

**User Story:** As an operator, I want signals accepted only for active configurations, so that no data is stored for a draft.

#### Acceptance Criteria

1. THE Signal_Trigger SHALL fire BEFORE INSERT on `signals` for each inserted row using the function `check_signal_active()`.
2. IF no row of the Config_Table has the same `installation_id` and `signal_name` as the inserted row with `status` equal to `active`, THEN THE Signal_Trigger SHALL abort the INSERT, store no row in `signals`, and raise an exception with the message `signal_needs_active_config: no active configuration for %`, where `%` is replaced by the inserted `signal_name`, ERRCODE `23503` and CONSTRAINT `signal_needs_active_config`.
3. WHEN at least one row of the Config_Table has the same `installation_id` and `signal_name` as the inserted row with `status` equal to `active`, THE Signal_Trigger SHALL let the row pass unchanged so that it is stored in `signals`.
4. IF a Config_Table row matching the inserted row's `installation_id` and `signal_name` exists only with `status` different from `active` (for example `draft`), THEN THE Signal_Trigger SHALL apply the behavior of criterion 2.

### Requirement 13: Roles and grants

**User Story:** As a security-minded builder, I want column-level grants per role, so that the agent can only insert drafts and only the approver approves.

#### Acceptance Criteria

1. THE Schema_File SHALL create the roles `agent_writer` and `approver`, both with the LOGIN attribute.
2. THE Schema_File SHALL create the roles `agent_writer` and `approver` without any PASSWORD clause, so that no role password text appears in the Schema_File.
3. THE Schema_File SHALL grant `agent_writer` SELECT on `installations`, `services`, `source_fields`, `signal_requests`, `allowed_units` and `signals`.
4. THE Schema_File SHALL grant `agent_writer` INSERT on the Config_Table only for the columns `run_id`, `installation_id`, `request_id`, `service_id`, `signal_name`, `signal_type`, `source_field`, `unit`, `sample_s` and `model_id`.
5. THE Schema_File SHALL grant `agent_writer` USAGE on the sequence of `config_id`, SELECT on the Config_Table and UPDATE on the Config_Table only for the column `status`.
6. THE Schema_File SHALL grant `approver` SELECT on the Config_Table and UPDATE on the Config_Table only for the columns `status` and `approved_by`.
7. THE Schema_File SHALL grant `approver` INSERT and SELECT on `review_log`.
8. THE Schema_File SHALL grant `approver` no privilege of any kind on `installations`, `services`, `source_fields`, `signal_requests`, `allowed_units` and `signals`.
9. IF `agent_writer` runs an INSERT on the Config_Table that names any column outside the granted list of criterion 4 (including `config_id`, `status`, `created_by`, `approved_by` and `is_bait`), THEN THE Database SHALL reject the statement with a permission denied error and SHALL leave the Config_Table without a new row.
10. IF `agent_writer` runs an UPDATE on the Config_Table that sets any column other than `status`, THEN THE Database SHALL reject the statement with a permission denied error and SHALL leave the existing row unchanged.
11. IF `approver` runs an INSERT or DELETE on the Config_Table, or an UPDATE that sets any column other than `status` and `approved_by`, THEN THE Database SHALL reject the statement with a permission denied error and SHALL leave the Config_Table unchanged.

### Requirement 14: Applying the schema

**User Story:** As a builder, I want one script that applies the schema on either backend, so that the setup is a single action.

#### Acceptance Criteria

1. WHEN the Schema_Applier starts, THE Schema_Applier SHALL connect to the Database as the `admin` Role.
2. IF the connection as the `admin` Role fails, THEN THE Schema_Applier SHALL run no statement, exit with a non-zero status, and report an error indicating the connection failure.
3. WHEN the Schema_Applier reads the Schema_File, THE Schema_Applier SHALL split it into single statements, because the Data API accepts one statement per call.
4. THE Schema_File SHALL separate statements with a separator line that cannot be confused with text inside a comment or a function body, and the Schema_Applier SHALL split only on that line.
5. WHEN the Schema_Applier runs the statements, THE Schema_Applier SHALL run each statement in the order of the Schema_File, one statement per call, and SHALL start a statement only after the previous statement has completed successfully.
6. WHERE the environment variable `OPSMEM_LOCAL_PG` is set, THE Schema_Applier SHALL set the role passwords to the local logins of Requirement 3.
7. WHERE the environment variable `OPSMEM_LOCAL_PG` is not set, THE Schema_Applier SHALL set the role passwords from the role secrets.
8. IF a statement fails, THEN THE Schema_Applier SHALL stop without running later statements, exit with a non-zero status, and report the text of the failing statement, its position in the Schema_File, and the database error.
9. IF the schema already exists in the Database, THEN THE Schema_Applier SHALL apply nothing, print an error message stating that the database is not empty and how to recreate it (`scripts/local_db.sh up` for Local_Backend, a new stack for Aurora_Backend), and exit with a non-zero status.

### Requirement 15: Loading the catalog

**User Story:** As a builder, I want the catalog loaded from the manual files, so that the database content comes from the input data and not from code.

#### Acceptance Criteria

1. WHEN the schema has been applied and the Catalog_Loader is run, THE Catalog_Loader SHALL load exactly one installation with `installation_id` `install-07` and name `Course platform, installation 07`.
2. WHEN the Catalog_Loader is run, THE Catalog_Loader SHALL read the file at `OPENAPI`, pass its text to `parse_services`, and load one service for each tag in the OpenAPI_Schema, using the tag name as `service_id` and the tag description as `name`.
3. WHEN the Catalog_Loader is run, THE Catalog_Loader SHALL read the file at `OPENAPI`, pass its text to `parse_fields`, and load one field for each property of the response schema of each GET stats operation in the OpenAPI_Schema, assign the field to the service whose `service_id` equals the first tag of that operation, and store the `x-unit`, `x-sampling-min-s` and `x-sampling-max-s` values of the property.
4. WHEN the Catalog_Loader is run, THE Catalog_Loader SHALL read the file at `MANUAL`, pass its text to `parse_requests`, and load one request for each data row of the table under the `## Requests from operations` heading in the Manual, excluding the header and separator rows.
5. WHEN loading finishes successfully, THE Catalog_Loader SHALL print the number of installations, services, fields and requests loaded, each labelled with its entity name, and exit with a success status.
6. THE Catalog_Loader SHALL leave the files in `manuals/` byte-for-byte unchanged.
7. THE Catalog_Loader SHALL load into an empty catalog as part of the first successful application of the schema, and SHALL insert every row without upserting.
8. IF the schema has not been applied, a file in `manuals/` is missing or unreadable, or the Manual has no `## Requests from operations` heading, THEN THE Catalog_Loader SHALL print an error message naming the missing item and exit with a failure status.
9. IF a field property lacks `x-unit`, `x-sampling-min-s` or `x-sampling-max-s`, or a table row has fewer columns than the table header, or a GET stats operation has no tag, THEN THE Catalog_Loader SHALL print an error message naming the offending property, row or operation and exit with a failure status.

### Requirement 16: Manual parsers

**User Story:** As a builder, I want deterministic parsers of the manual and the OpenAPI schema, so that the same input always gives the same catalog.

#### Acceptance Criteria

1. THE Manual_Parser SHALL provide the functions `parse_services(openapi_text)`, `parse_fields(openapi_text)` and `parse_requests(manual_text)`, each taking the text of a file as a string and returning a list, and SHALL read no file itself.
2. THE Manual_Parser SHALL provide the constants `MANUAL` and `OPENAPI` holding the paths of the Manual and the OpenAPI_Schema, which the Catalog_Loader reads to obtain the text it passes to the parsers.
3. WHEN the same input text is parsed twice, THE Manual_Parser SHALL return results that compare equal element by element, with the same number of elements and the same element order, for each of `parse_services`, `parse_fields` and `parse_requests`.
4. WHEN a schema in the `openapi_text` is given by `$ref`, THE Manual_Parser SHALL resolve the reference before reading its properties.
5. IF a `$ref` in the `openapi_text` points to a target that does not exist, THEN THE Manual_Parser SHALL raise an error that names the unresolved reference and SHALL return no partial result.
6. IF the section `## Requests from operations` is missing from the `manual_text`, THEN THE Manual_Parser SHALL raise an error that names the missing section and SHALL return no partial result.
7. IF the section `## Requests from operations` in the `manual_text` contains no request rows, THEN THE Manual_Parser SHALL raise an error that names the section and states that no rows were found.
8. IF the `openapi_text` contains no tags or no GET stats responses, THEN THE Manual_Parser SHALL raise an error that states which element is missing, tags or GET stats responses.

### Requirement 17: Unit tests of the parsers

**User Story:** As a builder, I want unit tests without a database, so that I can verify the catalog parsing offline.

#### Acceptance Criteria

1. THE test suite SHALL run the parser tests (`parse_services`, `parse_fields`, `parse_requests`) with no database connection, no network access and no AWS access, reading at most the OpenAPI_Schema and the Manual from local files and passing their text to the parsers.
2. WHEN `parse_services` runs on the text of the OpenAPI_Schema, THE test suite SHALL verify that it returns exactly 5 services in the order `media`, `encoding`, `api`, `classes`, `queue`.
3. WHEN `parse_fields` runs on the text of the OpenAPI_Schema, THE test suite SHALL verify that it returns exactly 9 fields.
4. WHEN `parse_fields` runs on the text of the OpenAPI_Schema, THE test suite SHALL verify that the field `api_p95` has unit `s`, minimum sampling 10 seconds and maximum sampling 300 seconds.
5. WHEN `parse_fields` runs on the text of the OpenAPI_Schema, THE test suite SHALL verify that the field `mst_wr_lat` has unit `ms`.
6. WHEN `parse_requests` runs on the text of the Manual, THE test suite SHALL verify that it returns exactly 6 requests and that request `R5` has a sampling of 60 seconds.
7. WHEN `parse_requests` runs on the text of the Manual, THE test suite SHALL verify that the service of each of the 6 requests is equal to one of the 5 service names returned by `parse_services`.
8. WHEN `parse_fields` runs on a small inline OpenAPI text containing a `$ref` whose target does not exist, THE test suite SHALL verify that the parser raises an error whose message names the unresolved reference.
9. WHEN `parse_requests` runs on a small inline Manual text without the section `## Requests from operations`, THE test suite SHALL verify that the parser raises an error whose message names that section.
10. WHEN `parse_requests` runs on a small inline Manual text whose section `## Requests from operations` contains no request rows, THE test suite SHALL verify that the parser raises an error whose message names that section and states that no rows were found.
11. WHEN `parse_services` runs on a small inline OpenAPI text with no tags, and `parse_fields` runs on a small inline OpenAPI text with no GET stats responses, THE test suite SHALL verify that each parser raises an error whose message names the missing element, tags or GET stats responses respectively.
12. THE test suite SHALL test the pure logic (the parsers, the Local_Backend parameter conversion, the `host:port` parsing, the retry schedule of Requirement 2, `check_config` and the statement splitting of Requirement 14) with property-based tests where the design document designates them, and with example tests otherwise.
13. IF any parser test assertion fails, THEN THE test suite SHALL report the test as failed, SHALL identify the parser function and the expected and actual values, and SHALL finish with a non-zero exit status.

### Requirement 18: Tests of the database error

**User Story:** As a builder, I want tests that prove the database error keeps the native text on both backends, so that the tool layer and the trace receive the exact error.

#### Acceptance Criteria

1. WHEN the Local_Backend runs a statement that violates a constraint with a DETAIL line, THE test suite SHALL verify that `str(err)` equals `str(native)`, that `err.__cause__` is the Native_Exception, and that `err.sqlstate` and `err.constraint` equal the values reported by PostgreSQL.
2. THE test of criterion 1 SHALL run against the local Docker PostgreSQL.
3. WHEN the Aurora_Backend receives from a Fake_Data_API_Client a `BadRequestException` whose message includes a DETAIL line, THE test suite SHALL verify that `str(err)` equals `str(native)`, that `err.__cause__` is the Native_Exception, and that `err.sqlstate` and `err.constraint` are None, or are set when the exception reports them.
4. THE test of criterion 3 SHALL use no network access and no AWS access.

### Requirement 19: Tests of the database rules

**User Story:** As a builder, I want each database rule verified by example tests on the local database, so that every rule and its boundaries are checked in a readable, repeatable way.

#### Acceptance Criteria

1. THE test suite SHALL implement every Rule_Test as an example test run against the local Database, and SHALL NOT implement any Rule_Test as a property-based test with generated inputs.
2. THE test suite SHALL provide one Rule_Test for each rule of Requirements 7 to 13, each Rule_Test checking the rule by the constraint name or error code defined in that requirement.
3. WHERE a rule has a numeric or length boundary (sampling bounds, signal name length 3 and 41 characters), THE test suite SHALL include in the Rule_Test one case at each side of each boundary and one case on each boundary value.
4. WHERE a rule applies to a Role, THE Rule_Test SHALL run the statement with the connection of that Role.
5. IF a Rule_Test assertion fails, THEN THE test suite SHALL report the test as failed, SHALL identify the rule and the expected and actual constraint name, and SHALL finish with a non-zero exit status.

### Requirement 20: Test suite selection and container isolation

**User Story:** As a builder, I want the tests that start and stop the local container kept apart from the tests that use it, so that they never break each other.

#### Acceptance Criteria

1. THE test suite SHALL mark the tests of the Local_DB_Script with the marker `docker_script`, and SHALL mark the tests that use the shared container `opsmem-pg` with the marker `local_pg`.
2. THE test suite SHALL run the tests marked `docker_script` only WHEN they are explicitly selected, and SHALL NOT run them in a default run.
3. IF a run selects both the marker `docker_script` and the marker `local_pg`, THEN THE test suite SHALL stop before running any test and report that both markers use the container `opsmem-pg` and cannot run together.
