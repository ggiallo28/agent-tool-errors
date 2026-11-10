# Implementation Plan: instructive-rejections

## Overview

The implementation language is Python 3.12, as in the rest of the repository. All code goes into `opsmem/errors.py`. The plan builds it in four increments: the instruction table with `render`, then `classify`, then `valid_values`, then the README step. Each increment ends with its tests. The pure parts need no database and no network (Requirement 5.1). The README task is the last task before the final checkpoint, because it shows real output of the finished code.

## Tasks

- [x] 1. Instruction table and renderer
  - [x] 1.1 Create `opsmem/errors.py` with the constants, `INSTRUCTIONS` and `render`
    - Define `MODES`, `MAX_VALID`, `NONE_LISTED`, `UNKNOWN`, `UNKNOWN_INSTRUCTION`
    - Define `INSTRUCTIONS` with the 14 strings of Requirement 1, byte for byte
    - Implement `render(rule, valid, mode, raw_message)` and `_instruction` as in the design: `str.replace` for `{valid}`, first 10 values, `none listed`, `ValueError` with the invalid mode
    - Add a module docstring that says the lookup needs the `agent_writer` object
    - _Requirements: 1.1 to 1.17, 2.1 to 2.10_

  - [x] 1.2 Write unit tests for the table and the renderer
    - Create `tests/test_errors_pure.py`, no database, no network
    - A parametrized test with the 14 literal strings and a check that the key set has exactly 14 members (5.11)
    - No table value contains `propose_config` (5.10)
    - Raw mode returns `ERROR: ` plus the unchanged message (5.7)
    - 12 valid values show exactly the first 10 (5.8); no valid values show `none listed` (5.9)
    - `render("not_a_rule", [], "instructive", "x")` equals `REJECTED (not_a_rule). Not saved. Rejected.` (5.12)
    - An invalid mode raises an error that contains the value
    - _Requirements: 5.1, 5.7, 5.8, 5.9, 5.10, 5.11, 5.12, 2.9_

  - [x] 1.3 Write property tests for the renderer
    - File `tests/test_errors_pure.py`, `hypothesis`, at least 100 examples, tag comment `# Feature: instructive-rejections, Property <n>: <text>`
    - **Property 1: Raw mode returns the message unchanged**
    - **Property 2: Instructive output is the prefix plus the filled template**
    - **Property 3: The Valid_List holds the first 10 values in order**
    - **Property 4: An invalid mode is rejected with its value**
    - **Property 5: Instructions never name a tool**
    - **Validates: Requirements 1.16, 1.17, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10**

- [x] 2. Rule classifier
  - [x] 2.1 Implement `classify` in `opsmem/errors.py`
    - Add the `_NAME` and `_SQLSTATE` expressions and the function as in the design
    - Check order: first qualifying name, then `22P02` or `invalid input syntax for type integer`, then `signal_name` with the substring `check` (any letter case), then `unknown`
    - _Requirements: 3.1 to 3.12_

  - [x] 2.2 Write unit tests for the classifier
    - Add to `tests/test_errors_pure.py`
    - Foreign key violation that names `config_field_exists` (5.2)
    - `ERROR: config_sampling_supported: sample_s 5 outside 10 to 300 for api_p95` (5.3)
    - `ERROR: invalid input syntax for type integer: "every minute"` (5.4)
    - Check violation that names `collection_configs_signal_name_check` (5.5)
    - Data API style message with `SQLState: 22P02` and no constraint (5.6)
    - A message with no rule gives `unknown`
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.6, 3.7, 3.8, 3.9, 3.10, 3.11_

  - [x] 2.3 Write property tests for the classifier
    - File `tests/test_errors_pure.py`, with the `filler` and message-shape generators of the design
    - **Property 6: Classification is total and stays inside the table**
    - **Property 7: A message built around a rule name is classified as that rule**
    - **Property 8: The first qualifying name wins**
    - **Property 9: Integer and signal-name fallbacks apply only without a constraint name**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12**

- [x] 3. Valid values from the database
  - [x] 3.1 Implement `valid_values` in `opsmem/errors.py`
    - Add the `_LOOKUPS` table: rule to SQL, Proposal keys, `uses_installation` flag, row shaper (`_first_column`, `_sorted_first_column`, `_range_text`)
    - One `db.run` call per lookup, SELECT only, every cell converted with `str()`
    - Rules without a lookup return `[]` and send no statement; a missing or non-`str` Proposal value returns `[]` without a statement
    - `except db.DatabaseError` returns `[]`; nothing else is caught
    - `config_unit_allowed_for_type` reads `allowed_units` by `signal_type` only, because that table has no `installation_id`
    - _Requirements: 4.1 to 4.15_

  - [x] 3.2 Write unit test for lookup failure and the rules without lookup
    - Create `tests/test_errors_lookup.py`
    - A stand-in whose `run` raises `DatabaseError` gives `[]` for each rule with a lookup, and `render` then shows `none listed` (4.15)
    - A recording stand-in shows zero statements for the six rules without a lookup and for `unknown` (4.13)
    - _Requirements: 4.13, 4.15_

  - [x] 3.3 Write property test for statement shape and installation scope
    - File `tests/test_errors_lookup.py`, in-memory `sqlite3` stand-in with the column names of `sql/schema.sql`, recording `(sql, params)` like `tests/spy.py`
    - Tables with an `installation_id` column are read from the `CREATE TABLE` blocks of `sql/schema.sql`
    - **Property 10: Lookups send SELECT statements only, scoped to the installation**
    - **Validates: Requirements 4.1, 4.2, 4.13**

  - [x] 3.4 Write property test for lookup results
    - File `tests/test_errors_lookup.py`, catalog strategy and Python oracle as in the design
    - **Property 11: Lookup results match the catalog**
    - **Validates: Requirements 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 4.14**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Integration test on PostgreSQL
  - [x] 5.1 Write the integration test for `agent_writer`
    - Create `tests/test_errors_pg.py`, marked `local_pg` like `tests/test_rules_pg.py`, using `tests/pghelpers.py`
    - Insert a row with an unknown `source_field` as `agent_writer`, catch `DatabaseError`
    - Check `classify(str(err)) == "config_field_exists"` and that `valid_values` returns the 9 field names of `install-07`, sorted
    - _Requirements: 3.9, 4.1, 4.9_

- [x] 6. README step "Verify without spending"
  - [x] 6.1 Add the missing parts to `README.md`
    - Do not change any existing text of `README.md`
    - Add the section `## Part 1: the database says no` before the step, because it does not exist
    - Add the step `### 3. Verify without spending` under that heading, in the first person
    - Run the demo script of the design with `uv run python` against the local database, and paste the raw and instructive output unedited
    - Explain that the Instruction names the parameter to change and never a tool, and give the reason
    - Describe only behavior that the code implements; if the real output differs from the expectation in the design, show what the code printed
    - Check the title, the prerequisites section and `## Run it locally, paying only for the model`: they already exist, so add nothing for them
    - This task is the last task before the final checkpoint
    - _Requirements: 6.1 to 6.9_

- [x] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties; unit tests validate specific examples and edge cases
- Requirement 4.2 now reads "every query on a table that has an `installation_id` column", so `allowed_units` is outside its scope (open point 1 of the design is resolved)

### Process notes (guidance for the execution phase)

- One commit per step. Every commit message ends with a blank line and the trailer `Co-Authored-By: Kiro`, with no email address.
- After each push, show `git log --oneline -3`.
- No commits and no pushes while the spec is being written.
- On approval of the tasks: one commit with the three documents, message `docs(instructive-rejections): requirements, design and tasks`, then push.
- After each task, when its tests pass: commit the code and tests of that task only, as `feat(instructive-rejections): <task number> <task title in lowercase>`. Use `test(instructive-rejections): <task number> <task title in lowercase>` if the task only adds tests. Then push, then stop and wait for the user before the next task.
- When I report a difference between expected and actual output: one commit `fix(instructive-rejections): <what now matches>` for the code, then a separate commit `docs(instructive-rejections): <the rule, in a few words>` for `requirements.md` and `design.md`. Push after each commit.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1"] },
    { "id": 3, "tasks": ["1.3", "3.2", "5.1"] },
    { "id": 4, "tasks": ["2.3", "3.3"] },
    { "id": 5, "tasks": ["3.4"] },
    { "id": 6, "tasks": ["6.1"] }
  ]
}
```
