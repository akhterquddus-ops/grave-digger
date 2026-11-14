"""Acceptance tests for the plain-English Autopsy (Kiro spec: autopsy-explain).

The LLM turns scanner facts into business rules a non-programmer can read.
The guardrail is the point: a rule survives only if it is backed by the code.

Contract under test (module gravedigger.autopsy.explain):
  Rule(text, lines, category)                       frozen dataclass
  Explanation(unit, summary, rules, dropped, source) frozen dataclass
      source in {"llm", "cache", "static"}
  evidence_lines(unit) -> frozenset[int]
  check_rule(rule, unit, facts) -> str | None       None = keep, else the reason it was dropped
  build_prompt(unit, facts) -> str
  static_rules(unit, facts) -> tuple[Rule, ...]
  explain(unit, facts, client=None, cache_dir=None) -> Explanation
  make_client(provider, api_key, model=None) -> client | None

A client is any object with
  complete_json(system: str, prompt: str) -> dict
returning {"summary": str, "rules": [{"text": str, "lines": [int], "category": str}]}.

No test calls a real API. FakeClient below stands in for Claude or OpenAI.
"""

from __future__ import annotations

import json

import pytest

from gravedigger.autopsy.explain import (
    Explanation,
    Rule,
    build_prompt,
    check_rule,
    evidence_lines,
    explain,
    make_client,
    static_rules,
)
from gravedigger.autopsy.scanner import scan
from gravedigger.exhume import load_package


class FakeClient:
    """Returns a canned answer and records every call."""

    def __init__(self, answer: dict):
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, prompt: str) -> dict:
        self.calls.append((system, prompt))
        return self.answer


@pytest.fixture(scope="module")
def units(legacy_sources):
    return {u.name: u for u in load_package(*legacy_sources).units}


@pytest.fixture(scope="module")
def facts(units):
    return {name: scan(u) for name, u in units.items()}


ENRG_ANSWER = {
    "summary": "Works out the energy charge from the units used and the tariff.",
    "rules": [
        # kept: real line, real numbers
        {"text": "Above 300 units, every unit is charged Rs 22, not just the units above 300.",
         "lines": [42, 44], "category": "tariff"},
        # kept: shops pay a flat rate
        {"text": "Shops (tariff A2) pay a flat Rs 25 per unit.", "lines": [56], "category": "tariff"},
        # dropped: invented number (24 is not in the code)
        {"text": "Above 300 units the rate is Rs 24.", "lines": [44], "category": "tariff"},
        # dropped: line 48 is a commented-out old rate, not live code
        {"text": "Slab 3 is charged Rs 15.50 per unit.", "lines": [48], "category": "tariff"},
        # dropped: line outside this unit
        {"text": "The fixed charge is Rs 400 per kW.", "lines": [76], "category": "tariff"},
        # dropped: cites no line at all
        {"text": "Home customers get telescopic slabs.", "lines": [], "category": "tariff"},
    ],
}


# ---------------------------------------------------------------- evidence lines


def test_evidence_lines_are_live_code_with_facts(units):
    ev = evidence_lines(units["f_enrg_chg"])
    assert {42, 44, 56} <= ev  # IF p_units > 300 / * 22 / * 25
    assert 48 not in ev  # commented-out old rate
    assert 43 not in ev  # comment line


def test_evidence_lines_include_sql_and_handlers(units):
    ev = evidence_lines(units["p_gen_bill"])
    assert {195, 205} <= ev  # INSERT INTO BILL_HDR / WHEN OTHERS


# ---------------------------------------------------------------- guardrail


def test_guardrail_keeps_rules_backed_by_code(units, facts):
    u, f = units["f_enrg_chg"], facts["f_enrg_chg"]
    assert check_rule(Rule(ENRG_ANSWER["rules"][0]["text"], (42, 44), "tariff"), u, f) is None
    assert check_rule(Rule(ENRG_ANSWER["rules"][1]["text"], (56,), "tariff"), u, f) is None


@pytest.mark.parametrize("index", [2, 3, 4, 5])
def test_guardrail_drops_unsupported_rules_with_a_reason(units, facts, index):
    r = ENRG_ANSWER["rules"][index]
    reason = check_rule(Rule(r["text"], tuple(r["lines"]), r["category"]), units["f_enrg_chg"], facts["f_enrg_chg"])
    assert isinstance(reason, str) and reason


def test_percentages_match_decimal_constants(units, facts):
    rule = Rule("GST is 17% of energy, fixed charge, fuel adjustment and duty together.", (112,), "tax")
    assert check_rule(rule, units["p_taxes"], facts["p_taxes"]) is None
    wrong = Rule("GST is 16% of the bill.", (112,), "tax")
    assert check_rule(wrong, units["p_taxes"], facts["p_taxes"]) is not None


# ---------------------------------------------------------------- prompt


def test_prompt_shows_code_with_file_line_numbers(units, facts):
    prompt = build_prompt(units["f_enrg_chg"], facts["f_enrg_chg"])
    assert "44|" in prompt and "p_units * 22" in prompt
    assert "f_enrg_chg" in prompt


# ---------------------------------------------------------------- explain() with a model


def test_explain_with_client_keeps_and_drops(units, facts):
    client = FakeClient(ENRG_ANSWER)
    out = explain(units["f_enrg_chg"], facts["f_enrg_chg"], client=client)
    assert isinstance(out, Explanation)
    assert out.source == "llm"
    assert out.unit == "f_enrg_chg"
    assert out.summary.startswith("Works out")
    assert [r.lines for r in out.rules] == [(42, 44), (56,)]
    assert len(out.dropped) == 4
    assert len(client.calls) == 1


def test_malformed_model_answer_does_not_crash(units, facts):
    client = FakeClient({"rules": [{"text": 5}, "nonsense", {"lines": "x"}]})
    out = explain(units["f_lps"], facts["f_lps"], client=client)
    assert out.source == "llm"
    assert out.rules == ()


# ---------------------------------------------------------------- cache


def test_cache_avoids_a_second_call(units, facts, tmp_path):
    client = FakeClient(ENRG_ANSWER)
    first = explain(units["f_enrg_chg"], facts["f_enrg_chg"], client=client, cache_dir=tmp_path)
    second = explain(units["f_enrg_chg"], facts["f_enrg_chg"], client=client, cache_dir=tmp_path)
    assert len(client.calls) == 1
    assert first.source == "llm" and second.source == "cache"
    assert second.rules == first.rules
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    json.loads(files[0].read_text(encoding="utf-8"))  # valid JSON on disk


def test_cache_is_used_without_any_client(units, facts, tmp_path):
    explain(units["f_enrg_chg"], facts["f_enrg_chg"], client=FakeClient(ENRG_ANSWER), cache_dir=tmp_path)
    out = explain(units["f_enrg_chg"], facts["f_enrg_chg"], client=None, cache_dir=tmp_path)
    assert out.source == "cache"


def test_cache_is_rechecked_by_the_guardrail(units, facts, tmp_path):
    """A hand-edited cache file cannot sneak in an invented rule."""
    explain(units["f_enrg_chg"], facts["f_enrg_chg"], client=FakeClient(ENRG_ANSWER), cache_dir=tmp_path)
    (path,) = tmp_path.glob("*.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rules"].append({"text": "Everyone pays Rs 99.", "lines": [44], "category": "tariff"})
    path.write_text(json.dumps(data), encoding="utf-8")
    out = explain(units["f_enrg_chg"], facts["f_enrg_chg"], client=None, cache_dir=tmp_path)
    assert all("99" not in r.text for r in out.rules)


# ---------------------------------------------------------------- static fallback (no model, no cache)


def test_static_fallback_needs_no_model(units, facts):
    out = explain(units["p_gen_bill"], facts["p_gen_bill"], client=None)
    assert out.source == "static"
    texts = " ".join(r.text for r in out.rules).upper()
    assert "BILL_HDR" in texts
    assert "WHEN OTHERS" in texts


def test_static_rules_cite_the_right_lines(units, facts):
    rules = {r.text: r.lines for r in static_rules(units["p_gen_bill"], facts["p_gen_bill"])}
    assert any("BILL_HDR" in t and 195 in ln for t, ln in rules.items())
    assert any("WHEN OTHERS" in t.upper() and 205 in ln for t, ln in rules.items())
    fpa = static_rules(units["f_fpa"], facts["f_fpa"])
    assert any("FPA_RT" in r.text and 96 in r.lines for r in fpa)


def test_static_rules_pass_the_guardrail(units, facts):
    for name in units:
        for rule in static_rules(units[name], facts[name]):
            assert check_rule(rule, units[name], facts[name]) is None, (name, rule)


# ---------------------------------------------------------------- providers


def test_no_key_means_no_client():
    assert make_client("anthropic", None) is None
    assert make_client("anthropic", "") is None


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError):
        make_client("acme-ai", "key")


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_known_providers_build_without_network(provider):
    client = make_client(provider, "test-key-not-real")
    assert client is not None
    assert callable(getattr(client, "complete_json", None))
