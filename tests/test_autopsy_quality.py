"""Autopsy quality: does the cached Claude autopsy find the 8 rules we planted?

BILLING_PKG was written with 8 hidden business rules (see the HLD/LLD). This is
the answer key. Each check reads the cached explanation in golden/autopsy
(the same files the hosted demo shows), re-applies the guardrail, and asserts
that at least one KEPT rule:
  - belongs to the right unit,
  - cites at least one of the lines where the rule lives, and
  - says the key words a billing analyst would need to recognise it.

No API call is made. If golden/autopsy has no cache for a unit yet, the test
is skipped (run scripts/explain_sample.py to create it).

Score for the write-up: number of passed cases out of 8.
"""

from __future__ import annotations

import re

import pytest

from gravedigger.autopsy.explain import explain
from gravedigger.autopsy.scanner import scan
from gravedigger.exhume import load_package

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = REPO_ROOT / "golden" / "autopsy"

# (id, unit, lines where the rule lives, groups of words: every group needs one match)
PLANTED_RULES = [
    ("meter-rollover", "f_units", {21, 23},
     [["roll", "99999", "wrap", "reset", "back to 0", "back to zero"]]),
    ("slab-cliff-above-300", "f_enrg_chg", {42, 44},
     [["300"], ["22"], ["all", "every", "whole", "entire"]]),
    ("minimum-charge-75", "f_fix_chg", {78, 79},
     [["75"], ["minimum", "at least", "top up", "top-up", "below"]]),
    ("missing-fpa-rate-is-zero", "f_fpa", {99, 101},
     [["no rate", "missing", "not loaded", "not found", "no fuel", "no fpa", "isn't loaded", "is not loaded", "no matching"],
      ["0", "zero", "nothing", "no fpa", "without"]]),
    ("gst-on-top-of-duty", "p_taxes", {112},
     [["17", "0.17"], ["duty", "ed"]]),
    ("sunday-due-date-moves-to-monday", "f_due_dt", {122, 123},
     [["sunday"], ["monday", "next day", "one day later", "1 day"]]),
    ("surcharge-on-energy-only", "f_lps", {136, 137},
     [["10", "0.1", "0.10", "tenth"], ["energy"]]),
    ("errors-silently-swallowed", "p_gen_bill", {205, 206},
     [["ignored", "silently", "swallow", "hidden", "hides", "no bill", "not reported", "without error"]]),
]


@pytest.fixture(scope="module")
def units(legacy_sources):
    return {u.name: u for u in load_package(*legacy_sources).units}


def _has(text: str, word: str) -> bool:
    """Whole-word match for short words and numbers, substring for phrases."""
    if " " in word or (len(word) > 3 and not word.replace(".", "").isdigit()):
        return word in text
    return re.search(r"(?<![\w.])" + re.escape(word) + r"(?![\w]|\.\d)", text) is not None


def _matches(text: str, groups: list[list[str]]) -> bool:
    t = text.lower()
    return all(any(_has(t, w.lower()) for w in group) for group in groups)


@pytest.mark.parametrize(
    "rule_id, unit_name, lines, groups",
    PLANTED_RULES,
    ids=[r[0] for r in PLANTED_RULES],
)
def test_planted_rule_is_found(units, rule_id, unit_name, lines, groups):
    unit = units[unit_name]
    if not CACHE_DIR.is_dir() or not any(CACHE_DIR.glob(f"{unit_name}-*.json")):
        pytest.skip(f"no cached autopsy for {unit_name}: run scripts/explain_sample.py")
    out = explain(unit, scan(unit), client=None, cache_dir=CACHE_DIR)
    if out.source != "cache":
        pytest.skip(f"cache for {unit_name} is stale (prompt or model changed): run scripts/explain_sample.py")
    hits = [r for r in out.rules if set(r.lines) & lines and _matches(r.text, groups)]
    assert hits, (
        f"{rule_id}: no kept rule in {unit_name} cites {sorted(lines)} with {groups}.\n"
        "Kept rules:\n" + "\n".join(f"  {r.lines} {r.text}" for r in out.rules)
    )
