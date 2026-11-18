"""Acceptance tests for the ghost hunt (Kiro spec: ghost-hunt).

The hosted app cannot run Oracle, so real Oracle bills a large set of random
inputs ONCE and the results are saved as a golden snapshot. Any candidate port
can then be hunted against that snapshot in a browser, with no database.

The demo: a careless "first draft" port that uses Python's round() looks right
on every seed bill, but the hunt finds ghosts: bills where the draft and the
2004 PL/SQL disagree. The smallest ghost is shown, the draft is fixed, and the
hunt comes back clean.

Contract under test:
  gravedigger.prove.golden:
    GoldenCase(input: BillInput, oracle: Bill | None)        frozen dataclass
    save_cases(path, cases) / load_cases(path) -> tuple[GoldenCase, ...]
        JSON, UTF-8, exact round trip (Decimal as strings, datetimes ISO).
    build_golden(conn, inputs) -> tuple[GoldenCase, ...]     uses run_oracle
    GOLDEN_PATH                                               golden/cases.json
  gravedigger.prove.hunt:
    Ghost(input, oracle, python, diffs)                       frozen dataclass
    HuntReport(checked, matched, ghosts)                      frozen dataclass
        .smallest -> Ghost | None   (fewest units, then lowest Oracle total)
    hunt(port, cases) -> HuntReport  port is any callable BillInput -> Bill
  gravedigger.resurrected.billing_draft.generate_bill
        the DELIBERATELY wrong first draft: identical to the real port except
        the total uses Python's built-in round() (round half to even).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal as D

import pytest

from gravedigger.prove.golden import GOLDEN_PATH, GoldenCase, load_cases, save_cases
from gravedigger.prove.hunt import Ghost, HuntReport, hunt
from gravedigger.resurrected import billing, billing_draft
from gravedigger.resurrected.billing import BillInput

from test_resurrect_billing import SEED

GHOST_INPUT = BillInput("A1", D("2"), 0, 345, D("1"), datetime(2024, 1, 10), None, None)
GHOST_BILL = billing.generate_bill(GHOST_INPUT)  # Oracle-verified: total 9049 (test_prove_equivalence)


def seed_cases() -> tuple[GoldenCase, ...]:
    cases = [GoldenCase(inp, bill) for inp, bill in (SEED[c] for c in sorted(SEED))]
    cases.append(GoldenCase(GHOST_INPUT, GHOST_BILL))
    return tuple(cases)


# ---------------------------------------------------------------- golden file format


def test_save_and_load_round_trip_exactly(tmp_path):
    cases = seed_cases() + (GoldenCase(SEED[1001][0], None),)
    path = tmp_path / "cases.json"
    save_cases(path, cases)
    assert load_cases(path) == cases
    text = path.read_text(encoding="utf-8")
    assert "e+" not in text.lower()  # no float / scientific notation for money


# ---------------------------------------------------------------- the hunt


def test_the_real_port_has_no_ghosts():
    report = hunt(billing.generate_bill, seed_cases())
    assert isinstance(report, HuntReport)
    assert (report.checked, report.matched, report.ghosts) == (6, 6, ())
    assert report.smallest is None


def test_the_draft_looks_right_on_every_seed_bill():
    """Why the ghost is dangerous: all 5 seed bills from the old system still match."""
    report = hunt(billing_draft.generate_bill, seed_cases()[:5])
    assert report.ghosts == ()


def test_the_draft_is_haunted_by_the_rounding_ghost():
    report = hunt(billing_draft.generate_bill, seed_cases())
    assert report.checked == 6 and report.matched == 5
    (ghost,) = report.ghosts
    assert isinstance(ghost, Ghost)
    assert ghost.input == GHOST_INPUT
    assert [(d.field, d.oracle, d.python) for d in ghost.diffs] == [("total", D("9049"), D("9048"))]
    assert report.smallest == ghost


def test_a_missing_oracle_bill_is_a_ghost():
    report = hunt(billing.generate_bill, (GoldenCase(SEED[1001][0], None),))
    (ghost,) = report.ghosts
    assert ghost.oracle is None and ghost.diffs[0].field == "bill"


def test_smallest_ghost_is_fewest_units_then_lowest_total():
    import dataclasses

    big = BillInput("A1", D("2"), 0, 2345, D("1"), datetime(2024, 1, 10), None, None)

    def wrong(b):
        return dataclasses.replace(billing.generate_bill(b), total=D("1"))

    cases = (GoldenCase(big, billing.generate_bill(big)), GoldenCase(GHOST_INPUT, GHOST_BILL))
    assert hunt(wrong, cases).smallest.input == GHOST_INPUT


def test_draft_is_clearly_labelled_as_deliberately_wrong():
    assert "DELIBERATELY" in (billing_draft.__doc__ or "")
    assert "round()" in (billing_draft.generate_bill.__doc__ or "")


# ---------------------------------------------------------------- the golden snapshot (made once with real Oracle)


needs_golden = pytest.mark.skipif(
    not GOLDEN_PATH.is_file(), reason="golden/cases.json not built yet: run scripts/make_golden.py with Oracle up"
)


@needs_golden
def test_golden_snapshot_is_big_and_includes_the_known_cases():
    cases = load_cases(GOLDEN_PATH)
    assert len(cases) >= 2000
    inputs = {c.input for c in cases}
    assert GHOST_INPUT in inputs
    assert all(SEED[c][0] in inputs for c in SEED)
    assert all(c.oracle is not None for c in cases)  # strategy only makes bills Oracle can write


@needs_golden
def test_real_port_matches_every_golden_bill():
    report = hunt(billing.generate_bill, load_cases(GOLDEN_PATH))
    assert report.ghosts == ()
    assert report.matched == report.checked >= 2000


@needs_golden
def test_draft_port_is_caught_on_the_golden_snapshot():
    report = hunt(billing_draft.generate_bill, load_cases(GOLDEN_PATH))
    assert report.ghosts, "the hunt must catch the round() ghost"
    for g in report.ghosts:
        assert [d.field for d in g.diffs] == ["total"]
        assert abs(g.diffs[0].oracle - g.diffs[0].python) == 1
    assert report.smallest is not None


# ---------------------------------------------------------------- building the snapshot needs Oracle


@pytest.mark.oracle
def test_build_golden_uses_real_oracle():
    import oracledb

    from gravedigger.config import oracle_params
    from gravedigger.prove.golden import build_golden

    with oracledb.connect(**oracle_params()) as conn:
        cases = build_golden(conn, [SEED[1003][0], GHOST_INPUT])
    assert [c.oracle.total for c in cases] == [D("5179"), D("9049")]


@pytest.mark.oracle
@needs_golden
def test_golden_snapshot_is_genuine_oracle_output():
    """Re-bill an evenly spread sample of 50 snapshot cases in real Oracle: nothing may differ."""
    import oracledb

    from gravedigger.config import oracle_params
    from gravedigger.prove.compare import diff
    from gravedigger.prove.oracle_runner import run_oracle

    cases = load_cases(GOLDEN_PATH)
    sample = cases[:: max(1, len(cases) // 50)][:50]
    with oracledb.connect(**oracle_params()) as conn:
        for c in sample:
            assert diff(run_oracle(conn, c.input), c.oracle) == (), c.input
