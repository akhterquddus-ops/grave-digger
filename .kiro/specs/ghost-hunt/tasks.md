# Implementation Plan: Ghost Hunt

## Overview

Build the ghost hunt in Python 3.12 (the design uses concrete Python). The work adds `golden.py`, `hunt.py`, `billing_draft.py`, `scripts/make_golden.py` and one new test file. It never modifies `billing.py`, `oracle_runner.py`, `compare.py`, `strategies.py` or any existing test. Money is `Decimal` built from strings or integers. The pre-rounding sum has seven terms (`enrg`, `fix`, `fpa`, `ed`, `gst`, `tv`, `lps`), not eight; `units` is not part of it. Commands are PowerShell syntax and run from `C:\Akhtar-Works\grave-digger` with `.venv\Scripts\python.exe`.

## Tasks

- [x] 1. Baseline before any code
  - [x] 1.1 Re-read the Port's unit-function signatures
    - Read `src/gravedigger/resurrected/billing.py` (read only) and note the exact signatures of `units`, `energy_charge`, `fixed_charge`, `fpa`, `taxes`, `due_date`, `lps` and `generate_bill`, plus the `Bill` and `BillInput` field names and order.
    - Confirm the TV amount rule (35 for tariff `A1`, otherwise 60) against `generate_bill`.
    - Plan to call these only as `billing.xxx` so local variable names do not shadow the functions (`units`, `fpa`, `lps`).
    - Also read `src/gravedigger/prove/compare.py` (`diff`, `FieldDiff`), `oracle_runner.py` (`run_oracle`), `config.py` (the helper that gives Oracle connection parameters, and `REPO_ROOT`) and `tests/test_resurrect_billing.py` (shape of `SEED`). Do not edit them.
    - _Requirements: 5.3, 5.5, 9.7_

  - [x] 1.2 Run the baseline no-trace query through the MCP server
    - Load the tool with `tool_load` using `grave-digger-oracle::run_sql`, then run it with `tool_call` (single argument `query`).
    - Query (one statement, six rows):
      ```sql
      SELECT 'CUST_MST' AS tbl, COUNT(*) AS n FROM CUST_MST WHERE cust_no = 900001
      UNION ALL SELECT 'MTR_RDG', COUNT(*) FROM MTR_RDG WHERE cust_no = 900001
      UNION ALL SELECT 'PYMT', COUNT(*) FROM PYMT WHERE cust_no = 900001
      UNION ALL SELECT 'BILL_HDR (probe)', COUNT(*) FROM BILL_HDR WHERE cust_no = 900001
      UNION ALL SELECT 'FPA_RT (209912)', COUNT(*) FROM FPA_RT WHERE bill_mon = '209912'
      UNION ALL SELECT 'BILL_HDR (all)', COUNT(*) FROM BILL_HDR
      ```
    - Expected baseline: 0, 0, 0, 0, 0, 5. Record the six numbers. If the counts differ, stop and report.
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [x] 2. Implement `src/gravedigger/prove/golden.py`
  - [x] 2.1 Add `GoldenCase`, `GOLDEN_PATH`, `save_cases` and `load_cases`
    - Create the module with `oracledb` only under `TYPE_CHECKING`, so it imports without the driver.
    - `GoldenCase` is a frozen dataclass with fields `input: BillInput`, `oracle: Bill | None`, in that order. `GOLDEN_PATH = REPO_ROOT / "golden" / "cases.json"`.
    - `save_cases(path, cases)`: one record per line in the layout `[\n<record>,\n...<record>\n]\n` (`[]\n` when empty). Each record is `json.dumps(record, separators=(",", ":"), ensure_ascii=True)`. Write with `path.write_bytes(text.encode("utf-8"))` so there is no BOM and no `\r\n`.
    - Encoding: `Decimal` as `format(d, "f")` string, `datetime` and `date` as `isoformat()`, `prev_rdg` and `curr_rdg` as JSON integers, `None` as `null`. Key order follows the dataclass field order.
    - `load_cases(path)`: read bytes, decode UTF-8, parse, return a tuple in file order. A missing file lets `FileNotFoundError` propagate. Every other problem raises `ValueError` naming the record index and field (top level not a list, wrong keys, non-string or non-finite decimals, bad ISO text, `bool` or non-`int` readings). Catch `json.JSONDecodeError`, `KeyError`, `TypeError`, `decimal.InvalidOperation` and re-raise as `ValueError(...) from exc`. `rdg_dt` and `pay_dt` return `datetime`, `due_dt` returns `date`.
    - Add type hints everywhere. Each public docstring says it ports no legacy unit or names `BILLING_PKG.p_gen_bill` (pkb lines 146-207).
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 1.9, 1.10, 9.1, 9.3, 9.4, 9.5_

  - [x] 2.2 Add `build_golden`
    - `build_golden(conn, inputs) -> tuple[GoldenCase, ...]`: import `run_oracle` inside the function. Call it once per input in order, append `GoldenCase(b, result)` (`None` result stored as `oracle=None`), and convert to a tuple only after the loop, so an error propagates unchanged with no partial result.
    - Never call `commit()`, open a connection or read settings.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 9.4_

  - [x] 2.3 Smoke check `golden.py` without Oracle
    - Run a one-off PowerShell check with `.venv\Scripts\python.exe -c "..."`: import the module and confirm `oracledb` is not in `sys.modules`.
    - Round-trip a small list of cases (including one with `oracle=None`, a `Decimal("2.00")` scale and a datetime with a time part) through a temporary folder. Confirm equality, no `e+` in the text, no BOM bytes and no `\r`.
    - Confirm `FileNotFoundError` for a missing path, `ValueError` for malformed JSON, and `FrozenInstanceError` on assignment to a `GoldenCase`.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 1.9, 1.10_

- [x] 3. Implement `src/gravedigger/prove/hunt.py`
  - [x] 3.1 Add `Ghost`, `HuntReport` and `hunt`
    - `Ghost(input, oracle, python, diffs)` and `HuntReport(checked, matched, ghosts)` are frozen dataclasses with those field orders.
    - `hunt(port, cases)`: materialise `cases` once with `tuple(cases)`. For each case call `port(case.input)` once, compute `diff(case.oracle, python)`, count a match when the tuple is empty, otherwise append `Ghost(case.input, case.oracle, python, diffs)`. Return `HuntReport(checked=len(cases), matched=len(cases) - len(ghosts), ghosts=tuple(ghosts))`. Do not catch port exceptions.
    - `smallest` property: `None` when there are no ghosts, else `min(self.ghosts, key=_size)` where `_size` takes the bill from `g.oracle` or, when it is `None`, from `g.python`, and returns `(bill.units, bill.total)`.
    - Import only `compare.diff`, `compare.FieldDiff`, `golden.GoldenCase` and `billing` types. Nothing that imports `oracledb`. No I/O, no global state.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 9.3, 9.4_

  - [x] 3.2 Smoke check `hunt.py` and run the existing non-Oracle tests
    - One-off check: importing `gravedigger.prove.hunt` does not load `oracledb`. An empty case list gives `checked` 0, `matched` 0, `ghosts == ()` and `smallest is None`. A port returning `total` 1 for a 2345-unit case and a 345-unit case gives the 345-unit ghost as `smallest`.
    - Run `.venv\Scripts\python.exe -m pytest -q -rs tests\test_ghost_hunt.py` and note which tests still wait for the draft or the snapshot (they may fail or skip until later tasks; do not edit the test file).
    - _Requirements: 3.8, 3.10, 4.1, 6.4_

- [x] 4. Implement `src/gravedigger/resurrected/billing_draft.py`
  - [x] 4.1 Add the deliberately wrong draft
    - Module docstring contains `DELIBERATELY` and says the module is wrong on purpose: Python's built-in `round()` rounds half to even, Oracle `ROUND` rounds half up.
    - `generate_bill(inp: BillInput) -> Bill`: `port = billing.generate_bill(inp)`, `pre = port.enrg + port.fix + port.fpa + port.ed + port.gst + port.tv + port.lps` (seven terms, no `units`), then `total = Decimal(str(round(pre)))` with a comment marking it as the deliberate defect, and `return dataclasses.replace(port, total=total)`.
    - Docstring contains the text `round()`, says it is wrong on purpose, names `BILLING_PKG.p_gen_bill` and `pkb line 193`, and gives the example: a sum of 9048.50 gives 9048 in the draft and 9049 in Oracle.
    - Do not copy any Port code. Leave `billing.py` untouched. This is the only `round()` call on money in the repository.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.8, 5.9, 5.10, 9.1, 9.3, 9.4_

  - [x] 4.2 Smoke check the draft
    - One-off check: the draft bill equals the Port bill in every field except `total` for the five seed inputs, and for the Rounding_Ghost_Input the draft total is `Decimal("9048")` while the Port total is `Decimal("9049")`.
    - Search `src` for `round(` and confirm the only money use is in `billing_draft.py`.
    - _Requirements: 5.3, 5.7, 5.8, 5.9, 5.10_

- [x] 5. Checkpoint - Ensure all tests pass
  - Run `.venv\Scripts\python.exe -m pytest -q -rs -m "not oracle"` and ensure existing tests still pass (snapshot-dependent tests may skip only while `golden/cases.json` does not exist). Ask the user if questions arise.

- [x] 6. Implement `scripts/make_golden.py`
  - [x] 6.1 Add `known_inputs`, `draw_inputs` and `write_atomically`
    - Module docstring documents the fixed seed (`20261113`), `derandomize=True`, the draw size, the dedupe rule, and that it ports no legacy unit. Constants: `SEED_VALUE = 20261113`, `DRAW_COUNT = 2000`, `OVERDRAW = 2600`.
    - `known_inputs()`: the five seed inputs sorted by customer number, then the Rounding_Ghost_Input (tariff `A1`, load 2, readings 0 and 345, mf 1, rdg_dt 2024-01-10 00:00:00, no FPA rate, no payment). Import `SEED` from `tests/test_resurrect_billing.py` by adding `REPO_ROOT / "tests"` to `sys.path`; use the shape read in task 1.1.
    - `draw_inputs(known)`: a collecting Hypothesis test with `@seed(SEED_VALUE)`, `@settings(max_examples=OVERDRAW, derandomize=True, database=None, phases=[Phase.generate], suppress_health_check=list(HealthCheck), deadline=None)` and `@given(bill_inputs())`. Walk the draws in order, keep each input not already in a `seen` set (pre-filled with the known inputs), stop at `DRAW_COUNT`. If fewer than 2000 distinct inputs result, signal the caller to exit 1 before touching Oracle.
    - `write_atomically(cases, target)`: create `golden/`, write `cases.json.tmp` with `save_cases`, re-read with `load_cases` and check equality with `tuple(cases)`, then `os.replace(tmp, target)`. On any exception delete the temp file with `unlink(missing_ok=True)` and re-raise, leaving an earlier snapshot intact.
    - No `float`, full type hints, no secrets.
    - _Requirements: 7.2, 7.3, 7.8, 7.9, 9.1, 9.3, 9.4, 9.5_

  - [x] 6.2 Add `main()` and the entry point
    - First check the real name of the settings helper in `gravedigger/config.py` (the design calls it `oracle_params()`), and use that name.
    - Flow: build the input list (known plus drawn), fewer than 2000 distinct returns 1 with a message and the count. Connect with `oracledb.connect(**<config helper>())`. On `RuntimeError` or `oracledb.Error` print "Could not reach Oracle. Start the container with scripts/start-oracle.ps1, then run this again." plus only the exception class name, and return 2 with no file written. Never print settings or passwords.
    - Then `cases = build_golden(conn, inputs)`. If any `case.oracle is None`, print that input and return 1 with no file written. Otherwise `write_atomically(cases, GOLDEN_PATH)`, print the number of cases written and the draft's ghost count (`len(hunt(billing_draft.generate_bill, cases).ghosts)`), return 0. Close the connection in a `finally`.
    - End the file with `if __name__ == "__main__": raise SystemExit(main())`.
    - _Requirements: 7.1, 7.4, 7.5, 7.6, 7.7, 7.9, 9.9_

  - [x] 6.3 Check the script without Oracle and check the ignore rules
    - Run `.venv\Scripts\python.exe -c "import runpy; ..."` or an equivalent import to confirm the module imports and `known_inputs()` returns 6 inputs with `draw_inputs` giving 2000 distinct, repeatable inputs (call it twice in separate processes and compare a hash of the sequence).
    - Run `git check-ignore -v golden/cases.json` and confirm it prints nothing (the file is not ignored). Confirm `.gitignore` does not list `.kiro`.
    - _Requirements: 7.2, 7.3, 7.11_

- [x] 7. Add `tests/test_ghost_hunt_properties.py` (new file, exactly three properties)
  - [x] 7.1 Add generators and shared helpers
    - Create the new file with UTF-8 (no BOM) and LF endings. Build `bill_inputs()` once at module level.
    - `golden_cases()`: `st.builds(GoldenCase, bill_inputs(), st.one_of(st.none(), port_bills, arbitrary_bills))` where `port_bills = bill_inputs().map(billing.generate_bill)` and `arbitrary_bills` uses `st.builds(Bill, ...)` with `st.decimals(min_value=-10**12, max_value=10**12, places=4, allow_nan=False, allow_infinity=False)` and `st.dates()`.
    - `ports()`: `st.sampled_from` over `billing.generate_bill`, `billing_draft.generate_bill`, and a perturbing port built from a drawn `delta` in `{-1, 0, 1}` and a drawn modulus `k` in `1..4` using `dataclasses.replace(..., total=total + delta)` when `hash(b) % k == 0`.
    - Define `pre_rounding_sum(b)` by chaining `billing.units`, `billing.energy_charge`, `billing.fixed_charge`, `billing.fpa`, `billing.taxes`, `billing.due_date`, `billing.lps` and the TV rule (35 for `A1`, else 60), returning `enrg + fix + fpa + ed + gst + tv + lps`. It must not read any `Bill` or the draft's internals.
    - Define `GHOST_INPUT` (the Rounding_Ghost_Input).
    - _Requirements: 11.6, 11.7, 11.8_

  - [x] 7.2 Write the property for R1.7
    - **Property 1: Golden file round trip**
    - Name it `test_r1_7_save_then_load_returns_the_same_cases`, with `@given(st.lists(golden_cases(), max_size=5))`. Use `tempfile.TemporaryDirectory()` per example (not `tmp_path`). Assert `load_cases(path) == tuple(cases)`.
    - **Validates: Requirements 1.7**

  - [x] 7.3 Write the property for R3.5
    - **Property 2: Hunt report adds up**
    - Name it `test_r3_5_checked_equals_matched_plus_ghosts`, with `@given(ports(), st.lists(golden_cases(), max_size=8))`. Assert `report.checked == len(cases)` and `report.checked == report.matched + len(report.ghosts)`.
    - **Validates: Requirements 3.5**

  - [x] 7.4 Write the property for R5.3 and R5.6
    - **Property 3: The draft differs from the port only by half-even rounding of the total**
    - Name it `test_r5_3_r5_6_draft_differs_from_port_only_by_half_even_total`, with `@given(bill_inputs())` and `@example(GHOST_INPUT)`.
    - Assert every `Bill` field except `total` is equal (use `dataclasses.fields(Bill)`). With `pre = pre_rounding_sum(inp)`, `expect_differ = (pre % 1 == Decimal("0.5")) and (int(pre) % 2 == 0)`. Assert `(draft.total != port.total) == expect_differ`; when they differ assert `port.total - draft.total == Decimal(1)`, otherwise equal totals.
    - **Validates: Requirements 5.3, 5.6**

  - [x] 7.5 Run the new file and time it
    - Run `.venv\Scripts\python.exe -m pytest -q -rs tests\test_ghost_hunt_properties.py --durations=3` under the default `dev` profile. Confirm three tests pass in under 5 seconds total, with no Oracle and no network. Confirm the file holds exactly three `@given` tests.
    - _Requirements: 11.6, 11.7, 11.8_

- [x] 8. Checkpoint - Ensure all tests pass without the snapshot
  - Run `.venv\Scripts\python.exe -m pytest -q -rs`. Confirm no failures except tests that wait for `golden/cases.json` (those skip only while the file is missing). Run `git status --short` and confirm nothing under `tests/` is modified (only the new properties file is added) and `billing.py` is unchanged. Ask the user if questions arise.

- [x] 9. Build the golden snapshot once (Oracle must be running)
  - [x] 9.1 Baseline no-trace check before the run
    - If the container is not running, start it with `scripts\start-oracle.ps1` and wait until it is healthy.
    - Run the MCP `grave-digger-oracle::run_sql` query from task 1.2 again. Expect 0, 0, 0, 0, 0, 5 and record the numbers.
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 9.2 Run `scripts\make_golden.py` once
    - Run `.venv\Scripts\python.exe scripts\make_golden.py` from the project root with an explicit timeout of 1800000 ms. Confirm exit code 0, record the printed case count (at least 2000, expected 2006) and the draft's ghost count (at least 1).
    - Confirm `golden\cases.json` exists, has no BOM, no `\r`, no `e+`, and that no `cases.json.tmp` is left behind.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.6, 7.8, 7.10_

  - [x] 9.3 No-trace check after the run
    - Run the same MCP `run_sql` query. Expect 0, 0, 0, 0, 0, 5. A non-zero probe count means something committed: stop and investigate. Record the six numbers.
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [x] 10. Final full run and report
  - [x] 10.1 Run the full test suite with Oracle up
    - Run `.venv\Scripts\python.exe -m pytest -q -rs` with the container running. Expect exit code 0, zero failed, zero skipped, and every `oracle` test passed.
    - Record the total number of tests passed.
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 11.1, 11.2, 11.5_

  - [x] 10.2 Report the numbers and log them
    - Compute with a one-off PowerShell check: the golden case count, the draft's ghost count, and the Smallest_Ghost of the draft (input, Oracle total, draft total) from `hunt(billing_draft.generate_bill, load_cases(GOLDEN_PATH))`.
    - Append a short section to `docs/kiro-log.md` (UTF-8 without BOM, LF) with: tests passed, oracle tests passed and not skipped, golden case count, draft ghost count, the Smallest_Ghost, and the six MCP counts from task 9.3.
    - State the same numbers in the final report to the user.
    - _Requirements: 10.4, 11.2, 11.3, 11.4_

## Notes

- Tasks marked with `*` are optional. None are marked here because the three properties are required by Requirement 11.6.
- The three Hypothesis properties are the only property tests; no other requirement obliges a property test (Requirement 11.8).
- Never modify an existing test, `billing.py`, `oracle_runner.py`, `compare.py` or `strategies.py`.
- The pre-rounding sum has seven terms. Requirements 5.3 and 5.4 mention eight amounts, but `units` is a quantity and is not summed (see the design's note).
- Tasks 9 and 10 need Docker and Oracle running. Do not start long-running servers in the agent; run them yourself if a step stalls.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "4.1"] },
    { "id": 2, "tasks": ["2.2", "3.1", "4.2"] },
    { "id": 3, "tasks": ["2.3", "3.2"] },
    { "id": 4, "tasks": ["6.1"] },
    { "id": 5, "tasks": ["6.2"] },
    { "id": 6, "tasks": ["6.3", "7.1"] },
    { "id": 7, "tasks": ["7.2"] },
    { "id": 8, "tasks": ["7.3"] },
    { "id": 9, "tasks": ["7.4"] },
    { "id": 10, "tasks": ["7.5"] },
    { "id": 11, "tasks": ["9.1"] },
    { "id": 12, "tasks": ["9.2"] },
    { "id": 13, "tasks": ["9.3"] },
    { "id": 14, "tasks": ["10.1"] },
    { "id": 15, "tasks": ["10.2"] }
  ]
}
```
