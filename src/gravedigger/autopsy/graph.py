"""Dependency graph of a legacy PL/SQL package (Autopsy stage).

Turns a loaded package into nodes (units, tables, globals) and edges
(calls, reads, writes, uses), then draws it as Graphviz DOT text.
All facts come from ``load_package`` and ``scan``; nothing is parsed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from gravedigger.autopsy.scanner import Facts, scan
from gravedigger.exhume import Package, Unit

NodeKind = Literal["unit", "table", "global"]
EdgeKind = Literal["calls", "reads", "writes", "uses"]


@dataclass(frozen=True)
class Node:
    """One box in the picture: a unit, a table or a package global."""

    id: str
    kind: NodeKind
    label: str
    risks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Edge:
    """One arrow in the picture, from a unit to something it depends on."""

    source: str
    target: str
    kind: EdgeKind


@dataclass(frozen=True)
class Graph:
    """All nodes and edges of one package."""

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]


@dataclass(frozen=True)
class Theme:
    """Every colour used in the DOT output."""

    background: str
    text: str
    purple: str
    red: str
    teal: str
    amber: str
    grey: str
    fill: str


@dataclass(frozen=True)
class EdgeStyle:
    """How one kind of edge is drawn."""

    color: str
    style: str
    penwidth: str


SWALLOW_RISK = "Swallows errors: WHEN OTHERS THEN NULL hides failures"

THEME = Theme(
    background="#1a1423",
    text="#e8e0f0",
    purple="#9b6bd6",
    red="#ff4d4d",
    teal="#2ec4b6",
    amber="#ffb347",
    grey="#8a8497",
    fill="#2a2038",
)

EDGE_STYLES: dict[str, EdgeStyle] = {
    "calls": EdgeStyle(THEME.purple, "solid", "1.5"),
    "reads": EdgeStyle(THEME.teal, "dashed", "1.0"),
    "writes": EdgeStyle(THEME.amber, "solid", "3.0"),
    "uses": EdgeStyle(THEME.grey, "dotted", "1.0"),
}


def _unit_node(unit: Unit, facts: Facts) -> Node:
    """Make the box for one unit, flagged with a risk if it hides errors."""
    risks = (SWALLOW_RISK,) if facts.swallows_errors else ()
    return Node(unit.name, "unit", f"{unit.name} ({unit.kind})", risks)


def _table_nodes(all_facts: tuple[Facts, ...]) -> tuple[Node, ...]:
    """Make one box per table that any unit reads or writes."""
    names = frozenset().union(
        *(f.tables_read | f.tables_written for f in all_facts)
    )
    return tuple(Node(name, "table", name) for name in names)


def _global_nodes(all_facts: tuple[Facts, ...]) -> tuple[Node, ...]:
    """Make one box per package global that any unit uses."""
    names = frozenset().union(*(f.globals_used for f in all_facts))
    return tuple(Node(name, "global", name) for name in names)


def _edges_for(
    unit: Unit, facts: Facts, unit_names: frozenset[str]
) -> frozenset[Edge]:
    """List the arrows leaving one unit: calls, reads, writes and uses.

    Calls to names that are not units of the package are left out.
    """
    return frozenset(
        {Edge(unit.name, name, "calls") for name in facts.calls if name in unit_names}
        | {Edge(unit.name, name, "reads") for name in facts.tables_read}
        | {Edge(unit.name, name, "writes") for name in facts.tables_written}
        | {Edge(unit.name, name, "uses") for name in facts.globals_used}
    )


def _node_key(node: Node) -> tuple[str, str]:
    """Sort key for nodes: kind first, then id."""
    return (node.kind, node.id)


def _edge_key(edge: Edge) -> tuple[str, str, str]:
    """Sort key for edges: kind first, then source, then target."""
    return (edge.kind, edge.source, edge.target)


def build_graph(package: Package) -> Graph:
    """Build the dependency graph of a loaded package.

    Each unit is scanned exactly once. Nodes and edges come back in a fixed
    order, so the same package always gives the same graph.
    """
    scanned = tuple((unit, scan(unit)) for unit in package.units)
    unit_names = frozenset(unit.name for unit in package.units)
    all_facts = tuple(facts for _, facts in scanned)
    nodes = (
        *(_unit_node(unit, facts) for unit, facts in scanned),
        *_table_nodes(all_facts),
        *_global_nodes(all_facts),
    )
    edges = frozenset[Edge]().union(
        *(_edges_for(unit, facts, unit_names) for unit, facts in scanned)
    )
    return Graph(
        tuple(sorted(nodes, key=_node_key)),
        tuple(sorted(edges, key=_edge_key)),
    )


def _escape(text: str) -> str:
    """Make text safe to put inside a double-quoted DOT string.

    Backslashes and double quotes get a backslash in front. Every line break
    (CR LF, CR or LF) becomes the two characters backslash and n, so the
    text always stays on one line.
    """
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
    )


def _unit_label(node: Node) -> str:
    """Write the text drawn inside a node: its label, then each risk.

    Each part is escaped first and the parts are then joined with the
    two-character backslash-n, so the joiner itself is not escaped again.
    A node with no risks gives just its escaped label.
    """
    return "\\n".join(_escape(part) for part in (node.label, *node.risks))


NODE_SHAPES: dict[str, str] = {
    "unit": "box",
    "table": "cylinder",
    "global": "note",
}

# Outline colour per node kind. Units are handled separately (purple or red).
NODE_OUTLINES: dict[str, str] = {
    "unit": THEME.purple,
    "table": THEME.teal,
    "global": THEME.grey,
}


def _node_statement(node: Node) -> str:
    """Write one DOT line for a node, ending in ``];``.

    Units are rounded boxes with a purple outline, or a red outline when the
    node carries risks. Tables are cylinders and globals are notes, with a
    non-red outline. An unknown kind raises KeyError.
    """
    shape = NODE_SHAPES[node.kind]
    outline = NODE_OUTLINES[node.kind]
    if node.kind == "unit" and node.risks:
        outline = THEME.red
    style = '"rounded,filled"' if node.kind == "unit" else "filled"
    return (
        f'"{_escape(node.id)}" '
        f'[label="{_unit_label(node)}", shape={shape}, style={style}, '
        f'color="{outline}", fillcolor="{THEME.fill}"];'
    )


def _edge_statement(edge: Edge) -> str:
    """Write one DOT line for an edge, styled by its kind.

    An unknown kind raises KeyError.
    """
    look = EDGE_STYLES[edge.kind]
    return (
        f'"{_escape(edge.source)}" -> "{_escape(edge.target)}" '
        f'[color="{look.color}", style={look.style}, penwidth={look.penwidth}];'
    )


def to_dot(graph: Graph) -> str:
    """Draw the graph as Graphviz DOT text.

    Nodes come first, sorted by kind then id. Edges follow, sorted by kind,
    source, target. The order of the input never changes the output. Lines
    are separated by LF only.
    """
    lines = [
        'digraph "autopsy" {',
        f'  graph [rankdir=LR, bgcolor="{THEME.background}", '
        f'fontcolor="{THEME.text}", fontname="Helvetica"];',
        f'  node [fontcolor="{THEME.text}", fontname="Helvetica"];',
        f'  edge [fontcolor="{THEME.text}"];',
        *(
            f"  {_node_statement(node)}"
            for node in sorted(graph.nodes, key=_node_key)
        ),
        *(
            f"  {_edge_statement(edge)}"
            for edge in sorted(graph.edges, key=_edge_key)
        ),
        "}",
    ]
    return "\n".join(lines) + "\n"
