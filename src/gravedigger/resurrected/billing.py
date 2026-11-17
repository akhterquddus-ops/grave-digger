"""Python port of the legacy BILLING_PKG (see .kiro/specs/resurrect-billing)."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

_TWO_PLACES = Decimal("0.01")
_ZERO_PLACES = Decimal("1")


def _round(value: Decimal, quantum: Decimal) -> Decimal:
    """Oracle ROUND(value, n): quantize with ROUND_HALF_UP (halves away from zero)."""
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


@dataclasses.dataclass(frozen=True)
class BillInput:
    """Inputs to one bill, after the database reads at pkb lines 162-183."""

    tariff: str
    load_kw: Decimal
    prev_rdg: int
    curr_rdg: int
    mf: Decimal
    rdg_dt: datetime
    fpa_rate: Decimal | None
    pay_dt: datetime | None


@dataclasses.dataclass(frozen=True)
class Bill:
    """One BILL_HDR row without cust_no, bill_mon and gen_dt."""

    units: Decimal
    enrg: Decimal
    fix: Decimal
    fpa: Decimal
    ed: Decimal
    gst: Decimal
    tv: Decimal
    lps: Decimal
    total: Decimal
    due_dt: date


def units(prev: Decimal | int, curr: Decimal | int, mf: Decimal) -> Decimal:
    """Ports BILLING_PKG.f_units (pkb lines 18-31).

    Units consumed from two meter readings, times the multiplying factor.
    No rounding is applied.

    LEGACY QUIRK: (pkb lines 21-24) when curr < prev the meter is assumed to
    have rolled over a 5-digit dial, so units = (99999 - prev + curr + 1) * mf.
    The rollover is assumed even if the drop is really a wrong reading.

    The debug output at pkb lines 27-29 (g_dbg) is not ported.
    """
    if curr < prev:
        return (Decimal(99999) - prev + curr + 1) * mf
    return (Decimal(curr) - prev) * mf


def energy_charge(tariff: str, units: Decimal) -> Decimal:
    """Ports BILLING_PKG.f_enrg_chg (pkb lines 38-65).

    Energy charge for the units billed.
    A1 (telescopic, strict ``>`` boundaries): up to 100 units at 10 each;
    up to 200: 1000 + (u - 100) * 13; up to 300: 2300 + (u - 200) * 16;
    above 300: u * 22.
    A2 (flat): u * 25. Any other tariff gives 0 and does not raise
    (pkb line 59 ELSE branch).

    LEGACY QUIRK: (pkb lines 43-44) above 300 units the WHOLE consumption is
    charged at 22, not just the units past 300, so the bill jumps at the
    301st unit (slab cliff).

    Rounded once, at the single return (pkb line 64), to 2 places.
    The debug output (g_dbg) is not ported.
    """
    if tariff == "A1":
        if units > 300:
            charge = units * 22
        elif units > 200:
            charge = Decimal(100 * 10 + 100 * 13) + (units - 200) * 16
        elif units > 100:
            charge = Decimal(100 * 10) + (units - 100) * 13
        else:
            charge = units * 10
    elif tariff == "A2":
        charge = units * 25
    else:
        charge = Decimal("0")
    return _round(Decimal(charge), _TWO_PLACES)


def fixed_charge(tariff: str, load_kw: Decimal, enrg: Decimal) -> Decimal:
    """Ports BILLING_PKG.f_fix_chg (pkb lines 72-88).

    Fixed charge. A2: 400 per sanctioned kW. A1: a top-up to a minimum bill
    of 75 when the energy charge is below 75, else 0. Any other tariff gives 0
    (no ELSE branch, v_fix keeps its initial 0 from line 73).
    No rounding is applied.

    LEGACY QUIRK: (pkb lines 79-80) the A1 "fixed charge" is really a minimum
    charge: 75 - enrg when enrg < 75, otherwise 0. The comparison is strict,
    so enrg == 75 gives 0.

    The debug output at pkb lines 84-86 (g_dbg) is not ported.
    """
    if tariff == "A2":
        return 400 * load_kw
    if tariff == "A1":
        if enrg < 75:
            return 75 - enrg
        return Decimal("0")
    return Decimal("0")


def fpa(units: Decimal, rate: Decimal | None) -> Decimal:
    """Ports BILLING_PKG.f_fpa (pkb lines 93-102).

    Fuel price adjustment: units times the monthly rate per kWh, rounded to
    2 places (pkb line 97). The rate lookup (FPA_RT by bill month) is done by
    the caller; ``rate`` is None when no row exists for the month.

    LEGACY QUIRK: (pkb lines 99-101) when no rate is loaded for the month the
    legacy NO_DATA_FOUND handler returns 0, so the customer is billed without
    FPA instead of raising an error.
    """
    if rate is None:
        # Mirrors the legacy NO_DATA_FOUND handler (pkb lines 99-101): return 0.
        return Decimal("0")
    return _round(units * rate, _TWO_PLACES)


def taxes(enrg: Decimal, fix: Decimal, fpa: Decimal) -> tuple[Decimal, Decimal]:
    """Ports BILLING_PKG.p_taxes (pkb lines 108-113).

    Returns ``(ed, gst)``. Electricity duty is 1.5% of the energy charge,
    rounded to 2 places (pkb line 111). GST is 17% of energy + fixed + FPA +
    the already-rounded duty, rounded to 2 places (pkb line 112).

    LEGACY QUIRK: tax on tax (pkb comment lines 105-106 and line 112). The GST
    base includes the electricity duty, so duty is itself taxed.
    """
    ed = _round(enrg * Decimal("0.015"), _TWO_PLACES)
    gst = _round((enrg + fix + fpa + ed) * Decimal("0.17"), _TWO_PLACES)
    return ed, gst


def due_date(rdg_dt: datetime) -> date:
    """Ports BILLING_PKG.f_due_dt (pkb lines 118-126).

    Due date is the reading date plus 14 days. The time part of the reading
    is dropped (TRUNC, pkb line 121). The weekday test uses ``weekday()``
    (Sunday == 6), which does not depend on locale, matching the legacy
    NLS_DATE_LANGUAGE=ENGLISH check of 'SUN'.

    LEGACY QUIRK: (pkb lines 122-124) when the due date falls on a Sunday it
    is moved forward one day to Monday.
    """
    d = rdg_dt.date() + timedelta(days=14)
    if d.weekday() == 6:
        d = d + timedelta(days=1)
    return d


def lps(enrg: Decimal, due_dt: date, pay_dt: datetime | None) -> Decimal:
    """Ports BILLING_PKG.f_lps (pkb lines 131-141).

    Late payment surcharge: 10% of the energy charge, rounded to 2 places
    (pkb line 137), when the payment date is later than the due date.
    No payment date (NULL) gives 0 (pkb lines 133-135).

    LEGACY QUIRK: (pkb line 136) the comparison keeps the time of day of the
    payment. The due date is a plain date (midnight), so a payment made on the
    due date itself at any time after 00:00:00 counts as late. Only a payment
    at exactly midnight on the due date, or earlier, is on time.

    LEGACY QUIRK: (pkb line 137) the base is the energy charge only. Fixed
    charge, FPA and taxes are not surcharged.
    """
    if pay_dt is None:
        return Decimal("0")
    if pay_dt > datetime.combine(due_dt, time.min):
        return _round(enrg * Decimal("0.10"), _TWO_PLACES)
    return Decimal("0")


def generate_bill(inp: BillInput) -> Bill:
    """Ports BILLING_PKG.p_gen_bill (pkb lines 146-207).

    Builds one bill by chaining the unit functions in the legacy order
    (pkb lines 170-185): units, energy charge, fixed charge, FPA, taxes,
    due date, surcharge. Then adds the TV fee (35 for tariff A1, else 60,
    pkb lines 187-191) and the total (pkb line 193).

    Deliberate differences from the legacy procedure:
    - No database access. The reads of CUST_MST, MTR_RDG, PYMT and FPA_RT
      (pkb lines 162-183) are done by the caller and arrive in ``inp``.
      The BILL_HDR insert (pkb line 195) and the debug output are not ported.
    - The legacy ``WHEN OTHERS THEN NULL`` handler (pkb lines 205-206) is not
      reproduced. This function has no try block and does not catch
      exceptions raised by its inputs.

    Autopsy risk: the legacy handler swallows every error. For example,
    customer 1006 has no meter reading, so the SELECT at pkb lines 165-168
    raises NO_DATA_FOUND, the handler hides it, and no bill row is written
    and nobody is told.

    LEGACY QUIRK: (pkb line 187, comment at line 186) the TV fee is not taxed.
    It is added to the total but is not part of the GST base.

    LEGACY QUIRK: (pkb line 193) the total is rounded to 0 decimal places,
    half up, so a sum of 9048.50 gives 9049.
    """
    n_unt = units(inp.prev_rdg, inp.curr_rdg, inp.mf)
    v_enrg = energy_charge(inp.tariff, n_unt)
    v_fix = fixed_charge(inp.tariff, inp.load_kw, v_enrg)
    v_fpa = fpa(n_unt, inp.fpa_rate)
    v_ed, v_gst = taxes(v_enrg, v_fix, v_fpa)
    d_due = due_date(inp.rdg_dt)
    v_lps = lps(v_enrg, d_due, inp.pay_dt)
    v_tv = Decimal("35") if inp.tariff == "A1" else Decimal("60")
    n_tot = _round(v_enrg + v_fix + v_fpa + v_ed + v_gst + v_tv + v_lps, _ZERO_PLACES)
    return Bill(n_unt, v_enrg, v_fix, v_fpa, v_ed, v_gst, v_tv, v_lps, n_tot, d_due)
