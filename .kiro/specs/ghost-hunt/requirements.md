# Requirements Document

## Introduction

The hosted Grave Digger app cannot run Oracle. The ghost hunt therefore bills a large set of inputs in real Oracle once, saves the results as a golden snapshot (`golden/cases.json`), and hunts any candidate port against that snapshot with no database. The demo story: a careless first draft of the port uses Python's built-in `round()` and matches all five seed bills, yet the hunt finds ghosts, bills where the draft and the legacy PL/SQL disagree. The smallest ghost is shown, the draft is replaced by the real port, and the hunt comes back clean.

This spec adds three modules and one script:

- `src/gravedigger/prove/golden.py`: `GoldenCase`, `save_cases`, `load_cases`, `build_golden`, `GOLDEN_PATH`.
- `src/gravedigger/prove/hunt.py`: `Ghost`, `HuntReport`, `hunt`.
- `src/gravedigger/resurrected/billing_draft.py`: the deliberately wrong first draft.
- `scripts/make_golden.py`: builds `golden/cases.json` once, with Oracle running.

The contract is the module docstring and the tests of `tests/test_ghost_hunt.py`. That file is not modified. The existing `run_oracle` (`gravedigger.prove.oracle_runner`), `diff` and `FieldDiff` (`gravedigger.prove.compare`), `bill_inputs` (`gravedigger.prove.strategies`) and `generate_bill` (`gravedigger.resurrected.billing`) are reused unchanged.

## Glossary

- **Golden_Module**: The module `gravedigger.prove.golden`.
- **Hunt_Module**: The module `gravedigger.prove.hunt`.
- **Draft_Module**: The module `gravedigger.resurrected.billing_draft`.
- **Make_Golden_Script**: The script `scripts/make_golden.py`.
- **BillInput**: The frozen dataclass of billing inputs defined in `gravedigger.resurrected.billing`.
- **Bill**: The frozen dataclass of billing results defined in `gravedigger.resurrected.billing`.
- **Port**: The function `gravedigger.resurrected.billing.generate_bill`, which ports `BILLING_PKG.p_gen_bill` (pkb lines 146-207).
- **Draft_Port**: The function `gravedigger.resurrected.billing_draft.generate_bill`, a deliberately wrong first draft of the Port.
- **Candidate_Port**: Any callable that takes one BillInput and returns one Bill. The Port and the Draft_Port are Candidate_Ports.
- **GoldenCase**: A frozen dataclass with fields `input` (a BillInput) and `oracle` (a Bill, or `None` when Oracle wrote no bill row), in that order.
- **Golden_Snapshot**: The JSON file `golden/cases.json` holding GoldenCase values billed by real Oracle.
- **Golden_Path**: The constant `GOLDEN_PATH`, the absolute path of the Golden_Snapshot, equal to the repository root joined with `golden/cases.json`.
- **Run_Oracle_Function**: The function `run_oracle(conn, BillInput)` that bills one input through `BILLING_PKG.p_gen_bill` and rolls back.
- **Diff_Function**: The function `diff(oracle, python)` that returns a tuple of FieldDiff values, empty when the bills are equal.
- **FieldDiff**: A frozen dataclass with fields `field`, `oracle` and `python`, describing one differing bill field.
- **Ghost**: A frozen dataclass with fields `input`, `oracle`, `python` and `diffs`, describing one GoldenCase for which a Candidate_Port and Oracle produce different bills.
- **HuntReport**: A frozen dataclass with fields `checked`, `matched` and `ghosts`, plus the property `smallest`.
- **Smallest_Ghost**: The Ghost with the fewest `units` in its bill, with ties broken by the lowest Oracle `total`.
- **Rounding_Ghost_Input**: The BillInput with tariff `A1`, load 2, readings 0 and 345, multiplying factor 1, reading date 2024-01-10 00:00:00, no FPA rate and no payment. Its sum before the final ROUND is 9048.50, Oracle returns total 9049 and the Draft_Port returns 9048.
- **Seed_Inputs**: The five BillInput values of seed customers 1001 to 1005 in `tests/test_resurrect_billing.py` (`SEED`).
- **Bill_Input_Strategy**: The Hypothesis strategy `bill_inputs()` in `gravedigger.prove.strategies`.
- **Oracle_Container**: The local Oracle Database Free container `gd-oracle`, started with `scripts/start-oracle.ps1`.
- **Probe_Customer**: The temporary customer used for one Oracle billing run, with `cust_no` 900001 and `bill_mon` '209912'.
- **MCP_Run_SQL**: The `run_sql` tool of the grave-digger-oracle MCP server (read-only).
- **Hypothesis_Profiles**: The profiles registered in `tests/conftest.py`: `dev` (200 examples) and `ci` (2000 examples, derandomized).
- **Test_Suite**: The command `.venv\Scripts\python.exe -m pytest -q -rs`.

## Requirements

### Requirement 1: Golden Snapshot File Format

**User Story:** As a migration engineer, I want the golden snapshot saved in a plain file that reloads exactly, so that the hunt in the browser sees the same bills Oracle produced.

#### Acceptance Criteria

1. THE GoldenCase SHALL be a frozen dataclass with the fields `input` and `oracle`, in that order, whose attribute assignment raises `FrozenInstanceError`.
2. WHEN `save_cases(path, cases)` is called, THE Golden_Module SHALL write the cases to `path` as JSON encoded in UTF-8 without a byte order mark and with LF line endings.
3. WHEN `load_cases(path)` is called on a file written by `save_cases`, THE Golden_Module SHALL return a tuple of GoldenCase values equal to the saved cases, in the saved order, for every field, including cases whose `oracle` is `None`.
4. THE Golden_Module SHALL write every `Decimal` value as a JSON string holding the exact text of the value and SHALL read it back with `Decimal` constructed from that string.
5. THE Golden_Module SHALL write every `datetime` and `date` value in ISO 8601 text and SHALL read it back to the same type and the same value, including the time part of `rdg_dt` and `pay_dt`.
6. THE Golden_Module SHALL write no JSON number for money, so that the file text contains no float notation and no `e+` exponent.
7. FOR ALL lists of GoldenCase values, THE Golden_Module SHALL satisfy `load_cases(path)` equal to the cases after `save_cases(path, cases)` (round-trip property).
8. IF the file at `path` does not exist, THEN THE `load_cases` function SHALL raise `FileNotFoundError`.
9. IF the file at `path` holds JSON that is not a list of valid GoldenCase records, THEN THE `load_cases` function SHALL raise `ValueError` that names the problem.
10. THE Golden_Path SHALL be the absolute path `golden/cases.json` under the repository root, independent of the current working directory.

### Requirement 2: Building the Snapshot from Oracle

**User Story:** As a migration engineer, I want one function that bills a list of inputs in real Oracle, so that the snapshot holds genuine legacy results.

#### Acceptance Criteria

1. WHEN `build_golden(conn, inputs)` is called, THE Golden_Module SHALL call the Run_Oracle_Function once for each input, in input order, and SHALL return a tuple holding one GoldenCase per input with the input unchanged and the Oracle result unchanged.
2. WHEN the Run_Oracle_Function returns `None` for an input, THE Golden_Module SHALL store `oracle` equal to `None` for that GoldenCase and SHALL NOT raise.
3. IF the Run_Oracle_Function raises an error, THEN THE `build_golden` function SHALL let the original error propagate unchanged and SHALL return no partial result.
4. THE `build_golden` function SHALL NOT commit to the database. After the call returns, the row counts of `CUST_MST`, `MTR_RDG`, `FPA_RT`, `PYMT` and `BILL_HDR` SHALL equal their values before the call.
5. WHEN `build_golden` bills the 1003 seed input and the Rounding_Ghost_Input in that order, THE Golden_Module SHALL return two cases whose Oracle totals are 5179 and 9049, in that order.
6. THE `build_golden` function SHALL open no connection and read no settings; the caller SHALL pass an open `oracledb` connection.

### Requirement 3: Hunting a Candidate Port

**User Story:** As a migration engineer, I want to run any candidate port over the golden cases, so that I see every bill where it disagrees with Oracle.

#### Acceptance Criteria

1. THE Ghost SHALL be a frozen dataclass with the fields `input`, `oracle`, `python` and `diffs`, in that order. THE HuntReport SHALL be a frozen dataclass with the fields `checked`, `matched` and `ghosts`, in that order.
2. WHEN `hunt(port, cases)` is called, THE Hunt_Module SHALL call the Candidate_Port once for each case with the case `input` and SHALL compare the returned Bill with the case `oracle` by the Diff_Function.
3. WHEN the Diff_Function returns an empty tuple for a case, THE Hunt_Module SHALL count the case as matched.
4. WHEN the Diff_Function returns a non-empty tuple for a case, THE Hunt_Module SHALL add one Ghost to `ghosts` with the case `input`, the case `oracle`, the Bill returned by the Candidate_Port as `python`, and the tuple as `diffs`.
5. THE HuntReport SHALL satisfy `checked` equal to the number of cases, `matched` equal to the number of cases without a Ghost, and `checked` equal to `matched` plus the length of `ghosts` (invariant).
6. THE Hunt_Module SHALL keep `ghosts` in the order of the input cases and SHALL return `ghosts` as a tuple.
7. WHEN the case `oracle` is `None`, THE Hunt_Module SHALL report a Ghost whose `oracle` is `None` and whose first diff has the field name `bill`.
8. WHEN `cases` is empty, THE Hunt_Module SHALL return a HuntReport with `checked` 0, `matched` 0, `ghosts` equal to the empty tuple and `smallest` equal to `None`.
9. IF the Candidate_Port raises an error for a case, THEN THE `hunt` function SHALL let the original error propagate unchanged.
10. THE `hunt` function SHALL open no database connection and SHALL import no `oracledb` module, so that the hunt runs in a browser session with no database.
11. WHEN `hunt` is called twice with the same Candidate_Port and the same cases, THE Hunt_Module SHALL return equal HuntReport values (idempotence).

### Requirement 4: Smallest Ghost

**User Story:** As a migration engineer, I want the smallest failing bill shown first, so that I can understand a ghost on the simplest input.

#### Acceptance Criteria

1. WHEN `ghosts` is empty, THE HuntReport `smallest` property SHALL return `None`.
2. WHEN `ghosts` is not empty, THE HuntReport `smallest` property SHALL return the Ghost with the fewest `units` in its Oracle bill.
3. WHEN several Ghost values have equal `units`, THE HuntReport `smallest` property SHALL return, among them, the Ghost with the lowest Oracle `total`.
4. WHEN several Ghost values have equal `units` and equal Oracle `total`, THE HuntReport `smallest` property SHALL return the first of them in `ghosts` order.
5. WHEN a Ghost has `oracle` equal to `None`, THE HuntReport `smallest` property SHALL take `units` and `total` from the `python` bill of that Ghost.
6. THE `smallest` property SHALL return a Ghost that is an element of `ghosts`, whatever the order of the input cases (metamorphic property: reordering the cases does not change which input is the Smallest_Ghost, unless two Ghost values tie on units and total).

### Requirement 5: The Deliberately Wrong Draft

**User Story:** As a demo presenter, I want a first-draft port that is wrong on purpose and says so, so that the ghost hunt has a real ghost to catch.

#### Acceptance Criteria

1. THE Draft_Module docstring SHALL contain the word `DELIBERATELY` and SHALL state that the module is wrong on purpose and why: Python's built-in `round()` rounds half to even, while Oracle `ROUND` rounds half up.
2. THE Draft_Port docstring SHALL contain the text `round()` and SHALL state that the Draft_Port is wrong on purpose, SHALL name the legacy unit `BILLING_PKG.p_gen_bill` with the line `pkb line 193`, and SHALL give one worked example: a sum of 9048.50 gives 9048 in the draft and 9049 in Oracle.
3. THE Draft_Port SHALL return, for every BillInput, a Bill whose `units`, `enrg`, `fix`, `fpa`, `ed`, `gst`, `tv`, `lps` and `due_dt` equal those returned by the Port for the same BillInput.
4. THE Draft_Port SHALL compute `total` as the Python built-in `round()` of the sum of the seven amounts `enrg`, `fix`, `fpa`, `ed`, `gst`, `tv` and `lps` of criterion 3 (before the final ROUND of pkb line 193) to 0 decimal places, converted to a `Decimal` built from the string form of the resulting integer.
5. THE Draft_Port SHALL reuse the Port functions for every value other than `total` and SHALL NOT copy their code.
6. FOR ALL BillInput values produced by the Bill_Input_Strategy, THE Draft_Port total SHALL differ from the Port total by 0 or by exactly 1 (metamorphic property), and SHALL differ if and only if the sum before the final ROUND has a fractional part of exactly 0.50 and an even integer part (round half to even rounds an odd integer part up, like Oracle).
7. THE Draft_Port SHALL return a Bill that equals the Bill of the Port for each of the Seed_Inputs, so that the draft looks right on all five seed bills.
8. WHEN the Draft_Port bills the Rounding_Ghost_Input, THE Draft_Port SHALL return `total` equal to `Decimal("9048")`.
9. THE Draft_Module SHALL be the only module in the repository allowed to call the built-in `round()` on a money value, and SHALL carry a comment at that call that names it as the deliberate defect.
10. THE Port module `gravedigger.resurrected.billing` SHALL remain unchanged, so that the existing test that scans it for `round` and `float` calls still passes.

### Requirement 6: Hunt Results on Known Cases

**User Story:** As a demo presenter, I want the hunt to give the expected verdicts on the known cases, so that the demo story holds.

#### Acceptance Criteria

1. WHEN the Port is hunted against the five Seed_Inputs and the Rounding_Ghost_Input billed by Oracle, THE Hunt_Module SHALL report `checked` 6, `matched` 6, `ghosts` equal to the empty tuple and `smallest` equal to `None`.
2. WHEN the Draft_Port is hunted against the five Seed_Inputs billed by Oracle, THE Hunt_Module SHALL report no Ghost.
3. WHEN the Draft_Port is hunted against the five Seed_Inputs and the Rounding_Ghost_Input, THE Hunt_Module SHALL report `checked` 6, `matched` 5 and exactly one Ghost, whose `input` is the Rounding_Ghost_Input and whose `diffs` are exactly one FieldDiff with `field` equal to `total`, `oracle` equal to 9049 and `python` equal to 9048.
4. WHEN a Candidate_Port that returns `total` equal to 1 for every input is hunted against a case with 2345 units and a case with 345 units, THE `smallest` property SHALL return the Ghost of the 345-unit case.
5. FOR ALL cases built from the Bill_Input_Strategy and billed by the Port itself, THE Hunt_Module SHALL report no Ghost when the Port is the Candidate_Port.

### Requirement 7: Golden Snapshot Content and Reproducible Build

**User Story:** As a maintainer, I want one reproducible script that builds the snapshot, so that anyone with Oracle running can regenerate the same file.

#### Acceptance Criteria

1. WHEN the Make_Golden_Script runs with the Oracle_Container running and the Oracle settings available through `gravedigger.config`, THE Make_Golden_Script SHALL write the Golden_Snapshot to the Golden_Path through `save_cases`.
2. THE Golden_Snapshot SHALL contain the five Seed_Inputs, the Rounding_Ghost_Input and 2000 inputs drawn from the Bill_Input_Strategy, so that it holds at least 2000 cases.
3. THE Make_Golden_Script SHALL draw the 2000 inputs with a fixed Hypothesis seed and `derandomize` behaviour documented in its module docstring, so that two runs produce the same inputs in the same order and an identical file text for identical Oracle results.
4. THE Make_Golden_Script SHALL bill every input through `build_golden` and SHALL write no case whose `oracle` is `None`, because the Bill_Input_Strategy only produces inputs that Oracle can store.
5. IF `build_golden` returns a case whose `oracle` is `None`, THEN THE Make_Golden_Script SHALL stop with a non-zero exit code, SHALL print the offending input and SHALL write no file.
6. WHEN the Make_Golden_Script finishes, THE Make_Golden_Script SHALL print the number of cases written and the number of Ghost values that the Draft_Port has against them.
7. IF the Oracle settings are missing or the connection fails, THEN THE Make_Golden_Script SHALL stop with a non-zero exit code, SHALL print a plain-English message that tells the user to start the Oracle_Container and SHALL write no file.
8. THE Make_Golden_Script SHALL write the Golden_Snapshot to a temporary file in the same folder and replace the target only after the full save succeeds, so that a failed run leaves any earlier snapshot intact.
9. THE Make_Golden_Script SHALL contain no password, DSN or API key and SHALL read settings only through `gravedigger.config`.
10. WHEN the Make_Golden_Script has finished, THE Golden_Snapshot SHALL contain no `None` Oracle result, SHALL contain every Seed_Input and the Rounding_Ghost_Input, and SHALL show at least one Ghost for the Draft_Port.
11. THE Golden_Snapshot SHALL be committed to the repository, and THE `.gitignore` SHALL NOT list `golden/cases.json`.

### Requirement 8: Hunt Results on the Golden Snapshot

**User Story:** As a migration engineer, I want the real port proven clean and the draft caught on thousands of genuine Oracle bills, so that the migration claim has evidence.

#### Acceptance Criteria

1. WHEN the Port is hunted against the Golden_Snapshot, THE Hunt_Module SHALL report no Ghost and `matched` equal to `checked`, with `checked` of at least 2000.
2. WHEN the Draft_Port is hunted against the Golden_Snapshot, THE Hunt_Module SHALL report at least one Ghost.
3. THE `diffs` of every Ghost of the Draft_Port on the Golden_Snapshot SHALL consist of exactly one FieldDiff with the field name `total` whose Oracle value and Python value differ by exactly 1.
4. THE Smallest_Ghost of the Draft_Port on the Golden_Snapshot SHALL be a Ghost, not `None`.
5. WHEN a sample of 50 cases spread evenly over the Golden_Snapshot is billed again by the Run_Oracle_Function, THE Diff_Function SHALL return an empty tuple for every one of them, which shows that the snapshot is genuine Oracle output.

### Requirement 9: Project Rules

**User Story:** As a project owner, I want the ghost hunt to follow the project rules, so that the repository stays consistent.

#### Acceptance Criteria

1. THE Golden_Module, THE Hunt_Module, THE Draft_Module and THE Make_Golden_Script SHALL construct every money value as a `Decimal` from a string or an integer and never from a `float`.
2. THE Golden_Module, THE Hunt_Module and THE Make_Golden_Script SHALL round no money value with the built-in `round()`; the Draft_Module is the single exception of Requirement 5.
3. THE Golden_Module, THE Hunt_Module, THE Draft_Module and THE Make_Golden_Script SHALL provide type hints on every parameter and return value, and every data type SHALL be a frozen dataclass.
4. THE docstring of every public function SHALL name the legacy unit it relates to (`BILLING_PKG.p_gen_bill`, pkb lines 146-207) or SHALL state that it ports no legacy unit.
5. THE Golden_Module, THE Hunt_Module, THE Draft_Module and THE Make_Golden_Script SHALL be written as UTF-8 without a byte order mark with LF line endings.
6. THE ghost-hunt work SHALL modify no existing test function, assertion or test file, so that `git status` shows no modified file under `tests/`. The only new test file SHALL be `tests/test_ghost_hunt_properties.py` (see Requirement 11 criteria 6 to 8).
7. THE Port module, THE Run_Oracle_Function, THE Diff_Function and THE Bill_Input_Strategy SHALL remain unchanged.
8. WHERE the Oracle settings are not available, THE tests marked `oracle` SHALL be skipped and not failed, and the tests that need the Golden_Snapshot SHALL be skipped only while `golden/cases.json` does not exist.
9. THE Make_Golden_Script SHALL print and log no password.

### Requirement 10: Probe Customer Leaves No Trace

**User Story:** As a maintainer, I want evidence that building the snapshot leaves no trace in the database, so that I know the proof does not pollute Oracle.

#### Acceptance Criteria

1. WHEN the Make_Golden_Script has finished, THE MCP_Run_SQL tool SHALL return zero rows for `cust_no` 900001 in each of `CUST_MST`, `MTR_RDG`, `PYMT` and `BILL_HDR`.
2. WHEN the Make_Golden_Script has finished, THE MCP_Run_SQL tool SHALL return zero rows for `bill_mon` '209912' in `FPA_RT`.
3. WHEN the Make_Golden_Script has finished, THE MCP_Run_SQL tool SHALL show that `BILL_HDR` still holds exactly the 5 seed rows.
4. THE final report SHALL state the five counts of criteria 1 and 2 and the row count of criterion 3.

### Requirement 11: Final Run and Report

**User Story:** As a project owner, I want a final full run with Oracle up, so that I know every test passes and the demo numbers are real.

#### Acceptance Criteria

1. WHEN the Oracle_Container is running and the Make_Golden_Script has been run once, THE Test_Suite SHALL exit with code 0, with zero tests failed and zero tests skipped.
2. WHEN the Test_Suite has finished, THE final report SHALL state the total number of tests passed and SHALL state that the `oracle` tests PASSED and were not skipped.
3. THE final report SHALL state the number of golden cases, the number of Ghost values of the Draft_Port, and the Smallest_Ghost of the Draft_Port as the input, the Oracle total and the draft total.
4. THE task list SHALL end with the task that runs the Make_Golden_Script once, followed by the task that runs the Test_Suite with Oracle running and reports the numbers of criterion 3.
5. THE Test_Suite SHALL report that every test marked `oracle` passed and none was skipped.
6. THE ghost-hunt work SHALL add the new test file `tests/test_ghost_hunt_properties.py` holding exactly three Hypothesis properties, each named after the requirement it covers: a property named for R1.7 (`save_cases` then `load_cases` returns any generated list of GoldenCase values exactly equal to the saved list), a property named for R3.5 (`hunt()` gives `checked` equal to `matched` plus the length of `ghosts` for any Candidate_Port and any generated cases), and a property named for R5.3 and R5.6 (for any BillInput from the Bill_Input_Strategy, the Draft_Port Bill equals the Port Bill in every field except `total`, and the two `total` values differ, by exactly 1, if and only if the sum before the final ROUND has a fractional part of exactly 0.50 and an even integer part).
7. THE three properties of `tests/test_ghost_hunt_properties.py` SHALL use no Oracle connection and no network access, and SHALL finish together in under 5 seconds with the `dev` Hypothesis profile (200 examples).
8. THE ghost-hunt work SHALL add no other Hypothesis property to the new file, and no requirement of this document SHALL oblige any further property test.
