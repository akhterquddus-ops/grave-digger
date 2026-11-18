"""Acceptance tests for the public demo app (Kiro spec: ui).

The hosted app is what judges click. It tells the whole story in four tabs with
NO database and NO live LLM call: everything comes from files in the repo
(legacy/, golden/autopsy/, golden/cases.json) and the Python code itself.

  Autopsy    plain-English rules per unit, each citing its code lines; dropped (invented) rules shown
  Graph      the dependency map with a legend
  Resurrect  legacy PL/SQL and the Python port side by side
  Prove      hunt the real port (0 ghosts) or the deliberately wrong draft (ghosts + smallest ghost explained)

Contract under test:
  gravedigger.ui.views (pure Python, no streamlit import needed to test it):
    rs(amount: Decimal) -> str                       "Rs 3,087", "Rs 9,048.50", "Rs 0"
    load_units() -> tuple[Unit, ...]                 the 8 units of BILLING_PKG, in package order
    PORT_OF: dict[str, str]                          legacy unit name -> function name in resurrected.billing
    legacy_source(unit_name) -> str                  the unit's PL/SQL text
    python_source(unit_name) -> str                  the source of the matching Python function
    autopsy_cards() -> tuple[Explanation, ...]       cached autopsy (golden/autopsy), package order, no client
    graph_dot() -> str                               DOT text of the dependency graph
    GRAPH_LEGEND: tuple[tuple[str, str, str], ...]   (name, colour "#rrggbb", meaning) per edge kind + the risk flag
    run_hunt(which: "port" | "draft") -> HuntReport  hunt over golden/cases.json
    ghost_table(report, limit=20) -> list[dict[str, str]]
        keys: "Tariff", "Units", "Oracle total", "Python total", "Difference"; smallest ghost first
    explain_ghost(ghost) -> str                      plain English: why Oracle and Python disagree
  app/streamlit_app.py  (run with: streamlit run app/streamlit_app.py)
  .streamlit/config.toml  dark theme
"""

from __future__ import annotations

import ast
import dataclasses
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from gravedigger.prove.golden import GoldenCase, load_cases, GOLDEN_PATH
from gravedigger.prove.hunt import HuntReport, hunt
from gravedigger.resurrected import billing, billing_draft
from gravedigger.resurrected.billing import BillInput
from gravedigger.ui import views

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "app" / "streamlit_app.py"
UNIT_NAMES = ["f_units", "f_enrg_chg", "f_fix_chg", "f_fpa", "p_taxes", "f_due_dt", "f_lps", "p_gen_bill"]
GHOST_INPUT = BillInput("A1", D("2"), 0, 345, D("1"), datetime(2024, 1, 10), None, None)


# ---------------------------------------------------------------- views: small helpers


@pytest.mark.parametrize(
    "amount, text",
    [(D("3087"), "Rs 3,087"), (D("9048.50"), "Rs 9,048.50"), (D("0"), "Rs 0"), (D("36.75"), "Rs 36.75"),
     (D("12599.00"), "Rs 12,599"), (D("-1"), "-Rs 1")],
)
def test_rupees_are_formatted_for_people(amount, text):
    assert views.rs(amount) == text


def test_units_come_in_package_order():
    assert [u.name for u in views.load_units()] == UNIT_NAMES


def test_every_unit_has_a_python_port():
    assert set(views.PORT_OF) == set(UNIT_NAMES)
    for unit, func in views.PORT_OF.items():
        assert callable(getattr(billing, func)), unit


def test_side_by_side_sources():
    plsql = views.legacy_source("f_lps")
    py = views.python_source("f_lps")
    assert "FUNCTION f_lps" in plsql and "0.1" in plsql
    assert py.lstrip().startswith("def lps(") and "BILLING_PKG.f_lps" in py


# ---------------------------------------------------------------- views: autopsy and graph


def test_autopsy_cards_come_from_the_cache_without_any_model():
    cards = views.autopsy_cards()
    assert [c.unit for c in cards] == UNIT_NAMES
    assert all(c.source == "cache" for c in cards), "golden/autopsy must cover every unit"
    assert sum(len(c.rules) for c in cards) >= 8


def test_graph_and_legend():
    dot = views.graph_dot()
    assert dot.lstrip().startswith("digraph") and "BILL_HDR" in dot and "p_gen_bill" in dot
    names = [name for name, _, _ in views.GRAPH_LEGEND]
    assert {"calls", "reads", "writes", "uses"} <= set(names)
    assert len(names) == 5  # + the "hides errors" risk flag
    for _, colour, meaning in views.GRAPH_LEGEND:
        assert colour.startswith("#") and len(colour) == 7 and meaning


# ---------------------------------------------------------------- views: the ghost hunt


def test_real_port_hunt_is_clean():
    report = views.run_hunt("port")
    assert isinstance(report, HuntReport)
    assert report.ghosts == () and report.checked == len(load_cases(GOLDEN_PATH)) >= 2000


def test_draft_hunt_matches_the_library_hunt():
    report = views.run_hunt("draft")
    expected = hunt(billing_draft.generate_bill, load_cases(GOLDEN_PATH))
    assert (report.checked, report.matched, len(report.ghosts)) == (expected.checked, expected.matched, len(expected.ghosts))
    assert report.ghosts


def test_unknown_hunt_is_rejected():
    with pytest.raises(ValueError):
        views.run_hunt("acme")


def test_ghost_table_starts_with_the_smallest_ghost_and_is_limited():
    report = views.run_hunt("draft")
    rows = views.ghost_table(report, limit=5)
    assert len(rows) == min(5, len(report.ghosts))
    assert list(rows[0]) == ["Tariff", "Units", "Oracle total", "Python total", "Difference"]
    s = report.smallest
    assert rows[0]["Oracle total"] == views.rs(s.oracle.total)
    assert rows[0]["Python total"] == views.rs(s.python.total)
    assert rows[0]["Difference"] in ("Rs 1", "-Rs 1")


def test_the_ghost_is_explained_in_plain_english():
    report = hunt(billing_draft.generate_bill, (GoldenCase(GHOST_INPUT, billing.generate_bill(GHOST_INPUT)),))
    text = views.explain_ghost(report.smallest)
    assert "Rs 9,049" in text and "Rs 9,048" in text
    assert "Rs 9,048.50" in text  # the total before rounding
    assert "half" in text.lower() and "round()" in text


def test_a_missing_oracle_bill_is_explained_too():
    case = GoldenCase(GHOST_INPUT, None)
    (ghost,) = hunt(billing.generate_bill, (case,)).ghosts
    assert "no bill" in views.explain_ghost(ghost).lower()


# ---------------------------------------------------------------- the hosted app never calls Oracle or an LLM


def _imports_and_calls(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
            imports |= {a.name for a in node.names}
        elif isinstance(node, ast.Call):
            f = node.func
            calls.add(f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else "")
    return imports, calls


@pytest.mark.parametrize("path", [APP, *sorted((REPO_ROOT / "src" / "gravedigger" / "ui").glob("*.py"))],
                         ids=lambda p: p.name)
def test_no_database_and_no_live_llm_in_the_app(path):
    imports, calls = _imports_and_calls(path)
    assert not imports & {"oracledb", "anthropic", "openai", "oracle_runner"}, path
    assert not calls & {"make_client", "build_golden", "run_oracle", "connect"}, path


def test_dark_theme_is_configured():
    text = (REPO_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert "[theme]" in text and 'base = "dark"' in text


# ---------------------------------------------------------------- the app itself (Streamlit AppTest, no browser)


@pytest.fixture(scope="module")
def app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def _texts(at) -> str:
    parts = []
    for kind in ("title", "header", "subheader", "markdown", "caption", "success", "error", "info", "warning"):
        parts += [str(e.value) for e in getattr(at, kind)]
    parts += [f"{m.label} {m.value}" for m in at.metric]
    parts += [e.label for e in at.expander]
    return "\n".join(parts)


def test_app_starts_and_tells_the_story_in_four_tabs(app):
    assert "Grave Digger" in " ".join(t.value for t in app.title)
    labels = [t.label for t in app.tabs]
    assert len(labels) == 4
    for label, word in zip(labels, ["Autopsy", "Graph", "Resurrect", "Prove"]):
        assert word in label


def test_headline_numbers(app):
    values = {m.value for m in app.metric}
    assert f"{len(load_cases(GOLDEN_PATH)):,}" in values  # bills proven against real Oracle
    assert "8" in values  # units raised


def test_autopsy_tab_shows_every_unit_and_its_rules(app):
    labels = " ".join(e.label for e in app.expander)
    for name in UNIT_NAMES:
        assert name in labels
    text = _texts(app)
    first_rule = views.autopsy_cards()[1].rules[0].text  # f_enrg_chg
    assert first_rule in text


def test_graph_tab_draws_the_graph_and_legend(app):
    assert app.get("graphviz_chart"), "the dependency graph must be drawn with st.graphviz_chart"
    text = _texts(app)
    assert "writes" in text and "reads" in text


def test_resurrect_tab_shows_old_and_new_code_side_by_side(app):
    box = app.selectbox(key="resurrect_unit")
    assert list(box.options) == UNIT_NAMES
    box.set_value("f_lps").run()
    code = [c.value for c in app.code]
    assert any("FUNCTION f_lps" in c for c in code)
    assert any("def lps(" in c for c in code)


def test_prove_tab_real_port_has_no_ghosts(app):
    app.button(key="hunt_port").click().run()
    assert not app.exception
    assert any("No ghosts" in s.value for s in app.success)


def test_prove_tab_draft_is_haunted_and_the_smallest_ghost_is_explained(app):
    app.button(key="hunt_draft").click().run()
    assert not app.exception
    report = views.run_hunt("draft")
    assert any(f"{len(report.ghosts)} ghost" in e.value for e in app.error)
    text = _texts(app)
    assert views.explain_ghost(report.smallest) in text
    assert app.dataframe or app.table, "the ghosts are listed in a table"
