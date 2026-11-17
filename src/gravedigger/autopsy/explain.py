"""Plain-English Autopsy: explain a legacy unit as business rules (Kiro spec: autopsy-explain).

Public contract:
  Rule, Dropped, Explanation      frozen data types
  LLMClient, LLMError             the client protocol and its error
  evidence_lines(unit)            live code lines that carry a fact
  check_rule(rule, unit, facts)   None = keep, else the reason it was dropped
  build_prompt(unit, facts)       the text sent to the model
  static_rules(unit, facts)       rules built from scanner facts alone
  explain(unit, facts, client, cache_dir) -> Explanation
  make_client(provider, api_key, model) -> LLMClient | None
  client_from_settings()          client built from config settings
"""

from __future__ import annotations

import hashlib  # noqa: F401
import json  # noqa: F401
import logging
import os  # noqa: F401
import re  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from decimal import Decimal  # noqa: F401
from pathlib import Path
from typing import Any, Literal, Protocol

from gravedigger.autopsy.blocks import Block, find_blocks  # noqa: F401
from gravedigger.autopsy.scanner import (  # noqa: F401
    Facts,
    find_constants,
    find_name_uses,
    find_tables,
    whole_word,
)
from gravedigger.autopsy.tokenizer import line_of, line_starts, mask, segments  # noqa: F401
from gravedigger.config import setting  # noqa: F401
from gravedigger.exhume import Unit

logger = logging.getLogger(__name__)

PROMPT_VERSION = "autopsy-explain-1"  # change with SYSTEM_PROMPT or the answer format
CATEGORIES: tuple[str, ...] = ("tariff", "tax", "date", "surcharge", "error", "other")
PROVIDERS: tuple[str, ...] = ("anthropic", "openai")
ANTHROPIC_DEFAULT_MODEL = "claude-haiku-5-5"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
Source = Literal["llm", "cache", "static"]


@dataclass(frozen=True)
class Rule:
    """One business rule: plain text, the file lines it cites, and a category."""

    text: str
    lines: tuple[int, ...]
    category: str


@dataclass(frozen=True)
class Dropped:
    """A rule the guardrail rejected, with the reason."""

    rule: Rule
    reason: str


@dataclass(frozen=True)
class Explanation:
    """The explanation of one unit."""

    unit: str
    summary: str
    rules: tuple[Rule, ...]
    dropped: tuple[Dropped, ...]
    source: Source


class LLMClient(Protocol):
    """Anything that can answer a prompt with a JSON object."""

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]: ...


class LLMError(RuntimeError):
    """A provider call failed or returned an unusable answer. The message never holds the API key."""


# ---------------------------------------------------------------- evidence lines


_BRANCH_WORD = re.compile(
    r"(?<![A-Za-z0-9_$#])(END\s+IF|ELSIF|IF)(?![A-Za-z0-9_$#])", re.IGNORECASE
)
_WHEN_WORD = whole_word("WHEN")


def _masked_lines(unit: Unit) -> tuple[str, ...]:
    """Unit source with comments and strings blanked, split by line.

    Index ``i`` is file line ``unit.start_line + i``.
    """
    return tuple(mask(unit.source).split("\n"))


def _owner(blocks: tuple[Block, ...], pos: int) -> Block | None:
    """Innermost block that contains offset ``pos``."""
    best: Block | None = None
    for b in blocks:
        if b.start <= pos and (b.end is None or pos < b.end):
            if best is None or b.start > best.start:
                best = b
    return best


def _handler_lines(
    masked: str, starts: tuple[int, ...], blocks: tuple[Block, ...], first: int
) -> frozenset[int]:
    """File lines of exception handlers: EXCEPTION keywords and WHEN clauses after them."""
    found: set[int] = set()
    for b in blocks:
        if b.exception_pos is not None:
            found.add(first + line_of(starts, b.exception_pos) - 1)
    for m in _WHEN_WORD.finditer(masked):
        owner = _owner(blocks, m.start())
        if owner is not None and owner.exception_pos is not None and owner.exception_pos <= m.start():
            found.add(first + line_of(starts, m.start()) - 1)
    return frozenset(found)


def evidence_lines(unit: Unit) -> frozenset[int]:
    """File lines of live code that carry a fact.

    A fact is a numeric constant, a table read or written, a string literal,
    a call to a sibling unit, an IF or ELSIF branch, or an exception handler.
    Comment lines and commented-out code never count. Pure: no file, no network.
    """
    first = unit.start_line
    masked = mask(unit.source)
    starts = line_starts(unit.source)
    blocks = find_blocks(masked)
    mlines = masked.split("\n")
    lines: set[int] = set()

    def add_word_lines(name: str) -> None:
        pattern = whole_word(name)
        for i, text in enumerate(mlines):
            if pattern.search(text):
                lines.add(first + i)

    lines.update(c.line for c in find_constants(masked, starts, first))

    read, written = find_tables(masked)
    for table in read | written:
        add_word_lines(table)

    others = [n for n in unit.sibling_names if n.lower() != unit.name.lower()]
    for name in find_name_uses(masked, others):
        add_word_lines(name)

    for m in _BRANCH_WORD.finditer(masked):
        if not m.group(1).upper().startswith("END"):
            lines.add(first + line_of(starts, m.start()) - 1)

    lines.update(_handler_lines(masked, starts, blocks, first))

    for seg in segments(unit.source):
        if seg.kind == "string":
            lo = line_of(starts, seg.start)
            hi = line_of(starts, max(seg.start, seg.end - 1))
            lines.update(first + n - 1 for n in range(lo, hi + 1))

    return frozenset(n for n in lines if unit.start_line <= n <= unit.end_line)


# ---------------------------------------------------------------- number helpers

# "line 42", "lines 10-12", "L42", "l. 7", "ll. 42"; not inside words such as "all 300".
_LINE_REF = re.compile(r"(?<![A-Za-z0-9_$#])(?:lines?|ll\.|l\.?)\s*\d+", re.IGNORECASE)

# A number not glued to identifier characters (the 2 in "A2" is not a token).
_NUMBER = re.compile(r"(?<![A-Za-z0-9_$#])(?:\d+(?:\.\d+)?|\.\d+)(?![A-Za-z0-9_$#])")


def _number_tokens(text: str) -> tuple[tuple[str, bool], ...]:
    """Numbers in ``text``, in order, as (token, followed by a percent sign)."""
    return tuple(
        (m.group(0), text[m.end() : m.end() + 1] == "%") for m in _NUMBER.finditer(text)
    )


def _code_numbers(facts: Facts) -> frozenset[Decimal]:
    """Numbers a rule text may state: constant values, their absolute values, and
    numbers inside string literals."""
    numbers: set[Decimal] = set()
    for c in facts.constants:
        numbers.add(c.value)
        numbers.add(abs(c.value))
    for literal in facts.string_literals:
        for token, _ in _number_tokens(literal):
            numbers.add(Decimal(token))
    return frozenset(numbers)


def _shift_down(d: Decimal) -> Decimal:
    """Exact ``d / 100``, rebuilt from the digit tuple so no context rounding applies."""
    sign, digits, exponent = d.as_tuple()
    assert isinstance(exponent, int)
    return Decimal((sign, digits, exponent - 2))


def _plain(d: Decimal) -> str:
    """Plain decimal text: no exponent, never ``-0``."""
    return "0" if d == 0 else format(d.normalize(), "f")


# A comparison against a numeric literal: "> 100" (not >=, <>, =>, >>) or "< 75" (not <=, <>, <<).
_GREATER = re.compile(r"(?<![<>=!~^])>(?![=>])\s*(\d+(?:\.\d+)?)(?![A-Za-z0-9_$#])")
_LESS = re.compile(r"(?<![<>])<(?![=<>])\s*(\d+(?:\.\d+)?)(?![A-Za-z0-9_$#])")


def _boundary_numbers(unit: Unit, ev: frozenset[int]) -> frozenset[Decimal]:
    """Boundary_Numbers: c + 1 for ``> c`` and c - 1 for ``< c`` on evidence lines.

    Searches the masked source (comments and strings blanked), so commented-out
    code never counts. A rule may say "101 to 200" for ``IF x > 100 ... <= 200``.
    """
    one = Decimal("1")
    found: set[Decimal] = set()
    for i, text in enumerate(_masked_lines(unit)):
        if unit.start_line + i not in ev:
            continue
        for m in _GREATER.finditer(text):
            found.add(Decimal(m.group(1)) + one)
        for m in _LESS.finditer(text):
            found.add(Decimal(m.group(1)) - one)
    return frozenset(found)


def _check(rule: Rule, unit: Unit, facts: Facts, ev: frozenset[int]) -> str | None:
    """Guardrail body: five checks in a fixed order, first failure wins.

    1. a line is cited; 2. every cited line is inside the unit; 3. at least one
    cited line is live code with a fact; 4. the text holds no line reference;
    5. every number is a code constant, 0, a percentage form of a constant, or a
    Boundary_Number.
    """
    if not rule.lines:
        return "It cites no line of the code."
    ordered = sorted(rule.lines)
    for n in ordered:
        if n < unit.start_line or n > unit.end_line:
            return f"Line {n} is outside the unit (lines {unit.start_line}-{unit.end_line})."
    if not any(n in ev for n in ordered):
        cited = ", ".join(str(n) for n in ordered)
        return (
            f"Lines {cited} are not live code with a fact (they may be comments, blank "
            "lines, or code without a number, table, call, branch or handler)."
        )
    if _LINE_REF.search(rule.text):
        return "The text mentions line numbers. Line numbers belong in the citation, not in the text."
    allowed = _code_numbers(facts) | {Decimal("0")} | _boundary_numbers(unit, ev)
    for token, is_percent in _number_tokens(rule.text):
        value = Decimal(token)
        if value in allowed:
            continue
        if is_percent and _shift_down(value) in allowed:
            continue
        return f"The text states the number {token}, which is not in the code."
    return None


def check_rule(rule: Rule, unit: Unit, facts: Facts) -> str | None:
    """Guardrail: None to keep the rule, else the reason it is dropped. Pure."""
    return _check(rule, unit, facts, evidence_lines(unit))


def _judge(
    rules: tuple[Rule, ...], unit: Unit, facts: Facts, ev: frozenset[int]
) -> tuple[tuple[Rule, ...], tuple[Dropped, ...]]:
    """Run the guardrail over ``rules``; keep input order. Only place that builds Dropped."""
    kept: list[Rule] = []
    dropped: list[Dropped] = []
    for rule in rules:
        reason = _check(rule, unit, facts, ev)
        if reason is None:
            kept.append(rule)
        else:
            dropped.append(Dropped(rule, reason))
    return tuple(kept), tuple(dropped)


# ---------------------------------------------------------------- tolerant parsing


def _skip(reason: str) -> None:
    """Debug log for a skipped entry. The reason is fixed text, never entry content."""
    logger.debug("explain: skipped a malformed rule entry (%s)", reason)
    return None


def _rule_from_entry(entry: Any) -> Rule | None:
    """One answer entry as a Rule, or None (with a debug log) when its shape is wrong.

    An unknown or non-string category becomes ``other``. Never raises.
    """
    if not isinstance(entry, dict):
        return _skip("not an object")
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        return _skip("text is missing, not a string, or blank")
    lines = entry.get("lines")
    if not isinstance(lines, list) or any(
        isinstance(n, bool) or not isinstance(n, int) for n in lines
    ):
        return _skip("lines is not a list of integers")
    category = entry.get("category")
    if not isinstance(category, str) or category not in CATEGORIES:
        category = "other"
    return Rule(text, tuple(lines), category)


def _parse_answer(answer: Any) -> tuple[str, tuple[Rule, ...]]:
    """Read a model answer into (summary, rules). Never raises; bad entries are skipped."""
    if not isinstance(answer, dict):
        return "", ()
    summary = answer.get("summary")
    if not isinstance(summary, str):
        summary = ""
    entries = answer.get("rules")
    if not isinstance(entries, list):
        return summary, ()
    rules = [r for r in map(_rule_from_entry, entries) if r is not None]
    return summary, tuple(rules)


# ---------------------------------------------------------------- prompts

SYSTEM_PROMPT = """\
You explain legacy Oracle PL/SQL billing code to people who do not read code.
You receive one function or procedure. Every code line starts with its file line
number, then a vertical bar, then the code. After the code you receive FACTS that
a scanner found. Write a structured answer with a summary and a list of rules.

summary
  One sentence in plain English that says what this unit does.

rules
  The business rules a billing analyst would recognise: rates and thresholds,
  slabs, taxes, dates and due dates, surcharges and fees, and error handling.
  One rule per idea. For every rule give:
  - text: plain English that a non-programmer can read. Say what happens and when.
    Avoid variable names and PL/SQL words.
  - lines: the file line numbers, as integers, taken from the left of the bars.
    Cite at least one line. Cite only live code lines that hold a number, a table,
    a string, a call to another unit, an IF or ELSIF, or an error handler.
  - category: one of tariff, tax, date, surcharge, error, other.

A checker rejects every rule that breaks one of these rules:
  1. Never write a line number in text. "line 42", "lines 10-12" and "L42" are not
     allowed. Line numbers belong only in lines.
  2. In text, use only numbers that appear in the code. Write a percentage when the
     code holds the fraction: 17% is allowed for 0.17 and 1.5% for 0.015. Do not
     compute new numbers, totals or worked examples. Put a space between a word and
     a number ("Rs 22", not "Rs22").
  3. Never base a rule on a comment or on commented-out code. An old rate in a
     comment is history, not a rule.
  4. Describe what the code does, even when it looks wrong, for example a rate that
     jumps at a threshold, tax charged on tax, or an error that is silently ignored.
     Do not fix, judge or soften it.
  5. Do not invent rules. If the unit has few rules, return few.
  6. Tariff codes such as A1 and A2 may be written as they are.

Return only the structured answer.
"""

_JSON_FORMAT_NOTE = (
    "Answer with one JSON object and nothing else, in this shape: "
    '{"summary": "<one sentence>", "rules": [{"text": "<plain English>", '
    '"lines": [<integer file line numbers>], '
    '"category": "<tariff|tax|date|surcharge|error|other>"}]}'
)


def _answer_schema() -> dict[str, Any]:
    """JSON schema of the answer (Anthropic tool input). A fresh dict on every call."""
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "One plain-English sentence."},
            "rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "lines": {"type": "array", "items": {"type": "integer"}},
                        "category": {"type": "string", "enum": list(CATEGORIES)},
                    },
                    "required": ["text", "lines", "category"],
                },
            },
        },
        "required": ["summary", "rules"],
    }


def _listed(items: Any) -> str:
    """Sorted, comma-separated names, or ``none``."""
    names = sorted(items)
    return ", ".join(names) if names else "none"


def build_prompt(unit: Unit, facts: Facts) -> str:
    """The user prompt: unit header, numbered code, and the scanner facts. Deterministic."""
    code = [
        f"{unit.start_line + i}|{line.rstrip(chr(13))}"
        for i, line in enumerate(unit.source.split("\n"))
    ]
    numbers = (
        ", ".join(f"{_plain(c.value)} (line {c.line})" for c in facts.constants) or "none"
    )
    parts = [
        f"UNIT: {unit.name} ({unit.kind}, file lines {unit.start_line}-{unit.end_line})",
        "",
        "CODE (each line is <file line number>|<code>):",
        *code,
        "",
        "FACTS (found by a scanner, not by you):",
        f"- Numbers in live code: {numbers}",
        f"- Tables read: {_listed(facts.tables_read)}",
        f"- Tables written: {_listed(facts.tables_written)}",
        f"- Calls to other units: {_listed(facts.calls)}",
        f"- Branches (IF and ELSIF): {facts.branches}",
        f"- Errors handled: {_listed(facts.exceptions_handled)}",
        f"- Errors swallowed (WHEN OTHERS THEN NULL): {'yes' if facts.swallows_errors else 'no'}",
        f"- Package globals used: {_listed(facts.globals_used)}",
        "- Comment lines and commented-out code are shown for context only. Do not cite them.",
    ]
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------- static fallback

_ID_BEFORE = r"(?<![A-Za-z0-9_$#])"
_ID_AFTER = r"(?![A-Za-z0-9_$#])"
_SCHEMA = r"(?:[A-Za-z_][A-Za-z0-9_$#]*\s*\.\s*)?"


def _first_line(masked_lines: tuple[str, ...], first: int, pattern: re.Pattern[str]) -> int | None:
    """First file line whose masked text matches ``pattern``, or None."""
    for i, text in enumerate(masked_lines):
        if pattern.search(text):
            return first + i
    return None


def _table_read_pattern(table: str) -> re.Pattern[str]:
    t = re.escape(table)
    return re.compile(
        rf"{_ID_BEFORE}(?:FROM|JOIN)\s+{_SCHEMA}{t}{_ID_AFTER}", re.IGNORECASE
    )


def _table_write_pattern(table: str) -> re.Pattern[str]:
    t = re.escape(table)
    return re.compile(
        rf"{_ID_BEFORE}(?:INSERT\s+INTO|UPDATE|DELETE\s+(?:FROM\s+)?)\s*{_SCHEMA}{t}{_ID_AFTER}",
        re.IGNORECASE,
    )


def _table_line(
    mlines: tuple[str, ...], first: int, table: str, pattern: re.Pattern[str]
) -> int | None:
    """Line of the statement that touches ``table``; whole-word hit as a fallback."""
    hit = _first_line(mlines, first, pattern)
    return hit if hit is not None else _first_line(mlines, first, whole_word(table))


def _handler_line(
    mlines: tuple[str, ...], first: int, handlers: frozenset[int], name: str
) -> int | None:
    """First handler line whose masked text holds ``name`` as a whole word."""
    pattern = whole_word(name)
    for i, text in enumerate(mlines):
        if first + i in handlers and pattern.search(text):
            return first + i
    return None


def static_rules(unit: Unit, facts: Facts) -> tuple[Rule, ...]:
    """Rules built from scanner facts alone (no LLM).

    Groups, in order: tables read, tables written, exceptions handled, the
    swallow rule, one constants rule. Sorted by name inside each group. A rule
    whose line is not found, or not in the evidence set, is skipped, so every
    static rule passes the guardrail.
    """
    first = unit.start_line
    mlines = _masked_lines(unit)
    masked = mask(unit.source)
    starts = line_starts(unit.source)
    handlers = _handler_lines(masked, starts, find_blocks(masked), first)
    ev = evidence_lines(unit)
    rules: list[Rule] = []

    def add(text: str, category: str, lines: tuple[int, ...]) -> None:
        if lines and all(n in ev for n in lines):
            rules.append(Rule(text, lines, category))

    for table in sorted(facts.tables_read):
        n = _table_line(mlines, first, table, _table_read_pattern(table))
        if n is not None:
            add(f"Reads data from table {table}.", "data", (n,))
    for table in sorted(facts.tables_written):
        n = _table_line(mlines, first, table, _table_write_pattern(table))
        if n is not None:
            add(f"Writes data to table {table}.", "data", (n,))
    for name in sorted(facts.exceptions_handled):
        n = _handler_line(mlines, first, handlers, name)
        if n is not None:
            add(f"Handles the error condition {name}.", "error", (n,))
    if facts.swallows_errors:
        n = _handler_line(mlines, first, handlers, "OTHERS")
        if n is not None:
            add(
                "Errors are swallowed: WHEN OTHERS THEN NULL hides every failure, "
                "so the unit never reports a problem.",
                "error",
                (n,),
            )
    if facts.constants:
        values: list[Decimal] = []
        for c in facts.constants:
            if c.value not in values:
                values.append(c.value)
        listed = ", ".join(_plain(v) for v in values)
        lines = tuple(sorted({c.line for c in facts.constants}))
        add(f"The code uses these fixed numbers: {listed}.", "other", lines)
    return tuple(rules)


def _static_summary(unit: Unit) -> str:
    """Summary text of a static explanation."""
    return (
        f"{unit.name} is a {unit.kind} of the billing package. No AI explanation is "
        "available, so the list below comes from the facts in the code alone."
    )


# ---------------------------------------------------------------- cache names
def _source_hash(unit: Unit) -> str:
    """12 hex characters of SHA-256 over the unit source and the prompt version."""
    raw = "\x00".join((unit.source, PROMPT_VERSION))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _key_hash(unit: Unit, client: LLMClient | None) -> str:
    """12 hex characters of SHA-256 over source, provider, model and prompt version.

    A client without ``provider`` or ``model`` (or no client) uses ``unknown``.
    """
    provider = getattr(client, "provider", "unknown")
    model = getattr(client, "model", "unknown")
    raw = "\x00".join((unit.source, str(provider), str(model), PROMPT_VERSION))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _cache_name(unit: Unit, client: LLMClient | None) -> str:
    """Cache file name: ``<unit>-<source hash>-<key hash>.json``."""
    return f"{unit.name}-{_source_hash(unit)}-{_key_hash(unit, client)}.json"


# ---------------------------------------------------------------- cache files
def _read_cache_file(path: Path) -> tuple[str, tuple[Rule, ...]] | None:
    """Read one cache file as (summary, rules), or None when it is unusable.

    Unusable: unreadable, not UTF-8, invalid JSON (a BOM counts), not an object,
    or without ``unit`` (str), ``summary`` (str) and ``rules`` (list). Rule entries
    go through the same shape filter as a live answer; the guardrail runs later.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    summary = data.get("summary")
    entries = data.get("rules")
    if not isinstance(data.get("unit"), str) or not isinstance(summary, str):
        return None
    if not isinstance(entries, list):
        return None
    rules = tuple(r for r in (_rule_from_entry(e) for e in entries) if r is not None)
    return summary, rules


def _find_cache(unit: Unit, directory: Path) -> tuple[str, tuple[Rule, ...]] | None:
    """Newest valid cache file for this unit source, whatever client wrote it."""
    try:
        found = list(directory.glob(f"{unit.name}-{_source_hash(unit)}-*.json"))
        keyed = sorted(((p.stat().st_mtime_ns, p.name, p) for p in found), reverse=True)
    except OSError:
        return None
    for _, _, path in keyed:
        hit = _read_cache_file(path)
        if hit is not None:
            return hit
    return None


def _write_cache(path: Path, unit: Unit, summary: str, rules: tuple[Rule, ...]) -> None:
    """Write the raw answer atomically (.tmp then os.replace), UTF-8 no BOM, LF.

    An OSError is logged with the unit name and exception type only; it is not raised.
    """
    payload = {
        "unit": unit.name,
        "summary": summary,
        "rules": [
            {"text": r.text, "lines": list(r.lines), "category": r.category} for r in rules
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("explain %s: the cache write failed (%s)", unit.name, type(exc).__name__)


# ---------------------------------------------------------------- scrubbing
_KEY_SHAPED = re.compile(r"\b(?:sk|key)-[A-Za-z0-9_\-]{8,}")


def _scrub(text: str, secret: str) -> str:
    """Remove the exact key, then key-shaped strings, from an error message."""
    if secret:
        text = text.replace(secret, "[key removed]")
    return _KEY_SHAPED.sub("[key removed]", text)


# ---------------------------------------------------------------- LLM clients
@dataclass(frozen=True)
class AnthropicClient:
    """Anthropic client. Structured output by a forced tool call. The key is hidden from repr."""

    api_key: str = field(repr=False)
    model: str = ANTHROPIC_DEFAULT_MODEL
    provider: str = "anthropic"
    max_tokens: int = 4096
    timeout: float = 60.0

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        """Ask the model and return the input of its tool call as a dict."""
        if not self.api_key:
            raise LLMError("LLM_API_KEY is not set.")
        try:
            import anthropic
        except ImportError:
            raise LLMError(
                'The "anthropic" package is not installed. Run: pip install -e ".[dev]"'
            ) from None
        tool = {
            "name": "record_explanation",
            "description": "Record the summary and the business rules of the unit.",
            "input_schema": _answer_schema(),
        }
        try:
            client = anthropic.Anthropic(
                api_key=self.api_key, timeout=self.timeout, max_retries=2
            )
            # Risk R-1: if a real run returns HTTP 400 naming tool_choice or thinking,
            # change this to {"type": "any"}.
            message = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise LLMError(
                f"Anthropic call failed ({type(exc).__name__}): "
                f"{_scrub(str(exc), self.api_key)}"
            ) from None
        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and isinstance(block.input, dict):
                return dict(block.input)
        raise LLMError("The Anthropic answer was not structured: it holds no tool call.")


@dataclass(frozen=True)
class OpenAIClient:
    """OpenAI client. Structured output by JSON mode. The key is hidden from repr."""

    api_key: str = field(repr=False)
    model: str = OPENAI_DEFAULT_MODEL
    provider: str = "openai"
    max_tokens: int = 4096
    timeout: float = 60.0

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        """Ask the model and return its JSON answer as a dict."""
        if not self.api_key:
            raise LLMError("LLM_API_KEY is not set.")
        try:
            import openai
        except ImportError:
            raise LLMError(
                'The "openai" package is not installed. Run: pip install -e ".[dev]"'
            ) from None
        try:
            client = openai.OpenAI(
                api_key=self.api_key, timeout=self.timeout, max_retries=2
            )
            # No temperature: some models accept only the default value.
            completion = client.chat.completions.create(
                model=self.model,
                max_completion_tokens=self.max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": f"{system}\n\n{_JSON_FORMAT_NOTE}"},
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception as exc:
            raise LLMError(
                f"OpenAI call failed ({type(exc).__name__}): "
                f"{_scrub(str(exc), self.api_key)}"
            ) from None
        content = completion.choices[0].message.content if completion.choices else None
        try:
            parsed = json.loads(content or "")
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict):
            raise LLMError("The OpenAI answer was not structured: it is not a JSON object.")
        return parsed


# ---------------------------------------------------------------- orchestration
def _ask(unit: Unit, facts: Facts, client: LLMClient) -> tuple[str, tuple[Rule, ...]] | None:
    """Call the client once. None on any error or a non-dict answer (static fallback).

    Logs hold the unit name and the exception or answer type name only.
    """
    try:
        answer = client.complete_json(SYSTEM_PROMPT, build_prompt(unit, facts))
    except Exception as exc:  # noqa: BLE001 - any client failure falls back to static
        logger.warning("explain %s: the LLM call failed (%s)", unit.name, type(exc).__name__)
        return None
    if not isinstance(answer, dict):
        logger.warning(
            "explain %s: the LLM answer was not an object (%s)", unit.name, type(answer).__name__
        )
        return None
    return _parse_answer(answer)


def _finish(
    unit: Unit,
    facts: Facts,
    ev: frozenset[int],
    summary: str,
    rules: tuple[Rule, ...],
    source: Source,
) -> Explanation:
    """Run the guardrail over raw rules and build the Explanation."""
    kept, dropped = _judge(rules, unit, facts, ev)
    return Explanation(unit.name, summary, kept, dropped, source)


def _static(unit: Unit, facts: Facts, ev: frozenset[int]) -> Explanation:
    """Static explanation from scanner facts. Writes no cache file."""
    return _finish(unit, facts, ev, _static_summary(unit), static_rules(unit, facts), "static")


def explain(
    unit: Unit,
    facts: Facts,
    client: LLMClient | None = None,
    cache_dir: Path | str | None = None,
) -> Explanation:
    """Explain one unit: LLM (or cache) rules, each checked by the guardrail.

    With a client and a cache directory the exact cache file is read first; on a
    miss the client is called once and its raw answer is cached. Without a client
    the newest matching cache file is used. Otherwise a static explanation is built.
    """
    ev = evidence_lines(unit)
    directory = Path(cache_dir) if cache_dir is not None else None

    if client is not None:
        if directory is not None:
            path = directory / _cache_name(unit, client)
            hit = _read_cache_file(path)
            if hit is not None:
                return _finish(unit, facts, ev, hit[0], hit[1], "cache")
        answer = _ask(unit, facts, client)
        if answer is None:
            return _static(unit, facts, ev)
        if directory is not None:
            _write_cache(directory / _cache_name(unit, client), unit, answer[0], answer[1])
        return _finish(unit, facts, ev, answer[0], answer[1], "llm")

    if directory is not None:
        hit = _find_cache(unit, directory)
        if hit is not None:
            return _finish(unit, facts, ev, hit[0], hit[1], "cache")
    return _static(unit, facts, ev)


def make_client(provider: str, api_key: str | None, model: str | None = None) -> LLMClient | None:
    """Build a provider client, or None when there is no key.

    The provider is checked first (case and spaces are ignored). An empty model
    means the provider default. Reads no setting, imports no SDK, makes no call.
    """
    name = provider.strip().lower()
    if name not in PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider {provider!r}. Supported providers: anthropic, openai."
        )
    if not api_key or not api_key.strip():
        return None
    key = api_key.strip()
    if name == "anthropic":
        return AnthropicClient(api_key=key, model=model or ANTHROPIC_DEFAULT_MODEL)
    return OpenAIClient(api_key=key, model=model or OPENAI_DEFAULT_MODEL)


def client_from_settings() -> LLMClient | None:
    """Build a client from LLM_PROVIDER, LLM_API_KEY and LLM_MODEL (None without a key)."""
    return make_client(
        setting("LLM_PROVIDER", "anthropic") or "anthropic",
        setting("LLM_API_KEY"),
        setting("LLM_MODEL") or None,
    )
