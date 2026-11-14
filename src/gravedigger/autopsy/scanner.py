"""Autopsy scanner: plain facts about one unit of a package."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from gravedigger.autopsy.blocks import Block, find_blocks
from gravedigger.autopsy.tokenizer import column_of, line_of, line_starts, mask, string_literals
from gravedigger.exhume import Unit

_ID = r"[A-Za-z_][A-Za-z0-9_$#]*"
_NOT_ID_BEFORE = r"(?<![A-Za-z0-9_$#])"
_NOT_ID_AFTER = r"(?![A-Za-z0-9_$#])"
_TABLE = r"((?:" + _ID + r"\s*\.\s*)?(" + _ID + r"))"

_NUMBER = re.compile(
    _NOT_ID_BEFORE + r"(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?" + _NOT_ID_AFTER
)
_WRITE_PATTERNS = (
    re.compile(_NOT_ID_BEFORE + r"INSERT\s+INTO\s+" + _TABLE, re.IGNORECASE),
    re.compile(_NOT_ID_BEFORE + r"UPDATE\s+" + _TABLE, re.IGNORECASE),
    re.compile(_NOT_ID_BEFORE + r"DELETE\s+(?:FROM\s+)?" + _TABLE, re.IGNORECASE),
)
_READ_PATTERN = re.compile(_NOT_ID_BEFORE + r"(?:FROM|JOIN)\s+" + _TABLE, re.IGNORECASE)
_FOR_BEFORE = re.compile(_NOT_ID_BEFORE + r"FOR\s+$", re.IGNORECASE)
_BRANCH = re.compile(
    _NOT_ID_BEFORE + r"(END\s+IF|ELSIF|IF)" + _NOT_ID_AFTER, re.IGNORECASE
)
_WHEN = re.compile(
    _NOT_ID_BEFORE + r"WHEN" + _NOT_ID_AFTER + r"([^;]*?)" + _NOT_ID_BEFORE + r"THEN" + _NOT_ID_AFTER,
    re.IGNORECASE,
)
_OR = re.compile(_NOT_ID_BEFORE + r"OR" + _NOT_ID_AFTER, re.IGNORECASE)
_NULL_BODY = re.compile(r"NULL\s*;", re.IGNORECASE)


@dataclass(frozen=True)
class Constant:
    """A numeric literal found in live code."""

    value: Decimal
    line: int  # 1-based line of the package body file
    col: int  # 1-based column in that line


@dataclass(frozen=True)
class Facts:
    """Plain facts about one unit."""

    constants: tuple[Constant, ...]
    string_literals: frozenset[str]
    tables_read: frozenset[str]
    tables_written: frozenset[str]
    calls: frozenset[str]
    branches: int
    exceptions_handled: frozenset[str]
    swallows_errors: bool
    globals_used: frozenset[str]


def _masked_with_lines(unit: Unit) -> tuple[str, tuple[int, ...]]:
    return mask(unit.source), line_starts(unit.source)


def find_constants(masked: str, starts: tuple[int, ...], first_line: int) -> tuple[Constant, ...]:
    """Numeric literals in masked text, ordered by position."""
    return tuple(
        Constant(
            Decimal(m.group()),
            first_line + line_of(starts, m.start()) - 1,
            column_of(starts, m.start()),
        )
        for m in _NUMBER.finditer(masked)
    )


def find_tables(masked: str) -> tuple[frozenset[str], frozenset[str]]:
    """Return (tables read, tables written), upper-case, schema prefix dropped."""
    written: set[str] = set()
    claimed: set[int] = set()
    for pattern in _WRITE_PATTERNS:
        for m in pattern.finditer(masked):
            if pattern is _WRITE_PATTERNS[1] and _FOR_BEFORE.search(masked[: m.start()]):
                continue  # FOR UPDATE locks rows, it writes nothing
            written.add(m.group(2).upper())
            claimed.add(m.start(1))
    read = {
        m.group(2).upper()
        for m in _READ_PATTERN.finditer(masked)
        if m.start(1) not in claimed
    }
    return frozenset(read), frozenset(written)


def whole_word(name: str) -> re.Pattern[str]:
    """Pattern matching ``name`` as a whole word, ignoring letter case."""
    return re.compile(_NOT_ID_BEFORE + re.escape(name) + _NOT_ID_AFTER, re.IGNORECASE)


def find_name_uses(masked: str, names: Iterable[str]) -> frozenset[str]:
    """Lower-case names that appear as whole words in masked text."""
    return frozenset(n.lower() for n in names if whole_word(n).search(masked))


def count_branches(masked: str) -> int:
    """Count IF and ELSIF (END IF does not count)."""
    return sum(1 for m in _BRANCH.finditer(masked) if not m.group(1).upper().startswith("END"))


def _innermost(blocks: tuple[Block, ...], pos: int) -> Block | None:
    best: Block | None = None
    for b in blocks:
        if b.start <= pos and (b.end is None or pos < b.end):
            if best is None or b.start > best.start:
                best = b
    return best


def find_handlers(masked: str, blocks: tuple[Block, ...]) -> tuple[frozenset[str], bool]:
    """Return (handled exception names, whether an OTHERS handler only does NULL;)."""
    clauses: list[tuple[int, str, int, Block]] = []
    for m in _WHEN.finditer(masked):
        owner = _innermost(blocks, m.start())
        if owner is None or owner.exception_pos is None or owner.exception_pos > m.start():
            continue
        clauses.append((m.start(), m.group(1), m.end(), owner))
    handled: set[str] = set()
    swallows = False
    for i, (_, cond, then_end, owner) in enumerate(clauses):
        names = {re.sub(r"\s+", "", n).upper() for n in _OR.split(cond)} - {""}
        handled |= names
        stop = owner.end if owner.end is not None else len(masked)
        for pos, _, _, other in clauses[i + 1:]:
            if other is owner:
                stop = pos
                break
        if "OTHERS" in names and _NULL_BODY.fullmatch(masked[then_end:stop].strip()):
            swallows = True
    return frozenset(handled), swallows


def scan(unit: Unit) -> Facts:
    """Scan one unit. Pure: no I/O, no network."""
    masked, starts = _masked_with_lines(unit)
    read, written = find_tables(masked)
    handled, swallows = find_handlers(masked, find_blocks(masked))
    return Facts(
        constants=find_constants(masked, starts, unit.start_line),
        string_literals=frozenset(string_literals(unit.source)),
        tables_read=read,
        tables_written=written,
        calls=find_name_uses(masked, (n for n in unit.sibling_names if n != unit.name)),
        branches=count_branches(masked),
        exceptions_handled=handled,
        swallows_errors=swallows,
        globals_used=find_name_uses(masked, unit.global_names),
    )
