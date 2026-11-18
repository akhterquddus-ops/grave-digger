# Requirements Document

## Introduction

The public demo app is what hackathon judges open and click. It tells the whole Grave Digger story in four tabs (Autopsy, Graph, Resurrect, Prove) for readers who are not programmers. It needs no database, no live LLM call and no API key. Every fact shown comes from files in the repository (`legacy/`, `golden/autopsy/`, `golden/cases.json`) and from the Python port itself.

The feature has three parts. `gravedigger.ui.views` holds pure Python functions with no Streamlit import. `app/streamlit_app.py` is a thin page that calls only those functions. `.streamlit/config.toml` sets the dark theme. The acceptance contract is `tests/test_ui.py`; each requirement below names the tests it traces to.

## Glossary

- **Views**: The module `gravedigger.ui.views` (`src/gravedigger/ui/views.py`), made of pure functions with no Streamlit import.
- **App**: The Streamlit page `app/streamlit_app.py`, run with `streamlit run app/streamlit_app.py`.
- **Theme_Config**: The file `.streamlit/config.toml`.
- **Unit**: One procedure or function of the legacy package BILLING_PKG. The package has eight, in this order: f_units, f_enrg_chg, f_fix_chg, f_fpa, p_taxes, f_due_dt, f_lps, p_gen_bill.
- **Port**: The Python function in `gravedigger.resurrected.billing` that reproduces one Unit.
- **Draft**: The deliberately wrong port in `gravedigger.resurrected.billing_draft`, used to show ghosts.
- **Autopsy_Card**: The `Explanation` of one Unit (fields `unit`, `summary`, `rules`, `dropped`, `source`), read from the cache in `golden/autopsy/` (`source` "cache") or, when the cache has no entry for the Unit, built from scanner facts alone by `explain()` with `client=None` (`source` "static").
- **Kept_Rule**: A rule of an Autopsy_Card that passed the guardrail. It has text and cited code line numbers.
- **Dropped_Rule**: An invented rule that the guardrail rejected. It has the rule and the rejection reason.
- **Golden_Cases**: The stored Oracle results in `golden/cases.json`, loaded with `gravedigger.prove.golden.load_cases`.
- **Hunt**: A run of a port over every Golden_Case, returning a `HuntReport`.
- **Ghost**: One input where the port and Oracle disagree.
- **Smallest_Ghost**: The Ghost reported by `HuntReport.smallest`.
- **Legend**: `GRAPH_LEGEND`, a tuple of (name, colour, meaning) entries.
- **Theme_Colours**: The colours of `gravedigger.autopsy.graph.THEME`: background #1a1423, purple #9b6bd6, red #ff4d4d, teal #2ec4b6, amber #ffb347.
- **CI_Badge**: The status badge of the GitHub Actions workflow `prove.yml`.
- **Forbidden_Dependency**: Any of the imports `oracledb`, `anthropic`, `openai`, `oracle_runner`, or any call to `make_client`, `build_golden`, `run_oracle` or `connect`.

## Requirements

### Requirement 1: Format rupee amounts for people

**User Story:** As a judge, I want money shown as readable rupee amounts, so that I can compare Oracle and Python totals at a glance.

#### Acceptance Criteria

1. WHEN `rs` receives a Decimal amount, THE Views SHALL return the text "Rs " followed by the amount with thousands separators, for example "Rs 3,087".
2. WHEN the amount has a non-zero fractional part, THE Views SHALL show it with exactly two decimal places, for example "Rs 9,048.50" and "Rs 36.75".
3. WHEN the amount is a whole number, THE Views SHALL omit the decimal part, so that Decimal("12599.00") gives "Rs 12,599" and Decimal("0") gives "Rs 0".
4. WHEN the amount is negative, THE Views SHALL put the minus sign before "Rs", for example "-Rs 1".
5. THE Views SHALL perform all money handling with `decimal.Decimal` and no float.

_Traces to:_ `test_rupees_are_formatted_for_people`.

### Requirement 2: Load the eight units and their ports

**User Story:** As a judge, I want each legacy unit shown next to its Python port, so that I can see what was raised from the dead.

#### Acceptance Criteria

1. WHEN `load_units` is called, THE Views SHALL return the eight Units of BILLING_PKG, in package order.
2. THE Views SHALL expose `PORT_OF`, a mapping with exactly one entry per Unit name, from the Unit name to the name of a callable in `gravedigger.resurrected.billing`.
3. WHEN `legacy_source` receives a Unit name, THE Views SHALL return the PL/SQL text of that Unit.
4. WHEN `python_source` receives a Unit name, THE Views SHALL return the source text of the matching Port function, beginning at its `def` line.
5. THE Views SHALL return, for `f_lps`, PL/SQL text that contains "FUNCTION f_lps" and "0.1", and Python text that starts with "def lps(" and contains "BILLING_PKG.f_lps".
6. IF a Unit name is not one of the eight Units, THEN THE Views SHALL raise a `KeyError` that names the unknown Unit.

_Traces to:_ `test_units_come_in_package_order`, `test_every_unit_has_a_python_port`, `test_side_by_side_sources`. Criterion 6 is an addition to keep failures explicit.

### Requirement 3: Serve the Autopsy from cache

**User Story:** As a judge, I want to read what each unit does in plain English, so that I understand the old code without reading PL/SQL.

#### Acceptance Criteria

1. WHEN `autopsy_cards` is called, THE Views SHALL return one Autopsy_Card per Unit, in package order.
2. WHEN the cache in `golden/autopsy/` covers a Unit, THE Views SHALL build the Autopsy_Card of that Unit from the cache, so that the card has `source` equal to "cache". The cache covers all eight Units today.
3. THE Views SHALL create no LLM client and need no API key to build the Autopsy_Cards.
4. THE Views SHALL return Autopsy_Cards whose Kept_Rules number at least eight in total.
5. IF the cache has no entry for a Unit, THEN THE Views SHALL build the Autopsy_Card of that Unit by calling `gravedigger.autopsy.explain.explain` with `client` set to None, which builds the card from scanner facts alone with `source` equal to "static", and SHALL call no model.
6. THE Views SHALL build each Autopsy_Card with `explain(unit, facts, client=None, cache_dir=<golden/autopsy>)`, so that the cached card is used when the cache covers the Unit and the static fallback card is used otherwise.

_Traces to:_ `test_autopsy_cards_come_from_the_cache_without_any_model`. Criteria 5 and 6 are additions: they replace an error with the static fallback of `explain()` and keep the no-LLM rule enforceable.

### Requirement 4: Build the dependency graph and its legend

**User Story:** As a judge, I want a map of what depends on what, with a key to the colours, so that I can read the picture without asking.

#### Acceptance Criteria

1. WHEN `graph_dot` is called, THE Views SHALL return Graphviz DOT text that starts with "digraph" and contains the names "BILL_HDR" and "p_gen_bill".
2. THE Views SHALL expose the Legend with five entries: one each for "calls", "reads", "writes" and "uses", and one for the flag of a Unit that hides errors.
3. THE Views SHALL give every Legend entry a colour written as "#" followed by six hexadecimal digits, and a non-empty plain-English meaning.
4. THE Views SHALL take the Legend colours from the edge and risk colours used by `gravedigger.autopsy.graph`, so that the Legend matches the drawn graph.

_Traces to:_ `test_graph_and_legend`.

### Requirement 5: Run the ghost hunt offline

**User Story:** As a judge, I want to hunt the real port and the wrong draft, so that I can see proof that one is correct and the other is haunted.

#### Acceptance Criteria

1. WHEN `run_hunt` receives "port", THE Views SHALL run the Hunt with `billing.generate_bill` over all Golden_Cases and return a `HuntReport`.
2. WHEN `run_hunt` receives "port", THE Views SHALL return a report with no Ghosts and with `checked` equal to the number of Golden_Cases, which is at least 2000.
3. WHEN `run_hunt` receives "draft", THE Views SHALL run the Hunt with `billing_draft.generate_bill` over all Golden_Cases and return a report with the same `checked`, `matched` and Ghost count as the library `hunt`, with at least one Ghost.
4. IF `run_hunt` receives any value other than "port" or "draft", THEN THE Views SHALL raise `ValueError`.
5. THE Views SHALL load Golden_Cases from `golden/cases.json` at most once per process and cache the result of each Hunt, so that a repeated click does not repeat the work.
6. THE Views SHALL run every Hunt without a database connection.

_Traces to:_ `test_real_port_hunt_is_clean`, `test_draft_hunt_matches_the_library_hunt`, `test_unknown_hunt_is_rejected`.

### Requirement 6: List ghosts in a table

**User Story:** As a judge, I want a short table of the disagreements, smallest first, so that I can see exactly where Oracle and Python differ.

#### Acceptance Criteria

1. WHEN `ghost_table` receives a report and a limit, THE Views SHALL return a list of rows with at most `limit` rows, and `limit` SHALL default to 20.
2. THE Views SHALL give every row exactly the keys "Tariff", "Units", "Oracle total", "Python total" and "Difference", in that order.
3. THE Views SHALL order the rows with the Smallest_Ghost first.
4. THE Views SHALL write the totals and the difference with `rs`, so that the first row's "Oracle total" and "Python total" equal `rs` of the Smallest_Ghost totals.
5. WHEN the Smallest_Ghost differs by one rupee, THE Views SHALL show its "Difference" as "Rs 1" or "-Rs 1".
6. WHEN the report has no Ghosts, THE Views SHALL return an empty list.
7. WHEN the Oracle wrote no bill for a Ghost, THE Views SHALL show a plain-English marker such as "no bill" in the "Oracle total" cell of its row.
8. THE Views SHALL write the "Tariff" cell of each row in plain English from the `tariff` field of the input of the Ghost: "A1 (home)" for the tariff "A1" and "A2 (shop)" for the tariff "A2".
9. IF the `tariff` of a Ghost input is neither "A1" nor "A2", THEN THE Views SHALL write the tariff code itself in the "Tariff" cell.

_Traces to:_ `test_ghost_table_starts_with_the_smallest_ghost_and_is_limited`. Criteria 6 to 9 cover cases the test does not build or check. Criterion 9 matches the legacy code, which accepts any other tariff and bills it with zero energy charge.

### Requirement 7: Explain a ghost in plain English

**User Story:** As a judge who is not a programmer, I want the smallest ghost explained in plain words, so that I understand why two correct-looking systems disagree.

#### Acceptance Criteria

1. WHEN `explain_ghost` receives a Ghost where Oracle and Python totals differ by rounding, THE Views SHALL return text that names both totals with `rs`, for example "Rs 9,049" and "Rs 9,048".
2. WHEN the total before rounding is a half rupee, THE Views SHALL include that unrounded total in the text, for example "Rs 9,048.50".
3. WHEN the cause is a half-rupee rounding difference, THE Views SHALL state in the text that Oracle rounds halves up and that Python's built-in `round()` rounds halves to the even number, using the words "half" and "round()".
4. WHEN the Oracle wrote no bill for the Ghost, THE Views SHALL return text that contains "no bill".
5. THE Views SHALL write every explanation in plain English with no unexplained programming terms except "round()".

_Traces to:_ `test_the_ghost_is_explained_in_plain_english`, `test_a_missing_oracle_bill_is_explained_too`.

### Requirement 8: Keep the app free of database and LLM

**User Story:** As the project owner, I want the hosted app to need no secrets and no infrastructure, so that it runs on Streamlit Community Cloud for anyone.

#### Acceptance Criteria

1. THE App and every module under `src/gravedigger/ui/` SHALL contain no Forbidden_Dependency.
2. THE App SHALL start with no `ORACLE_DSN`, `APP_USER_PASSWORD` or `LLM_API_KEY` set and with no network access.
3. THE Views SHALL import nothing from `streamlit`.
4. THE App SHALL call only `gravedigger.ui.views` for data and logic, and use Streamlit only to lay out what Views returns.

_Traces to:_ `test_no_database_and_no_live_llm_in_the_app`, `app` fixture.

### Requirement 9: Apply the dark graveyard theme

**User Story:** As a judge, I want a dark, spooky but readable look, so that the demo is memorable and still easy to read.

#### Acceptance Criteria

1. THE Theme_Config SHALL contain a `[theme]` section with `base = "dark"`.
2. THE Theme_Config SHALL set the background colour to #1a1423 and the primary colour to #9b6bd6, from the Theme_Colours.
3. THE App SHALL use the Theme_Colours for its coloured labels, with red for errors and risks, teal for reads and success, amber for writes and warnings, and purple for calls and accents.
4. THE App SHALL keep the Halloween mood light, using graveyard words such as exhume, ghost and grave, and no gory imagery.
5. WHERE a coloured label carries meaning, THE App SHALL also show that meaning as text, so that the page stays readable without colour.

_Traces to:_ `test_dark_theme_is_configured`.

### Requirement 10: Show the header, headline numbers and CI badge

**User Story:** As a judge, I want the headline facts at the top of the page, so that I grasp the result in ten seconds.

#### Acceptance Criteria

1. WHEN the App starts, THE App SHALL show a title containing "Grave Digger" and, below it, the tagline "Legacy billing code never dies. It just haunts you."
2. WHEN the App starts, THE App SHALL show three metrics: units raised, rules found, and Oracle bills proven.
3. THE App SHALL show "8" as the units raised, computed from `load_units`.
4. THE App SHALL show the number of Golden_Cases, formatted with thousands separators, as the Oracle bills proven.
5. THE App SHALL show as rules found the total number of Kept_Rules across all Autopsy_Cards.
6. THE App SHALL show the CI_Badge as the image https://github.com/akhterquddus-ops/grave-digger/actions/workflows/prove.yml/badge.svg, linking to https://github.com/akhterquddus-ops/grave-digger/actions/workflows/prove.yml.
7. WHEN the App starts, THE App SHALL finish its first run without raising an exception.

_Traces to:_ `test_app_starts_and_tells_the_story_in_four_tabs`, `test_headline_numbers`.

### Requirement 11: Organise the story in four tabs

**User Story:** As a judge, I want four clearly named tabs, each starting with one plain sentence, so that I always know what I am looking at.

#### Acceptance Criteria

1. THE App SHALL show exactly four tabs, in this order, with labels containing "Autopsy", "Graph", "Resurrect" and "Prove".
2. WHEN a tab is opened, THE App SHALL first show one short plain-English sentence that says what the tab shows.
3. THE App SHALL write every visible text for readers who are not programmers.

_Traces to:_ `test_app_starts_and_tells_the_story_in_four_tabs`. Criteria 2 and 3 come from the product brief.

### Requirement 12: Autopsy tab

**User Story:** As a judge, I want one expandable section per unit, so that I can read the rules of any unit and see which code line each rule came from.

#### Acceptance Criteria

1. THE App SHALL show one expander per Unit in the Autopsy tab, whose label contains the Unit name, in package order.
2. WHEN an expander is shown, THE App SHALL show the summary of the Autopsy_Card and the text of every Kept_Rule.
3. THE App SHALL show, beside each Kept_Rule, the code line numbers it cites.
4. WHERE an Autopsy_Card has Dropped_Rules, THE App SHALL show each one greyed out, together with the guardrail's reason for dropping it.
5. THE App SHALL make the text of the first Kept_Rule of f_enrg_chg appear on the page.
6. WHERE an Autopsy_Card has `source` equal to "static", THE App SHALL show on the expander of that Unit a small grey note with the exact text "Showing rules found by the scanner only (no cached AI autopsy)".

_Traces to:_ `test_autopsy_tab_shows_every_unit_and_its_rules`. Criteria 3 and 4 come from the product rule that every rule cites its code line. Criterion 6 is an addition that pairs with Requirement 3, criterion 5.

### Requirement 13: Graph tab

**User Story:** As a judge, I want the dependency map with a colour key beside it, so that I can tell which unit writes to which table.

#### Acceptance Criteria

1. THE App SHALL draw the DOT text of `graph_dot` with `st.graphviz_chart` in the Graph tab.
2. THE App SHALL show the Legend next to the graph as small coloured labels, one per Legend entry, each with its name and plain-English meaning.
3. THE App SHALL make the words "writes" and "reads" appear on the Graph tab.

_Traces to:_ `test_graph_tab_draws_the_graph_and_legend`.

### Requirement 14: Resurrect tab

**User Story:** As a judge, I want old and new code side by side, so that I can see the dead code and its living Python twin.

#### Acceptance Criteria

1. THE App SHALL show a selectbox with the key `resurrect_unit`, whose options are the eight Unit names in package order.
2. WHEN a Unit is selected, THE App SHALL show the PL/SQL text from `legacy_source` and the Python text from `python_source` in two code blocks side by side.
3. WHEN "f_lps" is selected, THE App SHALL show a code block containing "FUNCTION f_lps" and a code block containing "def lps(".

_Traces to:_ `test_resurrect_tab_shows_old_and_new_code_side_by_side`.

### Requirement 15: Prove tab

**User Story:** As a judge, I want to press one button for the real port and one for the wrong draft, so that I see proof of zero ghosts and see a ghost caught.

#### Acceptance Criteria

1. THE App SHALL show a button with the key `hunt_port` and a button with the key `hunt_draft` in the Prove tab.
2. WHEN `hunt_port` is clicked, THE App SHALL show a green success message that contains "No ghosts".
3. WHEN `hunt_draft` is clicked, THE App SHALL show a red error message that contains the number of Ghosts and the word "ghost".
4. WHEN `hunt_draft` is clicked, THE App SHALL show, in order, the red error, the `explain_ghost` text of the Smallest_Ghost, and the ghost table.
5. WHEN `hunt_draft` is clicked, THE App SHALL show the ghost table as a dataframe or table with the rows from `ghost_table`.
6. WHEN either button is clicked, THE App SHALL finish without raising an exception.
7. THE App SHALL reuse the cached Hunt result when the same button is clicked again.

_Traces to:_ `test_prove_tab_real_port_has_no_ghosts`, `test_prove_tab_draft_is_haunted_and_the_smallest_ghost_is_explained`.

### Requirement 16: Pure and deterministic views

**User Story:** As a developer, I want the views to be pure, so that they are simple to test and safe to cache.

#### Acceptance Criteria

1. FOR ALL Decimal amounts, THE Views SHALL return the same `rs` text on every call with the same input.
2. FOR ALL hunt kinds, THE Views SHALL return equal reports on repeated calls of `run_hunt`.
3. FOR ALL Ghosts in a report, THE Views SHALL give a `ghost_table` row count equal to the smaller of the Ghost count and the limit.
4. FOR ALL non-negative Decimal amounts with at most two decimal places, THE Views SHALL return `rs` text from which removing "Rs ", the commas and, when present, the zero fractional part yields a value equal to the amount (round-trip of the formatting).
5. THE Views SHALL hold no global mutable state other than the caches named in Requirement 5.

_Traces to:_ the whole `views` contract. These are the properties the design will turn into Hypothesis tests, per the migration rule that every requirement becomes at least one property.
