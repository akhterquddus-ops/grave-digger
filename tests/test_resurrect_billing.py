"""Acceptance tests for the Python port of BILLING_PKG (Kiro spec: resurrect-billing).

The port must bill EXACTLY like the legacy PL/SQL, quirks included
(see .kiro/steering/migration-rules.md). Expected values below were computed
independently and the seed bills were confirmed in real Oracle on Nov 13.
Equivalence on random inputs against live Oracle comes in the next spec.

Contract under test (module gravedigger.resurrected.billing):
  BillInput(tariff, load_kw, prev_rdg, curr_rdg, mf, rdg_dt, fpa_rate, pay_dt)  frozen dataclass
      fpa_rate: Decimal | None   (None = no FPA_RT row for the month)
      pay_dt:   datetime | None  (None = not paid yet)
  Bill(units, enrg, fix, fpa, ed, gst, tv, lps, total, due_dt)                  frozen dataclass
  units(prev, curr, mf)              ports f_units
  energy_charge(tariff, units)       ports f_enrg_chg
  fixed_charge(tariff, load_kw, enrg) ports f_fix_chg
  fpa(units, rate)                   ports f_fpa (rate None -> 0)
  taxes(enrg, fix, fpa) -> (ed, gst) ports p_taxes
  due_date(rdg_dt) -> date           ports f_due_dt
  lps(enrg, due_dt, pay_dt)          ports f_lps
  generate_bill(BillInput) -> Bill   ports p_gen_bill (the calculation; no database)
All money and units are Decimal.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from gravedigger.resurrected import billing
from gravedigger.resurrected.billing import (
    Bill,
    BillInput,
    due_date,
    energy_charge,
    fixed_charge,
    fpa,
    generate_bill,
    lps,
    taxes,
    units,
)

RATE_JAN = D("0.35")  # FPA_RT row for 202401 in legacy/schema.sql

# ---------------------------------------------------------------- the 5 seed bills (verified in Oracle)

SEED = {
    1001: (BillInput("A1", D("2.00"), 1000, 1005, D("1"), datetime(2024, 1, 10), RATE_JAN, None),
           Bill(D("5"), D("50.00"), D("25.00"), D("1.75"), D("0.75"), D("13.18"), D("35"), D("0"), D("126"), date(2024, 1, 24))),
    1002: (BillInput("A1", D("3.00"), 2000, 2150, D("1"), datetime(2024, 1, 10), RATE_JAN, datetime(2024, 1, 20, 11, 30)),
           Bill(D("150"), D("1650.00"), D("0"), D("52.50"), D("24.75"), D("293.63"), D("35"), D("0"), D("2056"), date(2024, 1, 24))),
    1003: (BillInput("A1", D("5.00"), 99900, 50, D("2"), datetime(2024, 1, 7), RATE_JAN, datetime(2024, 1, 22, 10, 0)),
           Bill(D("300"), D("3900.00"), D("0"), D("105.00"), D("58.50"), D("690.80"), D("35"), D("390.00"), D("5179"), date(2024, 1, 22))),
    1004: (BillInput("A1", D("4.00"), 5000, 5301, D("1"), datetime(2024, 2, 5), None, datetime(2024, 2, 25, 9, 15)),
           Bill(D("301"), D("6622.00"), D("0"), D("0"), D("99.33"), D("1142.63"), D("35"), D("662.20"), D("8561"), date(2024, 2, 19))),
    1005: (BillInput("A2", D("7.50"), 100, 400, D("1"), datetime(2024, 1, 10), RATE_JAN, datetime(2024, 1, 24, 0, 0)),
           Bill(D("300"), D("7500.00"), D("3000.00"), D("105.00"), D("112.50"), D("1821.98"), D("60"), D("0"), D("12599"), date(2024, 1, 24))),
}


@pytest.mark.parametrize("cust", sorted(SEED))
def test_seed_bills_match_oracle_to_the_paisa(cust):
    given, expected = SEED[cust]
    got = generate_bill(given)
    for field in dataclasses.fields(Bill):
        assert getattr(got, field.name) == getattr(expected, field.name), (cust, field.name)


# ---------------------------------------------------------------- the 8 planted rules, one by one


def test_meter_rollover():
    assert units(99900, 50, D("2")) == D("300")
    assert units(5, 5, D("1")) == D("0")
    assert units(100, 250, D("1.5")) == D("225.0")


@pytest.mark.parametrize(
    "u, expected",
    [(0, "0"), (100, "1000"), (101, "1013"), (200, "2300"), (201, "2316"), (300, "3900"), (301, "6622")],
)
def test_home_slabs_and_the_300_unit_cliff(u, expected):
    assert energy_charge("A1", D(u)) == D(expected)


def test_shop_flat_rate_and_unknown_tariff():
    assert energy_charge("A2", D("300")) == D("7500")
    assert energy_charge("Z9", D("300")) == D("0")


def test_minimum_charge_and_shop_fixed_charge():
    assert fixed_charge("A1", D("2"), D("50.00")) == D("25.00")
    assert fixed_charge("A1", D("2"), D("75.00")) == D("0")
    assert fixed_charge("A1", D("2"), D("80.00")) == D("0")
    assert fixed_charge("A2", D("7.50"), D("7500")) == D("3000")


def test_missing_fpa_rate_is_zero_and_rounding_is_half_up():
    assert fpa(D("300"), None) == D("0")
    assert fpa(D("5"), D("0.333")) == D("1.67")  # 1.665 rounds UP like Oracle ROUND


def test_gst_is_charged_on_top_of_duty():
    ed, gst = taxes(D("100"), D("0"), D("0"))
    assert ed == D("1.50")
    assert gst == D("17.26")  # 17% of 101.50 = 17.255 -> 17.26 (half up)


def test_sunday_due_date_moves_to_monday():
    assert due_date(datetime(2024, 1, 7)) == date(2024, 1, 22)  # 21st is a Sunday
    assert due_date(datetime(2024, 1, 10, 15, 30)) == date(2024, 1, 24)  # time part ignored


def test_surcharge_is_ten_percent_of_energy_and_time_of_day_counts():
    due = date(2024, 1, 22)
    assert lps(D("1234.55"), due, None) == D("0")
    assert lps(D("1234.55"), due, datetime(2024, 1, 22, 0, 0)) == D("0")  # exactly midnight: on time
    assert lps(D("1234.55"), due, datetime(2024, 1, 22, 10, 0)) == D("123.46")  # 10 AM on due date: late


# ---------------------------------------------------------------- the rounding ghost


def test_total_rounds_half_up_like_oracle_not_bankers_rounding():
    """345 units of A1: total before rounding is 9048.50. Oracle ROUND gives 9049.

    Python's built-in round() would give 9048 (round half to even): a one-rupee ghost.
    """
    bill = generate_bill(BillInput("A1", D("2"), 0, 345, D("1"), datetime(2024, 1, 10), None, None))
    assert bill.total == D("9049")


# ---------------------------------------------------------------- types and migration rules


def test_money_is_decimal_and_types_are_frozen():
    bill = generate_bill(SEED[1002][0])
    for field in ("units", "enrg", "fix", "fpa", "ed", "gst", "tv", "lps", "total"):
        assert isinstance(getattr(bill, field), D), field
    assert type(bill.due_dt) is date
    with pytest.raises(dataclasses.FrozenInstanceError):
        bill.total = D("0")  # type: ignore[misc]


@pytest.mark.parametrize(
    "func, legacy",
    [(units, "f_units"), (energy_charge, "f_enrg_chg"), (fixed_charge, "f_fix_chg"), (fpa, "f_fpa"),
     (taxes, "p_taxes"), (due_date, "f_due_dt"), (lps, "f_lps"), (generate_bill, "p_gen_bill")],
)
def test_every_function_names_the_legacy_unit_it_ports(func, legacy):
    assert func.__doc__ and f"BILLING_PKG.{legacy}" in func.__doc__


def test_no_float_and_no_builtin_round_in_the_port():
    """Money never goes through float() or Python's round() (round half to even)."""
    import ast

    tree = ast.parse(open(billing.__file__, encoding="utf-8").read())
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "float" not in calls
    assert "round" not in calls
