"""Acceptance tests for the Autopsy dependency graph (Kiro spec: dependency-graph).

Contract under test:
  gravedigger.autopsy.graph.build_graph(package) -> Graph
  gravedigger.autopsy.graph.to_dot(graph) -> str   (Graphviz DOT text)

Graph(nodes: tuple[Node, ...], edges: tuple[Edge, ...])
Node(id, kind, label, risks)      kind in {"unit", "table", "global"}
Edge(source, target, kind)        kind in {"calls", "reads", "writes", "uses"}

The graph is what the Autopsy page draws: which unit calls which, which tables
each unit reads and writes, and which package globals it touches. Units that
hide failures (WHEN OTHERS THEN NULL) are marked as a risk.
"""

from __future__ import annotations

import re

import pytest

from gravedigger.autopsy.graph import build_graph, to_dot
from gravedigger.exhume import load_package

UNITS = {"f_units", "f_enrg_chg", "f_fix_chg", "f_fpa", "p_taxes", "f_due_dt", "f_lps", "p_gen_bill"}
TABLES = {"CUST_MST", "MTR_RDG", "FPA_RT", "PYMT", "BILL_HDR"}


@pytest.fixture(scope="module")
def graph(legacy_sources):
    return build_graph(load_package(*legacy_sources))


def node_ids(graph, kind):
    return {n.id for n in graph.nodes if n.kind == kind}


def edges_of(graph, kind):
    return {(e.source, e.target) for e in graph.edges if e.kind == kind}


# ---------------------------------------------------------------- nodes


def test_unit_nodes(graph):
    assert node_ids(graph, "unit") == UNITS


def test_table_nodes(graph):
    assert node_ids(graph, "table") == TABLES


def test_global_nodes(graph):
    assert node_ids(graph, "global") == {"g_dbg"}


def test_node_ids_are_unique(graph):
    ids = [n.id for n in graph.nodes]
    assert len(ids) == len(set(ids))


def test_unit_labels_say_what_they_are(graph):
    labels = {n.id: n.label for n in graph.nodes}
    assert "f_enrg_chg" in labels["f_enrg_chg"]
    assert "function" in labels["f_enrg_chg"].lower()
    assert "procedure" in labels["p_gen_bill"].lower()


# ---------------------------------------------------------------- edges


def test_call_edges(graph):
    assert edges_of(graph, "calls") == {
        ("p_gen_bill", u) for u in UNITS - {"p_gen_bill"}
    }


def test_read_edges(graph):
    assert edges_of(graph, "reads") == {
        ("f_fpa", "FPA_RT"),
        ("p_gen_bill", "CUST_MST"),
        ("p_gen_bill", "MTR_RDG"),
        ("p_gen_bill", "PYMT"),
    }


def test_write_edges(graph):
    assert edges_of(graph, "writes") == {("p_gen_bill", "BILL_HDR")}


def test_global_use_edges(graph):
    assert edges_of(graph, "uses") == {
        ("f_units", "g_dbg"),
        ("f_enrg_chg", "g_dbg"),
        ("f_fix_chg", "g_dbg"),
        ("p_gen_bill", "g_dbg"),
    }


def test_every_edge_points_at_a_known_node(graph):
    ids = {n.id for n in graph.nodes}
    for e in graph.edges:
        assert e.source in ids and e.target in ids, e


# ---------------------------------------------------------------- risks


def test_swallowed_errors_are_a_risk(graph):
    risks = {n.id: n.risks for n in graph.nodes}
    assert any("swallow" in r.lower() for r in risks["p_gen_bill"])
    assert risks["f_units"] == ()


# ---------------------------------------------------------------- DOT output


def test_dot_is_a_directed_graph(graph):
    dot = to_dot(graph)
    assert dot.lstrip().startswith("digraph")
    assert dot.rstrip().endswith("}")
    assert dot.count("{") == dot.count("}")


def test_dot_contains_every_node_and_edge(graph):
    dot = to_dot(graph)
    for n in graph.nodes:
        assert f'"{n.id}"' in dot
    arrows = re.findall(r'"([^"]+)"\s*->\s*"([^"]+)"', dot)
    assert len(arrows) == len(graph.edges)
    assert set(arrows) == {(e.source, e.target) for e in graph.edges}


def _node_attrs(dot: str, node_id: str) -> str:
    m = re.search(r'^\s*"' + re.escape(node_id) + r'"\s*\[(.*?)\]\s*;?\s*$', dot, re.M)
    assert m, f"no single-line node statement for {node_id}"
    return m.group(1)


def test_each_node_statement_is_one_line(graph):
    """Multi-line labels must use the escaped \\n, never a raw line break."""
    dot = to_dot(graph)
    for n in graph.nodes:
        _node_attrs(dot, n.id)


def test_dot_marks_the_risky_unit(graph):
    """The risky unit carries a colour that safe units do not (e.g. a red outline)."""
    dot = to_dot(graph)
    risky = _node_attrs(dot, "p_gen_bill")
    safe = _node_attrs(dot, "f_units")
    assert re.search(r"color\s*=", risky)
    assert risky != safe


def test_dot_is_deterministic(graph, legacy_sources):
    again = build_graph(load_package(*legacy_sources))
    assert to_dot(graph) == to_dot(again)
