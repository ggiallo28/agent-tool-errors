# Implementation Plan: repeated-runs

## Overview

The implementation language is Python 3.12, as in the rest of the repository. The pure logic goes into `opsmem/evaluation.py`; `scripts/run_experiment.py`, `scripts/summarize_runs.py` and `scripts/make_gists.py` stay thin `main(argv, ...)` functions with injectable dependencies. The plan builds in this order: golden files of the current output, the selection and naming helpers, the one-line selection in `make_gists.py`, the Repeats_Table and its fixtures, the `--repeats` argument of the summarizer, then the runner. Every increment ends with its tests. All tests run offline: no AWS, no Docker, no model, no network.

No task runs `scripts/run_experiment.py --yes`. That action belongs to the author (Requirement 9.5). A task that reaches that point stops and asks the author. The author keeps new runs in directories separate from `runs/2026-11-10`.

## Tasks

- [x] 1. Golden files of the current output
  - [x] 1.1 Produce the golden files with the unchanged scripts and add the comparison tests
    - Do this before any code change in this spec
    - `tests/fixtures/expected/summarize-2026-11-10.txt`: the output of `scripts/summarize_runs.py runs/2026-11-10`, captured by calling `main` with injected streams
    - `tests/fixtures/expected/gists-2026-11-10/`: the files of `scripts/make_gists.py runs/2026-11-10`, produced by calling `main` with `gists_dir` set to a temporary directory, so the real `gists/` folder is not touched
    - Add a test in `tests/test_summarize_runs.py` that compares the summarizer output on `runs/2026-11-10` with the golden file, and a test in `tests/test_make_gists.py` that compares the generated gists with the golden folder, file by file, byte for byte
    - Both tests must pass on the unchanged code
    - _Requirements: 7.1, 7.10, 8.10, 8.18_

- [x] 2. Selection and naming helpers
  - [x] 2.1 Add the selection and naming helpers to `opsmem/evaluation.py`
    - `is_repeated(run)`: true if and only if `repeat` and `repeat_count` are both present; never reads the file name
    - `run_mode(run)`: `run.get("mode", "instructive")`
    - `results_runs(runs)`: the Single_Runs with Mode `instructive`
    - `load_runs` also stores the file name as `_file`
    - `base_name(label, mode)`, `run_file_name(label, mode, repeat, repeat_count)` (no number part when `repeat_count` is 1, two-digit number otherwise) and `make_run_id(label, mode, repeat, unix_seconds)` giving `eval-<label>-<mode>-<NN>-<unix>`
    - Existing functions and outputs do not change
    - _Requirements: 1.5, 3.1 to 3.4, 5.2, 7.2, 7.4, 7.5_

  - [x] 2.2 Select single instructive runs in `scripts/make_gists.py`
    - After `load_runs`, set `runs = evaluation.results_runs(runs)`; the rest of the script is unchanged
    - A directory with Run_Files but no selected run prints `No run files in <dir>`, returns 1 and writes nothing
    - Tests in `tests/test_make_gists.py`: the golden comparison of task 1.1 still passes; Repeated_Runs and runs with Mode `raw` added to a copy of the directory change no Gist_File; a Run_File without `mode` is treated as `instructive`; a directory with only Repeated_Runs returns non-zero and writes nothing
    - Tests for the helpers of task 2.1 in `tests/test_evaluation_core.py`: `is_repeated` with names that end in digits (`claude-sonnet-4-6.json`) and with a repeated run that has no numeric suffix, `run_mode` with and without `mode`, `results_runs`, `run_file_name` for the four rows of the file-name table, `make_run_id` with the same second for two repetitions
    - _Requirements: 5.2, 7.2, 7.4, 7.5, 7.10, 8.14, 8.18, 8.19_

  - [x]* 2.3 Write property tests for the selection helpers
    - File `tests/test_repeats_core.py`, `hypothesis`, at least 100 examples, tag comment `# Feature: repeated-runs, Property <n>: <text>`
    - **Property 10: Repeated runs are recognised from the fields**
    - **Property 11: Results_Table selection**
    - **Property 18: Gists use only single instructive runs**
    - **Property 19: Missing mode is instructive**
    - **Validates: Requirements 5.2, 7.1, 7.2, 7.4, 7.5, 7.10**

- [x] 3. Repeats_Table
  - [x] 3.1 Create the synthetic fixtures
    - `tests/fixtures/runs-repeated/`, written by hand, never published, with a `README` line that says so
    - `nova-micro-01.json`, `-02.json`, `-03.json`: `repeat` 1 to 3, `repeat_count` 4, complete, identical rows; `-02` has other signal names on purpose
    - `nova-micro-04.json`: `repeat` 4, complete, another `source_field` for request R4
    - `ministral-3-3b-01.json`: `repeat` 1 of 2, stopped by escalation with a Stopped_Reply; `ministral-3-3b-02.json`: `repeat` 2 of 2, Failed_Run
    - `nova-micro-raw-01.json` and `nova-micro-raw-02.json`: Mode `raw`, `repeat` 1 and 2 of 2, one complete and one stopped
    - `claude-sonnet-4-6.json`: Single_Run, instructive, complete, label that ends with digits
    - `claude-haiku-4-5-01.json`: Single_Run with a numeric suffix in the name and no `repeat` fields
    - `tests/fixtures/runs-repeated-only/`: only Repeated_Runs, no Single_Run
    - Every file holds `commit`, `label`, `model_id`, `mode` and `started_at`
    - _Requirements: 8.1_

  - [x] 3.2 Add the Repeats_Table to `opsmem/evaluation.py`
    - `repeat_groups(runs, catalog)`: groups by label and Mode, only for groups with a Repeated_Run or Mode `raw`, each group sorted by `_file`, ordered by catalog position and `instructive` before `raw`
    - `is_complete`, `row_keys` (built on `saved_rows`, which leaves out the signal name), `count_rejections_any_mode` (results that start with `REJECTED` or `ERROR: `, never a Stopped_Reply), `span` (`none`, a single number, or `min to max`)
    - `repeats_row`: Runs counts every Run_File including Failed_Runs; Saved 6 of 6 as `K of N`; Same rows as `K of M` against the first complete run by file name, or `none`; Tool calls and Rejections (with `count_rejections_any_mode`) over the runs that are not failed
    - `differing_rows`: one line for each complete run and request that differs from the first complete run, sorted by model, Mode, file name and request, with both values
    - `render_repeats(runs, catalog)`: header, rule, one line per group, blank line, `REPEATS_NOTE`, then `Differing rows:` and its lines only when some complete run differs
    - _Requirements: 5.1 to 5.13, 6.1 to 6.5_

  - [x] 3.3 Write unit tests for the Repeats_Table
    - Create `tests/test_summarize_repeats.py` (core part, calling `render_repeats` on the fixtures)
    - Every column of every line for the fixtures (8.2), including `3 of 4` in Same rows for `nova-micro` and the Failed_Run counted in Runs and skipped in the spans (8.17)
    - The Differing_Rows_Listing for request R4 of `nova-micro-04.json`, and no listing when all rows are equal (8.3)
    - A change of signal name only changes nothing, and the note says so (8.4)
    - A single raw run is listed with Runs 1 (8.15)
    - The Rejections column counts `REJECTED` and `ERROR: ` results, never a Stopped_Reply, while `count_rejections` keeps its definition (8.21)
    - Line order by catalog and Mode
    - _Requirements: 5.1 to 5.13, 6.1 to 6.5, 8.2, 8.3, 8.4, 8.15, 8.17, 8.21_

  - [x]* 3.4 Write property tests for the Repeats_Table
    - File `tests/test_repeats_core.py`
    - **Property 12: Repeats_Table line set**
    - **Property 13: Repeats_Table counts and spans**
    - **Property 14: Same rows**
    - **Property 15: Differing rows**
    - **Validates: Requirements 5.1 to 5.13, 6.1 to 6.5**

- [x] 4. Summarizer argument
  - [x] 4.1 Add `--repeats` to `scripts/summarize_runs.py`
    - `selected = evaluation.results_runs(runs)`
    - Without `--repeats`: an empty selection prints an error that names `--repeats` and returns 1; otherwise the output is today's output computed from `selected`, with `--rows` as before
    - With `--repeats`: the Results_Table and `--rows` output only when `selected` is not empty, then a blank line (only after a Results_Table) and `render_repeats`; return 0
    - An empty directory is an error in both cases, as today
    - _Requirements: 7.1, 7.2, 7.3, 7.8, 7.9, 8.20_

  - [x] 4.2 Write unit tests for the summarizer
    - In `tests/test_summarize_runs.py` and `tests/test_summarize_repeats.py`, with the fixtures of task 3.1
    - Output without `--repeats` on `runs/2026-11-10` equals the golden file (8.10); the existing tests keep passing unchanged
    - Output with `--repeats` on `tests/fixtures/runs-repeated/`: the Results_Table holds only `claude-sonnet-4-6` and `claude-haiku-4-5-01` as Single_Runs, then the Repeats_Table
    - The directory with only Repeated_Runs: with `--repeats` only the Repeats_Table, code 0; without it an error and a non-zero code (8.16)
    - A Run_File without `mode` is a run with Mode `instructive` in both tables (8.19)
    - Same files twice give the same output, with and without `--repeats` (8.11)
    - _Requirements: 7.1, 7.2, 7.3, 7.6, 7.8, 7.9, 8.10, 8.11, 8.16, 8.19_

  - [x]* 4.3 Write property tests for the summarizer output
    - File `tests/test_repeats_core.py`
    - **Property 16: Output without a Results_Table candidate**
    - **Property 17: Deterministic output**
    - **Validates: Requirements 7.3, 7.6, 7.7, 7.8, 7.9**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Experiment runner
  - [x] 6.1 Add `--repeat` and `--mode` to `scripts/run_experiment.py`
    - `repeat_arg` (argparse type, whole number from 1 to 20, error names the range), `--repeat` default 1, `--mode` with `choices=("raw", "instructive")` default `instructive`; both are checked by `parse_args`, before `check_config` and before any model call
    - Remove the module constant `MODE`; the Mode comes from `args.mode`
    - The seam becomes `run_model(entry, task, run_id, mode)`; `real_run_model` passes `mode` to `RunContext`. Update the fakes of `tests/test_run_experiment.py` to the four-argument form and change nothing else in that file
    - Cost line: `cost_upper_bound(selected)` times the Repeat_Count; unchanged text when the Repeat_Count is 1, and `for N runs of each model` before the price note when it is greater
    - Loop: each model in catalog order, each repetition from 1 to N; file name from `run_file_name`; `run_id` from `make_run_id`; an existing file is skipped with a message and the next repetition runs; `repeat` and `repeat_count` are added to the metadata only when N is greater than 1, so a Failed_Run holds them too; an exception from `run_model` writes a Failed_Run and the loop continues
    - Exclusive creation of files as today; the checks on configuration, Dirty_Tree and commit are unchanged
    - Do not run this script with `--yes` in this task. Tests use fakes only
    - _Requirements: 1.1 to 1.8, 2.1 to 2.5, 3.1 to 3.6, 4.1 to 4.4, 8.20_

  - [x] 6.2 Write unit tests for the runner
    - Create `tests/test_run_experiment_repeat.py`, with fake `run_model`, `git`, `now`, `check_config`
    - File names produced by `--repeat 3`, by `--mode raw`, and by both together (8.5)
    - An existing file in the middle of a sequence is not overwritten and the other repetitions run (8.6)
    - `--repeat 0`, `--repeat 21`, `--repeat x` and `--mode other` are refused, non-zero, no model called (8.7)
    - Without `--yes` no model and no git call, and the printed bound is multiplied by the Repeat_Count; with default arguments the printed line equals the line before this feature (8.8)
    - The Mode reaches `run_model` and every Run_File, including a Failed_Run (8.9)
    - With a clock fixed at one second, `--repeat 3` and a failed start give pairwise different `run_id` values that hold the Mode and the repetition number (8.12)
    - `repeat` and `repeat_count` in every Run_File with `--repeat 3`, including a Failed_Run, and in none with `--repeat 1` (8.13)
    - With default arguments the file names and fields equal those of the existing tests, except `run_id`
    - _Requirements: 1.3 to 1.8, 2.2 to 2.5, 3.1 to 3.6, 4.1 to 4.3, 8.5 to 8.9, 8.12, 8.13_

  - [x]* 6.3 Write property tests for the runner
    - File `tests/test_run_experiment_repeat.py`, fakes for every dependency
    - **Property 1: Invalid repeat or mode is refused**
    - **Property 2: Run count and order**
    - **Property 3: Unique run identifiers**
    - **Property 4: Repetition fields**
    - **Property 5: Failed start does not stop the repetitions**
    - **Property 6: Mode reaches the run and the file**
    - **Property 7: File names**
    - **Property 8: Existing files are never overwritten**
    - **Property 9: Cost bound scales with the Repeat_Count, and nothing runs without `--yes`**
    - **Validates: Requirements 1.3 to 1.8, 2.2 to 2.5, 3.1 to 3.6, 4.1 to 4.3**

- [x] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Then stop. The author runs `scripts/run_experiment.py --yes` with `--repeat` and `--mode`, into a directory separate from `runs/2026-11-10`, reviews the Run_Files and commits them

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties; unit tests validate specific examples and edge cases
- Some properties span several components; the tag comment names the property and each part lives in the test file of its component

### Process notes (guidance for the execution phase)

- One commit per task. Every commit message ends with a blank line and the trailer `Co-Authored-By: Kiro`, with no email address.
- After each task, when its tests pass: commit the code and tests of that task only, as `feat(repeated-runs): <task number> <task title in lowercase>`, for example `feat(repeated-runs): 2.1 add the selection and naming helpers to opsmem/evaluation.py`. Then push, show the output of `git log --oneline -3`, and stop and wait for the author before the next task.
- No commits and no pushes while the spec is being written.
- On approval of the tasks: one commit with the three documents, message `docs(repeated-runs): requirements, design and tasks`, then push.
- Never run `scripts/run_experiment.py --yes`. When a step needs it, stop and ask the author, who runs it.
- The runner refuses a Dirty_Tree, so each task commit must land before the author runs the experiment.
- Files that are not part of this feature and are modified or untracked in the working tree (for example `.kiro/specs/aws-deploy/`, `README.md`, `pyproject.toml`, `uv.lock`, `template.yaml`) are never added to a task commit. Stage files by name.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "3.2", "6.1"] },
    { "id": 3, "tasks": ["2.3", "3.3", "4.1", "6.2"] },
    { "id": 4, "tasks": ["3.4", "4.2", "6.3"] },
    { "id": 5, "tasks": ["4.3"] }
  ]
}
```
