# Requirements Document

## Introduction

This spec covers the agent that proposes collection configurations as drafts, one per request, with Strands Agents on Amazon Bedrock. It adds the function `agent_input` to `opsmem/manual.py`, the module `opsmem/writer.py` (the run state, the two tools, the agent and the run loop with its follow-ups), the script `scripts/run_writer.py`, the dependency `strands-agents==1.64.0`, and the README step "### 4. One writer run". The rejection text comes from `opsmem/errors.py` of the instructive-rejections spec. The database rules come from the catalog-schema spec.

The agent reads only the request texts. Services, fields, units and sampling are learned from the rejections. Strings, names and numbers in this document are an external contract. The model reads these strings, so changing one changes what the agent learns: keep them exactly.

Out of scope: the experiment over several models, the review of drafts, and the AWS deployment.

## Glossary

- **Writer_Module**: The module `opsmem/writer.py`.
- **Agent_Input_Builder**: The function `agent_input(root, installation_id="install-07")` of the module `opsmem/manual.py`.
- **Run_Context**: The class `RunContext(run_id, installation_id, model_id, mode, db)` of the Writer_Module. The five arguments are positional in this order.
- **Run_Lock**: The one lock per run, held by the Run_Context, that serializes the body of the Propose_Tool.
- **Propose_Tool**: The tool `propose_config` returned by the Tool_Factory.
- **Flag_Tool**: The tool `flag_for_review` returned by the Tool_Factory.
- **Tool_Factory**: The function `make_tools(ctx)` of the Writer_Module. It returns the list `[propose_config, flag_for_review]`.
- **Run_Runner**: The function `run_writer(ctx, task) -> dict` of the Writer_Module.
- **Run_Script**: The script `scripts/run_writer.py`.
- **Run_Mode**: One of the strings `raw` and `instructive`, held in the field `mode` of the Run_Context. It is the Mode of the instructive-rejections spec.
- **Stopped_Run**: A run whose escalation reason is not none.
- **Escalation_Reason**: The text that says why a run was stopped, or none while the run is not stopped. The first reason set stays.
- **Request_List**: The rows of the table "Requests from operations" in the manual, as returned by `parse_requests`.
- **Open_Request**: A request of the installation that has no row in `collection_configs` for the run id of the Run_Context.
- **Follow_Up**: A message sent to the agent after its first answer, listing the Open_Requests.
- **Draft**: A row of `collection_configs` with the status `draft`.
- **Trace_Entry**: The record `{ts, call, result, db_message}` that the Propose_Tool appends to the trace for every call.
- **Rejection_Count**: The number of database rejections of the same Rule on the same request id in one run.
- **Database**: The PostgreSQL database named `opsmemory`, as defined in the catalog-schema spec.
- **Database_Object**: The object returned by `connect(role)`, as defined in the catalog-schema spec. The Run_Context holds the one of the role `agent_writer`.
- **Errors_Module**: The module `opsmem/errors.py` of the instructive-rejections spec, with `classify`, `render` and `valid_values`.
- **Rule**: A key of the `INSTRUCTIONS` table of the Errors_Module, or the string `unknown`.
- **Manual**: The file `manuals/course-platform-install-07.md`, named by the constant `MANUAL` of `opsmem/manual.py`.
- **Project**: The Python project defined by `pyproject.toml`.
- **Lock_File**: The file `uv.lock`.
- **Fake_Database**: A test stand-in for the Database_Object that records every statement and needs no server.
- **Fake_Agent**: A test stand-in for the Strands agent that needs no model and no network.
- **Readme**: The file `README.md`, which already exists.

## Requirements

### Requirement 1: Strands dependency

**User Story:** As a builder, I want the agent library pinned in the project, so that every checkout installs the same version.

#### Acceptance Criteria

1. THE Project SHALL declare `strands-agents==1.64.0` in the list `dependencies` of the table `[project]` of `pyproject.toml`, next to `boto3==1.43.127` and `pyyaml==6.0.3`.
2. THE Lock_File SHALL record the package `strands-agents` at version 1.64.0.
3. WHEN the Writer_Module is imported, THE Writer_Module SHALL import Strands normally, with no stand-in for the Strands package.

### Requirement 2: Agent input

**User Story:** As a builder, I want the agent to read only the request texts, so that every fact about services, fields, units and sampling must come from the rejections.

#### Acceptance Criteria

1. WHEN `agent_input(root, installation_id)` is called, THE Agent_Input_Builder SHALL read the Manual under `root` and parse it with `parse_requests`.
2. THE Agent_Input_Builder SHALL return a string whose first line is `Installation: <installation_id>`, whose second line is `Requests:`, and whose following lines are one line per request in the order of the Request_List.
3. THE Agent_Input_Builder SHALL write each request line as `<request_id>: <request_text>`.
4. THE Agent_Input_Builder SHALL join the lines with the character `\n` and SHALL end the string without a trailing newline.
5. WHEN `agent_input(root)` is called without `installation_id`, THE Agent_Input_Builder SHALL use the value `install-07`.
6. THE Agent_Input_Builder SHALL leave service ids, signal types, field names, units and sampling seconds out of the returned string.
7. IF the Manual has no section "Requests from operations", THEN THE Agent_Input_Builder SHALL let the `ManualError` of `parse_requests` reach the caller.

### Requirement 3: Agent and model

**User Story:** As a builder, I want the agent built in one fixed way, so that two runs differ only in the model and the Run_Mode.

#### Acceptance Criteria

1. THE Writer_Module SHALL define the constant `SYSTEM_PROMPT` with the value `Configure one signal per request with propose_config. If a call is rejected, use the valid values in the rejection and call the tool again. Stop only when every request is saved.`
2. THE Writer_Module SHALL build the model as `BedrockModel(model_id=<model_id of the Run_Context>, region_name=os.environ["AWS_REGION"], temperature=0)`, with keyword arguments only and no other argument.
3. THE Writer_Module SHALL build the agent as `Agent(model=<the model>, tools=make_tools(ctx), system_prompt=SYSTEM_PROMPT, callback_handler=None)`, with no other argument.
4. THE Writer_Module SHALL read the region from the environment variable `AWS_REGION` and SHALL contain no literal region name.
5. IF the environment variable `AWS_REGION` is not set, THEN THE Writer_Module SHALL let the `KeyError` of the lookup reach the caller.

### Requirement 4: Run state

**User Story:** As a builder, I want all state of a run in one object, so that the result of a run can be built from it and tests can inspect it.

#### Acceptance Criteria

1. THE Run_Context SHALL accept `run_id`, `installation_id`, `model_id`, `mode` and `db` as positional arguments in this order.
2. THE Run_Context SHALL hold the Rejection_Count per pair of request id and Rule, starting empty.
3. THE Run_Context SHALL hold the number of tool calls, starting at 0.
4. THE Run_Context SHALL hold the Escalation_Reason, starting as none.
5. THE Run_Context SHALL hold the list of flagged reasons, starting empty.
6. THE Run_Context SHALL hold the trace, starting empty.
7. THE Run_Context SHALL hold the last raw Database message, starting as none.
8. THE Run_Context SHALL hold one Run_Lock.
9. THE Writer_Module SHALL define the constants `MAX_TOOL_CALLS = 40`, `ESCALATE_AFTER = 3` and `FOLLOW_UPS = 2`.

### Requirement 5: Tool specifications

**User Story:** As a builder, I want the tool specs the model receives fixed to the letter, so that every model sees the same tools.

#### Acceptance Criteria

1. THE Tool_Factory SHALL return a list of two tools, the Propose_Tool first and the Flag_Tool second.
2. THE Propose_Tool SHALL have the name `propose_config` and the description `Propose one signal configuration as a draft.`
3. THE Propose_Tool SHALL declare seven parameters, in this order, all of type string and all required: `request_id` with the description `request id`, `service_id` with `service id`, `signal_name` with `signal name`, `signal_type` with `signal type`, `source_field` with `source field`, `unit` with `unit`, and `sample_seconds` with `sampling interval in seconds`.
4. THE Flag_Tool SHALL have the name `flag_for_review` and the description `Ask a person to decide something you cannot.`
5. THE Flag_Tool SHALL declare one parameter `reason`, of type string and required, with the description `what you cannot decide`.
6. WHEN the Flag_Tool is called, THE Flag_Tool SHALL append the reason to the flagged reasons of the Run_Context.
7. WHEN the Flag_Tool is called, THE Flag_Tool SHALL reply `Noted for a person. Continue with the signals you can configure.`

### Requirement 6: Proposing a configuration

**User Story:** As a builder, I want every proposal either saved as a draft or answered with a rejection, so that the agent learns from the database and a person reviews what is saved.

#### Acceptance Criteria

1. WHEN the Propose_Tool is called, THE Propose_Tool SHALL add one to the number of tool calls while it holds the Run_Lock, as the first step of its body, so that the count and the check against `MAX_TOOL_CALLS` are atomic with respect to the other calls of the run.
2. WHEN the number of tool calls exceeds `MAX_TOOL_CALLS` and the run is not a Stopped_Run, THE Propose_Tool SHALL stop the run with the Escalation_Reason `more than 40 tool calls`.
3. WHILE the run is a Stopped_Run, THE Propose_Tool SHALL reply `STOPPED. This run is waiting for a person (<reason>). Do not propose more configurations.`, where `<reason>` is the Escalation_Reason, and SHALL send no statement to the Database.
4. WHEN the run is not a Stopped_Run, THE Propose_Tool SHALL insert one row into `collection_configs` through the Database_Object of the Run_Context, with the columns `run_id`, `installation_id`, `request_id`, `service_id`, `signal_name`, `signal_type`, `source_field`, `unit`, `sample_s` and `model_id`.
5. THE Propose_Tool SHALL pass `sample_seconds` to the insert as a string and SHALL convert it with `CAST(:sample_seconds AS integer)` in the SQL text, so that a value that is not a number is a rejection of the Database and not a Python error.
6. WHEN the insert succeeds, THE Propose_Tool SHALL reply `Saved as draft: <signal_name> <- <source_field> (<unit>, every <sample_seconds> s). A person will review it.`
7. IF the insert raises the exception held in `DatabaseError`, THEN THE Propose_Tool SHALL store `str(err)` as the last raw Database message and SHALL classify the Rule with `classify` of the Errors_Module.
8. IF the insert raises the exception held in `DatabaseError`, THEN THE Propose_Tool SHALL add one to the Rejection_Count of the pair of `request_id` and the Rule.
9. IF the Rejection_Count reaches `ESCALATE_AFTER`, THEN THE Propose_Tool SHALL stop the run with the Escalation_Reason `rule <rule> rejected 3 times`.
10. IF the Rejection_Count reaches `ESCALATE_AFTER`, THEN THE Propose_Tool SHALL change the status of the Drafts of this run from `draft` to `needs_review`.
11. IF the Rejection_Count reaches `ESCALATE_AFTER`, THEN THE Propose_Tool SHALL reply `STOPPED. The same rule rejected 3 times; a person will take over. Stop now.`
12. IF the insert raises the exception held in `DatabaseError` and the Rejection_Count is below `ESCALATE_AFTER`, THEN THE Propose_Tool SHALL reply with the text that `render` of the Errors_Module returns for the Run_Mode, the Rule, the raw message and the valid values.
13. WHILE the Run_Mode is `instructive`, THE Propose_Tool SHALL read the valid values with `valid_values` of the Errors_Module, using the Database_Object of the Run_Context.
14. WHILE the Run_Mode is `raw`, THE Propose_Tool SHALL pass an empty list of valid values to `render` and SHALL send no lookup statement.
15. THE Propose_Tool SHALL take the rejection text from `classify`, `valid_values` and `render` of the Errors_Module and SHALL contain no copy of the Instruction table.

### Requirement 7: Trace

**User Story:** As a builder, I want every proposal recorded with the raw database message, so that I can read what the model saw and what the database said.

#### Acceptance Criteria

1. WHEN the Propose_Tool is called, THE Propose_Tool SHALL append one Trace_Entry to the trace of the Run_Context, whatever the outcome of the call.
2. THE Trace_Entry SHALL have the keys `ts`, `call`, `result` and `db_message`.
3. THE Trace_Entry SHALL hold in `ts` the UTC time of the call as an ISO 8601 string with milliseconds.
4. THE Trace_Entry SHALL hold in `call` the arguments of the call.
5. THE Trace_Entry SHALL hold in `result` the reply returned to the agent.
6. IF the call ended in a Database rejection, THEN THE Trace_Entry SHALL hold in `db_message` the raw Database message, whatever text the agent was shown.
7. IF the call did not end in a Database rejection, THEN THE Trace_Entry SHALL hold none in `db_message`.

### Requirement 8: Concurrent tool calls

**User Story:** As a builder, I want concurrent tool calls of one run to behave as if they came one after the other, so that a run stopped by one call is stopped for all calls.

#### Acceptance Criteria

1. THE Propose_Tool SHALL hold the Run_Lock of the Run_Context during its whole body: the count of the call, the stop check, the insert, the lookup of valid values, the escalation decision, the change of status of the Drafts and the append to the trace.
2. WHEN several calls of the Propose_Tool run concurrently in one run, THE Propose_Tool SHALL serialize them so that the stop check, the insert and the escalation decision of one call are atomic with respect to the other calls.
3. WHILE the run is a Stopped_Run, THE Propose_Tool SHALL send no statement to the Database for any call, including calls that were started before the run was stopped.
4. WHEN a concurrent call triggers the escalation, THE Propose_Tool SHALL answer every later call with the STOPPED reply of Requirement 6.3.
5. THE Flag_Tool SHALL append to the flagged reasons while it holds the Run_Lock.

### Requirement 9: Follow-ups and the result of a run

**User Story:** As a builder, I want the run loop to ask again when requests are open, and to return one result dictionary, so that runs can be compared on the same keys.

#### Acceptance Criteria

1. WHEN the Run_Runner is called, THE Run_Runner SHALL send `task` to the agent as the first message.
2. WHILE the run is not a Stopped_Run and the number of Follow_Ups sent is below `FOLLOW_UPS`, WHEN the agent has answered and at least one Open_Request exists, THE Run_Runner SHALL send the Follow_Up `Not configured yet: <ids joined by ", ">. Call propose_config for each.`
3. THE Run_Runner SHALL find the Open_Requests with a database query on the requests of the installation and the rows of `collection_configs` of the run, and SHALL make no judgment of the model.
4. THE Run_Runner SHALL list the ids of the Open_Requests in ascending order in the Follow_Up.
5. WHEN `FOLLOW_UPS` Follow_Ups have been sent, the agent has answered and at least one Open_Request exists, THE Run_Runner SHALL stop the run with the Escalation_Reason `agent stopped with requests not configured: <ids joined by ", ">`.
6. WHEN no Open_Request exists after an answer, THE Run_Runner SHALL end the loop without sending a Follow_Up.
7. WHILE the run is a Stopped_Run, THE Run_Runner SHALL send no Follow_Up.
8. THE Run_Runner SHALL return a dictionary with exactly the keys `tool_calls`, `rejections`, `follow_ups`, `escalated`, `flagged`, `trace`, `input_tokens`, `output_tokens` and `final_text`.
9. THE Run_Runner SHALL give `rejections` one key `<request_id>:<rule>` per Rejection_Count, with the count as value.
10. THE Run_Runner SHALL give `escalated` the Escalation_Reason, or none when the run was not stopped.
11. THE Run_Runner SHALL give `input_tokens` and `output_tokens` the accumulated usage of the result of the last answer of the agent, and the value 0 when that usage is missing.
12. THE Run_Runner SHALL give `final_text` the text of the last answer, cut to at most 2000 characters.

### Requirement 10: Run script

**User Story:** As a builder, I want one command that checks the configuration, runs the agent once and saves the result, so that a run can be repeated and compared.

#### Acceptance Criteria

1. WHEN the Run_Script starts, THE Run_Script SHALL check the configuration with `check_config` before it connects to the Database or calls a model.
2. THE Run_Script SHALL accept the option `--model <id>` and the option `--mode raw|instructive`.
3. WHERE the option `--mode` is not given, THE Run_Script SHALL use the Run_Mode `instructive`.
4. IF the option `--mode` has a value other than `raw` or `instructive`, THEN THE Run_Script SHALL stop with an error before it connects to the Database.
5. THE Run_Script SHALL set the run id to `single-<mode>-<unix seconds>`, where `<unix seconds>` is the integer Unix time at the start of the run.
6. THE Run_Script SHALL run the agent once on the installation `install-07`, with the Database_Object of the role `agent_writer` and the task returned by `agent_input`.
7. THE Run_Script SHALL print one line of JSON per Trace_Entry, in the order of the trace.
8. THE Run_Script SHALL print after the trace one summary line with the run id, the number of tool calls, the number of Follow_Ups, the Escalation_Reason and the input and output tokens.
9. THE Run_Script SHALL save the result dictionary of the Run_Runner to the file `results/<run_id>.json`.

### Requirement 11: Tests without a model and without a network

**User Story:** As a builder, I want the rules of the agent verified without a model, so that every run of the test suite is free and repeatable.

#### Acceptance Criteria

1. THE test suite SHALL test the Writer_Module with a Fake_Database and a Fake_Agent, with no model call and no network access.
2. THE test suite SHALL include a test that three rejections of the same Rule on the same request id stop the run with the Escalation_Reason `rule <rule> rejected 3 times`, move the Drafts of the run to `needs_review` and reply with the STOPPED text of Requirement 6.11.
3. THE test suite SHALL include a test that the 41st call stops the run with the Escalation_Reason `more than 40 tool calls` and sends no statement to the Database.
4. THE test suite SHALL include a test of the Follow_Up text and of the stop after 2 Follow_Ups with Open_Requests left.
5. THE test suite SHALL include a test with several concurrent calls of the Propose_Tool in which one call triggers the escalation, and SHALL check that no call after the escalation reaches the Database.
6. THE test suite SHALL include a test that the string returned by `agent_input` for the Manual contains no field name, no unit, no sampling value and no service id.
7. THE test suite SHALL include a test that the tool specs of the Propose_Tool and the Flag_Tool have the names, descriptions, parameter order, parameter descriptions, types and required lists of Requirement 5.
8. THE test suite SHALL include a test that the model is built with exactly the keyword arguments `model_id`, `region_name` and `temperature`, and the agent with exactly `model`, `tools`, `system_prompt` and `callback_handler`.
9. THE test suite SHALL include one test marked `local_pg` that runs the Propose_Tool against the local Database as `agent_writer`.

### Requirement 12: README step "One writer run"

**User Story:** As a reader of the article, I want to see one real writer run, so that I can see what the agent did and what the database said.

#### Acceptance Criteria

1. WHEN the README task runs, THE Readme SHALL receive the addition without any change to the existing text of the Readme.
2. THE Readme SHALL contain, under the heading `## Part 1: the database says no`, the step with the heading `### 4. One writer run`. The heading `## Part 1: the database says no` stays unchanged, because the article links the anchor `#part-1-the-database-says-no`.
3. THE step SHALL show the command that runs the Run_Script, the first lines of the real trace and the real summary line.
4. THE Readme SHALL receive, in the section `## Run it locally, paying only for the model`, the command that runs the Run_Script.
5. THE README task SHALL call no model. Before it writes, THE README task SHALL ask the user to paste the real trace and the real summary line produced by the Run_Script.
6. THE step SHALL be written in the first person.
7. THE step SHALL describe only behavior that the code implements.
8. THE README task SHALL be the last task before the final checkpoint.
