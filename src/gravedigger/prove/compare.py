"""Field-by-field comparison of the Oracle bill and the Python bill.

Checks the Port against BILLING_PKG.p_gen_bill. Any difference is a "ghost".
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from gravedigger.resurrected.billing import Bill


@dataclass(frozen=True)
class FieldDiff:
    """One field where the Oracle bill (BILLING_PKG.p_gen_bill) and the Python bill disagree."""

    field: str
    oracle: Decimal | date | None
    python: Decimal | date | Bill


def diff(oracle: Bill | None, python: Bill) -> tuple[FieldDiff, ...]:
    """Compare a bill from BILLING_PKG.p_gen_bill with the Port's bill, exactly.

    Returns () when every field is equal. Fields are visited in Bill declaration
    order and compared with != (exact Decimal equality, no tolerance; trailing
    zeros do not matter). If Oracle wrote no BILL_HDR row (oracle is None), the
    result is a single FieldDiff named "bill".
    """
    if oracle is None:
        return (FieldDiff("bill", None, python),)
    return tuple(
        FieldDiff(f.name, getattr(oracle, f.name), getattr(python, f.name))
        for f in dataclasses.fields(Bill)
        if getattr(oracle, f.name) != getattr(python, f.name)
    )
