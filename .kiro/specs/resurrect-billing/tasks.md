# Implementation Plan: resurrect-billing

## Overview

Port `legacy/billing_pkg.pkb` to Python in one module, `src/gravedigger/resurrected/billing.py`, in Python 3.12. The module holds two frozen dataclasses, one rounding helper, seven unit functions, and `generate_bill`, which chains them in the legacy order. The acceptance contract is `tests/test_resurrect_billing.py` (30 tests). Do not modify any test file. Follow `.kiro/steering/migration-rules.md`: identical behaviour first, `Decimal` only, `ROUND_HALF_UP` through `quantize`, no `float`, no built-in `round`, and a "Ports BILLING_PKG.<unit> (pkb lines X-Y)." docstring on every function. Hypothesis property tests belong to the later Prove spec and are not tasks here.

All tasks edit the same file, so they run one after another.

## Tasks

- [x] 1. Create the module skeleton, dataclasses and rounding helper
  - [x] 1.1 Create `src/gravedigger/resurrected/billing.py` with imports, `_TWO_PLACES`, `_ZERO_PLACES` and `_round`
    - Imports: `dataclasses`, `datetime` (`date`, `datetime`, `time`, `timedelta`), `decimal` (`Decimal`, `ROUND_HALF_UP`)
    - `_round(value, quantum)` returns `value.quantize(quantum, rounding=ROUND_HALF_UP)`
    - Build every constant from strings, for example `Decimal("0.01")`
    - Write the file as UTF-8 without BOM, LF line endings
    - _Requirements: 9.1, 9.2, 9.3_
  - [x] 1.2 Add frozen dataclasses `BillInput` and `Bill`
    - `BillInput(tariff, load_kw, prev_rdg, curr_rdg, mf, rdg_dt, fpa_rate, pay_dt)` with `fpa_rate: Decimal | None` and `pay_dt: datetime | None`
    - `Bill(units, enrg, fix, fpa, ed, gst, tv, lps, total, due_dt)` with `due_dt: date`
    - Keep the field order above, because the tests build both classes positionally
    - Use `@dataclass(frozen=True)` so assignment raises `FrozenInstanceError`
    - _Requirements: 9.4, 9.5_

- [x] 2. Port the meter and charge units
  - [x] 2.1 Implement `units(prev, curr, mf)` (f_units, pkb lines 18-31)
    - Return `(curr - prev) * mf` when `curr >= prev`, else `(99999 - prev + curr + 1) * mf`
    - No rounding, so `units(100, 250, Decimal("1.5"))` is `Decimal("225.0")`
    - Docstring starts "Ports BILLING_PKG.f_units (pkb lines 18-31)." and includes "LEGACY QUIRK:" for the rollover at lines 21-24
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 9.6, 9.7_
  - [x] 2.2 Implement `energy_charge(tariff, units)` (f_enrg_chg, pkb lines 38-65)
    - `A1` slabs with strict `>` boundaries: up to 100 at 10, up to 200 at 1000 + (u - 100) * 13, up to 300 at 2300 + (u - 200) * 16, above 300 at `u * 22` on all units
    - `A2` is `u * 25`. Any other tariff gives `Decimal("0")` with no exception
    - Round once at the single return with `_round(..., _TWO_PLACES)`
    - Docstring starts "Ports BILLING_PKG.f_enrg_chg (pkb lines 38-65)." and includes "LEGACY QUIRK:" for the cliff at lines 43-44
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 9.6, 9.7_
  - [x] 2.3 Implement `fixed_charge(tariff, load_kw, enrg)` (f_fix_chg, pkb lines 72-88)
    - `A2` is `400 * load_kw`. `A1` is `75 - enrg` when `enrg < 75`, else 0. Other tariffs give 0
    - No rounding
    - Docstring starts "Ports BILLING_PKG.f_fix_chg (pkb lines 72-88)." and includes "LEGACY QUIRK:" for the minimum charge at lines 79-80
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 9.6, 9.7_
  - [x] 2.4 Implement `fpa(units, rate)` (f_fpa, pkb lines 93-102)
    - Return `Decimal("0")` when `rate is None`, with a comment that this mirrors the legacy NO_DATA_FOUND handler (lines 99-101)
    - Otherwise return `_round(units * rate, _TWO_PLACES)`, so 5 units at 0.333 gives 1.67
    - Docstring starts "Ports BILLING_PKG.f_fpa (pkb lines 93-102)." and includes "LEGACY QUIRK:" for lines 99-101
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 9.2, 9.6, 9.7_

- [x] 3. Checkpoint - Ensure all tests pass
  - Run `.venv\Scripts\python.exe -m pytest tests/test_resurrect_billing.py -q`. Failures in `taxes`, `due_date`, `lps` and `generate_bill` are expected until later tasks. Ask the user if questions arise.

- [x] 4. Port tax and date units
  - [x] 4.1 Implement `taxes(enrg, fix, fpa)` (p_taxes, pkb lines 108-113)
    - `ed = _round(enrg * Decimal("0.015"), _TWO_PLACES)`
    - `gst = _round((enrg + fix + fpa + ed) * Decimal("0.17"), _TWO_PLACES)`, using the already rounded `ed`
    - Return the tuple `(ed, gst)`
    - Docstring starts "Ports BILLING_PKG.p_taxes (pkb lines 108-113)." and includes "LEGACY QUIRK:" for tax on tax at lines 105-106 and 112
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 9.6, 9.7_
  - [x] 4.2 Implement `due_date(rdg_dt)` (f_due_dt, pkb lines 118-126)
    - `d = rdg_dt.date() + timedelta(days=14)`. If `d.weekday() == 6`, add one day
    - Return a `date`. Do not use `strftime` or any locale-dependent call
    - Docstring starts "Ports BILLING_PKG.f_due_dt (pkb lines 118-126)." and includes "LEGACY QUIRK:" for the Sunday shift at lines 122-124
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.6, 9.7_
  - [x] 4.3 Implement `lps(enrg, due_dt, pay_dt)` (f_lps, pkb lines 131-141)
    - Return `Decimal("0")` when `pay_dt is None`
    - Compare `pay_dt > datetime.combine(due_dt, time.min)`. If later, return `_round(enrg * Decimal("0.10"), _TWO_PLACES)`, else 0
    - Base is the energy charge only
    - Docstring starts "Ports BILLING_PKG.f_lps (pkb lines 131-141)." and includes "LEGACY QUIRK:" for time of day at line 136 and energy-only base at line 137
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 9.6, 9.7_

- [x] 5. Port bill generation
  - [x] 5.1 Implement `generate_bill(inp)` (p_gen_bill, pkb lines 146-207, calculation 170-193)
    - Chain `units`, `energy_charge`, `fixed_charge`, `fpa`, `taxes`, `due_date`, `lps` in the legacy order, using local names such as `n_unt`, `v_enrg`, so the unit functions are not shadowed
    - TV fee is `Decimal("35")` for `A1`, else `Decimal("60")`, and is not part of the GST base
    - `total = _round(enrg + fix + fpa + ed + gst + tv + lps, _ZERO_PLACES)`, so 9048.50 gives 9049
    - Return `Bill(n_unt, v_enrg, v_fix, v_fpa, v_ed, v_gst, v_tv, v_lps, n_tot, d_due)`
    - No `try` block and no database access
    - Docstring starts "Ports BILLING_PKG.p_gen_bill (pkb lines 146-207)." States the deliberate differences (no database access, `WHEN OTHERS THEN NULL` at lines 205-206 not reproduced), lists customer 1006 with no meter reading producing no bill row as an autopsy risk, and includes "LEGACY QUIRK:" for line 187 (TV not taxed) and line 193 (total rounded half up)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 9.1, 9.2, 9.5, 9.6, 9.7_

- [x] 6. Check docstring, float and round rules
  - [x] 6.1 Review `billing.py` against the cross-cutting rules and fix any gap in the module only
    - Each of `units`, `energy_charge`, `fixed_charge`, `fpa`, `taxes`, `due_date`, `lps`, `generate_bill` has a docstring beginning "Ports BILLING_PKG.<unit> (pkb lines X-Y)." with the ranges from the requirements
    - Each function with a quirk has "LEGACY QUIRK:" and its legacy line numbers
    - The module has no call to `float` or the built-in `round`, and all Decimal constants are built from strings
    - Do not edit any file under `tests/`
    - _Requirements: 9.1, 9.2, 9.3, 9.6, 9.7_

- [x] 7. Final checkpoint - Run the full suite
  - [x] 7.1 Run `.venv\Scripts\python.exe -m pytest -q` and expect all green
    - Expect 117 passed (87 existing plus 30 in `tests/test_resurrect_billing.py`) and no failures or errors
    - If a test fails, fix `billing.py` only. Never change a test file
    - Ask the user if questions arise
    - _Requirements: 9.8_

## Notes

- Every task edits `src/gravedigger/resurrected/billing.py`, so the dependency graph is strictly sequential.
- Property-based tests for Requirements 1 to 8 are out of scope and belong to the later Prove spec.
- Oracle equivalence testing is also left to the Prove spec.
- Tasks 3 and 7 are checkpoints. Task 7.1 is the closing test run.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1"] },
    { "id": 3, "tasks": ["2.2"] },
    { "id": 4, "tasks": ["2.3"] },
    { "id": 5, "tasks": ["2.4"] },
    { "id": 6, "tasks": ["4.1"] },
    { "id": 7, "tasks": ["4.2"] },
    { "id": 8, "tasks": ["4.3"] },
    { "id": 9, "tasks": ["5.1"] },
    { "id": 10, "tasks": ["6.1"] },
    { "id": 11, "tasks": ["7.1"] }
  ]
}
```
