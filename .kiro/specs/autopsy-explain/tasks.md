# Implementation Plan: Autopsy Explain

## Overview

Implement one module, `src/gravedigger/autopsy/explain.py`, in Python 3.12, so that the 21 existing acceptance tests in `tests/test_autopsy_explain.py` pass. The full suite must then report 74 passing tests (53 existing plus those 21). A last task adds the sample script `scripts/explain_sample.py`.

Scope for this plan:

- Create `src/gravedigger/autopsy/explain.py` and `scripts/explain_sample.py`, and edit `pyproject.toml` and `docs/kiro-log.md`.
- Add no new test file and modify no existing test file. `tests/test_autopsy_explain.py` is the acceptance suite and stays unchanged.
- Module-level imports of `explain.py` are the standard library and `gravedigger` only. The `anthropic` and `openai` SDKs are imported inside `complete_json`.
- Money and number comparisons use `Decimal` built from strings. No `float`, no `round()`.
- Logs hold the unit name and the exception type only. Never log the API key, `str(exc)`, a prompt or an answer.
- Write files as UTF-8 without BOM with LF line endings.
- Run commands in PowerShell from the project root `C:\Akhtar-Works\grave-digger`, with the venv Python `.venv\Scripts\python.exe`.
- The design (`design.md`) holds the exact algorithms, regexes, reason texts and code sketches. Follow it.

## Tasks

- [ ] 1. Dependencies
  - [ ] 1.1 Add the pinned SDKs to `pyproject.toml`
    - Add `"anthropic==2.8.0"` and `"openai==3.51.0"` to `dependencies`, each with a short comment that says it is pinned and why
    - Leave the other dependencies unchanged
    - _Requirements: 10.4_

  - [ ] 1.2 Run the install check in the venv, with the Smart App Control fallback
    - Run `.venv\Scripts\python.exe -m pip install -e ".[dev]"`
    - Run `.venv\Scripts\python.exe -c "import anthropic, openai, jiter; print(anthropic.__version__, openai.__version__, jiter.__version__)"`
    - IF a step fails with `An Application Control policy has blocked this file`, find the blocked package from the message and pin an older, widely used release, in this order: `jiter` first (any version below 0.19 that installs), then `anthropic` (2.7.0, then the last 1.x, then 0.125.0) or `openai` (earlier 3.x), then any other transitive wheel. Put the final pin in `pyproject.toml` with a comment
    - After any pin change, re-run the import line above
    - Record the final pins and the reason in the log entry of task 13
    - _Requirements: 10.4_

- [ ] 2. Data types, constants and `evidence_lines`
  - [ ] 2.1 Create `explain.py` with the constants and frozen data types
    - Create `src/gravedigger/autopsy/explain.py` with `from __future__ import annotations`, a module docstring that names the public contract, and the imports listed in the design (standard library, `gravedigger.autopsy.blocks`, `scanner`, `tokenizer`, `gravedigger.config.setting`, `gravedigger.exhume.Unit`)
    - Define `logger`, `PROMPT_VERSION = "autopsy-explain-1"`, `CATEGORIES`, `PROVIDERS`, `ANTHROPIC_DEFAULT_MODEL = "claude-haiku-5-5"`, `OPENAI_DEFAULT_MODEL = "gpt-4o-mini"` and the `Source` literal
    - Define the frozen dataclasses `Rule(text, lines, category)`, `Dropped(rule, reason)`, `Explanation(unit, summary, rules, dropped, source)`, the `LLMClient` protocol with `complete_json(system, prompt) -> dict`, and `LLMError(RuntimeError)`
    - Keep the module free of mutable global state
    - Also define temporary stubs for every public function not yet implemented: `build_prompt`, `check_rule`, `evidence_lines`, `explain`, `make_client`, `static_rules` and `client_from_settings`. Each stub has the signature exactly as in the design and its body raises `NotImplementedError`. This lets `tests/test_autopsy_explain.py` import all its names at module level and be collected. Later tasks replace each stub with the real code
    - _Requirements: 1.2, 1.3, 1.4, 4.1, 4.9, 4.10, 7.5, 10.1, 10.2, 12.4_

  - [ ] 2.2 Implement `evidence_lines` and its private helpers
    - Implement `_masked_lines`, `_owner` and `_handler_lines` as described in the design
    - Replace the stub of `evidence_lines(unit) -> frozenset[int]` with the six steps of the design: constants, tables, sibling calls, `IF`/`ELSIF` branches, exception handlers, string segments of the unmasked source. Search the masked text so comment lines and commented-out code never count
    - Convert every offset to a file line with `unit.start_line + line_of(starts, offset) - 1`, and clamp the result to `unit.start_line .. unit.end_line`
    - The function reads no file and uses no network
    - Docstring names the facts it uses in plain English
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

- [ ] 3. Guardrail
  - [ ] 3.1 Implement the number helpers
    - Implement the `_LINE_REF` and `_NUMBER` regexes exactly as in the design
    - Implement `_number_tokens(text)` returning `(token, is_percent)` in text order, `_code_numbers(facts)` (constant values, their absolute values, and numbers inside string literals), `_shift_down(d)` (exact divide by 100 by rebuilding from `as_tuple`) and `_plain(d)` (plain decimal text, no exponent, never `-0`)
    - Digits glued to letters or underscores (the `2` in `A2`) are not tokens
    - _Requirements: 3.6, 3.7, 3.8, 3.9, 3.10, 8.8, 12.4_

  - [ ] 3.2 Implement `check_rule` and `_judge`
    - Implement `_check(rule, unit, facts, ev)` with the five checks in the fixed order of the design and the exact reason texts: no line, outside the unit, not live code with a fact, line numbers in text, unknown number
    - Replace the stub of `check_rule(rule, unit, facts)` with the real code that computes `ev = evidence_lines(unit)` and delegates to `_check`; it returns `None` to keep or a non-empty reason to drop; it is pure
    - Implement `_judge(rules, unit, facts, ev)` returning `(kept, dropped)` tuples in input order; it is the only place that builds `Dropped` values
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.17_

- [ ] 4. Checkpoint - Evidence and guardrail tests
  - Run `.venv\Scripts\python.exe -m pytest tests/test_autopsy_explain.py -q` from the project root
  - At this point the evidence and guardrail tests must pass: `test_evidence_lines_are_live_code_with_facts`, `test_evidence_lines_include_sql_and_handlers`, `test_guardrail_keeps_rules_backed_by_code`, `test_guardrail_drops_unsupported_rules_with_a_reason` (four cases) and `test_percentages_match_decimal_constants`. Tests of not-yet-implemented groups fail with `NotImplementedError` (from the stubs), which is expected at this checkpoint
  - Fix `explain.py` (never the tests) if an expected test fails, then re-run
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Prompts
  - [ ] 5.1 Implement `SYSTEM_PROMPT`, the answer schema and `build_prompt`
    - Define `SYSTEM_PROMPT` as a module constant with the text of the design (summary, rules, topics, citation of file lines, categories, no line numbers in text, only code numbers, percentage form, no comments, no fixing, no invention)
    - Implement `_answer_schema()` as a function that returns a fresh dict, and the `_JSON_FORMAT_NOTE` constant for the OpenAI client
    - Replace the stub of `build_prompt(unit, facts)` with the real code: header with name, kind and file lines; code lines written as `<file line number>|<code line>` starting at `unit.start_line`; a FACTS block with constants and their lines (through `_plain`), tables read and written, calls, branch count, errors handled, swallowed errors yes or no, and globals. Sort every set so the text is deterministic. Print `none` for an empty list
    - The prompt holds no setting and no key
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9_

- [ ] 6. Static fallback
  - [ ] 6.1 Implement `static_rules` and `_static_summary`
    - Implement `_first_line` and the line patterns of the design (table read, table written, handler of a name, `OTHERS`), searching masked lines only, with the whole-word fallback
    - Replace the stub of `static_rules(unit, facts)` with the real code, with the groups in the fixed order: tables read (category `data`), tables written (`data`), exceptions handled (`error`), the swallow rule (`error`, text contains `WHEN OTHERS` and says errors are swallowed), and one constants rule (`other`, plain decimals, distinct values, all constant lines). Sort within each group by name
    - Skip a rule whose line is not found or not in the evidence set, so every static rule passes the guardrail
    - Implement `_static_summary(unit)` with the unit name and the word `function` or `procedure`
    - _Requirements: 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12_

- [ ] 7. Tolerant answer parsing
  - [ ] 7.1 Implement `_rule_from_entry` and `_parse_answer`
    - `_rule_from_entry(entry)` returns `None` and writes a debug log message (no entry content) when the entry is not a `dict`, its `text` is missing, not a string or only whitespace, or its `lines` is not a list of integers (a `bool` is not an integer). Otherwise it returns a `Rule` with the category when it is in `CATEGORIES`, else `other`
    - `_parse_answer(answer)` never raises: a missing or non-string `summary` becomes `""`; `rules` that is missing or not a list gives no rules; malformed entries are skipped and not listed as dropped
    - _Requirements: 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9_

- [ ] 8. Cache
  - [ ] 8.1 Implement the cache names
    - Implement `_source_hash(unit)`, `_key_hash(unit, client)` (provider and model through `getattr`, `unknown` when missing) and `_cache_name(unit, client)` as `<unit>-<Source_Hash>-<Key_Hash>.json`, with SHA-256, a NUL separator and 12 hex characters
    - _Requirements: 7.1, 7.5, 7.6, 7.12_

  - [ ] 8.2 Implement cache read, find and write
    - `_read_cache_file(path)` returns `(summary, rules)` or `None` for an unreadable file, invalid JSON (a BOM counts as invalid), a non-object, or a file without `unit: str`, `summary: str`, `rules: list`. Rule entries go through `_rule_from_entry`
    - `_find_cache(unit, directory)` globs `<unit>-<Source_Hash>-*.json`, sorts by `(st_mtime_ns, name)` descending and returns the first valid file. A missing directory is a miss
    - `_write_cache(path, unit, summary, rules)` writes the keys `unit`, `summary`, `rules` as UTF-8 without BOM, `newline="\n"`, trailing newline, through a `.tmp` file and `os.replace`, and creates the directory. The payload holds no key
    - A write error (`OSError`) is logged with the unit name and exception type only; the explanation is still returned
    - No file is read or written when `cache_dir` is `None`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.7, 7.10, 7.11, 7.12, 7.13, 7.14, 7.15, 7.16, 7.17, 10.3_

- [ ] 9. Orchestration
  - [ ] 9.1 Implement `_ask`, `_finish`, `_static` and `explain`; replace the stub of `explain`
    - `_ask(unit, facts, client)` calls `client.complete_json(SYSTEM_PROMPT, build_prompt(unit, facts))` exactly once. On any `Exception` it logs a warning with the unit name and `type(exc).__name__` only and returns `None`. A non-`dict` answer logs the unit name and the type name and returns `None`. A `dict` goes to `_parse_answer`
    - `_finish` runs `_judge` and builds the `Explanation`; `_static` does the same with `static_rules` and `_static_summary` and source `static`
    - `explain(unit, facts, client=None, cache_dir=None)` follows the flow of the design: client and directory read the exact cache file first, then call the client and write the file; no client and a directory read the newest matching file; otherwise static. Compute `evidence_lines` once per call. Sources are `llm`, `cache` and `static`. A static explanation writes no file
    - Logs never hold the API key, `str(exc)`, a prompt or an answer
    - _Requirements: 1.1, 1.4, 1.5, 1.6, 1.7, 1.8, 3.16, 6.1, 6.2, 6.3, 7.3, 7.4, 7.7, 7.8, 7.9, 7.10, 7.11, 7.13, 7.14, 7.16, 8.1, 8.13, 8.14, 9.1, 10.2, 10.5_

- [ ] 10. Checkpoint - Explainer tests
  - Run `.venv\Scripts\python.exe -m pytest tests/test_autopsy_explain.py -q` from the project root
  - Every test except the three provider tests (`test_no_key_means_no_client`, `test_unknown_provider_is_rejected`, `test_known_providers_build_without_network`) must pass now. These three fail with `NotImplementedError` because `make_client` is still a stub, which is expected at this checkpoint
  - Fix `explain.py` (never the tests) if an expected test fails, then re-run
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. LLM clients
  - [ ] 11.1 Implement `_scrub` and the key-shaped pattern
    - Implement `_KEY_SHAPED` and `_scrub(text, secret)`: replace the exact key, then key-shaped strings, with `[key removed]`
    - _Requirements: 9.1, 9.3_

  - [ ] 11.2 Implement `AnthropicClient`
    - Frozen dataclass with `api_key` (`field(repr=False)`), `model`, `provider = "anthropic"`, `max_tokens`, `timeout`
    - `complete_json`: raise `LLMError("LLM_API_KEY is not set.")` for an empty key; import `anthropic` inside the method and raise a clear `LLMError` when it is missing; call `messages.create` with one tool built from `_answer_schema()`, forced `tool_choice` of type `tool`, and no `temperature`; return the input of the first `tool_use` block as a `dict`; raise an `LLMError` whose message says the answer was not structured when there is no tool call
    - Wrap the vendor call in one `try`; re-raise as `LLMError` with the exception type and the scrubbed text, using `from None`
    - Note: IF the first real run returns an HTTP 400 that names `tool_choice` or thinking, the design's fallback (risk R-1) is to change `tool_choice` to `{"type": "any"}`. This is a one-line change in this client
    - _Requirements: 4.8, 4.12, 4.13, 4.15, 4.16, 9.1, 9.3_

  - [ ] 11.3 Implement `OpenAIClient`
    - Frozen dataclass with `api_key` (`field(repr=False)`), `model`, `provider = "openai"`, `max_tokens`, `timeout`
    - `complete_json`: same key check and lazy import; call `chat.completions.create` with `response_format={"type": "json_object"}`, `max_completion_tokens`, and the system prompt followed by `_JSON_FORMAT_NOTE`; parse the message content with `json.loads`; raise an `LLMError` that says the answer was not structured when it is not a JSON object
    - Same error wrapping and scrubbing as the Anthropic client
    - _Requirements: 4.8, 4.12, 4.14, 4.15, 4.16, 5.9, 9.1, 9.3_

  - [ ] 11.4 Implement `make_client` and `client_from_settings`
    - Replace the stubs of `make_client` and `client_from_settings` with the real code
    - `make_client(provider, api_key, model=None)`: normalise the provider (strip, lower case), raise `ValueError` naming the unknown provider and listing `anthropic` and `openai` first, then return `None` for a missing or blank key, otherwise the matching client with the default model when `model` is empty. It reads no setting, makes no network call and imports no SDK
    - `client_from_settings()`: read `LLM_PROVIDER` (default `anthropic`), `LLM_API_KEY` and `LLM_MODEL` through `gravedigger.config.setting` only and return `make_client(...)`; an empty `LLM_MODEL` means the default
    - Hard-code no key
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.9, 4.10, 4.11, 9.2_

- [ ] 12. Checkpoint - All 21 acceptance tests
  - Run `.venv\Scripts\python.exe -m pytest tests/test_autopsy_explain.py -q` from the project root and confirm all 21 tests pass
  - Run `git status --short tests` and confirm no file under `tests/` changed
  - Fix `explain.py` (never the tests) if any test fails, then re-run
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Project log
  - [ ] 13.1 Append an entry to `docs/kiro-log.md`
    - Append a short entry (keep the existing style of the file) about the `autopsy-explain` spec: requirements, design and tasks written with Kiro; the guardrail idea (every rule must cite live code lines with a fact, carry no line numbers in its text and use only numbers from the code; bad rules are kept with a reason); the cache that stores the raw answer and is re-checked on every read; the static fallback; the final SDK pins and any Smart App Control change from task 1.2
    - Contain no key and no secret
    - _Requirements: 9.1_

- [ ] 14. Final checkpoint - Full suite
  - [ ] 14.1 Run the whole suite and confirm 74 passing tests
    - Run `.venv\Scripts\python.exe -m pytest -q` from the project root
    - Confirm the summary reports 74 passed (53 existing plus 21 in `tests/test_autopsy_explain.py`) with no failures or errors, and report the exact summary line
    - Confirm with `git status --short tests` that no file under `tests/` was added or changed
    - Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

- [ ] 15. Sample script (extra, last task)
  - [ ] 15.1 Create `scripts/explain_sample.py`
    - Creating the script is part of this task. Do NOT run it against the real provider until the user has approved; ask the user first (one run costs about one cent).
    - Load `legacy/billing_pkg.pks` and `legacy/billing_pkg.pkb` as UTF-8 with `gravedigger.exhume.load_package`, scan all eight units with `scan`, build the client with `client_from_settings()`, and call `explain(unit, facts, client, cache_dir=golden/autopsy)` for each unit. Resolve paths from the repo root, not the current directory
    - Print for each unit: the name, the `source`, the summary, each kept rule with its cited lines, and each dropped rule with its reason
    - Use the cache lookup of the design: a unit has a cache file when `golden/autopsy` holds a file that matches `<unit>-<_source_hash(unit)>-*.json` (import `_source_hash` from `gravedigger.autopsy.explain`). When the client is `None` and any of the eight units has no cache file, exit with code 1 and a clear message that says `LLM_API_KEY` is not set and the cache in `golden/autopsy` is incomplete, before any call. When the client is `None` and all eight files exist, print the cached explanations and need no key
    - Print no API key, no setting value and no exception text beyond what `explain` logs
    - A second run with all cache files present makes no LLM call
    - Verify the script only with `.venv\Scripts\python.exe -c "import ast, pathlib; ast.parse(pathlib.Path('scripts/explain_sample.py').read_text(encoding='utf-8'))"`. Do not run it with a key set
    - If the first real run (after the user approves) returns an HTTP 400 about `tool_choice`, apply the design's fallback: set `tool_choice` to `{"type": "any"}` in `AnthropicClient`
    - _Requirements: 9.4, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

## Notes

- This plan has no test sub-tasks and no optional (`*`) tasks. The design's properties stay in prose, and the 21 existing acceptance tests plus the checkpoint runs are the verification (requirement 12.5).
- Requirements that no acceptance test covers (for example 3.5, 4.13 to 4.16, 6.1, 7.10 and 9.x) are implemented as in the design and verified by inspection or by the approved sample run. The design lists them per requirement.
- All tasks that edit `explain.py` run one after another, because they share the file.
- Do not modify `requirements.md`, `design.md` or any test file.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["3.1"] },
    { "id": 4, "tasks": ["3.2"] },
    { "id": 5, "tasks": ["5.1"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["7.1"] },
    { "id": 8, "tasks": ["8.1"] },
    { "id": 9, "tasks": ["8.2"] },
    { "id": 10, "tasks": ["9.1"] },
    { "id": 11, "tasks": ["11.1"] },
    { "id": 12, "tasks": ["11.2"] },
    { "id": 13, "tasks": ["11.3"] },
    { "id": 14, "tasks": ["11.4"] },
    { "id": 15, "tasks": ["13.1"] },
    { "id": 16, "tasks": ["14.1"] },
    { "id": 17, "tasks": ["15.1"] }
  ]
}
```
