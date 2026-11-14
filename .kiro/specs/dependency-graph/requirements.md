# Requirements Document

## Introduction

The dependency graph is the picture on the Autopsy page of Grave Digger. It shows which unit calls which unit, which tables each unit reads and writes, and which package globals each unit touches. Units that hide failures (`WHEN OTHERS THEN NULL`) are marked as a risk, in the data and in the picture.

The graph is built from the output of the existing `load_package` (`gravedigger.exhume`) and `scan` (`gravedigger.autopsy.scanner`). The graph module never parses PL/SQL itself. The module is `src/gravedigger/autopsy/graph.py` and offers two functions: `build_graph(package) -> Graph` and `to_dot(graph) -> str`. The acceptance tests are in `tests/test_autopsy_graph.py` and are not modified by this feature.

The picture is Graphviz DOT text, rendered by the app with `st.graphviz_chart`. It reads left to right, uses a dark Halloween theme, and is identical on every run for the same package.

## Glossary

- **Graph_Builder**: The function `build_graph` in `gravedigger.autopsy.graph`.
- **DOT_Writer**: The function `to_dot` in `gravedigger.autopsy.graph`.
- **Package**: The frozen dataclass returned by `load_package`, holding `name`, `globals` and `units`.
- **Facts**: The frozen dataclass returned by `scan` for one unit. Its fields used here are `calls`, `tables_read`, `tables_written`, `globals_used` and `swallows_errors`.
- **Graph**: Frozen dataclass with `nodes` (tuple of Node) and `edges` (tuple of Edge).
- **Node**: Frozen dataclass with `id`, `kind`, `label` and `risks`. `kind` is `unit`, `table` or `global`. `risks` is a tuple of plain-English texts.
- **Edge**: Frozen dataclass with `source`, `target` and `kind`. `kind` is `calls`, `reads`, `writes` or `uses`.
- **Unit_Node**: A Node of kind `unit`. Its `id` is the unit name as returned by `load_package` (lower case).
- **Table_Node**: A Node of kind `table`. Its `id` is the table name as returned by `scan` (upper case).
- **Global_Node**: A Node of kind `global`. Its `id` is the global name as returned by `load_package` (lower case).
- **Swallowed_Error**: A unit for which `Facts.swallows_errors` is true.
- **Node_Statement**: The DOT text that declares one node, such as `"f_units" [shape=box, ...];`.
- **Edge_Statement**: The DOT text that declares one edge, such as `"p_gen_bill" -> "f_units" [...];`.
- **Escaped_Newline**: The two characters backslash and `n` inside a DOT label, which Graphviz draws as a line break.
- **Theme**: The fixed set of DOT colours and fonts: dark background, light text, purple accents.

## Requirements

### Requirement 1: Nodes for units, tables and globals

**User Story:** As a migration engineer, I want one node for every unit, table and global, so that the picture shows every moving part of the package.

#### Acceptance Criteria

1. WHEN a Package is passed to `build_graph`, THE Graph_Builder SHALL return a Graph containing exactly one Unit_Node for each unit of the Package, and no other Unit_Nodes.
2. WHEN the legacy package is passed to `build_graph`, THE Graph_Builder SHALL return exactly eight Unit_Nodes: `f_units`, `f_enrg_chg`, `f_fix_chg`, `f_fpa`, `p_taxes`, `f_due_dt`, `f_lps` and `p_gen_bill`.
3. WHEN a Package is passed to `build_graph`, THE Graph_Builder SHALL return a Graph containing exactly one Table_Node for each distinct table name that appears in `tables_read` or `tables_written` of at least one unit, and no other Table_Nodes.
4. WHEN the legacy package is passed to `build_graph`, THE Graph_Builder SHALL return exactly five Table_Nodes: `CUST_MST`, `MTR_RDG`, `FPA_RT`, `PYMT` and `BILL_HDR`.
5. WHEN a Package is passed to `build_graph`, THE Graph_Builder SHALL return a Graph containing exactly one Global_Node for each distinct global name that appears in `globals_used` of at least one unit, and no other Global_Nodes.
6. WHEN the legacy package is passed to `build_graph`, THE Graph_Builder SHALL return exactly one Global_Node, `g_dbg`.
7. THE Graph_Builder SHALL give every Node of a Graph an `id` that differs from the `id` of every other Node of that Graph.
8. WHEN a table is read or written by several units, or both read and written by one unit, THE Graph_Builder SHALL create exactly one Table_Node for that table.
9. WHEN a Package has no units, THE Graph_Builder SHALL return a Graph whose `nodes` and `edges` are both empty tuples and SHALL NOT raise an error.

### Requirement 2: Readable node labels

**User Story:** As a non-programmer, I want each unit's label to say what it is, so that I can tell functions from procedures without reading code.

#### Acceptance Criteria

1. THE Graph_Builder SHALL set the `label` of each Unit_Node to a non-empty text that contains the exact unit name and the word `function` or `procedure`, matching the unit kind.
2. WHEN the legacy package is passed to `build_graph`, THE Graph_Builder SHALL set the label of `f_enrg_chg` to a text containing both `f_enrg_chg` and `function`, and the label of `p_gen_bill` to a text containing both `p_gen_bill` and `procedure`.
3. THE Graph_Builder SHALL set the `label` of each Table_Node to exactly the table name and the `label` of each Global_Node to exactly the global name, with no prefix, suffix or kind word.
4. WHEN a label spans more than one line, THE DOT_Writer SHALL write each line break as an Escaped_Newline and SHALL write no raw line-break character (LF or CR) inside the quoted label.

### Requirement 3: Edges for calls, reads, writes and global uses

**User Story:** As a migration engineer, I want edges that show calls, table access and global use, so that I can see what depends on what.

#### Acceptance Criteria

1. WHEN a unit has a name in `Facts.calls` that matches a unit of the Package, THE Graph_Builder SHALL create exactly one Edge of kind `calls` from that unit to the called unit, however many times the name appears in `Facts.calls`.
2. WHEN a unit has a name in `Facts.tables_read`, THE Graph_Builder SHALL create exactly one Edge of kind `reads` from that unit to the Table_Node of that table, however many times the name appears.
3. WHEN a unit has a name in `Facts.tables_written`, THE Graph_Builder SHALL create exactly one Edge of kind `writes` from that unit to the Table_Node of that table, however many times the name appears.
4. WHEN a unit has a name in `Facts.globals_used`, THE Graph_Builder SHALL create exactly one Edge of kind `uses` from that unit to the Global_Node of that global, however many times the name appears.
5. WHEN the legacy package is passed to `build_graph`, THE Graph_Builder SHALL return exactly seven `calls` edges, from `p_gen_bill` to each of the other seven units, and no other `calls` edges.
6. WHEN the legacy package is passed to `build_graph`, THE Graph_Builder SHALL return exactly four `reads` edges: `f_fpa` to `FPA_RT`, and `p_gen_bill` to `CUST_MST`, `MTR_RDG` and `PYMT`.
7. WHEN the legacy package is passed to `build_graph`, THE Graph_Builder SHALL return exactly one `writes` edge, from `p_gen_bill` to `BILL_HDR`.
8. WHEN the legacy package is passed to `build_graph`, THE Graph_Builder SHALL return exactly four `uses` edges, all to `g_dbg`, from `f_units`, `f_enrg_chg`, `f_fix_chg` and `p_gen_bill`.
9. THE Graph_Builder SHALL set `source` and `target` of every Edge to the `id` of a Node of the same Graph.
10. THE Graph_Builder SHALL create no two Edges with the same source, target and kind.
11. IF a name in `Facts.calls` matches no unit of the Package, THEN THE Graph_Builder SHALL create no `calls` Edge for that name and SHALL NOT raise an error.

### Requirement 4: Risk marking of swallowed errors

**User Story:** As a migration engineer, I want units that hide failures flagged, so that I know where the legacy code may lose errors silently.

#### Acceptance Criteria

1. WHEN a unit is a Swallowed_Error, THE Graph_Builder SHALL set the `risks` of its Unit_Node to a tuple of exactly one non-empty plain-English text that contains the word `swallow`, in any letter case.
2. WHEN a unit is not a Swallowed_Error, THE Graph_Builder SHALL set the `risks` of its Unit_Node to an empty tuple.
3. THE Graph_Builder SHALL set the `risks` of every Table_Node and Global_Node to an empty tuple.
4. WHEN the legacy package is passed to `build_graph`, THE Graph_Builder SHALL give `p_gen_bill` a swallowing risk and `f_units` an empty `risks` tuple.

### Requirement 5: Reuse of Exhume and the scanner

**User Story:** As a maintainer, I want the graph to reuse the existing loader and scanner, so that one place defines what a call, a table or a swallowed error is.

#### Acceptance Criteria

1. THE Graph_Builder SHALL take every unit, global, call, table, global use and Swallowed_Error fact from the Package and from the result of `scan`, and SHALL contain no PL/SQL parsing of its own (no tokenizing, regular-expression matching or splitting of PL/SQL source text).
2. WHEN the Graph_Builder builds a Graph from a Package of N units, THE Graph_Builder SHALL call `scan` exactly N times, once for each unit.
3. THE `graph.py` module SHALL import only the Python standard library and modules of the `gravedigger` package.
4. THE Graph_Builder SHALL return Graph, Node and Edge values as frozen dataclasses.
5. WHEN code assigns to a field of a Graph, Node or Edge, THE Graph, Node or Edge value SHALL raise `dataclasses.FrozenInstanceError` and keep its previous field value.
6. THE Graph_Builder SHALL read no file, use no network and keep no global state, so that two builds from the same Package return equal Graph values.
7. IF `scan` raises an exception for a unit, THEN THE Graph_Builder SHALL let that exception propagate unchanged and SHALL return no Graph.

### Requirement 6: Deterministic DOT text

**User Story:** As a developer, I want the same package to give the same DOT text every time, so that the picture and any test on it are stable.

#### Acceptance Criteria

1. WHEN a Graph is passed to `to_dot`, THE DOT_Writer SHALL return text whose first non-whitespace characters are `digraph` and whose last non-whitespace character is a closing brace `}`.
2. THE DOT_Writer SHALL return text with the same number of opening and closing braces.
3. THE DOT_Writer SHALL write the Node_Statements sorted ascending by node kind and then by `id`, and the Edge_Statements sorted ascending by edge kind, then `source`, then `target`, using code-point string comparison that does not depend on locale.
4. WHEN `build_graph` and `to_dot` run twice on the same legacy sources, THE DOT_Writer SHALL return character-for-character identical text both times.
5. WHEN two Graphs hold the same nodes and edges in a different order, THE DOT_Writer SHALL return identical text for both.
6. THE DOT_Writer SHALL write each Node_Statement and each Edge_Statement on exactly one line, and SHALL use the line feed character as the only line separator.
7. THE DOT_Writer SHALL write each node `id` and each edge endpoint in double quotes.
8. WHEN a Graph with zero nodes and zero edges is passed to `to_dot`, THE DOT_Writer SHALL return valid DOT text that satisfies criteria 1 and 2.

### Requirement 7: Complete DOT content

**User Story:** As a user of the Autopsy page, I want every node and edge in the picture, so that nothing in the dependency map is missing.

#### Acceptance Criteria

1. THE DOT_Writer SHALL write exactly one Node_Statement for each Node of the Graph.
2. THE DOT_Writer SHALL write exactly one Edge_Statement for each Edge of the Graph, and no other Edge_Statement.
3. WHEN a `label` or `id` contains a double quote or a backslash, THE DOT_Writer SHALL prefix that character with one backslash so that the DOT text stays valid and shows the original text.
4. WHEN a `label` or risk text contains a raw line-break character (CR, LF or CR LF), THE DOT_Writer SHALL replace each line break with one Escaped_Newline.
5. WHEN the Graph is empty, THE DOT_Writer SHALL return a valid `digraph` with the Theme settings and no Node_Statement or Edge_Statement.

### Requirement 8: Readable layout and shapes

**User Story:** As a non-programmer, I want different shapes for different things, so that I can read the picture at a glance.

#### Acceptance Criteria

1. THE DOT_Writer SHALL write exactly one graph-level `rankdir=LR` so that the picture reads from left to right.
2. THE DOT_Writer SHALL draw each Unit_Node as a rounded box (`shape=box` with `style` containing `rounded`).
3. THE DOT_Writer SHALL draw each Table_Node as a cylinder (`shape=cylinder`).
4. THE DOT_Writer SHALL draw each Global_Node as a note (`shape=note`).
5. THE DOT_Writer SHALL draw each Edge of kind `writes` with a numeric `penwidth` strictly greater than the `penwidth` of each Edge of kind `reads`.
6. THE DOT_Writer SHALL give each of the four edge kinds a combination of `color`, `style` and `penwidth` that differs from that of each other kind in at least one of the three.
7. THE DOT_Writer SHALL apply the same attribute values to every Edge of the same kind within one DOT text.

### Requirement 9: Halloween dark theme

**User Story:** As the owner of the Grave Digger app, I want a dark purple theme, so that the picture fits the app's graveyard look.

#### Acceptance Criteria

1. THE DOT_Writer SHALL set a dark `bgcolor` on the graph.
2. THE DOT_Writer SHALL set a light `fontcolor` on the graph, on the default node attributes and on the default edge attributes.
3. THE DOT_Writer SHALL use purple for the outline of safe Unit_Nodes and for the edges of kind `calls`.
4. THE DOT_Writer SHALL take all colours from one Theme definition and SHALL write no colour that is missing from that Theme.
5. WHEN the Graph is empty, THE DOT_Writer SHALL still write `bgcolor` and the `fontcolor` settings from the Theme.

### Requirement 10: Red outline for risky units

**User Story:** As a migration engineer, I want risky units drawn with a red outline, so that error-swallowing code stands out in the picture.

#### Acceptance Criteria

1. WHEN a Unit_Node has at least one risk, THE DOT_Writer SHALL write exactly one `color` attribute with a red value on its Node_Statement.
2. WHEN a Unit_Node has no risk, THE DOT_Writer SHALL write a Node_Statement whose `color` value is not red.
3. WHEN a Unit_Node has at least one risk, THE DOT_Writer SHALL write its label as the unit name and kind, then each risk text in reported order, with an Escaped_Newline between the parts.
4. WHEN a Unit_Node has no risk, THE DOT_Writer SHALL write a label with no risk text and no trailing Escaped_Newline.
5. WHEN the legacy package is passed to `build_graph` and `to_dot`, THE DOT_Writer SHALL write a red `color` on the `p_gen_bill` Node_Statement and a different, non-red `color` on the `f_units` Node_Statement.
6. WHEN a risk text contains a double quote, backslash or line break, THE DOT_Writer SHALL escape it so that the DOT text stays valid.