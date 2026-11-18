"""A DELIBERATELY wrong draft of the billing port, used to hunt a ghost.

This module is wrong on purpose. Python's built-in round() rounds half to
even (banker's rounding), while Oracle ROUND rounds half up (halves away
from zero). The draft takes the correct port and replaces only the final
total rounding, so the two disagree on exact halves.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

from gravedigger.resurrected import billing
from gravedigger.resurrected.billing import Bill, BillInput


def generate_bill(inp: BillInput) -> Bill:
    """Draft of BILLING_PKG.p_gen_bill (pkb line 193) with round() on the total.

    The total uses Python's built-in round(), which is wrong on purpose:
    it rounds half to even, but Oracle ROUND rounds half up. Example: a sum
    of 9048.50 gives 9048 in the draft and 9049 in Oracle.
    """
    port = billing.generate_bill(inp)
    pre = port.enrg + port.fix + port.fpa + port.ed + port.gst + port.tv + port.lps
    # DELIBERATE DEFECT: built-in round() is half-to-even, not Oracle half-up.
    total = Decimal(str(round(pre)))
    return dataclasses.replace(port, total=total)
