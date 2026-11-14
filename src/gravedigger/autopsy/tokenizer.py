"""Tokenizer: find comments and string literals in PL/SQL text.

Masking blanks them out while keeping every character offset and every
newline, so a match position in masked text is also a position in the original.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Literal

SegmentKind = Literal["code", "comment", "string"]


@dataclass(frozen=True)
class Segment:
    """One run of text of a single kind."""

    kind: SegmentKind
    start: int  # inclusive offset
    end: int  # exclusive offset
    closed: bool  # False only for an unterminated block comment or string


def _line_comment_end(text: str, start: int) -> int:
    end = len(text)
    for stop in ("\n", "\r"):
        found = text.find(stop, start)
        if found != -1:
            end = min(end, found)
    return end


def _string_end(text: str, start: int) -> tuple[int, bool]:
    """Return (end offset, closed) for a string literal opening at ``start``."""
    pos = start + 1
    while True:
        quote = text.find("'", pos)
        if quote == -1:
            return len(text), False
        if text.startswith("''", quote):
            pos = quote + 2
            continue
        return quote + 1, True


def segments(text: str) -> tuple[Segment, ...]:
    """Split ``text`` into code, comment and string segments, in order."""
    out: list[Segment] = []
    n = len(text)
    i = 0
    code_start = 0
    while i < n:
        if text.startswith("--", i):
            end, closed, kind = _line_comment_end(text, i), True, "comment"
        elif text.startswith("/*", i):
            close = text.find("*/", i + 2)
            if close == -1:
                end, closed = n, False
            else:
                end, closed = close + 2, True
            kind = "comment"
        elif text[i] == "'":
            end, closed = _string_end(text, i)
            kind = "string"
        else:
            i += 1
            continue
        if i > code_start:
            out.append(Segment("code", code_start, i, True))
        out.append(Segment(kind, i, end, closed))  # type: ignore[arg-type]
        i = end
        code_start = end
    if code_start < n:
        out.append(Segment("code", code_start, n, True))
    return tuple(out)


def mask(text: str) -> str:
    """Return ``text`` with comments and strings replaced by spaces.

    Same length as the input. Newline characters (``\\n`` and ``\\r``) stay.
    """
    parts: list[str] = []
    for seg in segments(text):
        chunk = text[seg.start : seg.end]
        if seg.kind == "code":
            parts.append(chunk)
        else:
            parts.append("".join(ch if ch in "\r\n" else " " for ch in chunk))
    return "".join(parts)


def string_literals(text: str) -> tuple[str, ...]:
    """Contents of every string literal, in order, without quotes."""
    out: list[str] = []
    for seg in segments(text):
        if seg.kind != "string":
            continue
        inner_end = seg.end - 1 if seg.closed else seg.end
        out.append(text[seg.start + 1 : inner_end].replace("''", "'"))
    return tuple(out)


def line_starts(text: str) -> tuple[int, ...]:
    """Offsets where each line starts. Lines are counted by ``\\n`` only."""
    starts = [0]
    pos = text.find("\n")
    while pos != -1:
        starts.append(pos + 1)
        pos = text.find("\n", pos + 1)
    return tuple(starts)


def line_of(starts: tuple[int, ...], pos: int) -> int:
    """1-based line number of offset ``pos``."""
    return bisect_right(starts, pos)


def column_of(starts: tuple[int, ...], pos: int) -> int:
    """1-based column of offset ``pos``."""
    return pos - starts[line_of(starts, pos) - 1] + 1
