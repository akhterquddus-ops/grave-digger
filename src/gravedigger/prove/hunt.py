"""Ghost hunt: run a candidate port over golden cases and collect disagreements.

This module ports no legacy unit. It checks a port against the stored results of
BILLING_PKG.p_gen_bill (pkb lines 146-207). No database, no I/O, no global state.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal

from gravedigger.prove.compare import FieldDiff, diff
from gravedigger.prove.golden import GoldenCase
from gravedigger.resurrected.billing import Bill, BillInput


@dataclass(frozen=True)
class Ghost:
    """One input where the port and BILLING_PKG.p_gen_bill (pkb lines 146-207) disagree.

    Ports no legacy unit. oracle is None when Oracle wrote no bill row.
    """

    input: BillInput
    oracle: Bill | None
    python: Bill
    diffs: tuple[FieldDiff, ...]


def _size(ghost: Ghost) -> tuple[Decimal, Decimal]:
    """Sort key for 'smallest' ghost: (units, total) of the Oracle bill, else the Python bill."""
    bill = ghost.oracle if ghost.oracle is not None else ghost.python
    return (bill.units, bill.total)


@dataclass(frozen=True)
class HuntReport:
    """Result of a hunt. Ports no legacy unit; summarises checks against BILLING_PKG.p_gen_bill."""

    checked: int
    matched: int
    ghosts: tuple[Ghost, ...]

    @property
    def smallest(self) -> Ghost | None:
        """The ghost with the fewest units, then the lowest total; None when there are no ghosts."""
        if not self.ghosts:
            return None
        return min(self.ghosts, key=_size)


def hunt(port: Callable[[BillInput], Bill], cases: Iterable[GoldenCase]) -> HuntReport:
    """Run port on every case once and collect the ghosts.

    Ports no legacy unit; compares against BILLING_PKG.p_gen_bill (pkb lines 146-207)
    results. Exceptions raised by port are not caught.
    """
    items = tuple(cases)
    ghosts: list[Ghost] = []
    for case in items:
        python = port(case.input)
        diffs = diff(case.oracle, python)
        if diffs:
            ghosts.append(Ghost(case.input, case.oracle, python, diffs))
    return HuntReport(
        checked=len(items),
        matched=len(items) - len(ghosts),
        ghosts=tuple(ghosts),
    )
