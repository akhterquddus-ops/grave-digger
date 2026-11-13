---
inclusion: always
---
# Migration rules: porting PL/SQL to Python

The goal of a port is IDENTICAL behaviour first. Clean-up comes after the
equivalence tests pass, never before.

1. Never "fix" a business rule during the port. If the legacy code has a quirk
   (a slab cliff, a Sunday due-date shift, tax on tax), reproduce it exactly
   and mark it in the docstring with "LEGACY QUIRK:" and the legacy line number.
2. Oracle ROUND(x, n) -> Decimal.quantize(..., rounding=ROUND_HALF_UP).
   Round at exactly the same points as the legacy code, in the same order.
3. NULL handling: NVL(x, d) -> d if x is None else x. Arithmetic with NULL in
   Oracle gives NULL; model that explicitly, never by accident.
4. NO_DATA_FOUND mapped to a default in PL/SQL -> the same default in Python,
   with a comment. Do not raise where the legacy code did not.
5. WHEN OTHERS THEN NULL: do not copy it silently. Reproduce the observable
   result (e.g. no bill row written) and log a warning; list it as a risk in
   the autopsy.
6. Dates: Oracle DATE has a time part; TRUNC(d) -> date. Day-of-week logic
   must not depend on locale (legacy uses NLS_DATE_LANGUAGE=ENGLISH).
7. Integer division and NUMBER precision: use Decimal end to end.
8. Every Python function's docstring names the legacy unit and line range it
   ports, e.g. "Ports BILLING_PKG.f_lps (pkb lines 210-248)."
9. Every requirement in a spec becomes at least one Hypothesis property.
