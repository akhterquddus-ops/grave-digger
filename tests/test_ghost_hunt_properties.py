"""Hypothesis properties for the ghost hunt (spec: .kiro/specs/ghost-hunt).

Shared generators and helpers. Ports no legacy unit; the pre-rounding sum
mirrors BILLING_PKG.p_gen_bill (pkb lines 146-207, ROUND at line 193).
"""

from __future__ import annotations

import dataclasses
import tempfile
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from hypothesis import example, given
from hypothesis import strategies as st

from gravedigger.prove.golden import GoldenCase, load_cases, save_cases
from gravedigger.prove.hunt import hunt
from gravedigger.prove.strategies import bill_inputs
from gravedigger.resurrected import billing, billing_draft
from gravedigger.resurrected.billing import Bill, BillInput

INPUTS = bill_inputs()

GHOST_INPUT = BillInput(
    "A1", Decimal("2"), 0, 345, Decimal("1"), datetime(2024, 1, 10), None, None
)

_money = st.decimals(
    min_value=-(10**12),
    max_value=10**12,
    places=4,
    allow_nan=False,
    allow_infinity=False,
)

port_bills = INPUTS.map(billing.generate_bill)

arbitrary_bills = st.builds(
    Bill,
    units=_money,
    enrg=_money,
    fix=_money,
    fpa=_money,
    ed=_money,
    gst=_money,
    tv=_money,
    lps=_money,
    total=_money,
    due_dt=st.dates(),
)


def golden_cases() -> st.SearchStrategy[GoldenCase]:
    """Golden cases: no Oracle bill, a port bill, or an arbitrary bill."""
    return st.builds(
        GoldenCase, INPUTS, st.one_of(st.none(), port_bills, arbitrary_bills)
    )


@st.composite
def _perturbing_port(draw: st.DrawFn) -> Callable[[BillInput], Bill]:
    """A port that shifts the total by delta for inputs whose hash % k == 0."""
    delta = draw(st.sampled_from([-1, 0, 1]))
    k = draw(st.integers(min_value=1, max_value=4))

    def port(b: BillInput) -> Bill:
        bill = billing.generate_bill(b)
        if hash(b) % k == 0:
            return dataclasses.replace(bill, total=bill.total + delta)
        return bill

    return port


def ports() -> st.SearchStrategy[Callable[[BillInput], Bill]]:
    """Candidate ports: the real port, the wrong draft, or a perturbed port."""
    return st.one_of(
        st.sampled_from([billing.generate_bill, billing_draft.generate_bill]),
        _perturbing_port(),
    )


def pre_rounding_sum(b: BillInput) -> Decimal:
    """Sum before ROUND at pkb line 193, rebuilt from the unit functions."""
    u = billing.units(b.prev_rdg, b.curr_rdg, b.mf)
    enrg = billing.energy_charge(b.tariff, u)
    fix = billing.fixed_charge(b.tariff, b.load_kw, enrg)
    fpa_amt = billing.fpa(u, b.fpa_rate)
    ed, gst = billing.taxes(enrg, fix, fpa_amt)
    due = billing.due_date(b.rdg_dt)
    lps_amt = billing.lps(enrg, due, b.pay_dt)
    tv = Decimal("35") if b.tariff == "A1" else Decimal("60")
    return enrg + fix + fpa_amt + ed + gst + tv + lps_amt


# Feature: ghost-hunt, Property 1: Golden file round trip
@given(st.lists(golden_cases(), max_size=3))
def test_r1_7_save_then_load_returns_the_same_cases(cases: list[GoldenCase]) -> None:
    """**Validates: Requirements 1.7**"""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "cases.json"
        save_cases(path, cases)
        assert load_cases(path) == tuple(cases)

# Feature: ghost-hunt, Property 2: Hunt report adds up
@given(ports(), st.lists(golden_cases(), max_size=4))
def test_r3_5_checked_equals_matched_plus_ghosts(
    port: Callable[[BillInput], Bill], cases: list[GoldenCase]
) -> None:
    """**Validates: Requirements 3.5**"""
    report = hunt(port, cases)
    assert report.checked == len(cases)
    assert report.checked == report.matched + len(report.ghosts)


# Feature: ghost-hunt, Property 3: Draft differs only by half-even rounding of the total
@given(INPUTS)
@example(GHOST_INPUT)
def test_r5_3_r5_6_draft_differs_from_port_only_by_half_even_total(
    inp: BillInput,
) -> None:
    """**Validates: Requirements 5.3, 5.6**"""
    port = billing.generate_bill(inp)
    draft = billing_draft.generate_bill(inp)
    for f in dataclasses.fields(Bill):
        if f.name != "total":
            assert getattr(draft, f.name) == getattr(port, f.name), f.name
    pre = pre_rounding_sum(inp)
    expect_differ = (pre % 1 == Decimal("0.5")) and (int(pre) % 2 == 0)
    assert (draft.total != port.total) == expect_differ
    if expect_differ:
        assert port.total - draft.total == Decimal(1)
    else:
        assert draft.total == port.total
