"""Hypothesis strategy for the Prove stage: random but legal bill inputs.

Ports nothing itself. It generates inputs for BILLING_PKG.p_gen_bill and aims
at the units whose edges break legacy code: f_units (slab boundaries, meter
rollover), f_due_dt (Sunday shift) and f_lps (payment on the due date).

Every value fits the legacy columns: NUMBER(5) readings, NUMBER(6,2) load and
MF, NUMBER(8,4) FPA rate, tariff A1 or A2, whole-second DATE values in
2000..2100 (Oracle DATE is Julian before 1582 and swallows year-9999 overflow,
so early and late dates are never generated). Money-like values are Decimal
built from integers with scaleb, never float.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, time, timedelta
from decimal import Decimal

from hypothesis import strategies as st

from gravedigger.resurrected.billing import Bill, BillInput, due_date, generate_bill

RDG_DT_MIN = datetime(2000, 1, 1, 0, 0, 0)
RDG_DT_MAX = datetime(2099, 12, 31, 23, 59, 59)
PAY_DT_MIN = datetime(2000, 1, 1, 0, 0, 0)
PAY_DT_MAX = datetime(2100, 1, 31, 23, 59, 59)

_AMOUNT_LIMIT = Decimal(10) ** 10  # BILL_HDR NUMBER(12,2): below 10^10 in absolute value
_TOTAL_LIMIT = Decimal(10) ** 12  # BILL_HDR total NUMBER(12)


def fits_bill_header(b: BillInput) -> bool:
    """True if the bill for `b` fits the BILL_HDR columns (BILLING_PKG.p_gen_bill).

    Oracle swallows an overflow (WHEN OTHERS THEN NULL) and writes no row, which
    would show up as a false ghost, so such inputs are never generated.
    """
    try:
        bill: Bill = generate_bill(b)
    except OverflowError:
        return False
    amounts = (bill.units, bill.enrg, bill.fix, bill.fpa, bill.ed, bill.gst, bill.tv, bill.lps)
    return all(abs(a) < _AMOUNT_LIMIT for a in amounts) and abs(bill.total) < _TOTAL_LIMIT


def _whole_seconds(lo: datetime, hi: datetime) -> st.SearchStrategy[datetime]:
    return st.datetimes(min_value=lo, max_value=hi).map(lambda d: d.replace(microsecond=0))


def _scaled(lo: int, hi: int, places: int) -> st.SearchStrategy[Decimal]:
    return st.integers(min_value=lo, max_value=hi).map(lambda n: Decimal(n).scaleb(-places))


def _mf() -> st.SearchStrategy[Decimal]:
    """Multiplying factor 0.01..9999.99. Mostly small, so few bills overflow BILL_HDR."""
    small = _scaled(1, 1000, 2)
    return st.one_of(small, small, small, _scaled(1, 999999, 2))


@st.composite
def _random_input(draw: st.DrawFn) -> BillInput:
    """Every field drawn freely within its legal range."""
    return BillInput(
        tariff=draw(st.sampled_from(("A1", "A2"))),
        load_kw=draw(_scaled(1, 999999, 2)),
        prev_rdg=draw(st.integers(0, 99999)),
        curr_rdg=draw(st.integers(0, 99999)),
        mf=draw(_mf()),
        rdg_dt=draw(_whole_seconds(RDG_DT_MIN, RDG_DT_MAX)),
        fpa_rate=draw(st.one_of(st.none(), _scaled(0, 99999999, 4))),
        pay_dt=draw(st.one_of(st.none(), _whole_seconds(PAY_DT_MIN, PAY_DT_MAX))),
    )


_UNIT_TARGETS = (0, 99, 100, 101, 200, 201, 300, 301, 345)  # slab edges of f_enrg_chg

# Common cases are listed several times so they are drawn more often.
_SCENARIOS = (
    "random", "random", "random",
    "units_edge", "units_edge",
    "rollover", "rollover",
    "shop",
    "no_fpa", "no_fpa",
    "unpaid", "unpaid",
    "sunday_due", "sunday_due",
    "pay_on_due_day", "pay_on_due_day",
    "pay_midnight", "pay_midnight",
    "half_paisa", "half_paisa",
)

_HIGH_SUNDAY = datetime(2099, 12, 24, 23, 59, 59)
_LOW_SUNDAY = datetime(2000, 1, 9, 0, 0, 0)


def _half_paisa_pool() -> tuple[tuple[str, Decimal, int], ...]:
    """(tariff, load_kw, units) combinations whose sum before the final ROUND ends in .50.

    Ports nothing. Scans BILLING_PKG.p_gen_bill (via the Port) once, with
    mf = 1, no FPA rate and no payment, so the final ROUND(..., 0) in
    pkb line 193 sits exactly on a half and must round away from zero.
    """
    loads = [Decimal(n).scaleb(-2) for n in range(25, 1001, 25)]  # 0.25 .. 10.00
    pool: list[tuple[str, Decimal, int]] = []
    base = BillInput("A1", Decimal(1), 0, 0, Decimal(1), RDG_DT_MIN, None, None)
    for tariff, load_list in (("A1", loads[:1]), ("A2", loads)):
        for load in load_list:
            for n in range(0, 401):
                inp = dataclasses.replace(base, tariff=tariff, load_kw=load, curr_rdg=n)
                b = generate_bill(inp)
                pre = b.enrg + b.fix + b.fpa + b.ed + b.gst + b.tv + b.lps
                if pre % 1 == Decimal("0.5"):
                    pool.append((tariff, load, n))
    return tuple(pool)


def bill_inputs() -> st.SearchStrategy[BillInput]:
    """Random legal BillInput values for BILLING_PKG.p_gen_bill (f_units, f_due_dt, f_lps).

    A scenario is drawn first and shapes the random base input towards an edge:
    slab boundaries, meter rollover, shop tariff, no FPA rate, unpaid, Sunday
    due date, payment on the due date, and sums ending in half a rupee.
    Inputs whose bill would overflow BILL_HDR are filtered out.
    """
    pool = _half_paisa_pool()  # once per call, deterministic

    @st.composite
    def build(draw: st.DrawFn) -> BillInput:
        scenario = draw(st.sampled_from(_SCENARIOS))
        b = draw(_random_input())
        if scenario == "units_edge":
            target = draw(st.sampled_from(_UNIT_TARGETS))
            prev = draw(st.integers(0, 99999 - target))
            b = dataclasses.replace(b, mf=Decimal(1), prev_rdg=prev, curr_rdg=prev + target)
        elif scenario == "rollover":
            prev = draw(st.integers(1, 99999))
            b = dataclasses.replace(b, prev_rdg=prev, curr_rdg=draw(st.integers(0, prev - 1)))
        elif scenario == "shop":
            b = dataclasses.replace(b, tariff="A2")
        elif scenario == "no_fpa":
            b = dataclasses.replace(b, fpa_rate=None)
        elif scenario == "unpaid":
            b = dataclasses.replace(b, pay_dt=None)
        elif scenario == "sunday_due":
            d = draw(_whole_seconds(_LOW_SUNDAY, _HIGH_SUNDAY))
            back = (d.weekday() + 1) % 7  # step back to a Sunday: reading + 14 days is a Sunday
            b = dataclasses.replace(b, rdg_dt=d - timedelta(days=back))
        elif scenario in ("pay_on_due_day", "pay_midnight"):
            midnight = datetime.combine(due_date(b.rdg_dt), time.min)
            extra = 0 if scenario == "pay_midnight" else draw(st.integers(1, 86399))
            b = dataclasses.replace(b, pay_dt=midnight + timedelta(seconds=extra))
        elif scenario == "half_paisa" and pool:
            tariff, load, n = draw(st.sampled_from(pool))
            b = dataclasses.replace(
                b, tariff=tariff, load_kw=load, mf=Decimal(1), prev_rdg=0, curr_rdg=n,
                fpa_rate=None, pay_dt=None,
            )
        return b

    return build().filter(fits_bill_header)