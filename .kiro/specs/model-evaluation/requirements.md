# Requirements Document

## Introduction

This feature runs the writer agent on several Amazon Bedrock models, measures each run, and publishes the evidence as public GitHub gists linked from the README. It adds a model catalog (`models.json`), an experiment runner (`scripts/run_experiment.py`), a summarizer (`scripts/summarize_runs.py`), a gist generator (`scripts/make_gists.py`), a publisher (`scripts/publish_gists.sh`) and an `## Evidence` section in the README. The AWS region is `us-east-1`, always read from `AWS_REGION`. Every run file records the git commit of this repository, and the runner refuses to call models when tracked files have uncommitted changes.

Scripts follow the style of `scripts/run_writer.py`: a `main(argv, ...)` function with injectable dependencies, so tests run without AWS and without a model. The agent input comes from the existing `agent_input` function in `opsmem/manual.py`, and the system prompt from `SYSTEM_PROMPT` in `opsmem/writer.py`.

Out of scope: AWS deployment, review with baits, incident replay.

## Glossary

- **Model_Catalog**: The file `models.json`, one entry per model.
- **Model_Entry**: One entry of the Model_Catalog with the fields `label`, `name`, `model_id`, `input_usd_per_million`, `output_usd_per_million`, `price_source`.
- **Experiment_Runner**: The script `scripts/run_experiment.py`.
- **Run_File**: A JSON file `<out>/<label>.json` produced by the Experiment_Runner for one model.
- **Run_Directory**: A directory of Run_Files, by default `runs/<UTC date>`.
- **Writer**: The function `run_writer` in `opsmem/writer.py`, which runs one writer agent and returns a result with a trace.
- **Trace**: The list of tool-call entries, each with arguments and a result text, returned by the Writer.
- **Summarizer**: The script `scripts/summarize_runs.py`.
- **Results_Table**: The Markdown table with the columns Model, Saved, Tool calls, Rejections, Tokens in / out, Cost, Escalated.
- **Gist_Generator**: The script `scripts/make_gists.py`.
- **Gist_File**: A Markdown file in `gists/` produced by the Gist_Generator.
- **Publisher**: The script `scripts/publish_gists.sh`.
- **Gist_Index**: The file `gists/index.json`, mapping each Gist_File name to its gist URL.
- **Saved_Entry**: A Trace entry whose result starts with `Saved as draft`.
- **Rejection_Entry**: A Trace entry whose result starts with `REJECTED`.
- **Stopped_Reply**: A Trace entry whose result starts with `STOPPED`. It is not a Rejection_Entry.
- **Failed_Run**: A Run_File recording that a model failed to start, with the error text.
- **Finished_Model**: A model whose Run_File is not a Failed_Run.
- **Full_Save_Model**: A model whose Run_File has 6 Saved_Entries.
- **Commit**: The output of `git rev-parse HEAD` for this repository, stored as `commit` in each Run_File.
- **Dirty_Tree**: A state in which `git status --porcelain` reports uncommitted changes to tracked files. Untracked files do not make the tree dirty.
- **Cost_Upper_Bound**: The estimated maximum cost of an experiment, computed from 40 tool calls per run and a fixed per-call token budget stated in the code.
- **Evidence_Section**: The `## Evidence` section of the README.

## Requirements

### Requirement 1: Model catalog

**User Story:** As the author, I want a catalog of models with prices, so that cost is computed from one documented source.

#### Acceptance Criteria

1. THE Model_Catalog SHALL contain one Model_Entry for each of claude-sonnet-4-6, claude-haiku-4-5, nova-2-lite, nova-micro and ministral-3-3b.
2. THE Model_Catalog SHALL store for each Model_Entry the fields `label`, `name`, `model_id`, `input_usd_per_million`, `output_usd_per_million` and `price_source`.
3. THE Model_Catalog SHALL hold the names Claude Sonnet 4.6, Claude Haiku 4.5, Amazon Nova 2 Lite, Amazon Nova Micro and Ministral 3 3B for the five labels, in that order.
4. THE Model_Catalog SHALL hold the on-demand list prices in `us-east-1` of 3.00/15.00, 1.00/5.00, 0.33/2.75, 0.035/0.14 and 0.10/0.10 USD per million input/output tokens for the five labels, in that order.
5. THE Model_Catalog SHALL hold the model identifiers `us.anthropic.claude-sonnet-4-6`, `us.anthropic.claude-haiku-4-5-20251001-v1:0`, `us.amazon.nova-2-lite-v1:0`, `us.amazon.nova-micro-v1:0` and `mistral.ministral-3-3b-instruct` for the five labels, in that order.
6. THE Model_Catalog SHALL hold as `price_source` the value "Bedrock pricing page" for the two Claude entries and "AWS Price List API" for the three other entries.
7. WHEN a cost is shown in any output of this feature, THE System SHALL state that US cross-region inference profiles can be billed slightly higher than the list price.

### Requirement 2: Cost estimate and confirmation

**User Story:** As the author, I want the runner to show what it will call and what it can cost before any call, so that no model is called by accident.

#### Acceptance Criteria

1. WHEN the Experiment_Runner starts, THE Experiment_Runner SHALL check the configuration (`OPSMEM_LOCAL_PG` or the Aurora variables, and `AWS_REGION`) before any model call.
2. IF the configuration is incomplete, THEN THE Experiment_Runner SHALL print the missing variable names and exit with a non-zero code without calling any model.
3. THE Experiment_Runner SHALL accept the arguments `--models <label,...>`, `--out <directory>` and `--yes`.
4. WHERE `--models` is omitted, THE Experiment_Runner SHALL select all Model_Entries of the Model_Catalog.
5. WHERE `--out` is omitted, THE Experiment_Runner SHALL use `runs/<date>`, where `<date>` is the current UTC date.
6. IF `--models` contains a label that is not in the Model_Catalog, THEN THE Experiment_Runner SHALL print the unknown label and exit with a non-zero code without calling any model.
7. WHEN the configuration is valid, THE Experiment_Runner SHALL print the selected models and the Cost_Upper_Bound before any model call.
8. THE Experiment_Runner SHALL compute the Cost_Upper_Bound from at most 40 tool calls per run and a fixed per-call token budget defined as a named constant in the code.
9. IF `--yes` is not given, THEN THE Experiment_Runner SHALL exit after printing the cost estimate without calling any model.

### Requirement 3: Clean commit guard

**User Story:** As the author, I want every run tied to a clean commit, so that the evidence can be reproduced from the repository.

#### Acceptance Criteria

1. WHEN `--yes` is given and the cost estimate has been printed, THE Experiment_Runner SHALL run `git status --porcelain` before any model call.
2. IF the tree is a Dirty_Tree, THEN THE Experiment_Runner SHALL print a message telling the user to commit first, and exit with a non-zero code without calling any model.
3. WHILE the only uncommitted paths are untracked files, THE Experiment_Runner SHALL proceed with the experiment.
4. WHEN `--yes` is not given, THE Experiment_Runner SHALL skip the Dirty_Tree check.
5. WHEN the Dirty_Tree check passes, THE Experiment_Runner SHALL read the Commit with `git rev-parse HEAD`.
6. THE Experiment_Runner SHALL store the Commit as `commit` in every Run_File, including the Run_File of a Failed_Run.
7. IF a git command fails, THEN THE Experiment_Runner SHALL print the error and exit with a non-zero code without calling any model.

### Requirement 4: Per-model runs

**User Story:** As the author, I want one writer run per model with the full result saved, so that every figure can be checked against the raw trace.

#### Acceptance Criteria

1. WHEN the checks of Requirements 2 and 3 pass, THE Experiment_Runner SHALL run the Writer once for each selected model, in the order of the Model_Catalog, in mode `instructive`, for installation `install-07`, with the text returned by `agent_input` as input.
2. WHEN a run ends, THE Experiment_Runner SHALL save the full result of the Writer, including the Trace, as `<out>/<label>.json`.
3. THE Experiment_Runner SHALL add `model_id`, `label`, `mode`, `commit` and the UTC start time to each Run_File.
4. IF `<out>/<label>.json` already exists, THEN THE Experiment_Runner SHALL leave the existing file unchanged, print a message naming the file, and skip that model.
5. IF a model fails to start, THEN THE Experiment_Runner SHALL record a Failed_Run with the error text, and continue with the next model.
6. WHEN all selected models have been processed, THE Experiment_Runner SHALL exit with code 0.

### Requirement 5: Summary table

**User Story:** As the author, I want a deterministic summary table of the runs, so that the published numbers are reproducible.

#### Acceptance Criteria

1. WHEN the Summarizer is given a Run_Directory, THE Summarizer SHALL read every Run_File of that directory and print the Results_Table in Markdown.
2. THE Summarizer SHALL order the rows of the Results_Table by cost descending, and by label ascending for equal costs.
3. THE Summarizer SHALL write the Saved column as `N of 6`, where N is the number of Saved_Entries.
4. THE Summarizer SHALL count in the Rejections column the Trace entries that are Rejection_Entries, and exclude Stopped_Replies.
5. THE Summarizer SHALL compute the Cost column as input tokens times `input_usd_per_million` plus output tokens times `output_usd_per_million`, both divided by 1,000,000, using the prices of the Model_Catalog, in USD with 4 decimals, for example `$0.0022` for 51,844 input tokens and 2,454 output tokens at 0.035/0.14.
6. THE Summarizer SHALL show the Model column with the `name` of the Model_Entry, and the Tokens in / out and Tool calls columns from the Run_File.
7. THE Summarizer SHALL show in the Escalated column whether the run ended with a Stopped_Reply.
8. WHEN the Run_File is a Failed_Run, THE Summarizer SHALL show the row with 0 of 6 saved, zero cost, and the error text in the Escalated column.
9. WHERE `--rows` is given, THE Summarizer SHALL print for each Full_Save_Model the saved rows (request, service, field, type, unit, sampling) taken from the call arguments of the Saved_Entries.
10. WHERE `--rows` is given, THE Summarizer SHALL state whether the saved rows are identical across all Full_Save_Models.
11. WHEN the Summarizer reads the same files twice, THE Summarizer SHALL produce identical output.
12. THE Summarizer SHALL take every number from the Run_Files and the Model_Catalog.
13. IF the directory contains no Run_File, THEN THE Summarizer SHALL print an error and exit with a non-zero code.
14. THE Summarizer SHALL print the price note of Requirement 1, criterion 7 below the Results_Table.

### Requirement 6: Summarizer fixtures

**User Story:** As the author, I want the Summarizer verified on small hand-written fixtures, so that every column and the ordering are tested without AWS.

#### Acceptance Criteria

1. THE test suite SHALL include hand-written synthetic Run_Files in `tests/fixtures/runs/`, never published, with one model that saves 6 of 6 after rejections, one model stopped by escalation with a Stopped_Reply, and one Failed_Run.
2. THE test suite SHALL check every column of the Results_Table for the fixtures.
3. THE test suite SHALL check the cost rounding to 4 decimals with 51,844 input tokens and 2,454 output tokens at 0.035/0.14 giving `$0.0022`.
4. THE test suite SHALL check that a Stopped_Reply is not counted as a rejection.
5. THE test suite SHALL check the order of the rows by cost descending.
6. THE test suite SHALL check the statement on identical rows for the fixtures.

### Requirement 7: Gist generation

**User Story:** As a reader of the article, I want gists generated only from the run data, so that no statement exceeds the evidence.

#### Acceptance Criteria

1. WHEN the Gist_Generator is given a Run_Directory, THE Gist_Generator SHALL write Gist_Files into `gists/`.
2. THE Gist_Generator SHALL generate Gist_Files only from the Run_Files, the Model_Catalog, `agent_input` and `SYSTEM_PROMPT`.
3. THE Gist_Generator SHALL choose which model appears in which Gist_File from the Run_Files, and not from model names fixed in the code.
4. WHEN the Gist_Generator runs twice on the same inputs, THE Gist_Generator SHALL produce identical files.
5. THE Gist_Generator SHALL write `agent-learns-from-rejections.md` for the cheapest Full_Save_Model, with the model name in the title, two sentences on what the run shows, a setup line, the agent input and the system prompt in text blocks, the raw Trace with one unedited JSON line per tool call, the summary line, and the rows the database kept.
6. THE Gist_Generator SHALL write in the setup line the repository link, Strands Agents, Amazon Bedrock in `us-east-1`, local PostgreSQL 16 in Docker, the date, the fictional installation, and the Commit read from the Run_Files.
7. THE Gist_Generator SHALL write `five-models.md` with the same header, the Results_Table with the price note, the rows kept by the Finished_Models, and the identical-rows statement computed as in Requirement 5.
8. WHERE at least one Finished_Model has fewer than 6 Saved_Entries, THE Gist_Generator SHALL write `small-models-fail-safe.md` with the same header and, for each such model, its raw Trace, the escalation reason, and the number of rows kept counted from the Trace.
9. WHERE every Finished_Model has 6 Saved_Entries, THE Gist_Generator SHALL write no `small-models-fail-safe.md`.
10. THE Gist_Generator SHALL end every Gist_File with the line "Companion to the article *Predictability, not eloquence* on AWS Builder Center."
11. IF the Run_Files do not hold the same Commit, THEN THE Gist_Generator SHALL print the differing commits and exit with a non-zero code without writing a Gist_File.
12. IF no Full_Save_Model exists, THEN THE Gist_Generator SHALL skip `agent-learns-from-rejections.md` and print a message naming the skipped file.

### Requirement 8: Publishing

**User Story:** As the author, I want to publish the gists myself and link them from the README, so that publishing remains a deliberate outward action.

#### Acceptance Criteria

1. WHEN the Publisher runs and the Gist_Index holds no URL for a Gist_File, THE Publisher SHALL publish the file with `gh gist create --public`.
2. WHEN the Publisher runs and the Gist_Index holds a URL for a Gist_File, THE Publisher SHALL update the gist with `gh gist edit`.
3. WHEN the Publisher finishes, THE Publisher SHALL write the Gist_Index mapping each Gist_File name to its URL.
4. IF a `gh` command fails, THEN THE Publisher SHALL print the error and exit with a non-zero code.
5. THE Evidence_Section SHALL contain one line per gist with its title and link.
6. THE Evidence_Section SHALL contain one line on how to regenerate the gists with `summarize_runs.py` and `make_gists.py`.
7. WHEN a task would run the Publisher, THE task SHALL stop and ask the author, and the author runs it.

### Requirement 9: Offline tests

**User Story:** As the author, I want tests that need no AWS and no model, so that the feature is verified offline.

#### Acceptance Criteria

1. THE test suite SHALL check that `make_gists.py` run twice on the same inputs produces identical files.
2. THE test suite SHALL check that the Experiment_Runner without `--yes` calls no model, using a fake agent.
3. THE test suite SHALL check that an existing Run_File is never overwritten.
4. THE test suite SHALL check that a failed model start is recorded as a Failed_Run and that the next model runs.
5. THE test suite SHALL check that the Experiment_Runner with `--yes` and a Dirty_Tree exits with a non-zero code, prints a message telling the user to commit first, and calls no model.
6. THE test suite SHALL check that untracked files alone do not block the Experiment_Runner.
7. THE test suite SHALL check that the Dirty_Tree check runs after the cost estimate is printed and not without `--yes`.
8. THE test suite SHALL check that every Run_File, including a Failed_Run, holds the `commit` field.
9. THE test suite SHALL check that the setup line of the gists holds the Commit read from the Run_Files.
10. THE test suite SHALL check that the Gist_Generator writes `small-models-fail-safe.md` only when a Finished_Model has fewer than 6 Saved_Entries.
11. THE Experiment_Runner, the Summarizer and the Gist_Generator SHALL expose `main(argv, ...)` with injectable dependencies for the model runner, the git commands, the clock and the output streams, in the style of `scripts/run_writer.py`.

### Requirement 10: Evidence and workflow

**User Story:** As the author, I want the run files committed as evidence and the workflow guarded, so that the published numbers trace to reviewed data.

#### Acceptance Criteria

1. WHEN the author has reviewed the Run_Files, THE author SHALL commit them under `runs/<date>/`.
2. WHEN a task is complete and its tests pass, THE task SHALL commit and push that task only, in the form `feat(model-evaluation): <task number> <task title in lowercase>`, then stop and wait for the author.
3. WHEN the author approves `tasks.md`, THE task SHALL commit the three spec documents as `docs(model-evaluation): requirements, design and tasks` and push.
4. THE commit messages SHALL end with a blank line and the trailer `Co-Authored-By: Kiro`, without an email.
5. WHEN a push completes, THE task SHALL show the output of `git log --oneline -3`.
6. THE tasks SHALL leave the execution of `scripts/run_experiment.py --yes` and `scripts/publish_gists.sh` to the author.
