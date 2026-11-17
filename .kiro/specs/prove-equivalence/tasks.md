# Implementation Plan: Prove Equivalence

## Overview

Three modules go under `src/gravedigger/prove/`: `compare.py`, `oracle_runner.py` and `strategies.py`. The contract is the existing `tests/test_prove_equivalence.py`, which already holds the unit and property tests (Properties 1 to 7 of the design). Per the user's decision, no test file is added, no test function or assertion is changed, and the only edit under `tests/` is `deadline=None` on the `dev` and `ci` profile registrations in `tests/conftest.py`. There are no test sub-tasks. Verification is done by running the existing tests, by MCP queries and by searches. All commands are PowerShell. Money is always `Decimal` built from strings or integers. Every public function docstring names its legacy unit (migration rules 8 and requirement 7.7).

## Tasks

- [x] 0. Disable the Hypothesis deadline
  - [x] 0.1 Set `deadline=None` on the `dev` and `ci` profiles in `tests/conftest.py`
    - Change only the two `settings.register_profile` calls: `dev` becomes `max_examples=200, deadline=None`. `ci` already has `deadline=None` and stays `max_examples=2000, derandomize=True, deadline=None`. Touch no test function, assertion or other file under `tests/`, and add no test file.
    - Update the docstring line of `conftest.py` only if it describes the profiles (`dev = 200 examples, no deadline`).
    - _Requirements: 6.3, 6.4, 7.6_

- [x] 1. Implement the field-by-field comparison
  - [x] 1.1 Create `src/gravedigger/prove/compare.py` with `FieldDiff` and `diff`
    - `FieldDiff` is a frozen dataclass with fields `field`, `oracle`, `python`, in that order, fully type-hinted.
    - `diff(oracle: Bill | None, python: Bill) -> tuple[FieldDiff, ...]` walks `dataclasses.fields(Bill)` in declaration order and compares with `!=` (exact `Decimal` equality, no tolerance, `due_dt` by exact date equality).
    - When `oracle` is `None`, return `(FieldDiff("bill", None, python),)`.
    - The docstring names `BILLING_PKG.p_gen_bill`.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 7.5, 7.7_

- [x] 2. Implement the Oracle runner
  - [x] 2.1 Create `src/gravedigger/prove/oracle_runner.py` with `run_oracle`
    - Define module constants `PROBE_CUST_NO = 900001` and `PROBE_BILL_MON = "209912"`.
    - `run_oracle(conn: oracledb.Connection, b: BillInput) -> Bill | None` does all work in one `try:` with `finally: conn.rollback()`. There is no `except` clause and no `commit`, so Oracle errors propagate unchanged.
    - Set a per-cursor `outputtypehandler` that returns `cursor.var(decimal.Decimal, arraysize=cursor.arraysize)` for `DB_TYPE_NUMBER`. Do not use the global `oracledb.defaults.fetch_decimals`.
    - Insert one `CUST_MST` row and one `MTR_RDG` row. Insert `FPA_RT` only when `fpa_rate is not None`. Insert `PYMT` (with its time part, `pay_amt` NULL) only when `pay_dt is not None`.
    - Use bind variables for every `BillInput` value. SQL text, table names and column names are fixed strings.
    - Call `BILLING_PKG.P_GEN_BILL` once through `callproc`, then select the `BILL_HDR` row for the probe. No row gives `None`. One row gives a `Bill` with `Decimal` amounts and `due_dt.date()`.
    - The module does not connect and does not read settings. The docstring names `BILLING_PKG.p_gen_bill` (pkb lines 146-207).
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 4.13, 7.1, 7.2, 7.4, 7.5, 7.7_

- [x] 3. Implement the input strategy
  - [x] 3.1 Create `src/gravedigger/prove/strategies.py` with legal ranges and the overflow filter
    - `bill_inputs() -> st.SearchStrategy[BillInput]` built with `@st.composite`.
    - Tariff `A1` or `A2`. Readings are integers 0 to 99999 with no ordering constraint. `load_kw` and `mf` are `Decimal` 0.01 to 9999.99 built from integers with `scaleb(-2)`. `fpa_rate` is `None` or a `Decimal` 0 to 9999.9999 built with `scaleb(-4)`. Never use `float`.
    - `rdg_dt` is a whole-second datetime from 2000-01-01 00:00:00 to 2099-12-31 23:59:59. `pay_dt` is `None` or a whole-second datetime from 2000-01-01 00:00:00 to 2100-01-31 23:59:59, so a payment can fall on the due date of a December 2099 reading.
    - Apply `.filter(fits_bill_header)`. The predicate calls `generate_bill`, treats `OverflowError` as a reject, and requires the eight amounts below 10^10 and the total below 10^12 in absolute value. Keep `mf` small in most draws to keep the reject rate low.
    - The docstring names `BILLING_PKG.p_gen_bill`, `f_units`, `f_due_dt` and `f_lps`.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 7.1, 7.5, 7.7_

  - [x] 3.2 Add the edge-scenario weighting to `bill_inputs`
    - Draw a scenario first, with common cases listed several times: `random`, `units_edge` (targets 0, 99, 100, 101, 200, 201, 300, 301, 345 with `mf = 1` and `curr = prev + target`), `rollover` (`curr < prev`), `shop` (A2), `no_fpa`, `unpaid`, `sunday_due`, `pay_on_due_day` (due date at a time after 00:00:00), `pay_midnight` (due date at 00:00:00) and `half_paisa`.
    - For `half_paisa`, build a pool of `(tariff, load_kw, units)` combinations once per `bill_inputs()` call by a small deterministic scan. A combination qualifies when the Port's unrounded sum before the final ROUND has a fractional part of exactly 0.50. Set `mf = 1`, `fpa_rate = None`, `pay_dt = None`. If the pool is empty, fall back to `random`.
    - Use the Port's `units` and `due_date` only to aim at edges. Do no heavy work per draw. Implement no seeding of its own.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 7.1, 7.8_

- [x] 4. Checkpoint - Run the non-Oracle tests
  - Run `.venv\Scripts\python.exe -m pytest -q -m "not oracle"` from the project root. The `diff` example tests, `test_inputs_fit_the_legacy_columns` and `test_strategy_reaches_the_edges` must pass. Do not edit `tests/` beyond task 0.1. Ask the user if questions arise.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 6.8_

- [x] 5. Run the Oracle tests
  - [x] 5.1 Start the Oracle container
    - Run `.\scripts\start-oracle.ps1` (or `docker compose up -d`) and wait until `gd-oracle` is healthy. Confirm `ORACLE_DSN`, `ORACLE_USER` and `APP_USER_PASSWORD` are set through `.env` and `gravedigger.config`. Never print or commit secrets.
    - _Requirements: 7.2, 7.3_

  - [x] 5.2 Run the tests marked `oracle`
    - Run `.venv\Scripts\python.exe -m pytest -q -m oracle`. Expect 8 passed, 0 skipped, 0 failed: the five seed bills (1001 to 1005), the nothing-left-behind test, the 345-unit rounding ghost and the equivalence property.
    - If a Ghost appears, record the shrunk input and the `FieldDiff` list. Fix the cause in `src/gravedigger/prove/` only when it is a bug in the runner, strategy or diff. Do not change a business rule in the Port and do not edit `tests/` beyond task 0.1. Report any real Port difference to the user.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.5, 6.6, 6.7_

- [x] 6. Verify the probe customer left no trace
  - [x] 6.1 Query the database with the grave-digger-oracle MCP `run_sql` tool
    - Count rows for `cust_no = 900001` in `CUST_MST`, `MTR_RDG`, `PYMT` and `BILL_HDR`. Count rows in `FPA_RT` for `bill_mon = '209912'`. All five counts must be 0.
    - Count all rows in `BILL_HDR` and confirm it still holds the 5 seed rows.
    - Record the counts for the final report.
    - _Requirements: 9.1, 9.2, 9.3_

- [x] 7. Fix the stale line numbers in the resurrect-billing design
  - [x] 7.1 Edit `.kiro/specs/resurrect-billing/design.md` (text only)
    - Replace the string `106-107` with `105-106` and the string `163-183` with `162-183`, at the four known places (lines 57, 134, 160 and 289). Match the number strings, not the surrounding phrase. Change no other character. Do not touch the other resurrect-billing spec files.
    - If neither stale string is found, leave the file unchanged and note that in the final report.
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 7.2 Verify the edit by search
    - Search `.kiro/specs/resurrect-billing/design.md` for `106-107` and `163-183`: both must return nothing. Search for `105-106` and `162-183`: together they must find the four edited places. Run `git diff --stat -- .kiro/specs/resurrect-billing/design.md` and confirm only those lines changed.
    - _Requirements: 8.1, 8.2, 8.3_

- [x] 8. Write the Kiro log entry
  - [x] 8.1 Append an entry to `docs/kiro-log.md`
    - Describe how Kiro was used on the Prove stage: the MCP checks against the real database (probe keys, `NUMBER` limits, the swallowed overflow, the Julian calendar finding), the spec-driven order of work, and the results of tasks 5 and 6. Use plain English with a light graveyard theme. Write the file as UTF-8 without BOM with LF line endings.
    - _Requirements: 6.7, 9.1, 9.2_

- [x] 9. Final run and report
  - [x] 9.1 Run the whole suite and write the final report
    - With the Oracle container running and `ORACLE_DSN` set, run `.venv\Scripts\python.exe -m pytest -q --hypothesis-show-statistics`. Expect exit code 0, all tests green, and the 8 `oracle` tests PASSED, none skipped. Use the statistics output, not a change to any test, to read how many random bills the equivalence property checked under the active profile (200 for `dev`, 2000 for `ci`).
    - Confirm `git status` shows only `tests/conftest.py` changed under `tests/`.
    - The report states: the total number of tests passed, that the 8 `oracle` tests PASSED and were not skipped, the number of random bills (examples) checked, "Ghost found" with the smallest failing input or "No Ghost found", the trace check counts from task 6.1, and the task 7 result.
    - The report tells the Julian-calendar finding as a documented risk: Oracle `DATE` is Julian before 1582-10-15 and Python is proleptic Gregorian (1000-03-01 is a Friday in Oracle and a Saturday in Python), and Oracle swallows a due date beyond year 9999. The strategy avoids both by generating only 2000-2100 dates.
    - _Requirements: 1.9, 6.3, 6.4, 6.7, 6.8, 7.6, 9.4, 9.5_

## Notes

- No task is optional. The design's Correctness Properties are already covered by the existing tests in `tests/test_prove_equivalence.py`, which this spec does not edit.
- Each task references specific requirements for traceability.
- Task 4 is a checkpoint. Tasks 5 and 6 need Docker and the Oracle container.
- Task 0.1 is configuration only (`deadline=None` in `tests/conftest.py`).
- Task 7 touches only text in a spec file, never code.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["0.1", "1.1", "2.1", "7.1"] },
    { "id": 1, "tasks": ["3.1", "7.2"] },
    { "id": 2, "tasks": ["3.2"] },
    { "id": 3, "tasks": ["5.1"] },
    { "id": 4, "tasks": ["5.2"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["8.1"] },
    { "id": 7, "tasks": ["9.1"] }
  ]
}
```
