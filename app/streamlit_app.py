"""Grave Digger: the public demo page (layout only).

All data and text logic lives in ``gravedigger.ui.views``. This page needs no
database, no LLM call and no API key.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

try:
    _SRC = Path(__file__).resolve().parents[1] / "src"
except NameError:  # __file__ is undefined when the script is exec'd without a path
    _SRC = Path.cwd() / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import streamlit as st  # noqa: E402

from gravedigger.ui.views import (  # noqa: E402
    CI_BADGE_URL,
    CI_WORKFLOW_URL,
    GRAPH_LEGEND,
    STATIC_NOTE,
    TAGLINE,
    autopsy_cards,
    category_colour,
    citation,
    explain_ghost,
    ghost_table,
    graph_dot,
    headline,
    hunt_headline,
    legacy_source,
    load_units,
    md_escape,
    pill_html,
    python_source,
    run_hunt,
)

st.set_page_config(page_title="Grave Digger", page_icon="🪦", layout="wide")

AUTOPSY_INTRO = (
    "Here is what each old billing step really does, in plain English, "
    "with the line of old code each rule came from."
)
GRAPH_INTRO = "This map shows which step calls which, and which tables each step reads or writes."
RESURRECT_INTRO = "Pick a step to see the old Oracle code and its new Python twin side by side."
PROVE_INTRO = (
    "Bill every stored Oracle customer again in Python. "
    "A ghost is a bill where the two disagree."
)


def _header() -> None:
    """Title, tagline, CI badge and the three headline numbers."""
    numbers = headline()
    st.title("🪦 Grave Digger")
    st.caption(TAGLINE)
    st.markdown(f"[![CI]({CI_BADGE_URL})]({CI_WORKFLOW_URL})")
    col_units, col_rules, col_bills = st.columns(3)
    col_units.metric("Units raised", str(numbers.units_raised))
    col_rules.metric("Rules found", str(numbers.rules_found))
    col_bills.metric("Oracle bills proven", f"{numbers.bills_proven:,}")


def _tab_autopsy() -> None:
    st.markdown(AUTOPSY_INTRO)
    for card in autopsy_cards():
        with st.expander(card.unit):
            if card.source == "static":
                st.caption(STATIC_NOTE)
            st.markdown(md_escape(card.summary))
            for rule in card.rules:
                left, right = st.columns([5, 2])
                left.markdown(md_escape(rule.text))
                right.markdown(
                    pill_html(rule.category, category_colour(rule.category)),
                    unsafe_allow_html=True,
                )
                right.caption(citation(rule))
            if card.dropped:
                st.caption(
                    "Rules the checker threw out, because the AI invented them or got them wrong:"
                )
                for item in card.dropped:
                    st.caption(
                        f"~~{md_escape(item.rule.text)}~~  \n"
                        f"Why it was dropped: {md_escape(item.reason)}"
                    )


def _tab_graph() -> None:
    st.markdown(GRAPH_INTRO)
    left, right = st.columns([4, 1])
    left.graphviz_chart(graph_dot())
    right.markdown("**Colour key**")
    for name, colour, meaning in GRAPH_LEGEND:
        right.markdown(
            pill_html(name, colour) + " " + html.escape(meaning),
            unsafe_allow_html=True,
        )


def _tab_resurrect() -> None:
    st.markdown(RESURRECT_INTRO)
    names = [unit.name for unit in load_units()]
    selected = st.selectbox("Pick a billing step", options=names, key="resurrect_unit")
    old, new = st.columns(2)
    old.caption("Old: Oracle PL/SQL")
    old.code(legacy_source(selected), language="sql")
    new.caption("New: Python")
    new.code(python_source(selected), language="python")


def _show_hunt(which: str) -> None:
    report = run_hunt(which)
    if not report.ghosts:
        st.success(hunt_headline(report))
        return
    st.error(hunt_headline(report))
    st.caption("The smallest ghost, explained:")
    st.info(explain_ghost(report.smallest), icon="👻")
    st.caption("The first ghosts found:")
    st.dataframe(ghost_table(report), hide_index=True)


def _tab_prove() -> None:
    st.markdown(PROVE_INTRO)
    col_port, col_draft = st.columns(2)
    if col_port.button("Hunt the real port", key="hunt_port"):
        st.session_state["hunt_shown"] = "port"
    if col_draft.button("Hunt the wrong draft", key="hunt_draft"):
        st.session_state["hunt_shown"] = "draft"
    shown = st.session_state.get("hunt_shown")
    if shown is not None:
        _show_hunt(shown)


def main() -> None:
    """Draw the whole page."""
    try:
        _header()
    except (FileNotFoundError, ValueError) as err:
        st.error(f"The graveyard files could not be read: {err}")
        st.stop()
    tab_autopsy, tab_graph, tab_resurrect, tab_prove = st.tabs(
        ["🪦 Autopsy", "🕸️ Graph", "⚰️ Resurrect", "👻 Prove"]
    )
    with tab_autopsy:
        _tab_autopsy()
    with tab_graph:
        _tab_graph()
    with tab_resurrect:
        _tab_resurrect()
    with tab_prove:
        _tab_prove()


main()
