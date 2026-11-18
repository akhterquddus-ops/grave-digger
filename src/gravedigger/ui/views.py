"""Pure view logic for the Grave Digger demo app.

This module imports no ``streamlit``. It holds the data, text and formatting
logic that the thin page in ``app/streamlit_app.py`` lays out.
"""

from __future__ import annotations

import html
import inspect
import re
import textwrap
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from gravedigger import config
from gravedigger.autopsy.explain import Explanation, Rule, explain
from gravedigger.autopsy.graph import EDGE_STYLES, THEME, build_graph, to_dot
from gravedigger.autopsy.scanner import scan
from gravedigger.exhume import Package, Unit, load_package
from gravedigger.prove.golden import GoldenCase, load_cases
from gravedigger.prove.hunt import Ghost, HuntReport, hunt
from gravedigger.resurrected import billing, billing_draft
from gravedigger.resurrected.billing import Bill, BillInput

GHOST_COLUMNS: tuple[str, ...] = (
    "Tariff",
    "Units",
    "Oracle total",
    "Python total",
    "Difference",
)
TARIFF_LABELS: Mapping[str, str] = MappingProxyType(
    {"A1": "A1 (home)", "A2": "A2 (shop)"}
)
NO_BILL: str = "no bill"
STATIC_NOTE: str = "Showing rules found by the scanner only (no cached AI autopsy)"
TAGLINE: str = "Legacy billing code never dies. It just haunts you."
CI_BADGE_URL: str = (
    "https://github.com/akhterquddus-ops/grave-digger/actions/workflows/prove.yml/badge.svg"
)
CI_WORKFLOW_URL: str = (
    "https://github.com/akhterquddus-ops/grave-digger/actions/workflows/prove.yml"
)

PORT_OF: Mapping[str, str] = MappingProxyType(
    {
        "f_units": "units",
        "f_enrg_chg": "energy_charge",
        "f_fix_chg": "fixed_charge",
        "f_fpa": "fpa",
        "p_taxes": "taxes",
        "f_due_dt": "due_date",
        "f_lps": "lps",
        "p_gen_bill": "generate_bill",
    }
)

_TWO_PLACES = Decimal("0.01")
_MARKERS: tuple[str, ...] = (
    "legacy/billing_pkg.pkb",
    "golden/autopsy",
    "golden/cases.json",
)


def rs(amount: Decimal) -> str:
    """Format a money amount for people, e.g. ``Rs 12,599`` or ``-Rs 1``.

    Ports no legacy unit. Rounds half up like Oracle ROUND(x, 2); whole
    amounts print without decimals. Raises ``TypeError`` for non-Decimal.
    """
    if not isinstance(amount, Decimal):
        raise TypeError(f"rs() needs a Decimal, got {type(amount).__name__}")
    quantized = amount.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    negative = quantized < 0
    magnitude = abs(quantized)
    if magnitude == magnitude.to_integral_value():
        text = f"{magnitude:,.0f}"
    else:
        text = f"{magnitude:,.2f}"
    return ("-Rs " if negative else "Rs ") + text


def _has_markers(root: Path) -> bool:
    return all((root / marker).exists() for marker in _MARKERS)


@lru_cache(maxsize=None)
def repo_root() -> Path:
    """Return the folder holding legacy/ and golden/. Ports no legacy unit.

    Tries ``config.REPO_ROOT`` first, then the working directory and its
    parents. Raises ``FileNotFoundError`` if none holds the data files.
    """
    candidates = (config.REPO_ROOT, Path.cwd(), *Path.cwd().parents)
    for candidate in candidates:
        if _has_markers(candidate):
            return candidate
    raise FileNotFoundError(
        "The graveyard files (legacy/ and golden/) were not found. "
        "Run the app from the repository folder."
    )


@lru_cache(maxsize=None)
def _package() -> Package:
    """Load the legacy package from legacy/. Ports no legacy unit."""
    legacy = repo_root() / "legacy"
    spec_text = (legacy / "billing_pkg.pks").read_text(encoding="utf-8")
    body_text = (legacy / "billing_pkg.pkb").read_text(encoding="utf-8")
    return load_package(spec_text, body_text)


def load_units() -> tuple[Unit, ...]:
    """Return the eight BILLING_PKG units in package order."""
    return _package().units


@lru_cache(maxsize=None)
def _unit_order() -> tuple[str, ...]:
    """Unit names in package order. Ports no legacy unit."""
    return tuple(u.name for u in load_units())


def __getattr__(name: str) -> tuple[str, ...]:
    """Module attribute hook (PEP 562): ``UNIT_ORDER`` is derived lazily.

    Keeps ``from gravedigger.ui.views import UNIT_ORDER`` working while
    importing this module reads no file.
    """
    if name == "UNIT_ORDER":
        return _unit_order()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _unknown_unit(name: str) -> KeyError:
    known = ", ".join(PORT_OF)
    return KeyError(f"Unknown unit '{name}'. Known units: {known}")


def legacy_source(unit_name: str) -> str:
    """Return the PL/SQL text of one BILLING_PKG unit (FUNCTION/PROCEDURE to END)."""
    if unit_name not in PORT_OF:
        raise _unknown_unit(unit_name)
    for unit in load_units():
        if unit.name == unit_name:
            return unit.source
    raise _unknown_unit(unit_name)


def python_source(unit_name: str) -> str:
    """Return the source of the Python port of one BILLING_PKG unit.

    Includes the docstring (which names the legacy unit and line range).
    """
    if unit_name not in PORT_OF:
        raise _unknown_unit(unit_name)
    func_name = PORT_OF[unit_name]
    text = textwrap.dedent(inspect.getsource(getattr(billing, func_name))).rstrip("\n")
    if not text.startswith(f"def {func_name}("):
        raise ValueError(
            f"Source of the port of {unit_name!r} does not start with "
            f"'def {func_name}('."
        )
    return text


def build_autopsy_cards(cache_dir: Path) -> tuple[Explanation, ...]:
    """Explain every unit of BILLING_PKG, without any LLM client.

    Ports no legacy unit. ``client=None`` is literal: a unit with a cache file
    in ``cache_dir`` gets the cached rules, any other gets the static scan.
    """
    return tuple(
        explain(u, scan(u), client=None, cache_dir=cache_dir) for u in load_units()
    )


@lru_cache(maxsize=None)
def autopsy_cards() -> tuple[Explanation, ...]:
    """Cached autopsy cards from ``golden/autopsy``. Ports no legacy unit."""
    return build_autopsy_cards(repo_root() / "golden" / "autopsy")


@lru_cache(maxsize=None)
def _golden_cases() -> tuple[GoldenCase, ...]:
    """The single loader of ``golden/cases.json``. Ports no legacy unit."""
    return load_cases(repo_root() / "golden" / "cases.json")


_PORTS: Mapping[str, Callable[[BillInput], Bill]] = MappingProxyType(
    {"port": billing.generate_bill, "draft": billing_draft.generate_bill}
)


@lru_cache(maxsize=None)
def run_hunt(which: str) -> HuntReport:
    """Hunt for ghosts by billing every golden case with a Python port.

    Compares against BILLING_PKG.p_gen_bill results stored in the golden
    file; no Oracle connection is made. ``which`` is "port" or "draft";
    anything else raises ``ValueError``.
    """
    if which not in _PORTS:
        raise ValueError(f"Unknown hunt '{which}'. Choose 'port' or 'draft'.")
    return hunt(_PORTS[which], _golden_cases())


@lru_cache(maxsize=None)
def graph_dot() -> str:
    """Graphviz DOT text of the package dependency graph. Ports no legacy unit."""
    return to_dot(build_graph(_package()))


GRAPH_LEGEND: tuple[tuple[str, str, str], ...] = (
    (
        "calls",
        EDGE_STYLES["calls"].color,
        "One step of the bill asks another step to do part of the work.",
    ),
    (
        "reads",
        EDGE_STYLES["reads"].color,
        "Looks up information in a table.",
    ),
    (
        "writes",
        EDGE_STYLES["writes"].color,
        "Saves information into a table.",
    ),
    (
        "uses",
        EDGE_STYLES["uses"].color,
        "Uses a setting shared by the whole package.",
    ),
    (
        "hides errors",
        THEME.red,
        "Swallows every failure, so a problem is never reported.",
    ),
)


@dataclass(frozen=True)
class Headline:
    """The three big numbers at the top of the page."""

    units_raised: int
    rules_found: int
    bills_proven: int


@lru_cache(maxsize=None)
def headline() -> Headline:
    """Count units, rules and stored Oracle bills. Ports no legacy unit."""
    return Headline(
        units_raised=len(load_units()),
        rules_found=sum(len(card.rules) for card in autopsy_cards()),
        bills_proven=len(_golden_cases()),
    )


def _ghost_size(ghost: Ghost) -> tuple[Decimal, Decimal]:
    """Sort key: (units, total) of the Oracle bill, else the Python bill.

    Same key as ``hunt._size``, repeated so the private name is not imported.
    """
    bill = ghost.oracle if ghost.oracle is not None else ghost.python
    return (bill.units, bill.total)


def ghost_table(report: HuntReport, limit: int = 20) -> list[dict[str, str]]:
    """Rows for the ghost table, smallest ghosts first. Ports no legacy unit.

    Every value is text. The Difference is Python minus Oracle, or "n/a"
    when Oracle wrote no bill. At most ``max(limit, 0)`` rows are returned.
    """
    ordered = sorted(report.ghosts, key=_ghost_size)[: max(limit, 0)]
    rows: list[dict[str, str]] = []
    for ghost in ordered:
        shown = ghost.oracle if ghost.oracle is not None else ghost.python
        tariff = ghost.input.tariff
        if ghost.oracle is None:
            oracle_total = NO_BILL
            difference = "n/a"
        else:
            oracle_total = rs(ghost.oracle.total)
            difference = rs(ghost.python.total - ghost.oracle.total)
        values = (
            TARIFF_LABELS.get(tariff, tariff),
            format(shown.units.normalize(), ",f"),
            oracle_total,
            rs(ghost.python.total),
            difference,
        )
        rows.append(dict(zip(GHOST_COLUMNS, values)))
    return rows


def hunt_headline(report: HuntReport) -> str:
    """One plain sentence stating the result of a hunt. Ports no legacy unit.

    The ghost count is written without a thousands separator on purpose.
    """
    n = len(report.ghosts)
    if n == 0:
        return f"No ghosts. All {report.checked:,} bills match Oracle to the paisa."
    plural = "s" if n != 1 else ""
    return (
        f"{n} ghost{plural} found. {report.matched:,} of {report.checked:,} "
        f"bills match Oracle, but these {n} do not."
    )


_FIELD_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "units": "units used",
        "enrg": "energy charge",
        "fix": "fixed charge",
        "fpa": "fuel price adjustment",
        "ed": "electricity duty",
        "gst": "tax (GST)",
        "tv": "TV fee",
        "lps": "late payment surcharge",
        "total": "total",
        "due_dt": "due date",
    }
)


def _before_rounding(bill: Bill) -> Decimal:
    """Sum of the seven parts before the final rounding (mirrors pkb line 193)."""
    return bill.enrg + bill.fix + bill.fpa + bill.ed + bill.gst + bill.tv + bill.lps


def _half_rupee_pre_total(ghost: Ghost) -> Decimal | None:
    """Return the unrounded total when the only gap is a half-rupee rounding tie."""
    oracle = ghost.oracle
    if oracle is None or tuple(d.field for d in ghost.diffs) != ("total",):
        return None
    pre = _before_rounding(oracle)
    if pre - pre.to_integral_value(rounding=ROUND_FLOOR) != Decimal("0.5"):
        return None
    if oracle.total != pre.quantize(Decimal("1"), rounding=ROUND_HALF_UP):
        return None
    return pre


def _show_value(field: str, value: object) -> str:
    if value is None:
        return NO_BILL
    if field == "units" and isinstance(value, Decimal):
        return format(value.normalize(), ",f")
    if isinstance(value, Decimal):
        return rs(value)
    return str(value.isoformat() if hasattr(value, "isoformat") else value)


def explain_ghost(ghost: Ghost) -> str:
    """Explain in plain English why Oracle and Python disagree on one input.

    Ports no legacy unit; reads the difference against BILLING_PKG.p_gen_bill.
    """
    if ghost.oracle is None:
        return (
            f"Oracle wrote no bill for this customer, but the Python code "
            f"produced one of {rs(ghost.python.total)}. The old system hides "
            f"its errors, so a bill that fails is usually skipped in silence. "
            f"Python has no such habit."
        )
    pre = _half_rupee_pre_total(ghost)
    if pre is not None:
        return (
            f"Both systems add this bill up to {rs(pre)} before rounding to a "
            f"whole rupee. That is exactly half a rupee, so the answer depends "
            f"on the rounding rule. Oracle rounds a half up and bills "
            f"{rs(ghost.oracle.total)}. The Python side used round(), which "
            f"rounds a half to the nearest even number, and bills "
            f"{rs(ghost.python.total)}. That one-rupee gap is the ghost."
        )
    parts = []
    for d in ghost.diffs:
        label = _FIELD_LABELS.get(d.field, d.field)
        parts.append(
            f"{label} ({_show_value(d.field, d.oracle)} against "
            f"{_show_value(d.field, d.python)})"
        )
    text = "Oracle and Python disagree on: " + "; ".join(parts) + "."
    if tuple(d.field for d in ghost.diffs) == ("total",):
        text += " The two systems add the same parts and round the sum differently."
    return text

_MD_SPECIALS = frozenset("\\`*_~$[]<>")
_HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")


def md_escape(text: str) -> str:
    """Backslash-escape the Markdown specials in ``text``. Ports no legacy unit."""
    return "".join("\\" + ch if ch in _MD_SPECIALS else ch for ch in text)


def pill_html(text: str, colour: str) -> str:
    """Return a coloured pill as fixed-template HTML. Ports no legacy unit.

    ``colour`` must look like ``#rrggbb``, else ``ValueError``. ``text`` is
    HTML-escaped.
    """
    if not _HEX_COLOUR.fullmatch(colour):
        raise ValueError(f"Colour must look like '#rrggbb', got {colour!r}")
    return (
        f'<span style="background:{colour};color:#1a1423;padding:0.1rem 0.6rem;'
        f'border-radius:0.8rem;font-weight:600">{html.escape(text)}</span>'
    )


def category_colour(category: str) -> str:
    """Pick the pill colour of a rule category. Ports no legacy unit."""
    if category == "error":
        return THEME.red
    if category in ("tax", "surcharge"):
        return THEME.amber
    if category == "data":
        return THEME.teal
    return THEME.purple


def citation(rule: Rule) -> str:
    """Name the code lines a rule cites, e.g. ``Code lines 49, 50``."""
    lines = sorted(rule.lines)
    word = "line" if len(lines) == 1 else "lines"
    return f"Code {word} " + ", ".join(str(n) for n in lines)
