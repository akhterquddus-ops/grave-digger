"""Acceptance tests for the Prove stage (Kiro spec: prove-equivalence).

The proof: Hypothesis generates random customers and meter readings, each is
billed by the REAL legacy PL/SQL in Oracle and by the Python port, and every
field must match to the paisa. A mismatch is a "ghost".

Contract under test:
  gravedigger.prove.strategies.bill_inputs() -> SearchStrategy[BillInput]
      only values that fit the legacy columns (NUMBER(5) readings, NUMBER(6,2)
      load and MF, NUMBER(8,4) FPA rate, tariff A1 or A2), weighted towards the
      edges where legacy code breaks: slab boundaries, meter rollover, Sunday
      due dates, payments on the due date, missing FPA rates.
  gravedigger.prove.compare.FieldDiff(field, oracle, python)   frozen dataclass
  gravedigger.prove.compare.diff(oracle: Bill | None, python: Bill) -> tuple[FieldDiff, ...]
      () when equal; field "bill" when Oracle wrote no row.
  gravedigger.prove.oracle_runner.run_oracle(conn, BillInput) -> Bill | None
      bills ONE probe customer through BILLING_PKG.p_gen_bill in real Oracle,
      reads BILL_HDR, and ROLLS BACK so nothing is left behind. Numbers come
      back as Decimal, the due date as datetime.date.

Tests marked "oracle" need the local container (scripts/start-oracle.ps1) and
are skipped when ORACLE_DSN is not set.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta
from decimal import Decimal as D

import pytest
from hypothesis import HealthCheck, find, given, settings

from gravedigger.prove.compare import FieldDiff, diff
from gravedigger.prove.strategies import bill_inputs
from gravedigger.resurrected.billing import Bill, BillInput, due_date, generate_bill, units

from test_resurrect_billing import SEED

# ---------------------------------------------------------------- strategy (no Oracle)


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@given(bill_inputs())
def test_inputs_fit_the_legacy_columns(b):
    assert isinstance(b, BillInput)
    assert b.tariff in ("A1", "A2")
    assert 0 <= b.prev_rdg <= 99999 and 0 <= b.curr_rdg <= 99999
    assert isinstance(b.prev_rdg, int) and isinstance(b.curr_rdg, int)
    for value, digits, places in ((b.load_kw, 6, 2), (b.mf, 6, 2)):
        assert isinstance(value, D) and D(0) < value < D(10) ** (digits - places)
        assert value == value.quantize(D(1).scaleb(-places))
    if b.fpa_rate is not None:
        assert isinstance(b.fpa_rate, D) and D(0) <= b.fpa_rate < D(10) ** 4
        assert b.fpa_rate == b.fpa_rate.quantize(D("0.0001"))
    assert isinstance(b.rdg_dt, datetime)
    assert b.pay_dt is None or isinstance(b.pay_dt, datetime)
    # Oracle DATE keeps whole seconds only. A payment at 00:00:00.5 on the due date would be
    # truncated to midnight (on time) in Oracle but stay late in Python: a false ghost.
    assert b.rdg_dt.microsecond == 0
    assert b.pay_dt is None or b.pay_dt.microsecond == 0
    # The bill must also fit BILL_HDR (NUMBER(12,2) amounts, NUMBER(12) total). Otherwise Oracle
    # overflows, WHEN OTHERS THEN NULL swallows it, no row is written, and we report a false ghost.
    bill = generate_bill(b)
    for field in ("units", "enrg", "fix", "fpa", "ed", "gst", "tv", "lps"):
        assert abs(getattr(bill, field)) < D(10) ** 10, field
    assert abs(bill.total) < D(10) ** 12


def _reaches(predicate):
    """True if the strategy can produce an input with this property (bounded search)."""
    find(bill_inputs(), predicate, settings=settings(max_examples=3000, database=None))
    return True


@pytest.mark.parametrize(
    "name, predicate",
    [
        ("exactly 300 units", lambda b: units(b.prev_rdg, b.curr_rdg, b.mf) == 300),
        ("exactly 301 units", lambda b: units(b.prev_rdg, b.curr_rdg, b.mf) == 301),
        ("meter rollover", lambda b: b.curr_rdg < b.prev_rdg),
        ("shop tariff", lambda b: b.tariff == "A2"),
        ("missing FPA rate", lambda b: b.fpa_rate is None),
        ("not paid", lambda b: b.pay_dt is None),
        ("due date moved off a Sunday", lambda b: (b.rdg_dt.date() + timedelta(days=14)).weekday() == 6),
        ("paid on the due date after midnight",
         lambda b: b.pay_dt is not None
         and b.pay_dt.date() == due_date(b.rdg_dt)
         and b.pay_dt.time() != datetime.min.time()),
        ("paid exactly at midnight of the due date",
         lambda b: b.pay_dt is not None and b.pay_dt == datetime.combine(due_date(b.rdg_dt), datetime.min.time())),
    ],
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_strategy_reaches_the_edges(name, predicate):
    assert _reaches(predicate), name


# ---------------------------------------------------------------- compare (no Oracle)


def test_equal_bills_have_no_diff():
    bill = SEED[1002][1]
    assert diff(bill, bill) == ()


def test_one_field_differs():
    oracle = SEED[1002][1]
    python = dataclasses.replace(oracle, total=D("2055"))
    assert diff(oracle, python) == (FieldDiff("total", D("2056"), D("2055")),)


def test_numeric_equality_ignores_trailing_zeros():
    oracle = SEED[1005][1]
    python = dataclasses.replace(oracle, fix=D("3000"))  # Oracle may say 3000.00
    assert diff(oracle, python) == ()


def test_missing_oracle_row_is_a_diff():
    (d,) = diff(None, SEED[1001][1])
    assert d.field == "bill" and d.oracle is None


# ---------------------------------------------------------------- real Oracle


@pytest.fixture(scope="module")
def conn():
    import oracledb

    from gravedigger.config import oracle_params

    c = oracledb.connect(**oracle_params())
    yield c
    c.rollback()
    c.close()


def _count(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


@pytest.mark.oracle
@pytest.mark.parametrize("cust", sorted(SEED))
def test_oracle_runner_reproduces_the_seed_bills(conn, cust):
    from gravedigger.prove.oracle_runner import run_oracle

    given_input, expected = SEED[cust]
    got = run_oracle(conn, given_input)
    assert got is not None
    assert diff(got, expected) == ()
    assert all(isinstance(getattr(got, f), D) for f in ("units", "enrg", "fix", "fpa", "ed", "gst", "tv", "lps", "total"))
    assert type(got.due_dt) is date


@pytest.mark.oracle
def test_oracle_runner_leaves_nothing_behind(conn):
    from gravedigger.prove.oracle_runner import run_oracle

    before = [_count(conn, f"SELECT COUNT(*) FROM {t}") for t in ("CUST_MST", "MTR_RDG", "FPA_RT", "PYMT", "BILL_HDR")]
    run_oracle(conn, SEED[1003][0])
    after = [_count(conn, f"SELECT COUNT(*) FROM {t}") for t in ("CUST_MST", "MTR_RDG", "FPA_RT", "PYMT", "BILL_HDR")]
    assert before == after


@pytest.mark.oracle
def test_the_rounding_ghost_is_real_in_oracle(conn):
    """345 units: Oracle bills 9049; a port using Python's round() would bill 9048."""
    from gravedigger.prove.oracle_runner import run_oracle

    b = BillInput("A1", D("2"), 0, 345, D("1"), datetime(2024, 1, 10), None, None)
    oracle = run_oracle(conn, b)
    assert oracle.total == D("9049")
    pre = oracle.enrg + oracle.fix + oracle.fpa + oracle.ed + oracle.gst + oracle.tv + oracle.lps
    assert pre == D("9048.50")
    assert round(pre) == 9048  # the ghost a careless port would ship


@pytest.mark.oracle
@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(b=bill_inputs())
def test_python_port_bills_exactly_like_oracle(conn, b):
    """THE PROOF. dev profile: 200 random bills; ci profile: 2000."""
    from gravedigger.prove.oracle_runner import run_oracle

    assert diff(run_oracle(conn, b), generate_bill(b)) == ()
