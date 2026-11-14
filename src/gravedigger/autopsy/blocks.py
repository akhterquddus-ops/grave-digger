"""Block walker: find nested PL/SQL blocks in masked text.

Not a full parser. It is enough to find top-level units, their closing END,
and the exception handler sections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

BlockKind = Literal["function", "procedure", "begin", "declare", "if", "loop", "case"]

_WORD = re.compile(r"(?<![A-Za-z0-9_$#])[A-Za-z_][A-Za-z0-9_$#]*")
_END_TAIL = re.compile(r"\s*(IF|LOOP|CASE)(?![A-Za-z0-9_$#])", re.IGNORECASE)
_SUBPROGRAMS = ("function", "procedure")


@dataclass(frozen=True)
class Block:
    """One block of PL/SQL code."""

    kind: BlockKind
    name: str | None  # lower-case subprogram name, else None
    depth: int  # number of enclosing blocks; 0 = top level
    start: int  # offset of the opening keyword
    header_end: int | None  # offset of IS/AS for subprograms, else None
    end: int | None  # offset of the closing END keyword; None if never closed
    exception_pos: int | None  # offset of this block's own EXCEPTION keyword


class _Open:
    """Mutable block under construction."""

    def __init__(self, kind: BlockKind, name: str | None, depth: int, start: int,
                 header_end: int | None, begun: bool) -> None:
        self.kind = kind
        self.name = name
        self.depth = depth
        self.start = start
        self.header_end = header_end
        self.begun = begun
        self.end: int | None = None
        self.exception_pos: int | None = None

    def freeze(self) -> Block:
        return Block(self.kind, self.name, self.depth, self.start, self.header_end,
                     self.end, self.exception_pos)


def _scan_header(masked: str, pos: int) -> tuple[int | None, int]:
    """Look from ``pos`` for IS/AS at parenthesis depth 0.

    Returns (offset of IS/AS or None, offset to resume at). None means a
    forward declaration (a ``;`` came first) or no header end at all.
    """
    depth = 0
    n = len(masked)
    i = pos
    while i < n:
        ch = masked[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ";" and depth <= 0:
            return None, i + 1
        else:
            m = _WORD.match(masked, i)
            if m:
                if depth <= 0 and m.group().upper() in ("IS", "AS"):
                    return m.start(), m.end()
                i = m.end()
                continue
        i += 1
    return None, n


def find_blocks(masked: str) -> tuple[Block, ...]:
    """Return all blocks of ``masked`` text, in opening order."""
    opened: list[_Open] = []
    stack: list[_Open] = []
    words = list(_WORD.finditer(masked))
    skip_until = 0
    for idx, m in enumerate(words):
        if m.start() < skip_until:
            continue
        word = m.group().upper()
        if word in ("FUNCTION", "PROCEDURE"):
            name_m = words[idx + 1] if idx + 1 < len(words) else None
            header_end, resume = _scan_header(masked, m.end())
            skip_until = resume
            if header_end is None:
                continue  # forward declaration: opens no block
            name = name_m.group().lower() if name_m else None
            blk = _Open(word.lower(), name, len(stack), m.start(), header_end, False)  # type: ignore[arg-type]
            opened.append(blk)
            stack.append(blk)
        elif word == "DECLARE":
            blk = _Open("declare", None, len(stack), m.start(), None, False)
            opened.append(blk)
            stack.append(blk)
        elif word == "BEGIN":
            top = stack[-1] if stack else None
            if top is not None and top.kind in ("function", "procedure", "declare") and not top.begun:
                top.begun = True
            else:
                blk = _Open("begin", None, len(stack), m.start(), None, True)
                opened.append(blk)
                stack.append(blk)
        elif word in ("IF", "LOOP", "CASE"):
            blk = _Open(word.lower(), None, len(stack), m.start(), None, False)  # type: ignore[arg-type]
            opened.append(blk)
            stack.append(blk)
        elif word == "EXCEPTION":
            if stack and stack[-1].begun and stack[-1].exception_pos is None:
                stack[-1].exception_pos = m.start()
        elif word == "END":
            tail = _END_TAIL.match(masked, m.end())
            if tail:
                skip_until = tail.end()
            if stack:
                stack.pop().end = m.start()
    return tuple(b.freeze() for b in opened)
