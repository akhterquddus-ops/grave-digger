# Requirements Document

## Introduction

This spec covers the port of the synthetic legacy package `BILLING_PKG` (`legacy/billing_pkg.pkb`) to Python in `src/gravedigger/resurrected/billing.py`. The port must bill exactly like the legacy PL/SQL, quirks included, following `.kiro/steering/migration-rules.md`. The acceptance contract is `tests/test_resurrect_billing.py`, which this spec does not modify. Equivalence on random inputs against live Oracle is a later spec.

There is one requirement per legacy unit (Requirements 1 to 8), plus Requirement 9 for cross-cutting rules (types, rounding, docstrings). All `pkb` line numbers refer to `legacy/billing_pkg.pkb` as numbered in the file.

### Oracle evidence

The following results were observed on Oracle Database Free through the `grave-digger-oracle` MCP tool `run_plsql` (changes rolled back) while writing this spec.

| Legacy call | Observed Oracle result |
|---|---|
| `f_enrg_chg('A1', 300)` | 3900 |
| `f_enrg_chg('A1', 301)` | 6622 (301 x 22, the cliff) |
| `f_due_dt(DATE '2024-01-07')` | 2024-01-22, a Monday (21 Jan is a Sunday) |
| `f_fpa(5, '202402')` (no FPA_RT row) | 0 |
| `f_fpa(5, '202401')` (rate 0.35) | 1.75 |
| `p_taxes(100, 0, 0)` | ED 1.5, GST 17.26 |
| `f_units(99900, 50, 2)` | 300 |
| `f_fix_chg('A1', 2, 75)` and `f_fix_chg('A1', 2, 50)` | 0 and 25 |
| `f_lps(1234.55, 22-JAN-2024, 22-JAN-2024 00:00)` | 0 |
| `f_lps(1234.55, 22-JAN-2024, 22-JAN-2024 10:00)` | 123.46 |
| `ROUND(9048.5, 0)` | 9049 |

## Glossary

- **Billing_Port**: The Python module `gravedigger.resurrected.billing` in `src/gravedigger/resurrected/billing.py`.
- **Legacy_Package**: The Oracle package `BILLING_PKG` defined in `legacy/billing_pkg.pks` and `legacy/billing_pkg.pkb`.
- **Legacy_Quirk**: A behaviour of the Legacy_Package that looks like a defect or surprise and must be reproduced unchanged.
- **Round_Half_Up**: Rounding that moves exact halves away from zero, implemented with `Decimal.quantize` and `ROUND_HALF_UP`, matching Oracle `ROUND`.
- **Tariff**: A customer category code. `A1` is household, `A2` is shop. Any other code is an unknown tariff.
- **Units**: Energy consumed in kWh, held as `Decimal`.
- **Bill_Input**: Frozen dataclass `BillInput(tariff, load_kw, prev_rdg, curr_rdg, mf, rdg_dt, fpa_rate, pay_dt)`. `fpa_rate` is `None` when no FPA_RT row exists for the month. `pay_dt` is `None` when unpaid.
- **Bill**: Frozen dataclass `Bill(units, enrg, fix, fpa, ed, gst, tv, lps, total, due_dt)`. Money fields and `units` are `Decimal`, `due_dt` is `date`.
- **Due_Date**: The date after which a payment attracts the late payment surcharge.
- **Test_Suite**: The file `tests/test_resurrect_billing.py`.

## Requirements

### Requirement 1: Units from meter readings (f_units)

**User Story:** As a billing analyst, I want consumed units computed from two meter readings, so that meter rollover is billed correctly.

Legacy source: `BILLING_PKG.f_units`, pkb lines 18-31.

#### Acceptance Criteria

1. WHEN the current reading is greater than or equal to the previous reading, THE Billing_Port function `units` SHALL return (current reading minus previous reading) multiplied by the multiplying factor.
2. LEGACY QUIRK (pkb lines 21-24): WHEN the current reading is less than the previous reading, THE Billing_Port function `units` SHALL return (99999 minus previous reading plus current reading plus 1) multiplied by the multiplying factor.
3. WHEN the previous and current readings are equal, THE Billing_Port function `units` SHALL return 0.
4. THE Billing_Port function `units` SHALL return a `Decimal` that preserves the scale of the multiplying factor, so that `units(100, 250, Decimal("1.5"))` equals `Decimal("225.0")`.

### Requirement 2: Energy charge (f_enrg_chg)

**User Story:** As a billing analyst, I want the energy charge computed per tariff slab, so that each customer pays the legacy amount.

Legacy source: `BILLING_PKG.f_enrg_chg`, pkb lines 38-65.

#### Acceptance Criteria

1. WHEN the tariff is `A1` and Units are 100 or fewer, THE Billing_Port function `energy_charge` SHALL return Units multiplied by 10.
2. WHEN the tariff is `A1` and Units are above 100 and at most 200, THE Billing_Port function `energy_charge` SHALL return 1000 plus (Units minus 100) multiplied by 13.
3. WHEN the tariff is `A1` and Units are above 200 and at most 300, THE Billing_Port function `energy_charge` SHALL return 2300 plus (Units minus 200) multiplied by 16.
4. LEGACY QUIRK (pkb lines 43-44, the 300-unit cliff): WHEN the tariff is `A1` and Units are above 300, THE Billing_Port function `energy_charge` SHALL return Units multiplied by 22 for all Units, not only those above 300.
5. WHEN the tariff is `A2`, THE Billing_Port function `energy_charge` SHALL return Units multiplied by 25.
6. IF the tariff is neither `A1` nor `A2`, THEN THE Billing_Port function `energy_charge` SHALL return 0 and SHALL NOT raise an error (pkb lines 58-59).
7. THE Billing_Port function `energy_charge` SHALL round its result to 2 decimal places using Round_Half_Up (pkb line 64).
8. THE Billing_Port function `energy_charge` SHALL reproduce the Oracle results 3900 for `A1` with 300 Units and 6622 for `A1` with 301 Units.

### Requirement 3: Fixed charge (f_fix_chg)

**User Story:** As a billing analyst, I want the fixed charge and the household minimum top-up computed, so that bills match the legacy minimum-charge rule.

Legacy source: `BILLING_PKG.f_fix_chg`, pkb lines 72-88.

#### Acceptance Criteria

1. WHEN the tariff is `A2`, THE Billing_Port function `fixed_charge` SHALL return 400 multiplied by the sanctioned load in kW.
2. LEGACY QUIRK (pkb lines 79-80, minimum charge): WHEN the tariff is `A1` and the energy charge is below 75, THE Billing_Port function `fixed_charge` SHALL return 75 minus the energy charge.
3. WHEN the tariff is `A1` and the energy charge is 75 or more, THE Billing_Port function `fixed_charge` SHALL return 0.
4. IF the tariff is neither `A1` nor `A2`, THEN THE Billing_Port function `fixed_charge` SHALL return 0 (the legacy variable starts at 0, pkb line 74).
5. THE Billing_Port function `fixed_charge` SHALL return its result without additional rounding, as the legacy function does (pkb line 88).

### Requirement 4: Fuel price adjustment (f_fpa)

**User Story:** As a billing analyst, I want the fuel price adjustment computed from the monthly rate, so that months without a loaded rate bill without adjustment.

Legacy source: `BILLING_PKG.f_fpa`, pkb lines 93-102. The Billing_Port receives the looked-up rate instead of the bill month, because the lookup belongs to the database layer.

#### Acceptance Criteria

1. WHEN a rate is supplied, THE Billing_Port function `fpa` SHALL return Units multiplied by the rate, rounded to 2 decimal places using Round_Half_Up (pkb line 97).
2. LEGACY QUIRK (pkb lines 99-101, NO_DATA_FOUND mapped to a default): WHEN the rate is `None`, THE Billing_Port function `fpa` SHALL return 0 and SHALL NOT raise an error. The code SHALL carry a comment stating that this mirrors the legacy NO_DATA_FOUND handler.
3. THE Billing_Port function `fpa` SHALL reproduce the Oracle results 1.75 for 5 Units at rate 0.35 and 0 for a month with no FPA_RT row.
4. WHEN 5 Units are billed at rate 0.333, THE Billing_Port function `fpa` SHALL return 1.67, because 1.665 rounds up.

### Requirement 5: Electricity duty and GST (p_taxes)

**User Story:** As a billing analyst, I want electricity duty and GST computed, so that tax amounts match the legacy tax-on-tax rule.

Legacy source: `BILLING_PKG.p_taxes`, pkb lines 108-113.

#### Acceptance Criteria

1. THE Billing_Port function `taxes` SHALL return a tuple `(ed, gst)` of `Decimal` values.
2. THE Billing_Port function `taxes` SHALL compute ED as the energy charge multiplied by 0.015, rounded to 2 decimal places using Round_Half_Up (pkb line 111).
3. LEGACY QUIRK (pkb lines 105-106 and 112, tax on tax): THE Billing_Port function `taxes` SHALL compute GST as (energy charge plus fixed charge plus fuel price adjustment plus the already rounded ED) multiplied by 0.17, rounded to 2 decimal places using Round_Half_Up.
4. THE Billing_Port function `taxes` SHALL reproduce the Oracle results ED 1.50 and GST 17.26 for an energy charge of 100 with no fixed charge and no fuel price adjustment.

### Requirement 6: Due date (f_due_dt)

**User Story:** As a billing analyst, I want the due date computed from the reading date, so that Sunday due dates move to Monday as in the legacy system.

Legacy source: `BILLING_PKG.f_due_dt`, pkb lines 118-126.

#### Acceptance Criteria

1. THE Billing_Port function `due_date` SHALL return the reading date, with its time part discarded, plus 14 days (pkb line 121).
2. LEGACY QUIRK (pkb lines 122-124, Sunday shift): WHEN the date 14 days after the reading date is a Sunday, THE Billing_Port function `due_date` SHALL return the following Monday.
3. THE Billing_Port function `due_date` SHALL decide the weekday from the calendar date alone and SHALL give the same result under any operating-system locale.
4. THE Billing_Port function `due_date` SHALL return a `date` without a time part.
5. THE Billing_Port function `due_date` SHALL reproduce the Oracle result 2024-01-22 for the reading date 2024-01-07.

### Requirement 7: Late payment surcharge (f_lps)

**User Story:** As a billing analyst, I want the late payment surcharge computed, so that late payers are charged exactly as in the legacy system.

Legacy source: `BILLING_PKG.f_lps`, pkb lines 131-141.

#### Acceptance Criteria

1. WHEN the payment date is `None`, THE Billing_Port function `lps` SHALL return 0 (pkb lines 134-135).
2. LEGACY QUIRK (pkb line 136, time of day counts): WHEN the payment timestamp is later than the Due_Date at 00:00, THE Billing_Port function `lps` SHALL return the energy charge multiplied by 0.10, rounded to 2 decimal places using Round_Half_Up. A payment at 10:00 on the Due_Date therefore attracts the surcharge.
3. WHEN the payment timestamp is on or before the Due_Date at 00:00, THE Billing_Port function `lps` SHALL return 0. A payment at exactly midnight starting the Due_Date is on time.
4. LEGACY QUIRK (pkb line 137): THE Billing_Port function `lps` SHALL base the surcharge on the energy charge only, excluding fixed charge, fuel price adjustment, taxes and TV fee.
5. THE Billing_Port function `lps` SHALL reproduce the Oracle results 0 for a payment at 2024-01-22 00:00 and 123.46 for a payment at 2024-01-22 10:00, with energy charge 1234.55 and Due_Date 2024-01-22.

### Requirement 8: Bill generation (p_gen_bill)

**User Story:** As a billing analyst, I want a pure bill calculation that combines all units, so that I can compare Python bills with Oracle bills field by field.

Legacy source: `BILLING_PKG.p_gen_bill`, pkb lines 146-207. The Billing_Port covers the calculation only, in lines 170-193. Database reads (lines 162-183), the INSERT (lines 195-198) and the debug output are outside this port.

#### Acceptance Criteria

1. WHEN a Bill_Input is supplied, THE Billing_Port function `generate_bill` SHALL return a Bill whose fields are produced by chaining `units`, `energy_charge`, `fixed_charge`, `fpa`, `taxes`, `due_date` and `lps` in the legacy order (pkb lines 170-184).
2. WHEN the tariff is `A1`, THE Billing_Port function `generate_bill` SHALL set the TV fee to 35, and WHEN the tariff is any other value, THE Billing_Port function `generate_bill` SHALL set the TV fee to 60 (pkb lines 187-191).
3. LEGACY QUIRK (pkb line 187, TV fee is not taxed): THE Billing_Port function `generate_bill` SHALL exclude the TV fee from the GST base.
4. LEGACY QUIRK (pkb line 193, total rounded half up): THE Billing_Port function `generate_bill` SHALL compute the total as the sum of energy charge, fixed charge, fuel price adjustment, ED, GST, TV fee and surcharge, rounded to 0 decimal places using Round_Half_Up. A sum of 9048.50 SHALL give a total of 9049.
5. THE Billing_Port function `generate_bill` SHALL reproduce the five seed bills 1001 to 1005 verified in Oracle, matching every field of Bill exactly.
6. THE `generate_bill` docstring SHALL state as a deliberate difference that the function performs no database access and does not reproduce the legacy `WHEN OTHERS THEN NULL` handler at pkb lines 205-206. The docstring SHALL list the swallowed-error behaviour (customer 1006 with no meter reading produces no bill row) as a risk for the autopsy.
7. THE Billing_Port function `generate_bill` SHALL NOT catch exceptions raised by its inputs.

### Requirement 9: Cross-cutting porting rules

**User Story:** As a migration engineer, I want the port to follow the project migration rules, so that equivalence testing can prove identical behaviour.

#### Acceptance Criteria

1. THE Billing_Port SHALL represent all money and Units as `Decimal` and SHALL construct Decimal constants from strings.
2. THE Billing_Port SHALL perform every rounding with `Decimal.quantize` and `ROUND_HALF_UP` at the same points and in the same order as the Legacy_Package.
3. THE Billing_Port SHALL contain no call to the built-in `float` or the built-in `round`.
4. THE Billing_Port dataclasses `BillInput` and `Bill` SHALL be frozen, so that assigning to a field raises `dataclasses.FrozenInstanceError`.
5. THE Billing_Port function `generate_bill` SHALL return a `Bill` whose `due_dt` is of type `date` and whose money fields are of type `Decimal`.
6. THE docstring of each of `units`, `energy_charge`, `fixed_charge`, `fpa`, `taxes`, `due_date`, `lps` and `generate_bill` SHALL begin with "Ports BILLING_PKG.<legacy unit> (pkb lines X-Y)." using the line ranges in Requirements 1 to 8.
7. THE docstring of each function containing a Legacy_Quirk SHALL mark it with the text "LEGACY QUIRK:" and the legacy line numbers.
8. THE Billing_Port SHALL pass all 30 tests in the Test_Suite without any modification to the Test_Suite, so that the full suite of 117 tests (87 existing plus 30 new) passes with `.venv\Scripts\python.exe -m pytest -q`.
9. WHERE the property-based equivalence phase begins, THE Billing_Port SHALL have at least one Hypothesis property per requirement in Requirements 1 to 8 (migration rule 9). These properties belong to the later Prove spec.
