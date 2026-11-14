"""Acceptance tests for Exhume + the Autopsy scanner (Kiro spec: autopsy-scanner).

These tests define "done" for the spec. They pin the facts that really are in
legacy/billing_pkg.pkb, so the plain-English autopsy (Day 4+) can only cite
rules the code actually contains.

Contract under test:
  gravedigger.exhume.load_package(spec_text, body_text) -> Package
  gravedigger.autopsy.scanner.scan(unit) -> Facts
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from gravedigger.autopsy.scanner import scan
from gravedigger.exhume import load_package

UNIT_ORDER = [
    "f_units",
    "f_enrg_chg",
    "f_fix_chg",
    "f_fpa",
    "p_taxes",
    "f_due_dt",
    "f_lps",
    "p_gen_bill",
]

# (start_line, end_line) of each unit in legacy/billing_pkg.pkb, 1-based, inclusive.
UNIT_LINES = {
    "f_units": (18, 31),
    "f_enrg_chg": (38, 65),
    "f_fix_chg": (72, 88),
    "f_fpa": (93, 102),
    "p_taxes": (108, 113),
    "f_due_dt": (118, 126),
    "f_lps": (131, 141),
    "p_gen_bill": (146, 207),
}


@pytest.fixture(scope="module")
def pkg(legacy_sources):
    spec_text, body_text = legacy_sources
    return load_package(spec_text, body_text)


@pytest.fixture(scope="module")
def units(pkg):
    return {u.name: u for u in pkg.units}


@pytest.fixture(scope="module")
def facts(units):
    return {name: scan(u) for name, u in units.items()}


def values(f) -> set[Decimal]:
    return {c.value for c in f.constants}


# ---------------------------------------------------------------- Exhume


def test_package_name_and_globals(pkg):
    assert pkg.name == "billing_pkg"
    assert "g_dbg" in {g.name for g in pkg.globals}


def test_units_found_in_body_order(pkg):
    assert [u.name for u in pkg.units] == UNIT_ORDER


def test_unit_kinds_and_return_types(units):
    assert units["f_units"].kind == "function"
    assert units["f_units"].return_type == "NUMBER"
    assert units["f_due_dt"].return_type == "DATE"
    assert units["p_taxes"].kind == "procedure"
    assert units["p_taxes"].return_type is None
    assert units["p_gen_bill"].kind == "procedure"


@pytest.mark.parametrize("name", UNIT_ORDER)
def test_unit_line_ranges(units, name):
    u = units[name]
    assert (u.start_line, u.end_line) == UNIT_LINES[name]


def test_unit_source_is_exact_slice(units):
    src = units["f_units"].source
    assert src.lstrip().upper().startswith("FUNCTION F_UNITS")
    assert src.rstrip().upper().endswith("END F_UNITS;")


def test_parameters_with_modes(units):
    assert [p.name for p in units["f_units"].params] == ["p_prev", "p_curr", "p_mf"]
    assert [p.mode for p in units["p_taxes"].params] == ["IN", "IN", "IN", "OUT", "OUT"]
    assert [p.datatype for p in units["f_lps"].params] == ["NUMBER", "DATE", "DATE"]


# ---------------------------------------------------------------- Scanner: constants


def test_rollover_constant_with_line(facts):
    rollover = [c for c in facts["f_units"].constants if c.value == Decimal("99999")]
    assert [c.line for c in rollover] == [23]


def test_tariff_constants(facts):
    assert {Decimal(v) for v in ("300", "22", "200", "100", "10", "13", "16", "25")} <= values(
        facts["f_enrg_chg"]
    )
    cliff_rate = [c.line for c in facts["f_enrg_chg"].constants if c.value == Decimal("22")]
    assert cliff_rate == [44]


def test_commented_out_rates_are_not_live_rules(facts):
    """15.50 and 21 only appear in comments (old rates). They must not be reported."""
    found = values(facts["f_enrg_chg"])
    assert Decimal("15.50") not in found
    assert Decimal("21") not in found


def test_tax_and_charge_constants(facts):
    assert {Decimal("0.015"), Decimal("0.17")} <= values(facts["p_taxes"])
    assert Decimal("400") in values(facts["f_fix_chg"])
    assert Decimal("75") in values(facts["f_fix_chg"])
    assert Decimal("0.10") in values(facts["f_lps"])
    assert Decimal("14") in values(facts["f_due_dt"])
    assert {Decimal("35"), Decimal("60")} <= values(facts["p_gen_bill"])


def test_constants_keep_exact_decimal_text(facts):
    """0.10 must stay 0.10 (Decimal), never become the float 0.1."""
    lps = [c for c in facts["f_lps"].constants if c.value == Decimal("0.10")]
    assert lps and all(isinstance(c.value, Decimal) for c in lps)
    assert lps[0].line == 137


def test_string_literals(facts):
    assert {"A1", "A2"} <= facts["f_enrg_chg"].string_literals
    assert "SUN" in facts["f_due_dt"].string_literals


# ---------------------------------------------------------------- Scanner: data and calls


def test_tables_read_and_written(facts):
    assert facts["f_fpa"].tables_read == {"FPA_RT"}
    assert facts["f_fpa"].tables_written == set()
    assert facts["p_gen_bill"].tables_read == {"CUST_MST", "MTR_RDG", "PYMT"}
    assert facts["p_gen_bill"].tables_written == {"BILL_HDR"}
    assert facts["f_units"].tables_read == set()


def test_calls_to_other_units(facts):
    assert facts["p_gen_bill"].calls == {
        "f_units",
        "f_enrg_chg",
        "f_fix_chg",
        "f_fpa",
        "p_taxes",
        "f_due_dt",
        "f_lps",
    }
    assert facts["f_enrg_chg"].calls == set()


def test_branch_counts(facts):
    """IF and ELSIF only (END IF does not count)."""
    assert facts["f_enrg_chg"].branches == 6
    assert facts["f_lps"].branches == 2
    assert facts["p_gen_bill"].branches == 2


# ---------------------------------------------------------------- Scanner: risks


def test_exception_handlers(facts):
    assert facts["f_fpa"].exceptions_handled == {"NO_DATA_FOUND"}
    assert facts["p_gen_bill"].exceptions_handled == {"NO_DATA_FOUND", "OTHERS"}
    assert facts["f_units"].exceptions_handled == set()


def test_swallowed_errors_flagged(facts):
    assert facts["p_gen_bill"].swallows_errors is True
    assert facts["f_fpa"].swallows_errors is False


def test_reads_debug_global(facts):
    assert "g_dbg" in facts["f_units"].globals_used


# ---------------------------------------------------------------- Robustness on unseen code


TRICKY_SPEC = """CREATE OR REPLACE PACKAGE tricky_pkg AS
  FUNCTION f_x (p_a NUMBER) RETURN NUMBER;
END tricky_pkg;
/
"""

TRICKY_BODY = """CREATE OR REPLACE PACKAGE BODY tricky_pkg AS
  FUNCTION f_x (p_a NUMBER) RETURN NUMBER IS
    v_msg VARCHAR2(100) := 'rate 99 -- not a comment';
  BEGIN
    /* INSERT INTO BILL_HDR VALUES (1);
       rate was 12.5 */
    -- UPDATE CUST_MST SET x = 7;
    RETURN p_a * 1.25;
  END f_x;
END tricky_pkg;
/
"""


def test_comments_and_strings_do_not_leak():
    pkg = load_package(TRICKY_SPEC, TRICKY_BODY)
    (unit,) = pkg.units
    f = scan(unit)
    assert Decimal("1.25") in values(f)
    assert Decimal("12.5") not in values(f)  # inside /* */
    assert Decimal("7") not in values(f)  # inside --
    assert Decimal("99") not in values(f)  # inside a string literal
    assert "rate 99 -- not a comment" in f.string_literals
    assert f.tables_written == set()
    assert f.tables_read == set()
