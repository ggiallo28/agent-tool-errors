# Implementation Plan: model-evaluation

## Overview

The implementation language is Python 3.12, as in the rest of the repository. The pure logic goes into `opsmem/evaluation.py`; the three scripts are thin `main(argv, ...)` functions with injectable dependencies, in the style of `scripts/run_writer.py`. The plan builds in this order: catalog and cost helpers, run analysis and table, the summarizer, the experiment runner, the gist generator, then the publisher and the README Evidence section. Every increment ends with its tests. All tests run offline: no AWS, no Docker, no model, no network, and the real `gh` is never called.

No task runs `scripts/run_experiment.py --yes` or `scripts/publish_gists.sh`. Those two actions belong to the author (Requirements 8.7 and 10.6). A task that reaches that point stops and asks the author.

## Tasks

- [ ] 1. Model catalog and pure helpers
  - [x] 1.1 Create `models.json` and the first part of `opsmem/evaluation.py`
    - `models.json`: the five Model_Entries in the order of Requirement 1, with names, model identifiers, prices and `price_source` exactly as listed
    - In `opsmem/evaluation.py`: `PRICE_NOTE`, `MAX_TOOL_CALLS`, `TOKENS_IN_PER_CALL`, `TOKENS_OUT_PER_CALL`, `FULL_SAVE`, `CLOSING_LINE` as named constants, with a comment that explains the per-call token budget
    - `ModelEntry` (frozen dataclass), `load_catalog` (prices read as `Decimal(str(value))`), `cost_usd`, `format_cost` (`ROUND_HALF_UP`, 4 decimals, `$` prefix), `cost_upper_bound`, `is_dirty`
    - _Requirements: 1.1 to 1.7, 2.8, 5.5, 3.2, 3.3_

  - [~] 1.2 Write unit tests for the catalog and the helpers
    - Create `tests/test_evaluation_core.py`
    - `models.json` equals the table of Requirement 1: labels, names, identifiers, prices, `price_source`, order
    - `format_cost` gives `$0.0022` for 51,844 input and 2,454 output tokens at 0.035/0.14 (6.3)
    - `is_dirty` is false for empty output and for lines that start with `?? `, true for ` M file` and `A  file`
    - `cost_upper_bound` for one entry matches a hand-computed value
    - _Requirements: 1.1 to 1.6, 2.8, 3.2, 3.3, 6.3_

  - [ ]* 1.3 Write property test for cost formula and rounding
    - File `tests/test_evaluation_core.py`, `hypothesis`, at least 100 examples, tag comment `# Feature: model-evaluation, Property <n>: <text>`
    - **Property 11: Cost formula and rounding**
    - **Validates: Requirements 5.5**

- [ ] 2. Run analysis and Results_Table
  - [~] 2.1 Add run analysis and rendering to `opsmem/evaluation.py`
    - `is_failed`, `count_saved`, `count_rejections` (prefix `REJECTED` only, `STOPPED` excluded), `ended_stopped`, `saved_rows` (sorted by request), `load_runs` (sorted by file name, adds `_label`), `row_for`, `render_table` (rows sorted by `(-cost, label)` on the unrounded cost, `PRICE_NOTE` below the table), `identical_rows_statement`
    - Tokens shown with thousands separators; a Failed_Run shows 0 of 6, 0 tool calls, `0 / 0`, `$0.0000` and the error text in Escalated
    - _Requirements: 5.1 to 5.8, 5.9, 5.10, 5.12, 5.14, 1.7_

  - [~] 2.2 Create the synthetic fixtures in `tests/fixtures/runs/`
    - Three hand-written Run_Files: a model that saves 6 of 6 after rejections, a model stopped by escalation with a Stopped_Reply, and a Failed_Run
    - Every file holds `commit`, `label`, `model_id`, `mode` and `started_at`
    - Mark them as synthetic in a `README` line inside the folder; they are never published
    - _Requirements: 6.1_

  - [~] 2.3 Write unit tests for the run analysis
    - File `tests/test_evaluation_core.py`
    - Every column of the Results_Table for the three fixtures (6.2)
    - A Stopped_Reply is not counted as a rejection (6.4)
    - Rows ordered by cost descending, label ascending for ties (6.5)
    - Identical-rows statement for the fixtures (6.6)
    - Reading the same files twice gives identical output (5.11)
    - _Requirements: 5.2 to 5.8, 5.11, 6.2, 6.4, 6.5, 6.6_

  - [ ]* 2.4 Write property tests for the table
    - File `tests/test_evaluation_core.py`
    - **Property 1: Price note accompanies every cost output** (table part)
    - **Property 10: Table row contents**
    - **Property 12: Row ordering**
    - **Property 13: Identical rows statement**
    - **Validates: Requirements 1.7, 5.1, 5.2, 5.3, 5.4, 5.6, 5.7, 5.8, 5.9, 5.10, 5.14**

- [ ] 3. Summarizer script
  - [~] 3.1 Create `scripts/summarize_runs.py`
    - `main(argv=None, *, catalog_path=None, stdout=None, stderr=None) -> int`
    - Argument: a Run_Directory, optional `--rows`
    - Print `render_table`; with `--rows` print the saved rows of each Full_Save_Model and the identical-rows statement
    - An empty directory prints an error to `stderr` and returns 1
    - _Requirements: 5.1, 5.9, 5.10, 5.13, 5.14, 9.11_

  - [~] 3.2 Write unit tests for the summarizer script
    - Create `tests/test_summarize_runs.py`, using `load_script` from `tests/helpers.py`
    - Output on the fixtures, with and without `--rows`
    - Empty directory returns non-zero and prints an error
    - Same input twice gives the same output
    - _Requirements: 5.1, 5.9, 5.10, 5.11, 5.13, 6.2 to 6.6_

- [~] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Experiment runner
  - [~] 5.1 Create `scripts/run_experiment.py`
    - `main(argv=None, *, run_model=None, git=None, now=None, check_config=None, catalog_path=None, root=None, stdout=None, stderr=None) -> int`
    - Defaults: `run_model` builds a `RunContext` and calls `run_writer`; `git` runs the real command and raises `GitError` on a non-zero exit; `now` is the UTC clock; `check_config` is `db.check_config`
    - Order of steps as in the design: arguments, configuration, labels (unknown label returns 2), estimate with `PRICE_NOTE`, return 0 without `--yes`, `git status --porcelain` with `is_dirty` (return 1 and "commit first"), `git rev-parse HEAD`, then the models in catalog order
    - Default `--out` is `runs/<UTC date>`; mode `instructive`, installation `install-07`, input from `agent_input`
    - Write each Run_File with exclusive creation (`open(path, "x")`); an existing file is skipped with a message naming it
    - An exception from `run_model` writes a Failed_Run with the error text and `commit`, and the loop continues; return 0 at the end
    - Do not run this script with `--yes` in this task. Tests use fakes only
    - _Requirements: 2.1 to 2.9, 3.1 to 3.7, 4.1 to 4.6, 9.11_

  - [~] 5.2 Write unit tests for the runner
    - Create `tests/test_run_experiment.py`, with fake `run_model`, `git`, `now`, `check_config`
    - Incomplete configuration exits non-zero and calls no model (2.2)
    - Without `--yes`: estimate printed, no model call, no git call (9.2, 9.7)
    - With `--yes` and a dirty tree: non-zero, message to commit first, no model call (9.5)
    - Untracked files alone do not block (9.6)
    - Order of events: estimate, git status, commit read, models (9.7)
    - An existing Run_File is not overwritten (9.3)
    - A failed start is recorded as a Failed_Run and the next model runs (9.4)
    - Every Run_File, including a Failed_Run, holds `commit` (9.8)
    - A git failure returns non-zero and calls no model (3.7)
    - Default `--out` uses the injected UTC date; default `--models` selects all five in catalog order
    - _Requirements: 2.2, 2.4, 2.5, 3.2 to 3.7, 4.1 to 4.6, 9.2 to 9.8_

  - [ ]* 5.3 Write property tests for the runner
    - File `tests/test_run_experiment.py`, fakes for every dependency
    - **Property 1: Price note accompanies every cost output** (runner estimate part)
    - **Property 2: Unknown labels block the run**
    - **Property 3: Cost upper bound formula**
    - **Property 4: No model call without --yes**
    - **Property 5: Dirty tree detection**
    - **Property 6: Commit in every Run_File**
    - **Property 7: Run_File content**
    - **Property 8: Existing files are never overwritten**
    - **Property 9: Failed start is recorded and the run continues**
    - **Validates: Requirements 1.7, 2.6, 2.7, 2.8, 2.9, 3.2, 3.3, 3.4, 3.6, 4.2, 4.3, 4.4, 4.5, 4.6**

- [~] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Gist generator
  - [~] 7.1 Add `render_gists` to `opsmem/evaluation.py`
    - `render_gists(runs, catalog, agent_input_text, system_prompt, date) -> dict[str, str]`
    - `agent-learns-from-rejections.md` for the cheapest Full_Save_Model (ties by label), chosen from the data and not from model names in the code; omitted when no Full_Save_Model exists
    - `five-models.md` with the setup header, Results_Table with price note, rows kept by each Finished_Model, identical-rows statement
    - `small-models-fail-safe.md` only when a Finished_Model has fewer than 6 Saved_Entries, with raw Trace, escalation reason and rows kept counted from the Trace
    - Setup line with the repository link, Strands Agents, Amazon Bedrock in `us-east-1`, local PostgreSQL 16 in Docker, the date, the fictional installation and the Commit from the Run_Files
    - Raw Trace as one unedited JSON line per tool call; every file ends with `CLOSING_LINE`
    - _Requirements: 7.2 to 7.10, 7.12, 1.7_

  - [~] 7.2 Create `scripts/make_gists.py`
    - `main(argv=None, *, catalog_path=None, root=None, gists_dir=None, stdout=None, stderr=None) -> int`
    - Argument: a Run_Directory; read `agent_input(root, "install-07")` and `SYSTEM_PROMPT`
    - Differing commits across Run_Files: print them, return 1, write nothing
    - Date in the setup line is the UTC date of the earliest `started_at`, so output is deterministic
    - When `agent-learns-from-rejections.md` is skipped, print a message naming it
    - _Requirements: 7.1, 7.2, 7.4, 7.11, 7.12, 9.11_

  - [~] 7.3 Write unit tests for the gist generator
    - Create `tests/test_make_gists.py`, using the fixtures of task 2.2 and a temporary `gists_dir`
    - Running twice on the same inputs gives identical files (9.1)
    - The setup line holds the Commit read from the Run_Files (9.9)
    - `small-models-fail-safe.md` is written only when a Finished_Model has fewer than 6 Saved_Entries (9.10)
    - Mixed commits return non-zero and write no file
    - No Full_Save_Model skips the first gist and names it in the output
    - Every file ends with the closing line
    - _Requirements: 7.4, 7.5, 7.8, 7.9, 7.10, 7.11, 7.12, 9.1, 9.9, 9.10_

  - [ ]* 7.4 Write property tests for the gists
    - File `tests/test_make_gists.py`
    - **Property 1: Price note accompanies every cost output** (`five-models.md` part)
    - **Property 14: Deterministic output**
    - **Property 15: Gist model selection comes from the data**
    - **Property 16: Raw trace round trip**
    - **Property 17: Fail-safe gist is conditional**
    - **Property 18: Gist framing**
    - **Property 19: Mixed commits block generation**
    - **Validates: Requirements 1.7, 5.11, 7.3, 7.4, 7.5, 7.6, 7.8, 7.9, 7.10, 7.11, 9.1, 9.9, 9.10**

- [ ] 8. Publisher and README Evidence section
  - [~] 8.1 Create `scripts/publish_gists.sh`
    - `set -euo pipefail`; for each `gists/*.md`, read the URL from `gists/index.json`
    - No URL: `gh gist create --public <file>` and record the printed URL; with a URL: `gh gist edit <id> <file>`
    - Write `gists/index.json` at the end; a failed `gh` prints the error and exits non-zero
    - Make the file executable. Do not run it in this task; the author runs it
    - _Requirements: 8.1 to 8.4, 8.7_

  - [~] 8.2 Write tests for the publisher with a fake `gh`
    - Create `tests/test_publish_gists.py`, with a fake `gh` script first on `PATH` and a temporary working directory
    - Create when no URL, edit when a URL exists, index written, failure exits non-zero
    - The real `gh` is never called and no gist is published
    - _Requirements: 8.1 to 8.4_

  - [~] 8.3 Add the `## Evidence` section to `README.md`
    - Do not change any existing text of `README.md`
    - One line per gist with its title and a link placeholder that the author fills in after publishing
    - One line on regeneration with `summarize_runs.py` and `make_gists.py`
    - _Requirements: 8.5, 8.6_

  - [~] 8.4 Write smoke tests for the README and the Evidence section
    - File `tests/test_evidence_readme.py`
    - The README holds the `## Evidence` heading, one line per gist title and the regeneration line
    - _Requirements: 8.5, 8.6_

- [~] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Then stop. The author runs `scripts/run_experiment.py --yes`, reviews the Run_Files and commits them under `runs/<date>/`, runs `scripts/make_gists.py` and `scripts/publish_gists.sh`, and fills in the links of the Evidence section

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties; unit tests validate specific examples and edge cases
- Some properties span several components; the tag comment names the property and each part lives in the test file of its component

### Process notes (guidance for the execution phase)

- One commit per task. Every commit message ends with a blank line and the trailer `Co-Authored-By: Kiro`, with no email address.
- After each task, when its tests pass: commit the code and tests of that task only, as `feat(model-evaluation): <task number> <task title in lowercase>`, for example `feat(model-evaluation): 1.1 create models.json and the first part of opsmem/evaluation.py`. Then push, show the output of `git log --oneline -3`, and stop and wait for the author before the next task.
- No commits and no pushes while the spec is being written.
- On approval of the tasks: one commit with the three documents, message `docs(model-evaluation): requirements, design and tasks`, then push.
- Never run `scripts/run_experiment.py --yes` and never run `scripts/publish_gists.sh`. When a step needs either, stop and ask the author, who runs it.
- The runner refuses a Dirty_Tree, so each task commit must land before the author runs the experiment.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1", "8.1"] },
    { "id": 2, "tasks": ["1.3", "2.2", "5.1", "8.3"] },
    { "id": 3, "tasks": ["2.3", "3.1", "5.2", "7.1", "8.2"] },
    { "id": 4, "tasks": ["2.4", "3.2", "5.3", "7.2", "8.4"] },
    { "id": 5, "tasks": ["7.3"] },
    { "id": 6, "tasks": ["7.4"] }
  ]
}
```
