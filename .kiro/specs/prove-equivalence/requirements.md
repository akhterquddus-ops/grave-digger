# Requirements Document

## Introduction

The Prove stage shows that the Python port bills exactly like the legacy PL/SQL package `BILLING_PKG`. Hypothesis generates random customers and meter readings. Each one is billed by the real legacy procedure in Oracle and by the Python port, and every field of the bill must match. A mismatch is a "ghost".

This spec adds three modules under `src/gravedigger/prove/`: `strategies.py` (`bill_inputs`), `compare.py` (`FieldDiff`, `diff`) and `oracle_runner.py` (`run_oracle`). The contract is the module docstring of `tests/test_prove_equivalence.py`. That test file is not modified. The only change under `tests/` is `deadline=None` on the `dev` and `ci` profile registrations in `tests/conftest.py`. The spec also corrects two stale line numbers in `.kiro/specs/resurrect-billing/design.md`.

## Glossary

- **Prove_Package**: The Python package `gravedigger.prove`.
- **Strategy_Module**: The module `gravedigger.prove.strategies`.
- **Bill_Input_Strategy**: The Hypothesis strategy `bill_inputs()` that produces `BillInput` values.
- **Compare_Module**: The module `gravedigger.prove.compare`.
- **FieldDiff**: A frozen dataclass with fields `field`, `oracle` and `python`, describing one differing bill field.
- **Diff_Function**: The function `diff(oracle, python)` in the Compare_Module.
- **Oracle_Runner**: The module `gravedigger.prove.oracle_runner`.
- **Run_Oracle_Function**: The function `run_oracle(conn, BillInput)` in the Oracle_Runner.
- **Probe_Customer**: The temporary customer used for one Oracle billing run, with `cust_no` 900001 and `bill_mon` '209912'. No seed row uses either value.
- **Legacy_Procedure**: The Oracle procedure `BILLING_PKG.p_gen_bill`.
- **Port**: The Python function `gravedigger.resurrected.billing.generate_bill`.
- **BillInput**: The frozen dataclass of billing inputs defined in `gravedigger.resurrected.billing`.
- **Bill**: The frozen dataclass of billing results defined in `gravedigger.resurrected.billing`.
- **Ghost**: An input for which Oracle and the Port produce different bills.
- **Legacy_Column_Limits**: NUMBER(5) meter readings, NUMBER(6,2) sanctioned load and multiplying factor, NUMBER(8,4) FPA rate, and tariff `A1` or `A2`.
- **Bill_Header_Limits**: The `BILL_HDR` limits of NUMBER(12,2) for amounts and NUMBER(12) for the total. A bill beyond these limits makes Oracle swallow the overflow, write no row, and produce a false Ghost.
- **Oracle_Container**: The local Oracle Database Free container `gd-oracle`, started with `scripts/start-oracle.ps1`.
- **Hypothesis_Profiles**: The Hypothesis settings profiles registered in `tests/conftest.py` and selected by `HYPOTHESIS_PROFILE`. `dev` (default) sets `max_examples=200` and `deadline=None`. `ci` sets `max_examples=2000`, `derandomize=True` and `deadline=None`.
- **Equivalence_Property**: The Hypothesis test `test_python_port_bills_exactly_like_oracle`.
- **Test_Suite**: The command `.venv\Scripts\python.exe -m pytest -q`.
- **Resurrect_Design**: The file `.kiro/specs/resurrect-billing/design.md`.

## Requirements

### Requirement 1: Legal Random Inputs

**User Story:** As a migration engineer, I want random test inputs that fit the legacy database columns, so that every generated bill can be stored and compared in Oracle.

#### Acceptance Criteria

1. THE Bill_Input_Strategy SHALL produce only `BillInput` values whose tariff is exactly the upper-case string `A1` or `A2`.
2. THE Bill_Input_Strategy SHALL produce only `BillInput` values whose `prev_rdg` and `curr_rdg` are `int` values from 0 to 99999 inclusive, with no ordering constraint between them.
3. THE Bill_Input_Strategy SHALL produce `load_kw` and `mf` as finite `Decimal` values from 0.01 to 9999.99 inclusive with at most 2 decimal places.
4. WHERE `fpa_rate` is not `None`, THE Bill_Input_Strategy SHALL produce `fpa_rate` as a finite `Decimal` value from 0 to 9999.9999 inclusive with at most 4 decimal places.
5. THE Bill_Input_Strategy SHALL produce `rdg_dt` values with a microsecond part of 0 from 2000-01-01 00:00:00 to 2099-12-31 23:59:59 inclusive (realistic billing dates), and SHALL produce `pay_dt` as `None` or a value with a microsecond part of 0 from 2000-01-01 00:00:00 to 2100-01-31 23:59:59 inclusive, so that a payment can fall on the due date of a December 2099 reading.
6. THE Bill_Input_Strategy SHALL produce only `BillInput` values for which the Port returns a Bill whose `units`, `enrg`, `fix`, `fpa`, `ed`, `gst`, `tv` and `lps` each have an absolute value below 10 to the power 10, and whose `total` has an absolute value below 10 to the power 12.
7. THE Bill_Input_Strategy SHALL build every `Decimal` value from strings or integers and never from `float`.
8. IF a candidate `BillInput` cannot meet criterion 6, THEN THE Bill_Input_Strategy SHALL discard the candidate and pass it to none of the test, the Port and Oracle.
9. THE date range of criterion 5 SHALL avoid two known traps: Oracle DATE uses the Julian calendar before 1582-10-15 while the Port uses the proleptic Gregorian calendar, and Oracle swallows a due date beyond year 9999. THE Bill_Input_Strategy SHALL therefore produce no date before 2000-01-01 and no date after 2100-01-31. THE final report SHALL state the Julian-calendar finding as a documented risk.

### Requirement 2: Edge-Weighted Inputs

**User Story:** As a migration engineer, I want the random inputs weighted towards the places where legacy code is tricky, so that the proof finds ghosts quickly.

#### Acceptance Criteria

1. THE Bill_Input_Strategy SHALL be able to produce an input whose computed Units equal 0, and an input for each of the Units values 100, 101, 200, 201, 300, 301 and 345.
2. THE Bill_Input_Strategy SHALL be able to produce an input with `curr_rdg` less than `prev_rdg` (meter rollover).
3. THE Bill_Input_Strategy SHALL be able to produce an input with tariff `A2`.
4. THE Bill_Input_Strategy SHALL be able to produce an input with `fpa_rate` equal to `None`.
5. THE Bill_Input_Strategy SHALL be able to produce an input with `pay_dt` equal to `None`.
6. THE Bill_Input_Strategy SHALL be able to produce an input whose reading date plus 14 days falls on a Sunday.
7. THE Bill_Input_Strategy SHALL be able to produce an input whose `pay_dt` falls on the calendar day of the due date at a time later than 00:00:00.
8. THE Bill_Input_Strategy SHALL be able to produce an input whose `pay_dt` is exactly 00:00:00 of the due date.
9. THE Bill_Input_Strategy SHALL be able to produce an input whose unrounded total, before the final ROUND, has a fractional part of exactly half a paisa (third decimal digit 5 and no further non-zero digits).
10. THE Bill_Input_Strategy SHALL weight its draws towards the edge inputs of criteria 1 to 9. The weighting is design guidance, and no minimum count of hits per number of draws is required.
11. THE Hypothesis `ci` profile (`derandomize=True` in `tests/conftest.py`) SHALL provide reproducible example sequences, and the Bill_Input_Strategy SHALL implement no seeding of its own.

### Requirement 3: Field-by-Field Comparison

**User Story:** As a migration engineer, I want a field-by-field comparison of two bills, so that any ghost is reported with the exact field that differs.

#### Acceptance Criteria

1. THE FieldDiff SHALL be a frozen dataclass with the fields `field`, `oracle` and `python`, in that order.
2. WHEN the Oracle bill and the Python bill have equal values in every field, THE Diff_Function SHALL return an empty tuple.
3. WHEN exactly one field differs, THE Diff_Function SHALL return a tuple holding exactly one FieldDiff that carries the Bill field name and both values unchanged.
4. WHEN several fields differ, THE Diff_Function SHALL return exactly one FieldDiff for each differing field, with no duplicates, in the declaration order of the Bill fields.
5. WHEN two numeric values are numerically equal and differ only in trailing zeros, such as `Decimal("10.50")` and `Decimal("10.5")`, THE Diff_Function SHALL treat the values as equal and return no FieldDiff for them.
6. WHEN two numeric values differ by any amount, including 0.01 or less, THE Diff_Function SHALL return a FieldDiff for them without applying any tolerance.
7. IF the Oracle bill is `None`, THEN THE Diff_Function SHALL return a tuple holding one FieldDiff with `field` equal to "bill", `oracle` equal to `None`, and `python` equal to the Python bill.
8. THE Diff_Function SHALL compare every field of the Bill, including `due_dt`, and SHALL compare `due_dt` by exact date equality.

### Requirement 4: Oracle Runner

**User Story:** As a migration engineer, I want one function that bills a single customer through the real legacy procedure, so that the Oracle result is the ground truth.

#### Acceptance Criteria

1. WHEN the Run_Oracle_Function receives a BillInput, THE Run_Oracle_Function SHALL insert exactly one `CUST_MST` row and exactly one `MTR_RDG` row for the Probe_Customer from the tariff, load, multiplying factor, readings and reading date of the BillInput.
2. WHERE `fpa_rate` is not `None`, THE Run_Oracle_Function SHALL insert exactly one `FPA_RT` row for the bill month of the Probe_Customer with `fpa_rate` unchanged.
3. WHERE `fpa_rate` is `None`, THE Run_Oracle_Function SHALL insert zero `FPA_RT` rows.
4. WHERE `pay_dt` is not `None`, THE Run_Oracle_Function SHALL insert exactly one `PYMT` row for the Probe_Customer with that timestamp, preserving the time part.
5. WHERE `pay_dt` is `None`, THE Run_Oracle_Function SHALL insert zero `PYMT` rows.
6. WHEN all inserts have completed without error, THE Run_Oracle_Function SHALL call the Legacy_Procedure once and read the `BILL_HDR` row for the Probe_Customer.
7. WHEN exactly one `BILL_HDR` row exists for the Probe_Customer, THE Run_Oracle_Function SHALL return a Bill whose `units`, `enrg`, `fix`, `fpa`, `ed`, `gst`, `tv`, `lps` and `total` are `Decimal` values equal to the stored values and whose `due_dt` is a `datetime.date` with no time part.
8. IF no `BILL_HDR` row exists for the Probe_Customer, THEN THE Run_Oracle_Function SHALL return `None` without raising an exception.
9. THE Run_Oracle_Function SHALL NOT catch, wrap or rename Oracle errors; an error raised by an insert, the call to the Legacy_Procedure or the read SHALL propagate unchanged to the caller, so that a broken run fails loudly. The only guarantee on that path is the rollback of criterion 10.
10. THE Run_Oracle_Function SHALL roll back after every call (implemented with try/finally), whether the call returns a Bill, returns `None` or raises an exception, and SHALL never commit.
11. THE Run_Oracle_Function SHALL leave the row counts of `CUST_MST`, `MTR_RDG`, `FPA_RT`, `PYMT` and `BILL_HDR` equal to their values before the call, after every call.
12. THE Run_Oracle_Function SHALL bind every BillInput value as a bind variable and build no SQL text from BillInput values.
13. WHEN the Run_Oracle_Function reads a number from Oracle, THE Run_Oracle_Function SHALL return the number as a `Decimal` with the same digits and scale that Oracle returned, never converted through `float`.

### Requirement 5: Seed Bill Reproduction

**User Story:** As a migration engineer, I want the Run_Oracle_Function to reproduce the five seed bills, so that I can trust the runner before using it for random bills.

#### Acceptance Criteria

1. WHEN the Run_Oracle_Function bills the input of each seed customer 1001 to 1005 from `tests/test_resurrect_billing.py`, THE Run_Oracle_Function SHALL return a Bill for which the Diff_Function reports zero differences from the expected seed bill in every field, with exact `Decimal` values and exact dates.
2. WHEN the Run_Oracle_Function bills the 345-unit rounding input, THE Run_Oracle_Function SHALL return a Bill with `total` equal to `Decimal("9049")` regardless of scale, where the sum before rounding is 9048.50 and the rounding is half-up.
3. IF the Diff_Function reports differences for a seed bill, THEN THE seed test SHALL fail and its output SHALL list the field name, the expected value and the actual value for each difference.
4. IF `ORACLE_DSN` is not set, THEN THE seed tests SHALL be skipped and not reported as passed.
5. WHEN the Run_Oracle_Function is run repeatedly on the same seed input, THE Run_Oracle_Function SHALL leave the database state unchanged, and a second run SHALL have zero differences from the first.

### Requirement 6: Equivalence Property

**User Story:** As a migration engineer, I want the proof to run thousands of random bills against Oracle, so that I can claim the port is equivalent.

#### Acceptance Criteria

1. THE Equivalence_Property SHALL draw each example's BillInput only from the Bill_Input_Strategy.
2. WHEN the Equivalence_Property runs one example, THE Equivalence_Property SHALL pass the same BillInput to the Run_Oracle_Function and the Port and SHALL assert that the Diff_Function returns an empty tuple, with every field exact and no tolerance.
3. WHILE the Hypothesis profile `dev` is active (the default, `max_examples=200` and `deadline=None` as registered in `tests/conftest.py`), THE Equivalence_Property SHALL check the number of examples set by that profile.
4. WHILE the Hypothesis profile `ci` is active (selected by `HYPOTHESIS_PROFILE=ci`, registered in `tests/conftest.py` with `max_examples=2000`, `derandomize=True` and `deadline=None`), THE Equivalence_Property SHALL check the number of examples set by that profile with the same example sequence on every run. THE Equivalence_Property SHALL set no `max_examples` of its own.
5. IF the Equivalence_Property finds a Ghost, THEN THE Equivalence_Property SHALL fail and report the shrunk BillInput and every FieldDiff, with field name, Oracle value and Port value.
6. IF the Run_Oracle_Function raises an error, such as when the connection fails, THEN THE Run_Oracle_Function SHALL NOT catch, wrap or rename that error, and THE Equivalence_Property SHALL fail with the original error and SHALL NOT count the example as a match.
7. WHEN the Test_Suite runs with the Oracle_Container running and `ORACLE_DSN` set, THE Test_Suite SHALL report exactly 8 tests marked `oracle` as passed, 0 as skipped and 0 as failed.
8. WHILE `ORACLE_DSN` is not set, THE Test_Suite SHALL skip every test marked `oracle`, with none failed or errored.

### Requirement 7: Project Rules

**User Story:** As a project owner, I want the Prove stage to follow the project rules, so that the repository stays consistent.

#### Acceptance Criteria

1. THE Prove_Package SHALL construct every money value as a `Decimal` from a string, including values read from Oracle, values generated by the Bill_Input_Strategy and values written to reports, and never from `float`.
2. THE Prove_Package SHALL read `ORACLE_DSN`, `ORACLE_USER` and `APP_USER_PASSWORD` only through `gravedigger.config` and SHALL contain no hard-coded passwords, DSNs or API keys.
3. IF `ORACLE_DSN` is not set, THEN THE Oracle_Runner SHALL make no connection attempt, and the tests marked `oracle` SHALL be skipped and not failed.
4. THE Oracle_Runner SHALL connect with `python-oracledb` in thin mode without an Instant Client.
5. THE Prove_Package SHALL provide type hints on every parameter and return value, and every data type SHALL be a frozen dataclass whose attribute assignment raises `FrozenInstanceError`.
6. THE Prove_Package work SHALL modify or add no test function, assertion or test file. THE only change under `tests/` SHALL be `deadline=None` on the `dev` and `ci` profile registrations in `tests/conftest.py`, so that `git status` shows only `tests/conftest.py` changed under `tests/`.
7. THE Prove_Package SHALL name the legacy unit it exercises, such as `BILLING_PKG.f_lps`, in the docstring of each public function.
8. WHEN the Prove_Package rounds a money value, THE Prove_Package SHALL use `Decimal.quantize` with `ROUND_HALF_UP` and never the built-in `round()`.

### Requirement 8: Design Line Number Fix

**User Story:** As a maintainer, I want the stale line numbers in the resurrect-billing design corrected, so that the design cites the right legacy lines.

#### Acceptance Criteria

1. WHEN the Resurrect_Design is corrected, THE Resurrect_Design SHALL cite "pkb lines 105-106" wherever the text previously cited "pkb lines 106-107", with zero occurrences of 106-107 afterward.
2. WHEN the Resurrect_Design is corrected, THE Resurrect_Design SHALL cite "pkb lines 162-183" wherever the text previously cited "pkb lines 163-183", with zero occurrences of 163-183 afterward.
3. WHEN the Resurrect_Design is edited, THE edit SHALL change only those line-number citations, with zero changed characters elsewhere.
4. IF the Resurrect_Design contains no occurrence of either stale citation, THEN THE Resurrect_Design SHALL remain unchanged and the final report SHALL state that no stale citation was found.

### Requirement 9: Probe Customer Leaves No Trace

**User Story:** As a maintainer, I want evidence that the probe customer leaves no trace, so that I know the proof does not pollute the database.

#### Acceptance Criteria

1. WHEN the Run_Oracle_Function has returned, normally or with an error, THE `run_sql` tool of the grave-digger-oracle MCP server SHALL return zero rows for `cust_no` 900001 in each of `CUST_MST`, `MTR_RDG`, `PYMT` and `BILL_HDR`.
2. WHEN the Run_Oracle_Function has returned, normally or with an error, THE `run_sql` tool SHALL return zero rows for `bill_mon` '209912' in `FPA_RT`.
3. IF the Run_Oracle_Function fails part-way, THEN THE Run_Oracle_Function SHALL roll back so that the database stays in its prior state and criteria 1 and 2 still hold, and the original Oracle error SHALL propagate unchanged to the caller.
4. WHEN the final task runs, THE Test_Suite SHALL be executed as `.venv\Scripts\python.exe -m pytest -q` with the Oracle_Container running and `ORACLE_DSN` set, and the run SHALL pass only if the exit code is 0, zero tests failed and zero tests marked `oracle` were skipped.
5. WHEN the final task completes, THE final report SHALL state the integer number of examples the Equivalence_Property ran under the active Hypothesis_Profiles profile (200 for `dev`, 2000 for `ci`), and SHALL state either "Ghost found" with the smallest failing input or "No Ghost found". THE final report SHALL also state the total number of tests passed, that the `oracle` tests PASSED and were not skipped, and the Julian-calendar finding (Oracle DATE is Julian before 1582-10-15, Python is proleptic Gregorian, so 1000-03-01 is a Friday in Oracle and a Saturday in Python).