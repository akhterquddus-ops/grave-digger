# Requirements Document

## Introduction

The explainer is the "what does this code really do" step of the Autopsy page in Grave Digger. It turns one legacy unit and its scanner facts into a plain-English Explanation: a one-sentence summary and a list of business rules a billing analyst would recognise. Every rule cites the lines of the legacy file it came from.

An LLM writes the explanation, so every rule passes a guardrail before it is shown. The guardrail drops any rule that cites a line outside the unit, puts line numbers in its text, or states a number that does not appear in the code. Dropped rules are kept with a reason, so the user can see what was rejected. When no LLM is available, the explainer builds a static Explanation from the scanner facts alone.

The module is `src/gravedigger/autopsy/explain.py`. It reuses `Unit` (`gravedigger.exhume`), `Facts` and `scan` (`gravedigger.autopsy.scanner`) and the settings function `setting` (`gravedigger.config`). The acceptance tests are in `tests/test_autopsy_explain.py` and are not modified by this feature.

**Note on the test file:** `tests/test_autopsy_explain.py` does not exist in the workspace at the time of writing. The requirements below are based on the stated constraints. When the test file is added, its module docstring is the source of truth for names, signatures and field names, and any difference between it and this document is resolved in favour of the test file. The design phase must re-read the test file before fixing any signature.

The feature also adds the `anthropic` and `openai` SDKs to `pyproject.toml`, and one script, `scripts/explain_sample.py`, that runs the real provider once over the eight units of the legacy `BILLING_PKG`. That script costs about one cent per run and runs only after the user approves.

## Glossary

- **Explainer**: The function `explain` in `gravedigger.autopsy.explain`.
- **Guardrail**: The function `check_rule` in `gravedigger.autopsy.explain`. It decides whether one Rule is kept or dropped.
- **Unit**: The frozen dataclass from `gravedigger.exhume` for one function or procedure, with `name`, `start_line`, `end_line` and `source`.
- **Facts**: The frozen dataclass returned by `scan` for one Unit.
- **Rule**: A frozen dataclass with `text` (plain English) and `lines` (the cited file line numbers).
- **Explanation**: A frozen dataclass holding `summary`, the kept Rules, the dropped Rules with their reasons, and the `source` of the explanation (`llm`, `cache` or `static`).
- **Dropped_Rule**: A Rule rejected by the Guardrail, together with a plain-English reason.
- **Numbered_Code**: The Unit source with each line prefixed by its file line number (`start_line` for the first line), as sent to the LLM.
- **Code_Numbers**: The set of numbers that appear in the Unit source, taken from the numeric literals in `Facts.constants` and the numbers inside the string literals of `Facts.string_literals`.
- **Percentage_Form**: A Rule number written as a percentage whose value equals 100 times a Code_Numbers value, such as `17%` for `0.17`.
- **LLM_Client**: Any object with the method `complete_json(system, prompt) -> dict`.
- **Anthropic_Client**: The LLM_Client for the `anthropic` provider.
- **OpenAI_Client**: The LLM_Client for the `openai` provider.
- **Provider**: The name of an LLM vendor, `anthropic` (default) or `openai`.
- **Make_Client**: The function `make_client` in `gravedigger.autopsy.explain`.
- **Settings**: The values `LLM_PROVIDER`, `LLM_API_KEY` and `LLM_MODEL`, read through `gravedigger.config.setting`.
- **System_Prompt**: The fixed instruction text sent to the LLM with every request.
- **PROMPT_VERSION**: A string constant in `gravedigger.autopsy.explain` that is changed whenever the System_Prompt or the answer format changes.
- **Cache**: A directory, `cache_dir`, holding one JSON file per Unit.
- **Cache_Key**: The hash of the Unit source, the Provider, the model and PROMPT_VERSION.
- **Static_Explanation**: An Explanation built from Facts without any LLM call.
- **Sample_Script**: The script `scripts/explain_sample.py`.
- **Legacy_Package**: The synthetic `BILLING_PKG` in `legacy/billing_pkg.pks` and `legacy/billing_pkg.pkb`, with eight units.

## Requirements

### Requirement 1: Explanation of one unit

**User Story:** As a migration engineer, I want a plain-English explanation of one unit, so that I can understand the legacy code without reading PL/SQL.

#### Acceptance Criteria

1. WHEN a Unit and its Facts are passed to the Explainer, THE Explainer SHALL return an Explanation with a non-empty one-sentence `summary`.
2. WHEN a Unit and its Facts are passed to the Explainer, THE Explainer SHALL return an Explanation whose kept Rules each have non-empty `text` and a non-empty `lines` tuple.
3. THE Explainer SHALL return Explanation and Rule values as frozen dataclasses.
4. WHEN code assigns to a field of an Explanation or Rule, THE Explanation or Rule value SHALL raise `dataclasses.FrozenInstanceError` and keep its previous field value.
5. THE Explainer SHALL set the `source` of each Explanation to `llm` when the LLM_Client produced it, `cache` when it was read from the Cache, and `static` when it is a Static_Explanation.
6. THE Explainer SHALL keep the kept Rules in the order returned by the LLM_Client, or in the order of the Static_Explanation.

### Requirement 2: Guardrail on every rule

**User Story:** As a migration engineer, I want every rule checked against the code, so that an invented rate or a wrong line number never reaches the migration certificate.

#### Acceptance Criteria

1. WHEN a Rule is passed to the Guardrail, THE Guardrail SHALL return a verdict that says the Rule is kept, or dropped with a plain-English reason.
2. IF the `lines` of a Rule are empty, THEN THE Guardrail SHALL drop the Rule with a reason that says no line is cited.
3. IF the `lines` of a Rule contain a line number below `Unit.start_line` or above `Unit.end_line`, THEN THE Guardrail SHALL drop the Rule with a reason that names the offending line number.
4. IF the `text` of a Rule contains a line reference such as `line 42`, `lines 10-12`, `L42` or `ll. 42`, in any letter case, THEN THE Guardrail SHALL drop the Rule with a reason that says line numbers belong in the citation, not in the text.
5. IF the `text` of a Rule contains a number that is not in Code_Numbers and not in Percentage_Form of a Code_Numbers value, THEN THE Guardrail SHALL drop the Rule with a reason that names the unknown number.
6. WHEN the `text` of a Rule contains a percentage such as `17%` and Code_Numbers contains `0.17`, THE Guardrail SHALL accept that number.
7. WHEN every number in the `text` of a Rule is in Code_Numbers or in Percentage_Form, THE Guardrail SHALL keep the Rule.
8. WHEN the `text` of a Rule contains no number, THE Guardrail SHALL apply only the checks of criteria 2 to 4.
9. THE Guardrail SHALL compare numbers by value, so that `5`, `5.0` and `5.00` are the same number.
10. WHEN the Explainer returns an Explanation, THE Explainer SHALL have run the Guardrail on every Rule of that Explanation, whether the Rule came from the LLM_Client, from the Cache or from a Static_Explanation.
11. THE Explainer SHALL list each dropped Rule in the Explanation with its reason, and SHALL NOT list it among the kept Rules.
12. THE Guardrail SHALL be a pure function: it SHALL read no file and use no network.

### Requirement 3: LLM provider interface

**User Story:** As a developer, I want one small interface for LLM providers, so that I can switch vendor without changing the explainer.

#### Acceptance Criteria

1. THE LLM_Client SHALL offer the method `complete_json(system, prompt)` that takes the System_Prompt and the user prompt as texts and returns a `dict`.
2. THE Make_Client SHALL return an Anthropic_Client WHEN the Provider is `anthropic`, and an OpenAI_Client WHEN the Provider is `openai`.
3. WHEN no Provider is set, THE Make_Client SHALL use `anthropic`.
4. IF the Provider is neither `anthropic` nor `openai`, THEN THE Make_Client SHALL raise a `ValueError` whose message names the unknown Provider and lists the two supported Providers.
5. THE Make_Client SHALL read Provider, key and model from the Settings through `gravedigger.config.setting`.
6. WHEN `LLM_MODEL` is not set and the Provider is `anthropic`, THE Make_Client SHALL use the model `claude-haiku-5-5`.
7. THE Make_Client SHALL make no network call and SHALL import no vendor SDK.
8. THE Anthropic_Client and THE OpenAI_Client SHALL import their vendor SDK inside `complete_json`, so that `import gravedigger.autopsy.explain` succeeds without any network access.
9. THE Anthropic_Client SHALL obtain structured output by tool use, and SHALL return the input of the tool call as the `dict`.
10. THE OpenAI_Client SHALL obtain structured output in JSON mode, and SHALL return the parsed message content as the `dict`.
11. IF the answer of the vendor SDK holds no tool call (Anthropic) or no valid JSON object (OpenAI), THEN THE LLM_Client SHALL raise an error whose message says the answer was not structured.

### Requirement 4: System prompt

**User Story:** As a migration engineer, I want the LLM told exactly what a good explanation looks like, so that the rules are useful and checkable.

#### Acceptance Criteria

1. THE System_Prompt SHALL ask for a one-sentence summary in plain English.
2. THE System_Prompt SHALL ask for rules that a billing analyst would recognise, and SHALL name these topics: rates, thresholds, taxes, dates, surcharges and error handling.
3. THE System_Prompt SHALL ask that each rule cites the file line numbers taken from the Numbered_Code.
4. THE System_Prompt SHALL ask that the text of a rule contains no line numbers.
5. THE System_Prompt SHALL ask that the text of a rule uses only numbers that appear in the code, and SHALL state that a percentage such as 17% is allowed for 0.17.
6. THE Explainer SHALL send the Unit source as Numbered_Code, where the first line carries the number `Unit.start_line`.
7. THE Explainer SHALL send the scanner Facts (constants with lines, tables read and written, calls, exceptions handled, swallowed errors) in the user prompt as a help to the LLM.
8. THE Explainer SHALL define the answer format as an object with the key `summary` (text) and the key `rules` (list of objects with `text` and `lines`), and SHALL use the same format as the tool schema (Anthropic) and as the format described in the prompt (OpenAI).

### Requirement 5: Cache

**User Story:** As a developer, I want explanations cached on disk, so that a second run costs nothing and the committed samples stay stable.

#### Acceptance Criteria

1. WHEN `cache_dir` is given and the LLM_Client returns an Explanation for a Unit, THE Explainer SHALL write one JSON file for that Unit in `cache_dir`, and SHALL create `cache_dir` when it does not exist.
2. THE Explainer SHALL derive the Cache_Key from the Unit source, the Provider, the model and PROMPT_VERSION, and SHALL contain the Cache_Key in the file name.
3. WHEN a Cache file for the Cache_Key of a Unit exists, THE Explainer SHALL return the Explanation from that file and SHALL NOT call the LLM_Client.
4. WHEN the Unit source, the Provider, the model or PROMPT_VERSION changes, THE Explainer SHALL use a different Cache_Key.
5. WHEN two calls use identical Unit source, Provider, model and PROMPT_VERSION, THE Explainer SHALL use the same Cache_Key.
6. THE Explainer SHALL store in the Cache file the raw `summary` and the raw Rules as returned by the LLM_Client, so that the Guardrail runs again on every read (see Requirement 2, criterion 10).
7. FOR ALL Explanations written to the Cache, reading them back SHALL produce an Explanation equal to the one returned by the call that wrote them, except for `source`, which is `cache` after reading (round-trip property).
8. IF a Cache file is not valid JSON or does not have the answer format of Requirement 4, criterion 8, THEN THE Explainer SHALL ignore the file, call the LLM_Client, and replace the file.
9. WHERE `cache_dir` is not given, THE Explainer SHALL read and write no Cache file.
10. THE Explainer SHALL write Cache files as UTF-8 without a byte order mark, and with LF as line separator.
11. THE Explainer SHALL NOT write a Cache file for a Static_Explanation.
12. THE Cache file SHALL contain no API key.

### Requirement 6: Static fallback

**User Story:** As a user without an API key, I want the Autopsy page to still say something useful, so that the demo works offline.

#### Acceptance Criteria

1. WHEN no LLM_Client is given and no Cache file exists for the Unit, THE Explainer SHALL return a Static_Explanation built only from the Unit and its Facts.
2. IF the LLM_Client raises an error, THEN THE Explainer SHALL return a Static_Explanation and SHALL NOT raise the error.
3. IF the LLM_Client returns an answer that does not have the answer format of Requirement 4, criterion 8, THEN THE Explainer SHALL return a Static_Explanation.
4. THE Static_Explanation SHALL have a non-empty `summary` that contains the Unit name and the word `function` or `procedure`, matching the Unit kind.
5. THE Static_Explanation SHALL contain one Rule for each of: each constant group (Facts.constants), each table read, each table written, each exception handled, and the swallowing of errors, where Facts holds it, and each Rule SHALL cite the file line where the fact starts.
6. WHEN `Facts.swallows_errors` is true, THE Static_Explanation SHALL contain a Rule whose text says that errors are swallowed.
7. THE Static_Explanation SHALL pass the Guardrail for every Rule, so that its Rules are all kept.
8. WHEN the same Unit and Facts are passed twice, THE Explainer SHALL return equal Static_Explanations.
9. WHEN the Explainer falls back to a Static_Explanation after an error, THE Explainer SHALL write a warning to the log that contains the Unit name and the type of the error.

### Requirement 7: Secret handling

**User Story:** As the owner of the app, I want the API key never to appear anywhere, so that a log, a cache file or a screen share cannot leak it.

#### Acceptance Criteria

1. THE Explainer, THE Make_Client and THE LLM_Client SHALL NOT write the API key to the log, to standard output, to standard error, to a Cache file or to an exception message.
2. THE Make_Client SHALL read the API key only through `gravedigger.config.setting` and SHALL NOT hard-code a key.
3. IF the vendor SDK raises an error whose text contains the API key, THEN THE Explainer SHALL remove the key from the text before logging it.
4. THE Sample_Script SHALL NOT print the API key.
5. IF the API key is missing WHEN the LLM_Client calls the vendor, THEN THE LLM_Client SHALL raise an error whose message says that `LLM_API_KEY` is not set.

### Requirement 8: Purity and dependencies

**User Story:** As a maintainer, I want the module to stay small, testable and free of hidden state, so that the test suite stays fast and offline.

#### Acceptance Criteria

1. THE `explain.py` module SHALL import only the Python standard library and modules of the `gravedigger` package at module level.
2. THE Explainer SHALL keep no global state, so that two calls with the same input, the same LLM_Client and the same Cache return equal Explanations.
3. THE Explainer SHALL read or write files only in `cache_dir`.
4. THE `pyproject.toml` file SHALL list `anthropic` and `openai` among the project dependencies, with the SDK versions pinned to releases that load on a machine with Smart App Control.
5. THE Explainer SHALL accept an LLM_Client from the caller, so that a test can pass a fake client and no test needs the network.

### Requirement 9: Real-provider sample script

**User Story:** As the author of the hackathon write-up, I want one real run over the legacy package whose results are saved, so that the demo and the cache samples come from a real LLM.

#### Acceptance Criteria

1. WHEN the Sample_Script runs, THE Sample_Script SHALL load the Legacy_Package, scan each of its eight units, and call the Explainer once for each unit with the real LLM_Client from the Make_Client and `cache_dir` set to `golden/autopsy`.
2. WHEN the Sample_Script runs, THE Sample_Script SHALL print, for each unit, the unit name, the summary, the kept Rules with their cited lines, and the Dropped_Rules with their reasons.
3. WHEN the Sample_Script runs a second time and the Cache files exist, THE Sample_Script SHALL make no LLM call.
4. IF `LLM_API_KEY` is not set, THEN THE Sample_Script SHALL exit with a message that says the key is missing, and SHALL make no LLM call.
5. THE Sample_Script SHALL be run only after the user approves, because one run costs about one cent.

### Requirement 10: Acceptance and test suite

**User Story:** As the owner of the repo, I want the whole test suite green, so that the new module does not break the existing work.

#### Acceptance Criteria

1. WHEN `.venv\Scripts\python.exe -m pytest -q` runs, THE test suite SHALL pass all 74 tests: the 53 existing tests and the 21 new tests of `tests/test_autopsy_explain.py`.
2. THE implementation SHALL NOT modify `tests/test_autopsy_explain.py` or any other test file.
3. THE new tests SHALL run without network access and without `LLM_API_KEY`.
4. THE implementation SHALL follow the project code rules: type hints everywhere, frozen dataclasses for data types, small pure functions, and `Decimal` for every number compared by the Guardrail.
