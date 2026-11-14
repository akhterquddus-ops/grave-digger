# Requirements Document

## Introduction

The explainer is the "what does this code really do" step of the Autopsy page in Grave Digger. It turns one legacy unit and its scanner facts into a plain-English Explanation: a one-sentence summary and a list of business rules a billing analyst would recognise. Every rule cites the lines of the legacy file it came from.

An LLM writes the explanation, so every rule passes a guardrail before it is shown. The guardrail drops any rule that cites a line that is not live code carrying a fact, puts line numbers in its text, or states a number that does not appear in the code. Dropped rules are kept with a reason, so the user can see what was rejected. When no LLM is available, the explainer builds a static Explanation from the scanner facts alone.

The module is `src/gravedigger/autopsy/explain.py`. It reuses `Unit` (`gravedigger.exhume`), `Facts`, `Constant` and `scan` (`gravedigger.autopsy.scanner`) and the settings function `setting(key, default)` (`gravedigger.config`). The acceptance tests are in `tests/test_autopsy_explain.py`. Its module docstring and its tests are the source of truth for names, signatures and behaviour, and this feature does not modify that file.

The public contract is:

- `Rule(text, lines, category)`: frozen dataclass.
- `Dropped(rule, reason)`: frozen dataclass.
- `Explanation(unit, summary, rules, dropped, source)`: frozen dataclass.
- `evidence_lines(unit) -> frozenset[int]`
- `check_rule(rule, unit, facts) -> str | None`
- `build_prompt(unit, facts) -> str`
- `static_rules(unit, facts) -> tuple[Rule, ...]`
- `explain(unit, facts, client=None, cache_dir=None) -> Explanation`
- `make_client(provider, api_key, model=None) -> client | None`
- `client_from_settings() -> client | None`

The feature also adds the `anthropic` and `openai` SDKs to `pyproject.toml`, and one script, `scripts/explain_sample.py`, that runs the real provider once over the eight units of the legacy `BILLING_PKG`. That script costs about one cent per run and runs only after the user approves.

## Glossary

- **Explainer**: The function `explain` in `gravedigger.autopsy.explain`.
- **Guardrail**: The function `check_rule` in `gravedigger.autopsy.explain`. It returns `None` when a Rule is kept, otherwise the reason the Rule is dropped.
- **Unit**: The frozen dataclass from `gravedigger.exhume` for one function or procedure, with `name`, `kind` (`function` or `procedure`), `start_line`, `end_line` and `source`.
- **Facts**: The frozen dataclass returned by `scan` for one Unit. It holds `constants` (each a Constant with `value`, `line`, `col`), `string_literals`, `tables_read`, `tables_written`, `calls`, `branches`, `exceptions_handled`, `swallows_errors` and `globals_used`.
- **Rule**: A frozen dataclass with `text` (plain English), `lines` (a tuple of cited file line numbers) and `category` (a free string).
- **Category**: The `category` of a Rule. The prompt suggests `tariff`, `tax`, `date`, `surcharge`, `error` and `other`. A Rule with an unknown or missing category gets the category `other`.
- **Dropped**: A frozen dataclass with `rule` (the rejected Rule) and `reason` (plain English).
- **Explanation**: A frozen dataclass with `unit` (the Unit name, a `str`), `summary` (text), `rules` (a tuple of kept Rules), `dropped` (a tuple of Dropped) and `source` (`llm`, `cache` or `static`).
- **Live_Code**: The lines of a Unit that are neither blank, nor comments, nor commented-out code.
- **Evidence_Lines**: The result of `evidence_lines(unit)`: the file line numbers of Live_Code that carry at least one fact.
- **Fact_Carrier**: A numeric constant, a table read or written, a string literal, a call to a sibling unit, an `IF` or `ELSIF` branch, or an exception handler (`WHEN ... THEN` inside an `EXCEPTION` section, and the `EXCEPTION` keyword line).
- **Number_Token**: A number in the text of a Rule. A digit sequence glued to letters or underscores, such as the `2` in `A2` or in `p_2`, is part of a name and is not a Number_Token.
- **Code_Numbers**: The set of numbers allowed in Rule text: the value and the absolute value of every Constant in `Facts.constants`, and every number inside the strings of `Facts.string_literals`.
- **Percentage_Form**: A Number_Token followed by `%` whose value divided by 100 equals a Code_Numbers value, such as `17%` for `0.17` and `1.5%` for `0.015`.
- **Numbered_Code**: The Unit source with each line written as `<file line number>|<code line>`, where the first line carries `Unit.start_line`.
- **LLM_Client**: Any object with the method `complete_json(system, prompt) -> dict`. It may have the attributes `provider` and `model`.
- **Anthropic_Client**: The LLM_Client for the `anthropic` provider.
- **OpenAI_Client**: The LLM_Client for the `openai` provider.
- **Provider**: The name of an LLM vendor, `anthropic` (default) or `openai`.
- **Make_Client**: The function `make_client(provider, api_key, model=None)`. It takes explicit arguments and reads no setting.
- **Client_From_Settings**: The function `client_from_settings()`. It reads `LLM_PROVIDER` (default `anthropic`), `LLM_API_KEY` and `LLM_MODEL` through `gravedigger.config.setting` and calls Make_Client.
- **System_Prompt**: The fixed instruction text sent to the LLM with every request.
- **PROMPT_VERSION**: A string constant in `gravedigger.autopsy.explain` that is changed whenever the System_Prompt or the answer format changes.
- **Answer_Format**: An object with the key `summary` (text) and the key `rules` (list of objects with `text`, `lines` and `category`).
- **Cache**: A directory, `cache_dir`, holding one JSON file per Unit.
- **Source_Hash**: The first 12 hex characters of the SHA-256 of the Unit source joined with PROMPT_VERSION.
- **Key_Hash**: The first 12 hex characters of the SHA-256 of the Unit source joined with the provider name, the model name and PROMPT_VERSION. A client without `provider` or `model` attributes contributes the name `unknown` for each missing attribute.
- **Cache_File_Name**: `<unit>-<Source_Hash>-<Key_Hash>.json`.
- **Static_Explanation**: An Explanation built from Facts without any LLM call, with `source` equal to `static`.
- **Sample_Script**: The script `scripts/explain_sample.py`.
- **Legacy_Package**: The synthetic `BILLING_PKG` in `legacy/billing_pkg.pks` and `legacy/billing_pkg.pkb`, with eight units.

## Requirements

### Requirement 1: Explanation of one unit

**User Story:** As a migration engineer, I want a plain-English explanation of one unit, so that I can understand the legacy code without reading PL/SQL.

#### Acceptance Criteria

1. WHEN a Unit and its Facts are passed to the Explainer, THE Explainer SHALL return an Explanation whose `unit` equals `Unit.name`.
2. THE Explainer SHALL return Explanation, Rule and Dropped values as frozen dataclasses.
3. WHEN code assigns to a field of an Explanation, Rule or Dropped value, THE value SHALL raise `dataclasses.FrozenInstanceError` and keep its previous field value.
4. THE Explainer SHALL set `Explanation.source` to `llm` when the LLM_Client produced the answer, `cache` when the answer was read from the Cache, and `static` when the Explanation is a Static_Explanation.
5. THE Explainer SHALL return `rules` and `dropped` as tuples, in the order of the Rules in the answer, or in the order of the Static_Explanation.
6. THE Explainer SHALL keep in `rules` only Rules that the Guardrail kept, each with non-empty `text` and a non-empty `lines` tuple.
7. WHEN an LLM_Client answer yields kept Rules and dropped Rules, THE Explainer SHALL list each dropped Rule in `dropped` as a Dropped value with its reason, and SHALL NOT list it in `rules`.
8. WHEN `explain` is called with a client and no `cache_dir`, THE Explainer SHALL call the LLM_Client exactly once.

### Requirement 2: Evidence lines

**User Story:** As a migration engineer, I want to know which lines of a unit carry real facts, so that a rule can only cite lines that matter.

#### Acceptance Criteria

1. WHEN a Unit is passed to `evidence_lines`, THE Explainer SHALL return a `frozenset[int]` of file line numbers of Live_Code lines that contain at least one Fact_Carrier.
2. THE `evidence_lines` function SHALL include the line of every numeric constant in `Facts.constants`.
3. THE `evidence_lines` function SHALL include the line of every table read or written, every string literal, every call to a sibling unit, every `IF` or `ELSIF` branch, and every exception handler.
4. THE `evidence_lines` function SHALL NOT include a comment line or a line of commented-out code, even when that line contains a number, a table name or a keyword.
5. THE `evidence_lines` function SHALL NOT include a line number below `Unit.start_line` or above `Unit.end_line`.
6. WHEN the Unit is `f_enrg_chg`, THE `evidence_lines` function SHALL include lines 42, 44 and 56, and SHALL NOT include line 43 (a comment) or line 48 (a commented-out old rate).
7. WHEN the Unit is `p_gen_bill`, THE `evidence_lines` function SHALL include line 195 (`INSERT INTO BILL_HDR`) and line 205 (`WHEN OTHERS`).
8. THE `evidence_lines` function SHALL be a pure function: it SHALL read no file and use no network.

### Requirement 3: Guardrail on every rule

**User Story:** As a migration engineer, I want every rule checked against the code, so that an invented rate or a wrong line number never reaches the migration certificate.

#### Acceptance Criteria

1. WHEN a Rule, a Unit and its Facts are passed to the Guardrail, THE Guardrail SHALL return `None` when the Rule is kept, and a non-empty plain-English reason when the Rule is dropped.
2. IF the `lines` of a Rule are empty, THEN THE Guardrail SHALL drop the Rule with a reason that says no line is cited.
3. IF a cited line is below `Unit.start_line` or above `Unit.end_line`, THEN THE Guardrail SHALL drop the Rule with a reason that names the line number and says the line is outside the unit.
4. IF a cited line is inside the Unit and is not in Evidence_Lines, THEN THE Guardrail SHALL drop the Rule with a reason that names the line number and says the line is not live code with a fact.
5. IF the `text` of a Rule contains a line reference such as `line 42`, `lines 10-12`, `L42` or `ll. 42`, in any letter case, THEN THE Guardrail SHALL drop the Rule with a reason that says line numbers belong in the citation, not in the text.
6. IF the `text` of a Rule contains a Number_Token that is not in Code_Numbers and not in Percentage_Form of a Code_Numbers value, THEN THE Guardrail SHALL drop the Rule with a reason that names the unknown number.
7. WHEN the `text` of a Rule contains a percentage such as `17%` and Code_Numbers contains `0.17`, THE Guardrail SHALL accept that number.
8. THE Guardrail SHALL NOT treat a digit sequence glued to letters, such as the `2` in the tariff name `A2`, as a Number_Token.
9. THE Guardrail SHALL compare numbers by value, so that `5`, `5.0` and `5.00` are the same number.
10. THE Guardrail SHALL accept a number whose value or absolute value equals the value of a Constant, so that the text `5` is accepted for the constant `-5`.
11. WHEN the `text` of a Rule contains no Number_Token, THE Guardrail SHALL apply only the checks of criteria 2 to 5.
12. WHEN every cited line is in Evidence_Lines, the text has no line reference, and every Number_Token is in Code_Numbers or in Percentage_Form, THE Guardrail SHALL keep the Rule.
13. WHEN the Unit is `f_enrg_chg`, THE Guardrail SHALL keep the Rule "Above 300 units, every unit is charged Rs 22, not just the units above 300." citing lines 42 and 44, and the Rule "Shops (tariff A2) pay a flat Rs 25 per unit." citing line 56.
14. WHEN the Unit is `f_enrg_chg`, THE Guardrail SHALL drop a Rule with the number 24 that cites line 44, a Rule with the number 15.50 that cites the commented-out line 48, a Rule that cites line 76 (outside the unit), and a Rule that cites no line.
15. WHEN the Unit is `p_taxes`, THE Guardrail SHALL keep the Rule "GST is 17% of energy, fixed charge, fuel adjustment and duty together." citing line 112, and SHALL drop the same Rule with `16%`.
16. WHEN the Explainer returns an Explanation, THE Explainer SHALL have run the Guardrail on every Rule of that Explanation, whether the Rule came from the LLM_Client, from the Cache or from a Static_Explanation.
17. THE Guardrail SHALL be a pure function: it SHALL read no file and use no network.

### Requirement 4: LLM provider interface and client factory

**User Story:** As a developer, I want one small interface for LLM providers, so that I can switch vendor without changing the explainer.

#### Acceptance Criteria

1. THE LLM_Client SHALL offer the method `complete_json(system, prompt)` that takes the System_Prompt and the user prompt as texts and returns a `dict`.
2. WHEN Make_Client is called with the Provider `anthropic` and a non-empty key, THE Make_Client SHALL return an Anthropic_Client, and WHEN called with the Provider `openai` and a non-empty key, THE Make_Client SHALL return an OpenAI_Client.
3. IF the Provider passed to Make_Client is neither `anthropic` nor `openai`, THEN THE Make_Client SHALL raise a `ValueError` whose message names the unknown Provider and lists the two supported Providers, whether or not a key is given.
4. WHEN the Provider is valid and the key is `None` or an empty string, THE Make_Client SHALL return `None`.
5. THE Make_Client SHALL validate the Provider first and check the key second.
6. THE Make_Client SHALL read no setting, and SHALL take Provider, key and model only as arguments.
7. THE Make_Client SHALL make no network call and SHALL import no vendor SDK.
8. THE Anthropic_Client and THE OpenAI_Client SHALL expose the attributes `provider` and `model`.
9. WHEN `model` is not given and the Provider is `anthropic`, THE Make_Client SHALL use the model `claude-haiku-5-5`.
10. WHEN `model` is not given and the Provider is `openai`, THE Make_Client SHALL use the model `gpt-4o-mini`. The design phase SHALL verify this model name against the vendor documentation before it is fixed.
11. WHEN Client_From_Settings is called, THE Client_From_Settings SHALL read `LLM_PROVIDER` (default `anthropic`), `LLM_API_KEY` and `LLM_MODEL` through `gravedigger.config.setting` and SHALL return the result of Make_Client for those values.
12. THE Anthropic_Client and THE OpenAI_Client SHALL import their vendor SDK inside `complete_json`, so that `import gravedigger.autopsy.explain` succeeds without any network access and without the SDKs.
13. THE Anthropic_Client SHALL obtain structured output by tool use, and SHALL return the input of the tool call as the `dict`.
14. THE OpenAI_Client SHALL obtain structured output in JSON mode, and SHALL return the parsed message content as the `dict`.
15. IF the answer of the vendor SDK holds no tool call (Anthropic) or no valid JSON object (OpenAI), THEN THE LLM_Client SHALL raise an error whose message says the answer was not structured.
16. IF the API key is missing WHEN `complete_json` is called on an LLM_Client, THEN THE LLM_Client SHALL raise an error whose message says that `LLM_API_KEY` is not set.

### Requirement 5: Prompts

**User Story:** As a migration engineer, I want the LLM told exactly what a good explanation looks like, so that the rules are useful and checkable.

#### Acceptance Criteria

1. WHEN a Unit and its Facts are passed to `build_prompt`, THE Explainer SHALL return a text that contains the Unit name and the Numbered_Code of the Unit.
2. THE `build_prompt` text SHALL write each code line as `<file line number>|<code line>`, so that for `f_enrg_chg` the text contains `44|` and `p_units * 22`.
3. THE `build_prompt` text SHALL include the scanner Facts: constants with their lines, tables read and written, calls, exceptions handled, and whether errors are swallowed.
4. THE System_Prompt SHALL ask for a one-sentence summary in plain English.
5. THE System_Prompt SHALL ask for rules that a billing analyst would recognise, and SHALL name these topics: rates, thresholds, taxes, dates, surcharges and error handling.
6. THE System_Prompt SHALL ask that each rule cites the file line numbers taken from the Numbered_Code, and SHALL ask for a Category per rule, suggesting `tariff`, `tax`, `date`, `surcharge`, `error` and `other`.
7. THE System_Prompt SHALL ask that the text of a rule contains no line numbers.
8. THE System_Prompt SHALL ask that the text of a rule uses only numbers that appear in the code, and SHALL state that a percentage such as 17% is allowed for 0.17.
9. THE Explainer SHALL use the Answer_Format as the tool schema (Anthropic) and as the format described in the prompt (OpenAI).

### Requirement 6: Tolerant reading of the model answer

**User Story:** As a user, I want a sloppy model answer to cost me only the bad rules, so that one malformed entry never hides the good ones or crashes the page.

#### Acceptance Criteria

1. IF the LLM_Client raises an error, THEN THE Explainer SHALL return a Static_Explanation, SHALL NOT raise the error, and SHALL write a warning to the log that contains the Unit name and the type of the error.
2. IF the LLM_Client returns an answer that is not a `dict`, THEN THE Explainer SHALL return a Static_Explanation and SHALL write a warning to the log that contains the Unit name.
3. WHEN the LLM_Client returns a `dict`, THE Explainer SHALL return an Explanation with `source` equal to `llm`, even when the `dict` does not follow the Answer_Format.
4. IF the `summary` of a `dict` answer is missing or is not a string, THEN THE Explainer SHALL use an empty string as the `summary`.
5. IF the `rules` of a `dict` answer are missing or are not a list, THEN THE Explainer SHALL treat the answer as holding no Rules.
6. IF a rule entry is not a `dict`, has a `text` that is not a string, or has `lines` that are not a list of integers, THEN THE Explainer SHALL skip that entry, SHALL NOT list it in `dropped`, and SHALL write a message at debug level to the log.
7. IF a rule entry has a `category` that is missing, is not a string or is not one of the suggested Categories, THEN THE Explainer SHALL use the Category `other` for that Rule and SHALL NOT drop the Rule for that reason.
8. WHEN a rule entry has a valid shape, THE Explainer SHALL pass it to the Guardrail, and SHALL list it in `dropped` with the reason when the Guardrail drops it.
9. WHEN the LLM_Client answers `{"rules": [{"text": 5}, "nonsense", {"lines": "x"}]}` for the Unit `f_lps`, THE Explainer SHALL return an Explanation with `source` equal to `llm` and `rules` equal to `()`.

### Requirement 7: Cache

**User Story:** As a developer, I want explanations cached on disk, so that a second run costs nothing and the committed samples stay stable.

#### Acceptance Criteria

1. WHEN `cache_dir` is given and the LLM_Client answers for a Unit, THE Explainer SHALL write one JSON file named by the Cache_File_Name in `cache_dir`, and SHALL create `cache_dir` when it does not exist.
2. THE Cache file SHALL hold the top-level keys `unit` (the Unit name), `summary` (the raw summary) and `rules` (the raw list of objects with `text`, `lines` and `category`), exactly as the Explainer read them from the answer before the Guardrail ran.
3. WHEN `cache_dir` is given and an LLM_Client is given, THE Explainer SHALL read the file named by the Cache_File_Name of that client, and SHALL NOT call the LLM_Client when that file is valid.
4. WHEN `cache_dir` is given and no LLM_Client is given, THE Explainer SHALL search `cache_dir` for the files that match `<unit>-<Source_Hash>-*.json` and SHALL read the valid file with the latest modification time.
5. WHEN the Unit source, the Provider, the model or PROMPT_VERSION changes, THE Explainer SHALL use a different Cache_File_Name.
6. WHEN two calls use identical Unit source, provider, model and PROMPT_VERSION, THE Explainer SHALL use the same Cache_File_Name.
7. WHEN two calls with the same LLM_Client and the same `cache_dir` are made for a Unit, THE Explainer SHALL leave exactly one `*.json` file for that Unit in `cache_dir`, and the second call SHALL return `source` equal to `cache` with `rules` equal to those of the first call.
8. WHEN a Cache file is read, THE Explainer SHALL run the Guardrail again on every Rule of the file, so that a Rule added to the file by hand with an invented number is dropped.
9. FOR ALL Explanations written to the Cache, reading them back SHALL produce an Explanation equal to the one returned by the call that wrote them, except for `source`, which is `cache` after reading (round-trip property).
10. IF a Cache file is not valid JSON or does not have the top-level keys of criterion 2 with the types `str`, `str` and `list`, THEN THE Explainer SHALL ignore the file, and SHALL replace the file after a successful LLM_Client call when an LLM_Client is given.
11. IF a Cache file is ignored and no LLM_Client is given, THEN THE Explainer SHALL return a Static_Explanation.
12. THE Explainer SHALL accept an LLM_Client without `provider` and `model` attributes and SHALL use `unknown` for the missing attributes in the Key_Hash.
13. WHEN a Cache file written with a client without `provider` and `model` attributes exists, THE Explainer SHALL read that file when `explain` is called with `client=None`.
14. WHERE `cache_dir` is not given, THE Explainer SHALL read and write no Cache file.
15. THE Explainer SHALL write Cache files as UTF-8 without a byte order mark, and with LF as line separator.
16. THE Explainer SHALL NOT write a Cache file for a Static_Explanation.
17. THE Cache file SHALL contain no API key.

### Requirement 8: Static fallback

**User Story:** As a user without an API key, I want the Autopsy page to still say something useful, so that the demo works offline.

#### Acceptance Criteria

1. WHEN no LLM_Client is given and no valid Cache file exists for the Unit, THE Explainer SHALL return a Static_Explanation built only from the Unit and its Facts.
2. WHEN a Unit and its Facts are passed to `static_rules`, THE Explainer SHALL return a tuple of Rules built only from the Facts.
3. THE Static_Explanation SHALL have a non-empty `summary` that contains the Unit name and the word `function` or `procedure`, matching `Unit.kind`.
4. THE `static_rules` function SHALL return one Rule for each table read, with the upper-case table name in the text, the Category `data`, and the file line where the table is read.
5. THE `static_rules` function SHALL return one Rule for each table written, with the upper-case table name in the text, the Category `data`, and the file line where the table is written.
6. THE `static_rules` function SHALL return one Rule for each exception handled, with the Category `error` and the file line of the handler.
7. WHEN `Facts.swallows_errors` is true, THE `static_rules` function SHALL return a Rule with the Category `error` whose text contains the phrase `WHEN OTHERS` and says that errors are swallowed, and which cites the file line of the `WHEN OTHERS` handler.
8. WHEN `Facts.constants` is not empty, THE `static_rules` function SHALL return one Rule with the Category `other` that lists the constants of the Unit, with each number written in plain decimal notation without an exponent, and that cites the lines where the constants appear.
9. WHEN the Unit is `p_gen_bill`, THE `static_rules` function SHALL return a Rule whose text contains `BILL_HDR` and that cites line 195, and a Rule whose text contains `WHEN OTHERS` and that cites line 205.
10. WHEN the Unit is `f_fpa`, THE `static_rules` function SHALL return a Rule whose text contains `FPA_RT` and that cites line 96.
11. FOR ALL eight units of the Legacy_Package, THE Guardrail SHALL keep every Rule returned by `static_rules`.
12. WHEN the same Unit and Facts are passed twice, THE Explainer SHALL return equal Static_Explanations.
13. WHEN `explain` is called with `client=None` and without a Cache file, THE Explainer SHALL return `source` equal to `static` and SHALL need no API key.
14. WHEN `explain` is called with `client=None`, THE Explainer SHALL make no network call.

### Requirement 9: Secret handling

**User Story:** As the owner of the app, I want the API key never to appear anywhere, so that a log, a cache file or a screen share cannot leak it.

#### Acceptance Criteria

1. THE Explainer, THE Make_Client, THE Client_From_Settings and THE LLM_Client SHALL NOT write the API key to the log, to standard output, to standard error, to a Cache file or to an exception message.
2. THE Make_Client and THE Client_From_Settings SHALL NOT hard-code a key, and THE Client_From_Settings SHALL read the key only through `gravedigger.config.setting`.
3. IF the vendor SDK raises an error whose text contains the API key, THEN THE LLM_Client SHALL remove the key from the text before the error leaves the LLM_Client.
4. THE Sample_Script SHALL NOT print the API key.

### Requirement 10: Purity and dependencies

**User Story:** As a maintainer, I want the module to stay small, testable and free of hidden state, so that the test suite stays fast and offline.

#### Acceptance Criteria

1. THE `explain.py` module SHALL import only the Python standard library and modules of the `gravedigger` package at module level.
2. THE Explainer SHALL keep no global state, so that two calls with the same input, the same LLM_Client and the same Cache return equal Explanations.
3. THE Explainer SHALL read or write files only in `cache_dir`.
4. THE `pyproject.toml` file SHALL list `anthropic` and `openai` among the project dependencies, with each version pinned. IF a wheel is blocked by Smart App Control with the message "An Application Control policy has blocked this file", THEN the pin SHALL name an older, widely used release.
5. THE Explainer SHALL accept an LLM_Client from the caller, so that a test can pass a fake client and no test needs the network.

### Requirement 11: Real-provider sample script

**User Story:** As the author of the hackathon write-up, I want one real run over the legacy package whose results are saved, so that the demo and the cache samples come from a real LLM.

#### Acceptance Criteria

1. WHEN the Sample_Script runs, THE Sample_Script SHALL load the Legacy_Package, scan each of its eight units, and call the Explainer once for each unit with the client from Client_From_Settings and `cache_dir` set to `golden/autopsy`.
2. WHEN the Sample_Script runs, THE Sample_Script SHALL print, for each unit, the unit name, the summary, the kept Rules with their cited lines, and the Dropped values with their reasons.
3. WHEN the Sample_Script runs a second time and the Cache files exist, THE Sample_Script SHALL make no LLM call.
4. IF `LLM_API_KEY` is not set and a Cache file is missing for at least one unit, THEN THE Sample_Script SHALL exit with a message that says the key is missing, and SHALL make no LLM call.
5. WHEN `LLM_API_KEY` is not set and a valid Cache file exists for all eight units, THE Sample_Script SHALL print the cached Explanations and need no key.
6. THE Sample_Script SHALL be run only after the user approves, because one run costs about one cent.

### Requirement 12: Acceptance and test suite

**User Story:** As the owner of the repo, I want the whole test suite green, so that the new module does not break the existing work.

#### Acceptance Criteria

1. WHEN `.venv\Scripts\python.exe -m pytest -q` runs, THE test suite SHALL pass all 74 tests: the 53 existing tests and the 21 new tests of `tests/test_autopsy_explain.py`.
2. THE implementation SHALL NOT modify `tests/test_autopsy_explain.py` or any other test file.
3. THE new tests SHALL run without network access and without `LLM_API_KEY`.
4. THE implementation SHALL follow the project code rules: type hints everywhere, frozen dataclasses for data types, small pure functions, and `Decimal` for every number compared by the Guardrail.
5. THE acceptance of this feature SHALL rest on the 21 tests of tests/test_autopsy_explain.py alone: the implementation SHALL add no other test file, so that the total stays at 74. The design SHALL list, for each requirement, which of those 21 tests covers it, and SHALL mark a requirement that no test covers as verified by inspection or by the sample script.
