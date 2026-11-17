"""Guardrail cases for check_rule (Kiro spec: autopsy-explain, task 16.1).

Requirements 3.18-3.23: a rule that cites only lines of its own unit is judged
on numbers it states; rules without numbers are kept when every line is inside
the unit, and a number must appear in the code.
"""

from __future__ import annotations

import pytest

from gravedigger.autopsy.explain import Rule, check_rule
from gravedigger.autopsy.scanner import scan
from gravedigger.exhume import load_package


@pytest.fixture(scope="module")
def units(legacy_sources):
    return {u.name: u for u in load_package(*legacy_sources).units}


@pytest.fixture(scope="module")
def facts(units):
    return {name: scan(u) for name, u in units.items()}


def _check(units, facts, unit, text, lines):
    return check_rule(Rule(text, lines, "other"), units[unit], facts[unit])


def test_error_handler_line_range_is_kept(units, facts):
    """Validates: Requirements 3.18, 3.23"""
    assert _check(units, facts, "p_gen_bill", "Any other error is silently ignored.", (204, 205, 206)) is None


def test_slab_range_without_constants_is_kept(units, facts):
    """Validates: Requirements 3.19, 3.23"""
    assert _check(units, facts, "f_enrg_chg", "Units 101 to 200 are charged Rs 13.", (49, 50)) is None


def test_invented_number_is_dropped_naming_it(units, facts):
    """Validates: Requirements 3.20, 3.23"""
    reason = _check(units, facts, "f_enrg_chg", "Above 300 units the rate is Rs 24.", (44,))
    assert isinstance(reason, str) and "24" in reason


def test_line_outside_unit_is_dropped(units, facts):
    """Validates: Requirements 3.21, 3.23"""
    reason = _check(units, facts, "p_gen_bill", "The bill is written once.", (204, 300))
    assert isinstance(reason, str) and "outside the unit" in reason


def test_zero_in_text_with_zero_constant_is_kept(units, facts):
    """Validates: Requirements 3.22, 3.23"""
    assert _check(units, facts, "f_lps", "No surcharge (0) if paid on time.", (139,)) is None
