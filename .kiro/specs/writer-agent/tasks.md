# Implementation Plan: writer-agent

## Overview

The implementation language is Python 3.12, as in the rest of the repository. The plan builds the agent in this order: the pinned Strands dependency, then `agent_input` in `opsmem/manual.py`, then the run state and the tools in `opsmem/writer.py`, then the run loop, then `scripts/run_writer.py`, then one integration test on the local database, and last the README step. Each increment ends with its tests. The unit tests use a fake database and a fake agent and call no model. Strands is installed and imported normally. The README task calls no model: it stops and asks the user to paste the real trace and the real summary line (Requirement 12.5). The README task is the last task before the final checkpoint, because it shows real output of the finished code.

## Tasks

- [x] 1. Strands dependency
  - [x] 1.1 Add `strands-agents==1.64.0` to the dependencies and refresh `uv.lock`
    - Edit `pyproject.toml`: add `"strands-agents==1.64.0",` to `dependencies` in `[project]`, next to `boto3==1.43.127` and `pyyaml==6.0.3`
    - Refresh the lock file with `uv lock`, then run `uv sync --group dev --group local`
    - Create `tests/test_writer_setup.py` with a test that reads `pyproject.toml` and checks the three pinned entries, and a test that `uv.lock` records `strands-agents` at version 1.64.0
    - Run `uv run pytest` and check that the offline suite still passes
    - Finish: commit as `feat(writer-agent): 1.1 add strands-agents dependency`, push, show `git log --oneline -3`, then stop and wait for the user
    - _Requirements: 1.1, 1.2_

- [x] 2. Agent input
  - [x] 2.1 Implement `agent_input` in `opsmem/manual.py`
    - Add `agent_input(root, installation_id="install-07")` as in the design: read `MANUAL` under `root`, reuse `parse_requests`, build `Installation: <id>`, `Requests:` and one `<request_id>: <request_text>` line per request, join with `\n`, no trailing newline
    - Import `Path` and update the module docstring so it says the parsers read no file and `agent_input` is the one function that reads `MANUAL`
    - Do not copy the table parser and do not read service ids, signal types or sampling
    - Finish: commit as `feat(writer-agent): 2.1 implement agent_input in opsmem/manual.py`, push, show `git log --oneline -3`, then stop and wait for the user
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 2.2 Write unit tests for `agent_input`
    - Create `tests/test_agent_input.py`
    - `agent_input(ROOT)` on the real Manual equals the expected text: the first line `Installation: install-07`, the line `Requests:` and the six request lines, written by hand in the test
    - The result has no trailing newline and does not contain the field names, units, sampling values or service ids of `install-07` (lists written by hand in the test)
    - `agent_input(ROOT, "install-99")` changes only the first line
    - A manual text without the heading `## Requests from operations` raises `ManualError`
    - Finish: commit as `test(writer-agent): 2.2 write unit tests for agent_input`, push, show `git log --oneline -3`, then stop and wait for the user
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 11.6_

  - [x] 2.3 Write property test for the shape of the agent input
    - File `tests/test_agent_input.py`, `hypothesis`, at least 100 examples, tag comment `# Feature: writer-agent, Property <n>: <text>`
    - Generate request tables, write the Manual text into `tmp_path / MANUAL`, compare with an oracle that joins the lines
    - **Property 1: Agent input has the fixed shape**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
    - Finish: commit as `test(writer-agent): 2.3 write property test for the shape of the agent input`, push, show `git log --oneline -3`, then stop and wait for the user

  - [x] 2.4 Write property test for what the agent input hides
    - File `tests/test_agent_input.py`, marker values in the service, signal type and sampling cells that the id and text alphabets exclude
    - **Property 2: Agent input hides everything but the request texts**
    - **Validates: Requirements 2.6**
    - Finish: commit as `test(writer-agent): 2.4 write property test for what the agent input hides`, push, show `git log --oneline -3`, then stop and wait for the user

- [x] 3. Run state and tools
  - [x] 3.1 Create `opsmem/writer.py` with the constants and `RunContext`
    - Define `SYSTEM_PROMPT`, `MAX_TOOL_CALLS = 40`, `ESCALATE_AFTER = 3`, `FOLLOW_UPS = 2`, `MAX_FINAL_TEXT = 2000`
    - Define the dataclass `RunContext(run_id, installation_id, model_id, mode, db)` with positional fields in this order, and the fields `rejections`, `tool_calls`, `escalation_reason`, `flagged`, `trace`, `last_db_message` and `lock` (a `threading.Lock`)
    - Import `Agent` and `tool` from `strands` and `BedrockModel` from `strands.models`, with no stand-in
    - Add a module docstring that says the Database_Object must be the `agent_writer` one
    - Finish: commit as `feat(writer-agent): 3.1 create opsmem/writer.py with the constants and runcontext`, push, show `git log --oneline -3`, then stop and wait for the user
    - _Requirements: 1.3, 3.1, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9_

  - [x] 3.2 Implement `make_tools`, `propose_config` and `flag_for_review`
    - Add `INSERT_SQL` with `CAST(:sample_seconds AS integer)` and `MOVE_SQL`, the helpers `_stop`, `_now`, `_propose` and `_rejected` as in the design
    - The docstrings and signatures of the two tools must yield exactly the tool specs of Requirement 5: description in the first paragraph only, seven string parameters in order, the `Args:` descriptions of the requirement
    - Hold `ctx.lock` during the whole body of `propose_config`; the call count is incremented inside the lock as its first step, never before it: call count, stop check, insert, lookup, escalation, status update and trace append
    - Call `classify`, `valid_values` and `render` from `opsmem.errors`; read the valid values only in `instructive` mode; do not copy the Instruction table
    - Catch only `ctx.db.DatabaseError`
    - `flag_for_review` appends the reason under the lock and replies `Noted for a person. Continue with the signals you can configure.`
    - Finish: commit as `feat(writer-agent): 3.2 implement make_tools, propose_config and flag_for_review`, push, show `git log --oneline -3`, then stop and wait for the user
    - _Requirements: 3.1, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 6.11, 6.12, 6.13, 6.14, 6.15, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 3.3 Write the test doubles and unit tests for the tools
    - Create `tests/writer_fakes.py` with `FakeDatabase` (records `(sql, params)` under an internal lock, accepts or rejects inserts by a function, serves the lookup and open-request statements from a small catalog, optional delay per insert) and `FakeAgent` (records messages, runs a function that calls the real tools, returns an object with `metrics.accumulated_usage` and `__str__`)
    - Create `tests/test_writer_tools.py` with example tests: tool specs (names, descriptions, parameter order, parameter descriptions, `string` types, required list), `RunContext` defaults, the three constants, `SYSTEM_PROMPT` literal
    - Three rejections of one rule on `R1` stop the run with `rule <rule> rejected 3 times`, send one status update and give the STOPPED reply
    - The 41st call stops the run with `more than 40 tool calls` and sends no statement
    - Concurrent calls (more than 40 threads released together) leave `tool_calls` equal to the number of calls, and exactly 40 reach the Database
    - `raw` mode sends no lookup statement; `instructive` mode sends the lookup of the rule
    - A non-numeric `sample_seconds` reaches the Fake_Database as text and the rejection is classified `integer_input`
    - Several threads calling `flag_for_review` keep every reason
    - The source of `opsmem/writer.py` contains neither `Unknown source_field` nor `us-east-1`
    - Finish: commit as `test(writer-agent): 3.3 write the test doubles and unit tests for the tools`, push, show `git log --oneline -3`, then stop and wait for the user
    - _Requirements: 3.1, 3.4, 4.1 to 4.9, 5.1 to 5.5, 5.7, 6.2, 6.5, 6.13, 6.14, 6.15, 8.5, 11.1, 11.2, 11.3, 11.7_

  - [x] 3.4 Write property test for flagging
    - File `tests/test_writer_tools.py`, `hypothesis`, at least 100 examples, tag comment `# Feature: writer-agent, Property <n>: <text>`
    - **Property 3: Flagging records the reason and gives the fixed reply**
    - **Validates: Requirements 5.6, 5.7**
    - Finish: commit as `test(writer-agent): 3.4 write property test for flagging`, push, show `git log --oneline -3`, then stop and wait for the user

  - [x] 3.5 Write property test for the call cap
    - Create `tests/test_writer_stop.py`, generate the number of calls from 1 to 60 on a Fake_Database that accepts every insert
    - **Property 4: Calls are counted and the 41st call stops the run**
    - **Validates: Requirements 6.1, 6.2, 6.3**
    - Finish: commit as `test(writer-agent): 3.5 write property test for the call cap`, push, show `git log --oneline -3`, then stop and wait for the user

  - [x] 3.6 Write property test for the stopped run
    - File `tests/test_writer_stop.py`, generate call arguments and any stop reason
    - **Property 5: A stopped run never reaches the database**
    - **Validates: Requirements 6.3, 8.3**
    - Finish: commit as `test(writer-agent): 3.6 write property test for the stopped run`, push, show `git log --oneline -3`, then stop and wait for the user

  - [x] 3.7 Write property test for the saved draft
    - Create `tests/test_writer_insert.py`, generate the seven argument strings on a Fake_Database that accepts the insert
    - **Property 6: A saved draft is answered and inserted as given**
    - **Validates: Requirements 6.4, 6.5, 6.6**
    - Finish: commit as `test(writer-agent): 3.7 write property test for the saved draft`, push, show `git log --oneline -3`, then stop and wait for the user

  - [x] 3.8 Write property test for the escalation
    - Create `tests/test_writer_escalation.py`, generate call sequences with request ids from a small pool and rejection messages that name a rule of `INSTRUCTIONS`, in both Run_Modes, with a `Counter` oracle written independently of the code
    - **Property 7: Escalation happens exactly when one rule is rejected 3 times on one request**
    - **Validates: Requirements 6.7, 6.8, 6.9, 6.10, 6.11, 6.12, 6.13, 6.14**
    - Finish: commit as `test(writer-agent): 3.8 write property test for the escalation`, push, show `git log --oneline -3`, then stop and wait for the user

  - [x] 3.9 Write property test for the trace
    - File `tests/test_writer_escalation.py`, same call generator with accepted, rejected and stopped outcomes
    - **Property 8: The trace has one entry per call**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7**
    - Finish: commit as `test(writer-agent): 3.9 write property test for the trace`, push, show `git log --oneline -3`, then stop and wait for the user

  - [x] 3.10 Write the concurrency test
    - Create `tests/test_writer_concurrency.py`, N threads (4 to 12) released together by a `threading.Barrier`, a Fake_Database that sleeps a few milliseconds in each insert and rejects every insert for the same rule on the same request
    - Check from the recorded statements: exactly 3 inserts, one status update, no insert after the status update, and the STOPPED reply for every call that did not reach the database
    - Add one fixed example with 8 threads, named after the brief: several concurrent calls where one triggers escalation, no later call reaches the database
    - **Property 9: No call after the escalation reaches the database**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    - Finish: commit as `test(writer-agent): 3.10 write the concurrency test`, push, show `git log --oneline -3`, then stop and wait for the user
    - _Requirements: 11.5_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Agent and run loop
  - [x] 5.1 Implement `build_agent`, `run_writer`, `_open_requests` and `_result`
    - `build_agent(ctx)` builds `BedrockModel(model_id=..., region_name=os.environ["AWS_REGION"], temperature=0)` and `Agent(model=..., tools=make_tools(ctx), system_prompt=SYSTEM_PROMPT, callback_handler=None)`, keyword arguments only, nothing else
    - `run_writer(ctx, task, agent=None)` sends `task`, then runs the follow-up loop of the design: open requests from a database query, ids ascending, at most `FOLLOW_UPS` follow-ups, stop with `agent stopped with requests not configured: <ids joined by ", ">`, no follow-up while the run is stopped
    - `_result` returns exactly the nine keys, with `rejections` keys as `<request_id>:<rule>`, tokens from `accumulated_usage` or 0, and `final_text` cut to 2000 characters
    - Finish: commit as `feat(writer-agent): 5.1 implement build_agent, run_writer, _open_requests and _result`, push, show `git log --oneline -3`, then stop and wait for the user
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10, 9.11, 9.12_

  - [x] 5.2 Write unit tests for the agent builder and the run loop
    - In `tests/test_writer_setup.py`, replace `BedrockModel` and `Agent` in the module namespace with recorders: `build_agent` calls them with exactly the keyword arguments of Requirements 3.2 and 3.3, the region comes from `AWS_REGION` and changes with it, and a missing `AWS_REGION` raises `KeyError`
    - Create `tests/test_writer_run.py` with a Fake_Agent: the follow-up text is `Not configured yet: R2, R5. Call propose_config for each.` for open requests R2 and R5; after 2 follow-ups with requests left the run stops with `agent stopped with requests not configured: R2, R5`; no third message is sent
    - Finish: commit as `test(writer-agent): 5.2 write unit tests for the agent builder and the run loop`, push, show `git log --oneline -3`, then stop and wait for the user
    - _Requirements: 3.2, 3.3, 3.5, 9.2, 9.5, 11.1, 11.4, 11.8_

  - [x] 5.3 Write property test for the run loop
    - File `tests/test_writer_run.py`, a Fake_Agent that configures a generated subset of the open requests on each message, through the real tools and a Fake_Database
    - **Property 10: The run loop sends follow-ups until requests are configured or the budget is spent**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7**
    - Finish: commit as `test(writer-agent): 5.3 write property test for the run loop`, push, show `git log --oneline -3`, then stop and wait for the user

  - [x] 5.4 Write property test for the result
    - File `tests/test_writer_run.py`, generate the final text (including texts longer than 2000 characters) and usage records that may lack the token fields
    - **Property 11: The result has the fixed keys and bounded text**
    - **Validates: Requirements 9.8, 9.9, 9.10, 9.11, 9.12**
    - Finish: commit as `test(writer-agent): 5.4 write property test for the result`, push, show `git log --oneline -3`, then stop and wait for the user

- [x] 6. Run script
  - [x] 6.1 Create `scripts/run_writer.py`
    - Parse `--model <id>` (required) and `--mode raw|instructive` (default `instructive`) with `argparse` and `choices`, so another mode stops before any connection
    - Put the repository root on `sys.path` like `scripts/apply_schema.py`, then call `db.check_config(["CLUSTER_ARN", "AGENT_WRITER_SECRET_ARN", "AWS_REGION"])` before `db.connect`
    - Set the run id to `single-<mode>-<unix seconds>`, build the `RunContext` with `db.connect("agent_writer")`, run `run_writer(ctx, manual.agent_input(ROOT, "install-07"))`
    - Print one JSON line per trace entry, then the summary line `run=<id> calls=<n> follow_ups=<n> escalated=<reason or None> input_tokens=<n> output_tokens=<n>`
    - Save the result to `results/<run_id>.json`, creating the folder if needed (`results/` is already in `.gitignore`)
    - Finish: commit as `feat(writer-agent): 6.1 create scripts/run_writer.py`, push, show `git log --oneline -3`, then stop and wait for the user
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9_

  - [x] 6.2 Write unit tests for the script
    - Create `tests/test_writer_script.py`, load the script by path with `load_script` from `tests/helpers.py`, replace `run_writer` and `db.connect` with stand-ins
    - `check_config` runs before `connect`; an invalid `--mode` stops before `connect`; the default mode is `instructive`
    - The run id matches `single-<mode>-<digits>`; one JSON line per trace entry is printed in order, then the summary line; `results/<run_id>.json` holds the result (use `tmp_path`, not the real `results/`)
    - Finish: commit as `test(writer-agent): 6.2 write unit tests for the script`, push, show `git log --oneline -3`, then stop and wait for the user
    - _Requirements: 10.1, 10.3, 10.4, 10.5, 10.7, 10.8, 10.9_

- [x] 7. Integration test on PostgreSQL
  - [x] 7.1 Write the integration test for the tools on the local database
    - Create `tests/test_writer_pg.py`, marked `local_pg` like `tests/test_errors_pg.py`, using `tests/pghelpers.py`, with the `agent_writer` Database_Object and the real tools, no model
    - A valid proposal for `R1` with `sample_seconds` given as text is saved as a draft
    - A non-numeric `sample_seconds` is rejected and classified `integer_input`
    - Three rejections of one rule on one request stop the run and the earlier draft of the run is moved to `needs_review`
    - The open-request query returns the requests that have no row for the run
    - Finish: commit as `test(writer-agent): 7.1 write the integration test for the tools on the local database`, push, show `git log --oneline -3`, then stop and wait for the user
    - _Requirements: 6.4, 6.5, 6.6, 6.7, 6.9, 6.10, 9.3, 11.9_

- [x] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. README step "One writer run"
  - [x] 9.1 Add the step and the run command to `README.md`
    - Do not call Bedrock and do not run `scripts/run_writer.py` with a model. Stop and ask the user to paste the real trace and the real summary line from `scripts/run_writer.py`, and wait for the answer
    - Do not change any existing text of `README.md` and keep the heading `## Part 1: the database says no` unchanged, because the article links the anchor `#part-1-the-database-says-no`
    - Add the step `### 4. One writer run` under that heading, after the step `### 3. Verify without spending`, in the first person, with the command, the first lines of the pasted trace and the pasted summary line, unedited
    - Add the run command of the script to the section `## Run it locally, paying only for the model`
    - Describe only behavior that the code implements; if the pasted output differs from the expectation in the design, show what the pasted output says
    - This task is the last task before the final checkpoint
    - Finish: commit as `feat(writer-agent): 9.1 add the step and the run command to readme.md`, push, show `git log --oneline -3`, then stop and wait for the user
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties; unit tests validate specific examples and edge cases
- The end state: every test passes and the README shows a real run of the finished code
- The README task calls no model and waits for the user to paste the real output

### Process notes (guidance for the execution phase)

- One commit per step. Every commit message ends with a blank line and the trailer `Co-Authored-By: Kiro`, with no email address.
- After each push, show `git log --oneline -3`.
- No commits and no pushes while the spec is being written.
- On approval of the tasks: one commit with the three documents, message `docs(writer-agent): requirements, design and tasks`, then push. The documents are not committed one by one.
- After each task, when its tests pass: commit the code and tests of that task only, as `feat(writer-agent): <task number> <task title in lowercase>`. Use `test(writer-agent): <task number> <task title in lowercase>` if the task only adds tests. Then push, then stop and wait for the user before the next task.
- When I report a difference between expected and actual output: one commit `fix(writer-agent): <what now matches>` for the code, then a separate commit `docs(writer-agent): <the rule, in a few words>` for `requirements.md` and `design.md`. Push after each commit.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "3.2"] },
    { "id": 3, "tasks": ["2.3", "3.3", "5.1"] },
    { "id": 4, "tasks": ["2.4", "3.4", "3.10", "5.2"] },
    { "id": 5, "tasks": ["3.5", "3.7", "3.8", "5.3", "6.1"] },
    { "id": 6, "tasks": ["3.6", "3.9", "5.4", "6.2", "7.1"] },
    { "id": 7, "tasks": ["9.1"] }
  ]
}
```
