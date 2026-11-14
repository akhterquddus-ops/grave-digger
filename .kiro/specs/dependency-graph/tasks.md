# Implementation Plan: Dependency Graph

## Overview

Implement one module, `src/gravedigger/autopsy/graph.py`, in Python 3.12, so that the 16 existing acceptance tests in `tests/test_autopsy_graph.py` pass. The full suite must then report 53 passing tests (37 existing plus those 16).

Scope for this plan:

- Create only `src/gravedigger/autopsy/graph.py`.
- Add no new test file and modify no existing test file.
- Use the standard library and `gravedigger` imports only. The module must not parse PL/SQL: no `re` import and no tokenizing or splitting of source text. All facts come from `load_package` (via `Package`) and `scan` (via `Facts`).
- Write the file as UTF-8 without BOM with LF line endings.
- Run commands in PowerShell from the project root `C:\Akhtar-Works\grave-digger`.

## Tasks

- [x] 1. Data types and `build_graph`
  - [x] 1.1 Create `graph.py` with the frozen dataclasses and constants
    - Create `src/gravedigger/autopsy/graph.py` with `from __future__ import annotations` and imports limited to `dataclasses`, `typing` and `gravedigger` (`Facts`, `scan` from `gravedigger.autopsy.scanner`; `Package`, `Unit` from `gravedigger.exhume`)
    - Import `scan` as a module-level name so that it can be patched as `gravedigger.autopsy.graph.scan`
    - Define `NodeKind` and `EdgeKind` literals
    - Define frozen dataclasses `Node(id, kind, label, risks=())`, `Edge(source, target, kind)`, `Graph(nodes, edges)`, `Theme` (background, text, purple, red, plus teal, amber, grey and any fill colour needed) and `EdgeStyle(color, style, penwidth)`
    - Define the module constants `SWALLOW_RISK` (ASCII plain-English sentence containing `swallow`), `THEME` (a frozen `Theme` with a dark background, light text, purple accents) and `EDGE_STYLES` (mapping each edge kind to an `EdgeStyle`, built from `THEME`): calls purple/solid/1.5, reads teal/dashed/1.0, writes amber/solid/3.0, uses grey/dotted/1.0
    - Keep every colour string inside `THEME` only
    - _Requirements: 5.3, 5.4, 5.5, 8.5, 8.6, 9.3, 9.4_

  - [x] 1.2 Implement the private helpers and `build_graph`
    - Implement `_unit_node(unit, facts)` with label `f"{unit.name} ({unit.kind})"` and `risks=(SWALLOW_RISK,)` only when `facts.swallows_errors` is true
    - Implement `_table_nodes(all_facts)` and `_global_nodes(all_facts)`: one node per distinct name in the union of `tables_read` and `tables_written`, and of `globals_used`; label equals id; no risks
    - Implement `_edges_for(unit, facts, unit_names)` returning a frozenset of `calls` (only names that are units of the package), `reads`, `writes` and `uses` edges
    - Implement `_node_key` as `(kind, id)` and `_edge_key` as `(kind, source, target)`
    - Implement `build_graph(package)`: call `scan` exactly once per unit inside a tuple comprehension (so an exception propagates unchanged), union the edge sets to remove duplicates, and return a `Graph` with nodes and edges sorted by the keys above; an empty package gives empty tuples
    - Add docstrings that explain the function in plain English; no PL/SQL parsing
    - _Requirements: 1.1, 1.3, 1.5, 1.7, 1.8, 1.9, 2.1, 2.3, 3.1, 3.2, 3.3, 3.4, 3.9, 3.10, 3.11, 4.1, 4.2, 4.3, 5.1, 5.2, 5.6, 5.7_

- [x] 2. DOT output
  - [x] 2.1 Implement `_escape` and the label helper
    - Implement `_escape(text)`: backslash to `\\`, double quote to `\"`, then CR LF, CR and LF each to the two characters `\n`
    - Implement `_unit_label(node)`: the label, then each risk in order, joined by the two-character `\n`, all escaped; a node with no risks gets the label alone with no trailing `\n`
    - _Requirements: 2.4, 7.3, 7.4, 10.3, 10.4, 10.6_

  - [x] 2.2 Implement the statement helpers and `to_dot`
    - Implement `_node_statement(node)`: one line ending in `];`, id quoted and escaped; unit nodes use `shape=box`, `style="rounded,filled"` and exactly one `color` attribute (purple when safe, red when the node has risks); table nodes use `shape=cylinder`; global nodes use `shape=note`; table and global outlines use a non-red theme colour; look kinds up in constant mappings so an unknown kind raises `KeyError`
    - Implement `_edge_statement(edge)`: one line `"source" -> "target" [color=..., style=..., penwidth=...];` using `EDGE_STYLES[edge.kind]`
    - Implement `to_dot(graph)`: emit `digraph "autopsy" {`, a preamble with exactly one `rankdir=LR`, `bgcolor` and light `fontcolor` on the graph, node defaults and edge defaults (all from `THEME`), then node statements sorted by `(kind, id)`, then edge statements sorted by `(kind, source, target)`, then `}`; use LF as the only separator, two-space indent, and write no braces inside labels; an empty graph still emits the preamble
    - Re-sort inside `to_dot` so that input order never changes the output
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 7.1, 7.2, 7.5, 8.1, 8.2, 8.3, 8.4, 8.7, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.5_

- [x] 3. Checkpoint - Acceptance tests
  - Run `.venv\Scripts\python.exe -m pytest tests/test_autopsy_graph.py -q` from the project root and confirm all 16 tests pass
  - Fix `graph.py` (never the tests) if any test fails, then re-run
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Final checkpoint - Full suite
  - [x] 4.1 Run the whole suite and confirm 53 passing tests
    - Run `.venv\Scripts\python.exe -m pytest -q` from the project root
    - Confirm the summary reports 53 passed (37 existing plus 16 in `tests/test_autopsy_graph.py`) with no failures or errors; Oracle tests, if any, may only be counted as skipped if they are not part of the 53, so report the exact summary line
    - Confirm with `git status` that no file under `tests/` was added or changed
    - Ensure all tests pass, ask the user if questions arise.
    - _Requirements: 1.1 to 10.6 (whole feature)_

## Notes

- The design's Hypothesis property test file (`tests/test_autopsy_graph_properties.py`, Properties 1 to 12 and the example tests) is deliberately left out. This keeps the suite at exactly 53 tests. It can be added later as a separate task without changing `graph.py`.
- Because of that, this plan has no test sub-tasks and no `*` optional tasks. The 16 existing acceptance tests and the two checkpoint runs are the verification.
- Requirements not covered by the 16 acceptance tests (for example 5.3, 7.3, 7.4 and 8.5 to 8.7) are still implemented as specified in the design, but are not asserted by any test until the property file is added.
- Do not modify `requirements.md`, `design.md` or any existing test file.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1"] },
    { "id": 3, "tasks": ["2.2"] },
    { "id": 4, "tasks": ["4.1"] }
  ]
}
```
