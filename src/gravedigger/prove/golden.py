"""Golden snapshot of Oracle bills (golden/cases.json).

This module ports no legacy unit. It stores and loads the bills that
BILLING_PKG.p_gen_bill (pkb lines 146-207) produced in Oracle, so a candidate
port can be checked later with no database.

The file is one JSON array with one record per line. Money is always a JSON
string, never a float.
"""

from __future__ import annotations

import dataclasses
import decimal
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gravedigger.config import REPO_ROOT
from gravedigger.resurrected.billing import Bill, BillInput

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps the module driver-free
    import oracledb  # noqa: F401

GOLDEN_PATH: Path = REPO_ROOT / "golden" / "cases.json"

_INPUT_KEYS: tuple[str, ...] = tuple(f.name for f in dataclasses.fields(BillInput))
_BILL_KEYS: tuple[str, ...] = tuple(f.name for f in dataclasses.fields(Bill))

_DECIMAL_INPUTS = frozenset({"load_kw", "mf"})
_OPTIONAL_DECIMAL_INPUTS = frozenset({"fpa_rate"})
_INT_INPUTS = frozenset({"prev_rdg", "curr_rdg"})
_DATETIME_INPUTS = frozenset({"rdg_dt"})
_OPTIONAL_DATETIME_INPUTS = frozenset({"pay_dt"})


@dataclass(frozen=True)
class GoldenCase:
    """One input and the bill Oracle produced for it (None: no bill row).

    Ports no legacy unit; records BILLING_PKG.p_gen_bill (pkb lines 146-207).
    """

    input: BillInput
    oracle: Bill | None


# ---------------------------------------------------------------- saving


def _enc(value: Any) -> Any:
    """Encode one field value for JSON (Decimal text, ISO dates, ints, null)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _record(case: GoldenCase) -> dict[str, Any]:
    """Turn a case into a JSON-ready dict in dataclass field order."""
    inp = {k: _enc(getattr(case.input, k)) for k in _INPUT_KEYS}
    bill = (
        None
        if case.oracle is None
        else {k: _enc(getattr(case.oracle, k)) for k in _BILL_KEYS}
    )
    return {"input": inp, "oracle": bill}


def save_cases(path: Path, cases: Iterable[GoldenCase]) -> None:
    """Write cases as UTF-8 (no BOM, LF), one record per line.

    Ports no legacy unit; stores BILLING_PKG.p_gen_bill (pkb lines 146-207) results.
    """
    lines = [
        json.dumps(_record(c), separators=(",", ":"), ensure_ascii=True)
        for c in cases
    ]
    if lines:
        text = "[\n" + ",\n".join(lines) + "\n]\n"
    else:
        text = "[]\n"
    path.write_bytes(text.encode("utf-8"))


# ---------------------------------------------------------------- loading


def _dec(value: Any) -> Decimal:
    """Parse a finite Decimal from a JSON string."""
    if not isinstance(value, str):
        raise TypeError("not a decimal string")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("decimal is not finite")
    return result


def _int(value: Any) -> int:
    """Accept a real int (not bool)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("not an integer")
    return value


def _dt(value: Any) -> datetime:
    """Parse an ISO datetime string."""
    if not isinstance(value, str):
        raise TypeError("not an ISO datetime string")
    return datetime.fromisoformat(value)


def _dt_or_none(value: Any) -> datetime | None:
    """Parse an ISO datetime string or accept null."""
    return None if value is None else _dt(value)


def _dec_or_none(value: Any) -> Decimal | None:
    """Parse a finite Decimal string or accept null."""
    return None if value is None else _dec(value)


def _date(value: Any) -> date:
    """Parse an ISO date string."""
    if not isinstance(value, str):
        raise TypeError("not an ISO date string")
    return date.fromisoformat(value)


def _convert_input(obj: Any, where: str) -> BillInput:
    """Build a BillInput from a JSON object, naming the bad field on failure."""
    if not isinstance(obj, dict) or tuple(sorted(obj)) != tuple(sorted(_INPUT_KEYS)):
        raise ValueError(f"{where}: field 'input' must be an object with keys {list(_INPUT_KEYS)}")
    values: dict[str, Any] = {}
    for key in _INPUT_KEYS:
        raw = obj[key]
        field = f"{where}: field 'input.{key}'"
        try:
            if key in _DECIMAL_INPUTS:
                values[key] = _dec(raw)
            elif key in _OPTIONAL_DECIMAL_INPUTS:
                values[key] = _dec_or_none(raw)
            elif key in _INT_INPUTS:
                values[key] = _int(raw)
            elif key in _DATETIME_INPUTS:
                values[key] = _dt(raw)
            elif key in _OPTIONAL_DATETIME_INPUTS:
                values[key] = _dt_or_none(raw)
            else:  # tariff
                if not isinstance(raw, str):
                    raise TypeError("not a string")
                values[key] = raw
        except (ValueError, TypeError, KeyError, decimal.InvalidOperation) as exc:
            raise ValueError(f"{field} is invalid ({exc})") from exc
    return BillInput(**values)


def _convert_bill(obj: Any, where: str) -> Bill | None:
    """Build a Bill (or None) from a JSON value, naming the bad field on failure."""
    if obj is None:
        return None
    if not isinstance(obj, dict) or tuple(sorted(obj)) != tuple(sorted(_BILL_KEYS)):
        raise ValueError(f"{where}: field 'oracle' must be null or an object with keys {list(_BILL_KEYS)}")
    values: dict[str, Any] = {}
    for key in _BILL_KEYS:
        try:
            values[key] = _date(obj[key]) if key == "due_dt" else _dec(obj[key])
        except (ValueError, TypeError, KeyError, decimal.InvalidOperation) as exc:
            raise ValueError(f"{where}: field 'oracle.{key}' is invalid ({exc})") from exc
    return Bill(**values)


def load_cases(path: Path) -> tuple[GoldenCase, ...]:
    """Read a golden file and return its cases in file order.

    Ports no legacy unit; reads BILLING_PKG.p_gen_bill (pkb lines 146-207) results.
    A missing file raises FileNotFoundError. Any other problem raises
    ValueError naming the record index and field.
    """
    raw = path.read_bytes()  # FileNotFoundError propagates
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{path.name}: not valid UTF-8 JSON ({exc})") from exc
    if not isinstance(data, list):
        raise ValueError(f"{path.name}: top level must be a list")
    cases: list[GoldenCase] = []
    for index, record in enumerate(data):
        where = f"{path.name}: record {index}"
        if not isinstance(record, dict) or set(record) != {"input", "oracle"}:
            raise ValueError(f"{where}: must be an object with keys 'input' and 'oracle'")
        try:
            cases.append(
                GoldenCase(
                    _convert_input(record["input"], where),
                    _convert_bill(record["oracle"], where),
                )
            )
        except (KeyError, TypeError, decimal.InvalidOperation) as exc:
            raise ValueError(f"{where}: malformed record ({exc!r})") from exc
    return tuple(cases)


# ---------------------------------------------------------------- building


def build_golden(
    conn: "oracledb.Connection", inputs: Iterable[BillInput]
) -> tuple[GoldenCase, ...]:
    """Bill every input in Oracle, in order, and return the golden cases.

    Records BILLING_PKG.p_gen_bill (pkb lines 146-207) results. Calls
    run_oracle once per input; a None result (no bill row) is stored as
    oracle=None. The caller owns the connection: this function never opens,
    commits or reads settings. Any error propagates unchanged and no partial
    result is returned.
    """
    from gravedigger.prove.oracle_runner import run_oracle

    cases: list[GoldenCase] = []
    for b in inputs:
        cases.append(GoldenCase(b, run_oracle(conn, b)))
    return tuple(cases)
