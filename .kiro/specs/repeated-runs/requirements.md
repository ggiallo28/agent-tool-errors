# Requirements Document

## Introduction

This feature runs the same model several times and compares the rows each run saved. It also lets the author choose the rejection mode (`raw` or `instructive`) of an evaluation. It extends the `model-evaluation` spec: it adds the arguments `--repeat` and `--mode` to `scripts/run_experiment.py` and the argument `--repeats` to `scripts/summarize_runs.py`. When the new arguments are not given, no existing behaviour changes.

The scripts keep the style of the `model-evaluation` spec: a `main(argv, ...)` function with injectable dependencies, so tests run without AWS and without a model. The AWS region is `us-east-1`, always read from `AWS_REGION`.

Out of scope: charts, new gists, README changes, new models. The only change to `scripts/make_gists.py` is the selection of runs in Requirement 7, criterion 10.

## Glossary

- **Experiment_Runner**: The script `scripts/run_experiment.py`.
- **Summarizer**: The script `scripts/summarize_runs.py`.
- **Gist_Generator**: The script `scripts/make_gists.py`.
- **Run_File**: A JSON file produced by the Experiment_Runner for one run of one model, as defined in the `model-evaluation` spec.
- **Run_Directory**: A directory of Run_Files.
- **Mode**: The rejection mode of a run, `raw` or `instructive`, passed to `RunContext` and saved as `mode` in the Run_File.
- **Repeat_Count**: The value `N` of `--repeat`.
- **Base_Name**: The label of the model, followed by `-raw` when the Mode is `raw`. For example `nova-micro` and `nova-micro-raw`.
- **Repeated_Run**: A Run_File that holds the fields `repeat` and `repeat_count`. It is recognised only from these fields, never from its file name.
- **Single_Run**: A Run_File that holds neither `repeat` nor `repeat_count`.
- **Complete_Run**: A Run_File that is not a Failed_Run and has 6 Saved_Entries (6 of 6).
- **First_Complete_Run**: The Complete_Run of a model and Mode with the lowest file name in ascending order.
- **Row_Key**: For one saved request, the tuple of request, service, field, type, unit and sampling taken from the call arguments of its Saved_Entry. The signal name is not part of the Row_Key.
- **Same_Rows**: Two Complete_Runs have Same_Rows when their Row_Keys are equal for all six requests.
- **Repeats_Table**: The Markdown table printed by the Summarizer with `--repeats`, with the columns Model, Mode, Runs, Saved 6 of 6, Same rows as the first complete run, Tool calls (min to max), Rejections (min to max).
- **Differing_Rows_Listing**: The lines printed under the Repeats_Table for the Row_Keys that differ from the First_Complete_Run.
- **Results_Table**, **Failed_Run**, **Saved_Entry**, **Rejection_Entry**, **Stopped_Reply**, **Trace**, **Cost_Upper_Bound**: As defined in the `model-evaluation` spec.

## Requirements

### Requirement 1: Repeat argument

**User Story:** As the author, I want to run each model several times in one command, so that I can see whether the same model saves the same rows.

#### Acceptance Criteria

1. THE Experiment_Runner SHALL accept the argument `--repeat N`, where N is a whole number from 1 to 20.
2. WHERE `--repeat` is omitted, THE Experiment_Runner SHALL use a Repeat_Count of 1.
3. IF `--repeat` is not a whole number from 1 to 20, THEN THE Experiment_Runner SHALL print an error naming the accepted range and exit with a non-zero code without calling any model.
4. WHEN the Repeat_Count is greater than 1, THE Experiment_Runner SHALL run each selected model Repeat_Count times, one after the other, in the order of the Model_Catalog.
5. THE Experiment_Runner SHALL give each run its own `run_id`, which contains the model label, the Mode and the repetition number (from 1), so that the `run_id` values of one command are unique whatever the start times of the runs.
6. THE Experiment_Runner SHALL save `repeat` (the repetition number, from 1) and `repeat_count` (the Repeat_Count) in every Run_File, including the Run_File of a Failed_Run, WHEN the Repeat_Count is greater than 1.
7. WHILE the Repeat_Count is 1, THE Experiment_Runner SHALL save neither `repeat` nor `repeat_count`.
8. WHEN a run fails to start, THE Experiment_Runner SHALL record it as a Failed_Run as before and start the next run.

### Requirement 2: Mode argument

**User Story:** As the author, I want to choose the rejection mode of an evaluation, so that I can compare `raw` and `instructive` rejections on the same models.

#### Acceptance Criteria

1. THE Experiment_Runner SHALL accept the argument `--mode` with the values `raw` and `instructive`.
2. WHERE `--mode` is omitted, THE Experiment_Runner SHALL use the Mode `instructive`.
3. IF `--mode` has another value, THEN THE Experiment_Runner SHALL print an error naming the accepted values and exit with a non-zero code without calling any model.
4. THE Experiment_Runner SHALL pass the Mode to the run context of every run.
5. THE Experiment_Runner SHALL save the Mode as `mode` in every Run_File, including the Run_File of a Failed_Run.

### Requirement 3: File names

**User Story:** As the author, I want predictable file names that never overwrite earlier evidence, so that every run stays available for review.

#### Acceptance Criteria

1. WHILE the Repeat_Count is 1, THE Experiment_Runner SHALL name the Run_File `<out>/<Base_Name>.json`.
2. WHILE the Repeat_Count is greater than 1, THE Experiment_Runner SHALL name the Run_Files `<out>/<Base_Name>-01.json` to `<out>/<Base_Name>-NN.json`, where NN is the Repeat_Count with two digits.
3. WHERE the Mode is `raw`, THE Experiment_Runner SHALL use `<label>-raw` as the Base_Name.
4. WHERE the Mode is `instructive`, THE Experiment_Runner SHALL use `<label>` as the Base_Name.
5. IF the target Run_File already exists, THEN THE Experiment_Runner SHALL leave it unchanged, print a message naming the file, and skip that run.
6. WHEN a run is skipped because its file exists, THE Experiment_Runner SHALL continue with the next run.

### Requirement 4: Cost and confirmation

**User Story:** As the author, I want the cost bound to cover all repeated runs and no model called without confirmation, so that a repeat count never causes a surprise.

#### Acceptance Criteria

1. THE Experiment_Runner SHALL multiply the Cost_Upper_Bound printed before `--yes` by the Repeat_Count.
2. IF `--yes` is not given, THEN THE Experiment_Runner SHALL exit after printing the cost estimate without calling any model, for any Repeat_Count and Mode.
3. WHEN neither `--repeat` nor `--mode` is given, THE Experiment_Runner SHALL print the same cost estimate, create the same file names and save the same fields as before this feature, except the value of `run_id`.
4. THE checks of the `model-evaluation` spec on the configuration and on a Dirty_Tree SHALL apply unchanged.

### Requirement 5: Repeats table

**User Story:** As the author, I want one line per model and mode that shows how stable the runs are, so that I can state the result with numbers.

#### Acceptance Criteria

1. WHEN the Summarizer is given a Run_Directory and `--repeats`, THE Summarizer SHALL print the Repeats_Table with one line for each model and Mode that has at least one Repeated_Run or at least one Run_File with Mode `raw`.
2. THE Summarizer SHALL read the model from the `label` field and the Mode from the `mode` field of each Run_File, and group the Run_Files by these two values.
   A Run_File without a `mode` field SHALL be read as having the Mode `instructive`, wherever this document uses the Mode of a Run_File.
3. THE Summarizer SHALL write the Model column with the `name` of the Model_Entry.
4. THE Summarizer SHALL write the Runs column as the number of all Run_Files of the model and Mode, Single_Runs and Repeated_Runs, including Failed_Runs. A single run with Mode `raw` is therefore listed with Runs 1.
5. THE Summarizer SHALL write the Saved 6 of 6 column as `K of N`, where K is the number of Complete_Runs and N is the number in the Runs column.
6. THE Summarizer SHALL write the Same rows as the first complete run column as `K of M`, where M is the number of Complete_Runs and K is the number of Complete_Runs with Same_Rows as the First_Complete_Run, counting the First_Complete_Run itself.
7. WHERE the model and Mode have no Complete_Run, THE Summarizer SHALL write `none` in the Same rows as the first complete run column.
8. THE Summarizer SHALL write the Tool calls column as `min to max` of the `tool_calls` of the Run_Files that are not Failed_Runs, and `none` where all are Failed_Runs.
9. THE Summarizer SHALL write the Rejections column as `min to max` of the number of Rejection_Entries of the Run_Files that are not Failed_Runs, and `none` where all are Failed_Runs.
   In Mode `raw` a Rejection_Entry is a Trace entry whose result starts with `ERROR: `, because the tool returns the database message without the `REJECTED` prefix.
   The Repeats_Table counts both forms, in every Mode, and a Stopped_Reply is never counted.
   The Results_Table keeps the definition of Rejection_Entry of the `model-evaluation` spec.
10. WHERE the minimum and the maximum are equal, THE Summarizer SHALL write the single number.
11. THE Summarizer SHALL order the lines by the order of the Model_Catalog, and `instructive` before `raw` for the same model.
12. THE Summarizer SHALL print below the Repeats_Table a note stating that the signal name is not compared.
13. IF no model and Mode has a Repeated_Run or a Run_File with Mode `raw`, THEN THE Summarizer SHALL print the Repeats_Table header and the note, without lines.

### Requirement 6: Differing rows

**User Story:** As the author, I want to see which rows differ, so that I can quote the difference and not only count it.

#### Acceptance Criteria

1. IF the Complete_Runs of a model and Mode do not all have Same_Rows, THEN THE Summarizer SHALL print the Differing_Rows_Listing under the Repeats_Table.
2. THE Summarizer SHALL print in the Differing_Rows_Listing one line for each run and request whose Row_Key differs from the Row_Key of the First_Complete_Run for the same request.
3. THE Summarizer SHALL write in each line the model name, the Mode, the file name, the request, and the Row_Key values of that run and of the First_Complete_Run.
4. THE Summarizer SHALL order the lines by model, Mode, file name and request.
5. IF all Complete_Runs of every model and Mode have Same_Rows, THEN THE Summarizer SHALL print no Differing_Rows_Listing.

### Requirement 7: Existing outputs

**User Story:** As the author, I want the published summary and the gists to stay identical, so that the existing evidence is not disturbed by new runs.

#### Acceptance Criteria

1. WHERE `--repeats` is omitted, THE Summarizer SHALL produce the same output, byte for byte, as before this feature on the existing directories, including `runs/2026-11-10`.
2. WHERE `--repeats` is omitted, THE Summarizer SHALL include in the Results_Table only Single_Runs with Mode `instructive`, so Repeated_Runs and runs with Mode `raw` never reach it.
3. WHERE `--repeats` is given, THE Summarizer SHALL print the Repeats_Table of Requirement 5 after the Results_Table, and the Results_Table SHALL follow criterion 2.
   WHERE `--repeats` is given and the directory has no Single_Run with Mode `instructive`, THE Summarizer SHALL print only the Repeats_Table, with no Results_Table and no error, and exit with code 0.
4. THE Summarizer SHALL recognise a Repeated_Run only from the fields `repeat` and `repeat_count`, and never from the file name, because a model label can end with digits, as in `claude-sonnet-4-6`.
5. A Run_File without `repeat` and `repeat_count` SHALL be a Single_Run, whatever its file name.
6. WHEN the Summarizer reads the same files twice, THE Summarizer SHALL produce identical output.
7. THE Summarizer SHALL take every number from the Run_Files and the Model_Catalog.
8. IF the directory contains no Run_File, THEN THE Summarizer SHALL print an error and exit with a non-zero code, with or without `--repeats`.
9. IF `--repeats` is omitted and the directory contains Run_Files but none is a Single_Run with Mode `instructive`, THEN THE Summarizer SHALL print an error saying that no such run exists and that `--repeats` lists the others, and exit with a non-zero code.
10. THE Gist_Generator SHALL use only the Single_Runs with Mode `instructive` of the Run_Directory, and SHALL produce on `runs/2026-11-10` the same files, byte for byte, as before this feature.

### Requirement 8: Offline tests

**User Story:** As the author, I want tests that need no AWS and no model, so that the feature is verified offline.

#### Acceptance Criteria

1. THE test suite SHALL include hand-written synthetic Run_Files in `tests/fixtures/runs-repeated/`, never published, with: three Complete_Runs of one model with identical rows, one Complete_Run of the same model with a different field for one request, one run stopped by escalation, and two runs in Mode `raw`.
2. THE test suite SHALL check every column of the Repeats_Table for the fixtures.
3. THE test suite SHALL check the Differing_Rows_Listing for the fixtures.
4. THE test suite SHALL check that the signal name is not compared and that the note says so.
5. THE test suite SHALL check, with a fake agent, the file names produced by `--repeat 3`, by `--mode raw`, and by both together.
6. THE test suite SHALL check that an existing file is never overwritten.
7. THE test suite SHALL check that `--repeat 0` and `--repeat 21` are refused without calling any model.
8. THE test suite SHALL check that without `--yes` no model is called and that the printed Cost_Upper_Bound is multiplied by the Repeat_Count.
9. THE test suite SHALL check that the Mode reaches the run context and the Run_File.
10. THE test suite SHALL check that the output of the Summarizer without `--repeats` on `runs/2026-11-10` is unchanged.
11. THE test suite SHALL check that the output of the Summarizer is the same on two reads of the same files.
12. THE test suite SHALL check, with a fake agent and a clock that returns the same second for every run, that the `run_id` values of one command with `--repeat 3` and of a command with a failed start are all different, and that each contains the Mode and the repetition number.
13. THE test suite SHALL check that `repeat` and `repeat_count` are saved in every Run_File, including a Failed_Run, with `--repeat 3`, and in none with `--repeat 1`.
14. THE test suite SHALL check that the Summarizer recognises Repeated_Runs from the fields and not from the file name, with a Run_File for a label that ends with digits and has a numeric suffix in its name but no `repeat` fields, and with a Repeated_Run whose name has no numeric suffix.
15. THE test suite SHALL check that a single run with Mode `raw` is absent from the Results_Table and present in the Repeats_Table with Runs 1.
16. THE test suite SHALL check that, for a directory that holds only Repeated_Runs, the Summarizer with `--repeats` prints only the Repeats_Table, with no Results_Table and no error, and exits with code 0, and that without `--repeats` it prints the error of Requirement 7, criterion 9 and exits with a non-zero code.
17. THE test suite SHALL check that Failed_Runs count in the Runs column and are skipped in the Tool calls and Rejections columns.
18. THE test suite SHALL check that the Gist_Generator on `runs/2026-11-10` produces the same files as before this feature, and that Repeated_Runs and runs with Mode `raw` in the Run_Directory do not reach any Gist_File.
19. THE test suite SHALL check that a Run_File without `mode` is read as Mode `instructive` by the Results_Table, the Repeats_Table and the Gist_Generator.
20. THE Experiment_Runner, the Summarizer and the Gist_Generator SHALL keep the injectable dependencies of `main(argv, ...)`, so the tests need no AWS and no model.
21. THE test suite SHALL check that the Rejections column of the Repeats_Table counts a Trace entry whose result starts with `REJECTED` and a Trace entry whose result starts with `ERROR: `, counts no Stopped_Reply, and that a Run_File in Mode `raw` with `ERROR: ` entries gives a non-zero count, while the Results_Table counts the entries as the `model-evaluation` spec defines them.

### Requirement 9: Workflow

**User Story:** As the author, I want the work committed in small steps and the model runs left to me, so that I review each step and control every cost.

#### Acceptance Criteria

1. WHEN the author approves `tasks.md`, THE task SHALL commit the three spec documents as `docs(repeated-runs): requirements, design and tasks` and push.
2. WHEN a task is complete and its tests pass, THE task SHALL commit and push that task only, in the form `feat(repeated-runs): <task number> <task title in lowercase>`, then stop and wait for the author.
3. THE commit messages SHALL end with a blank line and the trailer `Co-Authored-By: Kiro`, without an email.
4. WHEN a push completes, THE task SHALL show the output of `git log --oneline -3`.
5. THE tasks SHALL leave the execution of `scripts/run_experiment.py --yes` to the author.
