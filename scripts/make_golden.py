"""Build golden/cases.json: bill a fixed set of inputs in real Oracle, once.

This script ports no legacy unit. It only collects inputs and (in main) asks
Oracle to bill them, then saves the bills as the golden snapshot.

How the inputs are chosen (reproducible):
- Fixed seed 20261113 (``@seed``), plus ``derandomize=True``, so every run
  draws the same sequence from ``bill_inputs()``.
- Draw size: 2600 examples are requested (OVERDRAW) and the first 2000
  distinct ones are kept (DRAW_COUNT).
- Dedupe rule: the strategy can produce equal inputs from different choices,
  so draws are walked in order and an input is kept only if it is not already
  in the ``seen`` set. The set starts with the five seed inputs and the
  rounding-ghost input, so the snapshot has no duplicate inputs.
- Final list: 5 seed inputs (ascending customer number), the rounding ghost
  input, then the 2000 drawn inputs (2006 cases).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from hypothesis import HealthCheck, Phase, given, seed, settings

from gravedigger.config import REPO_ROOT, oracle_params
from gravedigger.prove.golden import (
    GOLDEN_PATH,
    GoldenCase,
    build_golden,
    load_cases,
    save_cases,
)
from gravedigger.prove.hunt import hunt
from gravedigger.prove.strategies import bill_inputs
from gravedigger.resurrected import billing_draft
from gravedigger.resurrected.billing import BillInput

SEED_VALUE = 20261113
DRAW_COUNT = 2000  # distinct inputs wanted from bill_inputs()
OVERDRAW = 2600  # examples requested, so duplicates cannot leave us short


class NotEnoughInputsError(RuntimeError):
    """Raised when fewer than DRAW_COUNT distinct inputs could be drawn."""


def known_inputs() -> list[BillInput]:
    """Five seed inputs (ascending customer number), then the rounding ghost input."""
    tests_dir = str(REPO_ROOT / "tests")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    from test_resurrect_billing import SEED  # noqa: PLC0415

    inputs = [SEED[cust][0] for cust in sorted(SEED)]
    inputs.append(
        BillInput(
            "A1",
            Decimal("2"),
            0,
            345,
            Decimal("1"),
            datetime(2024, 1, 10),
            None,
            None,
        )
    )
    return inputs


def draw_inputs(known: Sequence[BillInput]) -> list[BillInput]:
    """Draw DRAW_COUNT distinct, reproducible inputs that are not in ``known``.

    Raises NotEnoughInputsError if fewer than DRAW_COUNT distinct inputs result.
    """
    got: list[BillInput] = []

    @seed(SEED_VALUE)
    @settings(
        max_examples=OVERDRAW,
        derandomize=True,
        database=None,
        phases=[Phase.generate],
        suppress_health_check=list(HealthCheck),
        deadline=None,
    )
    @given(bill_inputs())
    def collect(b: BillInput) -> None:
        got.append(b)

    collect()

    seen: set[BillInput] = set(known)
    drawn: list[BillInput] = []
    for b in got:
        if b in seen:
            continue
        seen.add(b)
        drawn.append(b)
        if len(drawn) == DRAW_COUNT:
            return drawn
    raise NotEnoughInputsError(
        f"Only {len(drawn)} distinct inputs were drawn; {DRAW_COUNT} are needed."
    )


def write_atomically(cases: Sequence[GoldenCase], target: Path) -> None:
    """Save cases to a temp file, verify by re-reading, then swap it into place."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name("cases.json.tmp")
    try:
        save_cases(tmp, cases)
        if load_cases(tmp) != tuple(cases):
            raise ValueError("cases.json.tmp did not read back identical to what was saved")
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def main() -> int:
    """Bill the fixed inputs in Oracle once and write golden/cases.json.

    Ports no legacy unit. Returns 0 on success, 1 if inputs are short or Oracle
    returned no bill for an input, 2 if Oracle cannot be reached. A file is
    written only on success.
    """
    known = known_inputs()
    try:
        inputs = known + draw_inputs(known)
    except NotEnoughInputsError as exc:
        print(f"Not enough distinct inputs: {exc}")
        return 1

    import oracledb  # noqa: PLC0415

    conn = None
    try:
        try:
            conn = oracledb.connect(**oracle_params())
        except (RuntimeError, oracledb.Error) as exc:
            print(
                "Could not reach Oracle. Start the container with "
                "scripts/start-oracle.ps1, then run this again. "
                f"({type(exc).__name__})"
            )
            return 2

        cases = build_golden(conn, inputs)
        for case in cases:
            if case.oracle is None:
                print(f"Oracle produced no bill for this input: {case.input}")
                return 1

        write_atomically(cases, GOLDEN_PATH)
        ghosts = len(hunt(billing_draft.generate_bill, cases).ghosts)
        print(f"Wrote {len(cases)} cases to {GOLDEN_PATH}.")
        print(f"The draft disagrees with Oracle on {ghosts} of them (ghosts).")
        return 0
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
