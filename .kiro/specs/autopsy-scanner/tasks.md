# Implementation Plan: Autopsy Scanner

## Overview

Build the tokenizer, the block walker, Exhume (`load_package` and its dataclasses) and the scanner, in that order. Then add property tests as new files. The last task is a full pytest run.

All code is Python 3.12 with type hints, frozen dataclasses and the standard library only. Docstrings are in plain English. Numeric constants use `Decimal` built from text, never float. Files are UTF-8 without BOM with LF line endings.

## Environment rules for every task

- The terminal works. Run shell commands (pytest, python) directly and fix any failure from their output.
- Never modify `tests/test_autopsy_scanner.py`. It must stay byte-identical (Requirement 14.4).
- Property tests go in new files under `tests/`. Do not set `max_examples`; the `dev` and `ci` profiles in `tests/conftest.py` apply.

## Tasks

- [x] 1. Implement the tokenizer
  - [x] 1.1 Create `src/gravedigger/autopsy/tokenizer.py`
    - Add frozen `Segment` (kind, start, end, closed) and the `segments(text)` state machine for code, line comment, block comment and string. A doubled `''` stays in the string. `/*/` does not close itself. Unterminated comments and strings run to the end with `closed=False` and raise no error.
    - Add `mask(text)`: same length, comment and string characters (delimiters included) become spaces, `\n` and `\r` kept.
    - Add `string_literals(text)`: contents in order, delimiters stripped, `''` turned into `'`.
    - Add `line_starts`, `line_of` and `column_of` (1-based, lines counted by `\n` only), using `bisect`.
    - Import only `bisect`, `dataclasses` and `typing`.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 7.7, 7.8, 14.1_

- [x] 2. Implement the block walker
  - [x] 2.1 Create `src/gravedigger/autopsy/blocks.py`
    - Add frozen `Block` (kind, name, depth, start, header_end, end, exception_pos) and `find_blocks(masked)` returning blocks in opening order.
    - Use a stack. Read whole words only. `FUNCTION` and `PROCEDURE` open a block unless a `;` comes before `IS` or `AS` at parenthesis depth 0 (forward declaration). `DECLARE`, `BEGIN`, `IF`, `LOOP` and `CASE` open blocks; a `BEGIN` directly after a subprogram or `DECLARE` header marks that block as begun instead of opening a new one. `ELSIF` and `ELSE` open nothing.
    - Record `exception_pos` for an `EXCEPTION` keyword only when the top block is begun. `EXCEPTION_INIT` is a different word.
    - `END` pops one block and records its offset. A following `IF`, `LOOP` or `CASE` word is consumed. A stray `END` on an empty stack is ignored. Unclosed blocks keep `end=None`.
    - _Requirements: 2.1, 2.7, 2.8, 3.2, 3.6, 11.1, 11.8_

- [x] 3. Implement Exhume dataclasses and `load_package`
  - [x] 3.1 Create `src/gravedigger/exhume.py` with the data types and error class
    - Add `ExhumeError(ValueError)` and frozen dataclasses `Param`, `Global`, `Unit` and `Package` exactly as in the design. `Unit.sibling_names` and `Unit.global_names` default to `()` with `repr=False`. `Package.units` and `Package.globals` are tuples.
    - _Requirements: 1.5, 1.6, 2.3, 4.1_

  - [x] 3.2 Implement `load_package(spec_text, body_text)` and its private helpers in `exhume.py`
    - Read the package name from the masked spec (lower case); raise `ExhumeError` when there is no `CREATE OR REPLACE PACKAGE`. Collect globals in declared order, skipping `FUNCTION`, `PROCEDURE`, `TYPE`, `SUBTYPE`, `CURSOR`, `PRAGMA`, `CONSTANT` and `EXCEPTION` statements.
    - Require a `PACKAGE BODY` header in the masked body, otherwise raise `ExhumeError`.
    - Keep blocks with `depth == 0` and kind function or procedure. If a kept block has `end is None`, raise `ExhumeError` naming the unit and return no units.
    - Compute `start_line`, `end_line` and `source` (exact text of those lines, final line break and trailing `\r` dropped).
    - Parse headers: lower-case name, mode `IN` by default, upper-case datatype with normalised whitespace, return type for functions, `None` for procedures. Raise `ExhumeError` naming the unit for unbalanced parentheses, an empty piece, an unparseable parameter, or a function with no `RETURN`.
    - Fill `sibling_names` and `global_names` on every unit. A body with no units returns `units == ()`.
    - Before finishing, ask the user to run `.venv\Scripts\python.exe -m pytest -q tests/test_autopsy_scanner.py` and paste the output. Fix any failure that is about Exhume.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 13.1, 13.4, 13.5, 14.1, 14.3_

- [x] 4. Implement the scanner
  - [x] 4.1 Create `src/gravedigger/autopsy/scanner.py` with `Constant`, `Facts`, constants and string literals
    - Add frozen `Constant` (value `Decimal`, line, col) and frozen `Facts` with the nine fields from the design. Sets are `frozenset`, constants are a tuple.
    - Add `_masked_with_lines`, `find_constants` (regex from the design, `Decimal(match.group())`, line = `unit.start_line` plus newlines before the match, 1-based column) and string literals via `string_literals(unit.source)`.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

  - [x] 4.2 Add tables, name uses and branch counting to `scanner.py`
    - Add `find_tables` (write patterns first, `FOR UPDATE` is not a write, read matches skip tokens already claimed as write targets, schema prefix dropped, names upper-cased), `whole_word`, `find_name_uses` (case-insensitive, whole word, lower-case results) and `count_branches` (`IF` and `ELSIF`, not `END IF`).
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 10.4, 10.5, 12.1, 12.2, 12.3, 12.4, 12.6_

  - [x] 4.3 Add `find_handlers` and the public `scan(unit)` to `scanner.py`
    - `find_handlers` uses `find_blocks`. A `WHEN` counts only when the innermost block containing it has an `exception_pos` before it. Split conditions on whole-word `OR`, upper-case the names, and set `swallows_errors` when an `OTHERS` handler body is only `NULL;`.
    - `scan` assembles `Facts`: calls are sibling names minus the unit's own name, globals come from `unit.global_names`. No I/O, no network.
    - Ask the user to run `.venv\Scripts\python.exe -m pytest -q tests/test_autopsy_scanner.py` and paste the output. Fix any failure.
    - _Requirements: 8.9, 9.6, 9.7, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 12.5, 13.2, 13.3, 14.1, 14.2, 14.3_

- [ ] 5. Property tests (new files only)
  - [ ]* 5.1 Write property test for masking layout in `tests/test_props_mask_layout.py`
    - **Property 1: Masking preserves layout**
    - **Validates: Requirements 5.3, 5.4, 5.8**

  - [ ]* 5.2 Write property test for masked text invariants in `tests/test_props_mask_invariants.py`
    - **Property 2: Masked text has no comment or quote markers, and masking is idempotent**
    - **Validates: Requirements 5.1, 5.2, 5.8**

  - [ ]* 5.3 Write property test for the structural oracle in `tests/test_props_mask_oracle.py`
    - **Property 3: Masking matches a structural oracle**
    - **Validates: Requirements 5.1, 5.2, 5.5, 5.6**

  - [ ]* 5.4 Write property test for unterminated openers in `tests/test_props_mask_unterminated.py`
    - **Property 4: Unterminated openers mask to the end**
    - **Validates: Requirements 5.7**

  - [ ]* 5.5 Write property test for string literal round trip in `tests/test_props_string_literals.py`
    - **Property 5: String literal round trip**
    - **Validates: Requirements 7.1, 7.2, 7.4, 7.7, 7.8**

  - [ ]* 5.6 Write property test for constants in `tests/test_props_constants.py`
    - Build values with `Decimal` from text. Never use float strategies.
    - **Property 6: Constants are exact, live, ordered and located**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.8**

  - [ ]* 5.7 Write property test for tables in `tests/test_props_tables.py`
    - **Property 7: Tables are classified, normalised and live-only**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8**

  - [ ]* 5.8 Write property test for name uses in `tests/test_props_name_uses.py`
    - **Property 8: Name uses are whole-word, live-only and case-insensitive**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 12.1, 12.2, 12.3, 12.6**

  - [ ]* 5.9 Write property test for branch counting in `tests/test_props_branches.py`
    - **Property 9: Branch count counts IF and ELSIF only**
    - **Validates: Requirements 10.1, 10.3, 10.5**

  - [ ]* 5.10 Write property test for handlers in `tests/test_props_handlers.py`
    - **Property 10: Handlers are collected only from handler sections**
    - **Validates: Requirements 11.1, 11.4, 11.5, 11.8, 11.9**

  - [ ]* 5.11 Write property test for keyword case independence in `tests/test_props_case.py`
    - **Property 11: Keyword case does not change facts**
    - **Validates: Requirements 2.10, 13.4**

  - [ ]* 5.12 Write property test for unit discovery in `tests/test_props_units.py`
    - **Property 12: Unit discovery, ranges and source slices**
    - **Validates: Requirements 2.1, 2.3, 2.4, 2.5, 2.7, 2.8, 2.9, 2.10, 3.1, 3.2, 3.4, 3.5, 13.1**

  - [ ]* 5.13 Write property test for parameters in `tests/test_props_params.py`
    - **Property 13: Parameters parse in order and ignore layout**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.7**

  - [ ]* 5.14 Write property test for package name and globals in `tests/test_props_globals.py`
    - **Property 14: Package name and globals**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4**

  - [ ]* 5.15 Write property test for malformed input in `tests/test_props_malformed.py`
    - **Property 15: Malformed input is rejected, never half-loaded**
    - **Validates: Requirements 1.7, 3.6, 4.8, 13.5**

  - [ ]* 5.16 Write property test for determinism in `tests/test_props_determinism.py`
    - **Property 16: Scanning is deterministic**
    - **Validates: Requirements 14.2**

- [x] 6. Fix edge cases found in review (pinned by `tests/test_autopsy_scanner_edge.py`, never edited)
  - [x] 6.1 Ignore DUAL in `find_tables`
    - Drop `DUAL` from `tables_read` after matching.
    - _Requirements: 15.1, 15.2_

  - [x] 6.2 Ignore FROM inside EXTRACT and TRIM in `find_tables`
    - For each read match, find the parenthesis that directly encloses it; skip the match when the word before that `(` is `EXTRACT` or `TRIM`.
    - _Requirements: 16.1, 16.2, 16.3_

  - [x] 6.3 Ignore datatype sizes in `find_constants`
    - Find `<datatype>(...)` spans on masked text and skip literals inside them.
    - _Requirements: 17.1, 17.2, 17.3_

  - [x] 6.4 Keep the sign of unary minus in `find_constants`
    - Look back from each literal for a `-`. It is unary unless the previous code character ends an operand, with the keyword exceptions in Requirement 18.1. Report the negative value at the minus position.
    - Run `.venv\Scripts\python.exe -m pytest -q tests/test_autopsy_scanner_edge.py` and fix any failure.
    - _Requirements: 18.1, 18.2, 18.3, 18.4_
- [x] 7. FINAL: Run the full test suite
  - The terminal is unavailable in this environment. Ask the user to run `.venv\Scripts\python.exe -m pytest -q` from the project root with `ORACLE_DSN` unset, and to paste the full output back.
  - Read the output. For every failed, errored or skipped test in `tests/test_autopsy_scanner.py`, find the cause and fix the source code under `src/gravedigger/`. Never edit `tests/test_autopsy_scanner.py`.
  - For a failing property test, fix the code if the counterexample shows a real bug, or fix the new test file if the generator is wrong.
  - Ask the user to run the command again after each fix, until the output shows zero failures, zero errors and zero skips for `tests/test_autopsy_scanner.py`.
  - _Requirements: 14.4, 14.5, 14.6, 15.1, 16.1, 17.1, 18.1_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP.
- Each task references specific requirements for traceability.
- Property tests validate the universal properties in the design. The existing acceptance tests cover the concrete legacy facts.
- Shell commands are always run by the user, who pastes the output back.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["3.2"] },
    { "id": 4, "tasks": ["4.1"] },
    { "id": 5, "tasks": ["4.2"] },
    { "id": 6, "tasks": ["4.3"] },
    { "id": 7, "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5", "5.6", "5.7", "5.8", "5.9", "5.10", "5.11", "5.12", "5.13", "5.14", "5.15", "5.16"] },
    { "id": 8, "tasks": ["6.1"] },
    { "id": 9, "tasks": ["6.2"] },
    { "id": 10, "tasks": ["6.3"] },
    { "id": 11, "tasks": ["6.4"] },
    { "id": 12, "tasks": ["7"] }
  ]
}
```
