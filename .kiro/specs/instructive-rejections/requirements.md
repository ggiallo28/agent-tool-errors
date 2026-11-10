# Requirements Document

## Introduction

This spec covers the module `opsmem/errors.py`, which turns a database rejection of a configuration row into the text the model reads. It offers two modes. In raw mode the model sees the database message untouched. In instructive mode the model sees the name of the violated rule, a statement that nothing was saved, and a one-line instruction that names the parameter to change and lists up to 10 valid values read from the database. The module also holds the README step that shows both modes with real output. Strings in this document are an external contract. Other tools compare them byte for byte, so they must be kept exactly.

Out of scope: the agent, the escalation after repeated rejections and the experiment.

## Glossary

- **Errors_Module**: The module `opsmem/errors.py`.
- **Rejection_Renderer**: The function `render(rule, valid, mode, raw_message) -> str` of the Errors_Module.
- **Rule_Classifier**: The function `classify(message) -> str` of the Errors_Module.
- **Valid_Values_Lookup**: The part of the Errors_Module that reads the valid values for a rule from the Database.
- **Instruction_Table**: The dictionary `INSTRUCTIONS` of the Errors_Module, mapping a rule name to an instruction template.
- **Rule**: A key of the Instruction_Table, or the string `unknown`.
- **Instruction**: The text of a template of the Instruction_Table after `{valid}` has been replaced.
- **Mode**: One of the strings `raw` and `instructive`.
- **Valid_List**: The text that replaces `{valid}` in a template, built from a list of valid values.
- **Database_Message**: The text of a database error, equal to `str(err)` of the exception held in `DatabaseError` of the Database_Object.
- **Proposal**: The values the agent sent for a configuration row: `request_id`, `service_id`, `signal_type`, `source_field` and `sample_s`.
- **Installation_Id**: The installation of the run, held by the run context.
- **Database**: The PostgreSQL database named `opsmemory`, as defined in the catalog-schema spec.
- **Database_Object**: The object returned by `connect(role)`, as defined in the catalog-schema spec.
- **Tool_Name**: The name of any tool the agent can call, including `propose_config`.
- **Sampling_Trigger_Message**: A message of the form `config_sampling_supported: sample_s <n> outside <min> to <max> for <field>`, as raised by the Sampling_Trigger of the catalog-schema spec.
- **SQLState_Marker**: The text `SQLState: ` followed by a five-character code, as it appears in a Data API error message.
- **Readme**: The file `README.md`, which already exists.

## Requirements

### Requirement 1: Instruction table

**User Story:** As a builder, I want one table with one instruction per rule, so that every rejection teaches the model the parameter to change in the same words on every run.

#### Acceptance Criteria

1. THE Errors_Module SHALL define the dictionary `INSTRUCTIONS` with exactly 14 keys: `config_field_exists`, `config_unit_matches_source`, `config_answers_request`, `config_service_matches_request`, `config_field_in_service`, `config_type_matches_request`, `config_sampling_requested`, `config_one_per_request`, `config_unit_allowed_for_type`, `config_sampling_supported`, `config_one_per_signal`, `config_one_per_field`, `signal_name_check` and `integer_input`.
2. THE Instruction_Table SHALL map `config_field_exists` to the string `Unknown source_field. Valid source_field: {valid}.`
3. THE Instruction_Table SHALL map `config_unit_matches_source` to the string `Wrong unit for this source_field. Valid unit: {valid}.`
4. THE Instruction_Table SHALL map `config_answers_request` to the string `Unknown request_id. Valid request_id: {valid}.`
5. THE Instruction_Table SHALL map `config_service_matches_request` to the string `Wrong service_id for this request. Valid service_id: {valid}.`
6. THE Instruction_Table SHALL map `config_field_in_service` to the string `This source_field is not in this service. Valid source_field: {valid}.`
7. THE Instruction_Table SHALL map `config_type_matches_request` to the string `Wrong signal_type for this request. Valid signal_type: {valid}.`
8. THE Instruction_Table SHALL map `config_sampling_requested` to the string `Wrong sample_seconds for this request. Valid sample_seconds: {valid}.`
9. THE Instruction_Table SHALL map `config_one_per_request` to the string `This request_id is already configured.`
10. THE Instruction_Table SHALL map `config_unit_allowed_for_type` to the string `This unit is not allowed for this signal_type. Valid unit: {valid}.`
11. THE Instruction_Table SHALL map `config_sampling_supported` to the string `sample_seconds not supported by this source_field. Valid range: {valid}.`
12. THE Instruction_Table SHALL map `config_one_per_signal` to the string `This signal_name is already used. Choose another signal_name.`
13. THE Instruction_Table SHALL map `config_one_per_field` to the string `This source_field is already configured.`
14. THE Instruction_Table SHALL map `signal_name_check` to the string `signal_name must be lowercase letters, digits and underscores, 3 to 41 characters.`
15. THE Instruction_Table SHALL map `integer_input` to the string `sample_seconds must be a whole number of seconds.`
16. THE Instruction_Table SHALL contain no value that includes a Tool_Name.
17. THE Instruction_Table SHALL contain no value that includes the text `propose_config`.

### Requirement 2: Rendering a rejection

**User Story:** As a builder, I want one function that builds the text the model reads in each mode, so that the two modes can be compared on the same rejection.

#### Acceptance Criteria

1. WHEN `render(rule, valid, mode, raw_message)` is called with `mode` equal to `raw`, THE Rejection_Renderer SHALL return the string `ERROR: ` followed by `raw_message` with no change to `raw_message`.
2. WHEN `render(rule, valid, mode, raw_message)` is called with `mode` equal to `instructive`, THE Rejection_Renderer SHALL return the string `REJECTED (<rule>). Not saved. ` followed by the Instruction, where `<rule>` is the value of `rule`.
3. WHEN the Rejection_Renderer builds an Instruction for a Rule that is a key of the Instruction_Table, THE Rejection_Renderer SHALL replace every occurrence of `{valid}` in the template with the Valid_List.
4. WHEN the template of a Rule contains no `{valid}`, THE Rejection_Renderer SHALL return the template unchanged as the Instruction.
5. IF `rule` is not a key of the Instruction_Table, THEN THE Rejection_Renderer SHALL use the string `Rejected.` as the Instruction.
6. WHEN `valid` holds 10 or fewer values, THE Rejection_Renderer SHALL build the Valid_List by joining all values with the separator `, ` in their given order.
7. WHEN `valid` holds more than 10 values, THE Rejection_Renderer SHALL build the Valid_List by joining the first 10 values, in their given order, with the separator `, `.
8. IF `valid` holds no values, THEN THE Rejection_Renderer SHALL use the string `none listed` as the Valid_List.
9. IF `mode` is neither `raw` nor `instructive`, THEN THE Rejection_Renderer SHALL raise an error whose message contains the invalid value.
10. THE Rejection_Renderer SHALL return an Instruction that contains no Tool_Name.

### Requirement 3: Classifying a database message

**User Story:** As a builder, I want the rule read from the database message in a fixed order of checks, so that the same message always gives the same rule on both backends.

#### Acceptance Criteria

1. WHEN `classify(message)` is called, THE Rule_Classifier SHALL collect constraint names from `message` in order of appearance, taking a name from each text of the form `constraint "<name>"`, `CONSTRAINT: <name>`, `CONSTRAINT=<name>` and from each bare word that starts with `config_`.
2. WHEN a collected name is a key of the Instruction_Table, THE Rule_Classifier SHALL return that name, choosing the first such name in order of appearance among the names that are a key or end with `signal_name_check`.
3. WHEN the chosen name ends with `signal_name_check`, THE Rule_Classifier SHALL return `signal_name_check`.
4. WHEN no collected name qualifies under criterion 2 and `message` contains a SQLState_Marker with the code `22P02`, THE Rule_Classifier SHALL return `integer_input`.
5. WHEN no collected name qualifies under criterion 2 and `message` contains the text `invalid input syntax for type integer`, THE Rule_Classifier SHALL return `integer_input`.
6. WHEN criteria 2 to 5 return no Rule and `message` contains the text `signal_name` and contains the text `check` in any letter case, as a substring and not as a separate word (so it also matches inside a longer name such as `collection_configs_signal_name_check`), THE Rule_Classifier SHALL return `signal_name_check`.
7. IF criteria 2 to 6 return no Rule, THEN THE Rule_Classifier SHALL return `unknown`.
8. WHEN `message` is a Sampling_Trigger_Message, THE Rule_Classifier SHALL return `config_sampling_supported`.
9. WHEN `message` is the text of a foreign key violation that names the constraint `config_field_exists`, THE Rule_Classifier SHALL return `config_field_exists`.
10. WHEN `message` is the text of a CHECK violation that names the constraint `collection_configs_signal_name_check`, THE Rule_Classifier SHALL return `signal_name_check`.
11. WHEN `message` carries the SQLState_Marker `SQLState: 22P02` and names no constraint, THE Rule_Classifier SHALL return `integer_input`.
12. THE Rule_Classifier SHALL return a string that is either a key of the Instruction_Table or `unknown`.

### Requirement 4: Valid values from the database

**User Story:** As a builder, I want the valid values read from the database at each rejection, so that the model gets real values for the installation and nothing is hard-coded in the module.

#### Acceptance Criteria

1. WHEN a rejection is rendered in instructive mode, THE Valid_Values_Lookup SHALL read the valid values for the Rule from the Database through a Database_Object, using only SELECT statements.
2. THE Valid_Values_Lookup SHALL restrict every query on a table that has an `installation_id` column to rows whose `installation_id` equals the Installation_Id.
3. THE Valid_Values_Lookup SHALL return every valid value as a string.
4. WHEN the Rule is `config_answers_request`, THE Valid_Values_Lookup SHALL return all request ids of the installation, sorted.
5. WHEN the Rule is `config_service_matches_request`, THE Valid_Values_Lookup SHALL return the service id of the request named by the Proposal.
6. WHEN the Rule is `config_type_matches_request`, THE Valid_Values_Lookup SHALL return the signal type of the request named by the Proposal.
7. WHEN the Rule is `config_sampling_requested`, THE Valid_Values_Lookup SHALL return the sample seconds of the request named by the Proposal.
8. WHEN the Rule is `config_field_in_service`, THE Valid_Values_Lookup SHALL return the field names of the service named by the Proposal, sorted.
9. WHEN the Rule is `config_field_exists`, THE Valid_Values_Lookup SHALL return all field names of the installation, sorted.
10. WHEN the Rule is `config_unit_matches_source`, THE Valid_Values_Lookup SHALL return the unit of the field named by the Proposal.
11. WHEN the Rule is `config_unit_allowed_for_type`, THE Valid_Values_Lookup SHALL return the units allowed for the signal type named by the Proposal, sorted.
12. WHEN the Rule is `config_sampling_supported`, THE Valid_Values_Lookup SHALL return one value of the form `<min> to <max> seconds`, built from the minimum and maximum sample seconds of the field named by the Proposal.
13. WHEN the Rule is `config_one_per_request`, `config_one_per_signal`, `config_one_per_field`, `signal_name_check`, `integer_input` or `unknown`, THE Valid_Values_Lookup SHALL return no values and SHALL send no statement to the Database.
14. IF the Proposal names a request, service, field or signal type that the Database does not hold for the Installation_Id, THEN THE Valid_Values_Lookup SHALL return no values for the rules that depend on that name.
15. IF the Database_Object raises the exception held in `DatabaseError` during a lookup, THEN THE Valid_Values_Lookup SHALL return no values, so that the Rejection_Renderer shows `none listed`.

### Requirement 5: Test coverage without a database

**User Story:** As a builder, I want tests that need no database and no network, so that the contract strings are verified on every run.

#### Acceptance Criteria

1. THE test suite SHALL test the Rule_Classifier, the Rejection_Renderer and the Instruction_Table without a database connection and without network access.
2. THE test suite SHALL include a test that `classify` returns `config_field_exists` for a foreign key violation message that names `config_field_exists`.
3. THE test suite SHALL include a test that `classify` returns `config_sampling_supported` for the message `ERROR: config_sampling_supported: sample_s 5 outside 10 to 300 for api_p95`.
4. THE test suite SHALL include a test that `classify` returns `integer_input` for the message `ERROR: invalid input syntax for type integer: "every minute"`.
5. THE test suite SHALL include a test that `classify` returns `signal_name_check` for a check violation message that names `collection_configs_signal_name_check`.
6. THE test suite SHALL include a test that `classify` returns `integer_input` for a Data API style message that carries `SQLState: 22P02`.
7. THE test suite SHALL include a test that `render` in raw mode returns `ERROR: ` followed by the unchanged message.
8. THE test suite SHALL include a test that `render` in instructive mode with more than 10 valid values shows exactly the first 10 values.
9. THE test suite SHALL include a test that `render` in instructive mode with no valid values shows `none listed`.
10. THE test suite SHALL include a test that every value of the Instruction_Table does not contain the text `propose_config`.
11. THE test suite SHALL include a test of the exact string of each of the 14 entries of the Instruction_Table.
12. THE test suite SHALL include a test that `render` returns `REJECTED (<rule>). Not saved. Rejected.` for a rule that is not a key of the Instruction_Table.

### Requirement 6: README step "Verify without spending"

**User Story:** As a reader of the article, I want to see one real rejection in both modes and the reason the instruction never names a tool, so that I can verify the idea without spending on a model.

#### Acceptance Criteria

1. WHEN the README task runs, THE Readme SHALL receive the addition without any change to the existing text of the Readme.
2. WHERE the Readme has no section `## Part 1: the database says no`, THE Readme SHALL receive that section heading before the step.
3. THE Readme SHALL contain, under the heading `## Part 1: the database says no`, the step with the heading `### 3. Verify without spending`.
4. THE step SHALL show one rejection rendered in raw mode and the same rejection rendered in instructive mode, each as real output produced by running the code against the local Database.
5. THE step SHALL explain that the Instruction names the parameter to change and never names a tool, and SHALL give the reason.
6. WHERE the Readme has no title, no prerequisites section or no section `## Run it locally, paying only for the model`, THE Readme SHALL receive the missing part.
7. THE step SHALL be written in the first person.
8. THE step SHALL describe only behavior that the code implements.
9. THE README task SHALL be the last task before the final checkpoint.
