---
inclusion: fileMatch
fileMatchPattern: "legacy/**"
---
# How to write the synthetic legacy PL/SQL

The legacy package is a TEST FIXTURE. It must look like real code written by a
utility IT team in 2003-2009, but it is invented and written in Nov 2026.

## Mandatory header (top of every legacy file)
    -- ==========================================================================
    -- SYNTHETIC LEGACY CODE - written in November 2026 for the Grave Digger
    -- project (Kiroween 2026). It imitates 2000s-era style on purpose. All names,
    -- rates, rules and dated comments are fictional and resemble no real utility.
    -- ==========================================================================

## Style (on purpose)
- Cryptic names: v_enrg_chg, n_unt, f_lps, g_dbg, CUST_MST, MTR_RDG.
- Magic numbers inline (10, 13, 16, 22, 0.015, 0.17, 99999) instead of constants.
- Nested IF/ELSIF; few CASE expressions; cursor FOR loops.
- A package global debug flag g_dbg and DBMS_OUTPUT calls.
- Fictional change-log comments with initials and 2000s dates, plus a
  commented-out old rate, e.g. "-- 12-MAR-2006 RKH: slab 3 was 15.50".
- At least one WHEN OTHERS THEN NULL;

## But it must still work
- Must compile and run on Oracle Database Free (current version).
- Use VARCHAR2, NUMBER, DATE. Units in kWh, money in rupees with 2 decimals.
- Every public function used by the tests is declared in the package spec.
