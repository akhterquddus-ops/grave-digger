"""Exhume: load a PL/SQL package and split its body into units."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Literal

from gravedigger.autopsy.blocks import Block, find_blocks
from gravedigger.autopsy.tokenizer import line_of, line_starts, mask

_IDENT = r"[A-Za-z_][A-Za-z0-9_$#]*"
_SPEC_HEADER = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+(?:(?:NON)?EDITIONABLE\s+)?PACKAGE\s+(?!BODY(?![\w$#]))"
    r"(?:" + _IDENT + r"\s*\.\s*)?(" + _IDENT + r")",
    re.IGNORECASE,
)
_BODY_HEADER = re.compile(r"(?<![\w$#])PACKAGE\s+BODY(?![\w$#])", re.IGNORECASE)
_AS_IS = re.compile(r"(?<![\w$#])(?:AS|IS)(?![\w$#])", re.IGNORECASE)
_UNIT_HEAD = re.compile(r"\s*(FUNCTION|PROCEDURE)\s+(" + _IDENT + r")", re.IGNORECASE)
_PARAM = re.compile(
    r"^(" + _IDENT + r")\s+(?:(IN\s+OUT|IN|OUT)\s+)?(?:NOCOPY\s+)?(.+?)\s*"
    r"(?:(?::=|(?<![\w$#])DEFAULT(?![\w$#])).*)?$",
    re.IGNORECASE | re.DOTALL,
)
_RETURN = re.compile(r"(?<![\w$#])RETURN\s+([\w$#.%]+)", re.IGNORECASE)
_WORD = re.compile(_IDENT)
_SKIP_FIRST = {"FUNCTION", "PROCEDURE", "TYPE", "SUBTYPE", "CURSOR", "PRAGMA"}
_SKIP_SECOND = {"CONSTANT", "EXCEPTION"}


class ExhumeError(ValueError):
    """The package text is malformed and cannot be split into units."""


@dataclass(frozen=True)
class Param:
    """One parameter of a unit."""

    name: str  # lower-case
    mode: str  # "IN" | "OUT" | "IN OUT"
    datatype: str  # upper-case


@dataclass(frozen=True)
class Global:
    """A package-level variable declared in the package spec."""

    name: str  # lower-case


@dataclass(frozen=True)
class Unit:
    """One top-level function or procedure of a package body."""

    name: str
    kind: Literal["function", "procedure"]
    params: tuple[Param, ...]
    return_type: str | None
    start_line: int
    end_line: int
    source: str
    sibling_names: tuple[str, ...] = field(default=(), repr=False)
    global_names: tuple[str, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class Package:
    """A loaded package."""

    name: str
    globals: tuple[Global, ...]
    units: tuple[Unit, ...]


def _package_name(spec_masked: str) -> tuple[str, int]:
    """Return (lower-case package name, offset just after the header)."""
    m = _SPEC_HEADER.search(spec_masked)
    if m is None:
        raise ExhumeError("package spec has no CREATE OR REPLACE PACKAGE statement")
    return m.group(1).lower(), m.end()


def _spec_globals(spec_masked: str, package: str, header_end: int) -> tuple[Global, ...]:
    """Variables declared in the spec, in declared order."""
    start = _AS_IS.search(spec_masked, header_end)
    if start is None:
        return ()
    section = spec_masked[start.end():]
    end = re.search(r"(?<![\w$#])END\s+" + re.escape(package) + r"\s*;", section, re.IGNORECASE)
    if end:
        section = section[: end.start()]
    found: list[Global] = []
    for statement in section.split(";"):
        words = _WORD.findall(statement)
        if not words:
            continue
        if words[0].upper() in _SKIP_FIRST:
            continue
        if len(words) > 1 and words[1].upper() in _SKIP_SECOND:
            continue
        found.append(Global(words[0].lower()))
    return tuple(found)


def _require_body_header(body_masked: str) -> None:
    if _BODY_HEADER.search(body_masked) is None:
        raise ExhumeError("package body has no PACKAGE BODY header")


def _split_top_level(text: str, sep: str) -> list[str]:
    """Split ``text`` on ``sep`` at parenthesis depth 0."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def _normalise_datatype(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.strip())
    return re.sub(r"\s*([().%,])\s*", r"\1", collapsed).upper()


def _parse_param(unit_name: str, text: str) -> Param:
    m = _PARAM.match(text.strip())
    if m is None:
        raise ExhumeError(f"{unit_name}: cannot parse parameter {text.strip()!r}")
    mode = re.sub(r"\s+", " ", m.group(2).upper()) if m.group(2) else "IN"
    return Param(m.group(1).lower(), mode, _normalise_datatype(m.group(3)))


def _parse_header(header_masked: str) -> tuple[str, Literal["function", "procedure"], tuple[Param, ...], str | None]:
    """Parse a unit header. Return (name, kind, params, return type)."""
    head = _UNIT_HEAD.match(header_masked)
    if head is None:
        raise ExhumeError(f"cannot read unit header {header_masked.strip()[:40]!r}")
    kind: Literal["function", "procedure"] = head.group(1).lower()  # type: ignore[assignment]
    name = head.group(2).lower()
    rest = header_masked[head.end():]
    params: tuple[Param, ...] = ()
    stripped = rest.lstrip()
    if stripped.startswith("("):
        offset = len(rest) - len(stripped)
        depth = 0
        close = -1
        for i, ch in enumerate(stripped):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    close = i
                    break
        if close == -1:
            raise ExhumeError(f"{name}: unbalanced parentheses in parameter list")
        pieces = _split_top_level(stripped[1:close], ",")
        if len(pieces) == 1 and not pieces[0].strip():
            raise ExhumeError(f"{name}: empty parameter list")
        parsed: list[Param] = []
        for piece in pieces:
            if not piece.strip():
                raise ExhumeError(f"{name}: empty piece in parameter list")
            parsed.append(_parse_param(name, piece))
        params = tuple(parsed)
        rest = rest[offset + close + 1:]
    return_type: str | None = None
    if kind == "function":
        ret = _RETURN.search(rest)
        if ret is None:
            raise ExhumeError(f"{name}: function has no RETURN type")
        return_type = ret.group(1).upper()
    return name, kind, params, return_type


def _slice_lines(text: str, starts: tuple[int, ...], first: int, last: int) -> str:
    """Exact text of lines ``first``..``last`` (1-based), without the final line break."""
    begin = starts[first - 1]
    stop = starts[last] - 1 if last < len(starts) else len(text)
    chunk = text[begin:stop]
    return chunk[:-1] if chunk.endswith("\r") else chunk


def _top_level_units(body_text: str, body_masked: str, blocks: tuple[Block, ...]) -> tuple[Unit, ...]:
    starts = line_starts(body_text)
    units: list[Unit] = []
    for blk in blocks:
        if blk.depth != 0 or blk.kind not in ("function", "procedure"):
            continue
        if blk.end is None or blk.header_end is None:
            raise ExhumeError(f"{blk.name}: unit has no closing END")
        name, kind, params, return_type = _parse_header(body_masked[blk.start:blk.header_end])
        first = line_of(starts, blk.start)
        last = line_of(starts, blk.end)
        units.append(
            Unit(name, kind, params, return_type, first, last,
                 _slice_lines(body_text, starts, first, last))
        )
    return tuple(units)


def load_package(spec_text: str, body_text: str) -> Package:
    """Load a package from its spec text and body text.

    Raises ExhumeError (a ValueError) for malformed input. Nothing partial is
    ever returned.
    """
    spec_masked = mask(spec_text)
    name, header_end = _package_name(spec_masked)
    globals_ = _spec_globals(spec_masked, name, header_end)
    body_masked = mask(body_text)
    _require_body_header(body_masked)
    units = _top_level_units(body_text, body_masked, find_blocks(body_masked))
    siblings = tuple(u.name for u in units)
    global_names = tuple(g.name for g in globals_)
    return Package(
        name,
        globals_,
        tuple(replace(u, sibling_names=siblings, global_names=global_names) for u in units),
    )
