# Implementation Plan: ui (public demo app)

## Overview

The design is already in Python, so no language question applies. The work builds the pure `gravedigger.ui.views` module first, in small steps, each followed by its property tests. The theme file and root `requirements.txt` come next, then the thin Streamlit page, then the acceptance gate (`tests/test_ui.py`), a speed check of the property tests, the Kiro log entry and a final checkpoint.

Constraints that apply to every task:

- `tests/test_ui.py` is the approved acceptance contract and MUST NOT be modified. All new tests go in `tests/test_ui_properties.py`.
- Views (`src/gravedigger/ui/views.py`) import no `streamlit`. Neither Views nor the app import or call `oracledb`, `anthropic`, `openai`, `oracle_runner`, `make_client`, `build_golden`, `run_oracle` or `connect`.
- Money is `decimal.Decimal` built from strings or integers, never float. Rounding uses `ROUND_HALF_UP`, never the built-in `round()`.
- Type hints everywhere. Data types are frozen dataclasses. No module-level `list`, `dict` or `set`; use `tuple` and `MappingProxyType`. The only module state is `functools.lru_cache`.
- Every function docstring names the legacy unit it relates to where one exists (for example "Ports BILLING_PKG.f_lps"); helpers with no legacy unit say so.
- Files are UTF-8 without BOM, LF line endings. Commands are PowerShell 5.1 syntax with the venv active (`.venv\Scripts\Activate.ps1`).
- Do not modify library modules outside `src/gravedigger/ui/`.

Property-test speed constraint (applies to every sub-task that writes to `tests/test_ui_properties.py`):

- The whole file MUST run in under 30 seconds with `$env:HYPOTHESIS_PROFILE = "ci"` (2000 examples, fixed seed).
- No property may run a full hunt over `golden/cases.json` and none may start the Streamlit app (`AppTest`) per example. Build small inputs instead: a few hand-built `GoldenCase`, `Ghost` and `HuntReport` values, or small generated `BillInput` values.
- Any property that is still slow gets an explicit `@settings(max_examples=...)` cap. Properties over a tiny domain (the eight unit names, the two hunt kinds) and properties that touch the disk (Property 5) get a cap from the start.
- Each property test carries the comment `# Feature: ui, Property N: <title>`.

## Tasks

- [x] 1. Views foundation: package, money, repo root, units and sources
  - [x] 1.1 Create the `ui` package and the money, constants and repo-root helpers
    - Create `src/gravedigger/ui/__init__.py` (empty) and `src/gravedigger/ui/views.py`.
    - Add constants `GHOST_COLUMNS`, `TARIFF_LABELS` (`MappingProxyType`), `NO_BILL`, `STATIC_NOTE`, `TAGLINE`, `CI_BADGE_URL`, `CI_WORKFLOW_URL` with the exact texts from the design.
    - Implement `rs(amount: Decimal) -> str`: `TypeError` for non-`Decimal`, quantize to two places with `ROUND_HALF_UP`, sign taken from the quantized value, no decimals for whole amounts, "-Rs " prefix for negatives.
    - Implement `repo_root()` (`lru_cache`): accept `config.REPO_ROOT`, else the working directory and its parents, when `legacy/billing_pkg.pkb`, `golden/autopsy` and `golden/cases.json` exist; otherwise `FileNotFoundError` with a plain sentence. Read files with `Path.read_text(encoding="utf-8")`.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 8.3, 16.1, 16.5_

  - [x] 1.2 Implement unit loading, `PORT_OF`, `UNIT_ORDER` and the two source functions
    - `_package()` (`lru_cache`) calls `load_package` on `legacy/billing_pkg.pks` and `.pkb`; `load_units()` returns `_package().units`.
    - `PORT_OF` is a `MappingProxyType` of the eight unit names to `units, energy_charge, fixed_charge, fpa, taxes, due_date, lps, generate_bill`. `UNIT_ORDER` is derived lazily through a cached helper so importing Views reads no file.
    - `legacy_source(name)` returns the unit's PL/SQL text. `python_source(name)` uses `inspect.getsource`, `textwrap.dedent`, strips trailing newlines, and raises `ValueError` if the text does not start with `def <func_name>(`.
    - Both raise `KeyError` naming the unit for an unknown name, and list the known units in the message.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 16.5_

  - [x] 1.3 Write property tests for money formatting
    - Create `tests/test_ui_properties.py` with the module docstring stating the speed constraint above. Do not edit `tests/test_ui.py`.
    - Amount strategy: `st.integers(...).map(lambda n: Decimal(n).scaleb(-2))`, no floats.
    - **Property 1: Rupee formatting round trip**, including determinism on a second call.
    - **Property 2: Negative amounts put the minus sign first.**
    - Add a small example test that `rs(1.5)` raises `TypeError`.
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 16.1, 16.4**

  - [x] 1.4 Write property tests for unit sources
    - **Property 3: Every unit has both sources.** Use `st.sampled_from(UNIT_ORDER)` with `@settings(max_examples=16)` (eight units only).
    - **Property 4: Unknown units are rejected by name.** Text filtered to exclude the eight names; the `KeyError` message contains the text.
    - **Validates: Requirements 2.3, 2.4, 2.6**

- [x] 2. Autopsy, graph, legend and headline
  - [x] 2.1 Implement the autopsy cards and the shared golden-case loader
    - `build_autopsy_cards(cache_dir: Path)` returns `tuple(explain(u, scan(u), client=None, cache_dir=cache_dir) for u in load_units())`. `client=None` is a literal; do not import `make_client` or `client_from_settings`.
    - `autopsy_cards()` is `lru_cache`d and uses `repo_root() / "golden" / "autopsy"`.
    - Add `_golden_cases()` (`lru_cache`): `load_cases(repo_root() / "golden" / "cases.json")`, the single loader of the file.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 5.5, 8.1_

  - [x] 2.2 Implement `graph_dot`, `GRAPH_LEGEND`, `Headline` and `headline`
    - `graph_dot()` (`lru_cache`) is `to_dot(build_graph(_package()))`.
    - `GRAPH_LEGEND` is built once from `graph.EDGE_STYLES` and `graph.THEME`: calls, reads, writes, uses, hides errors, each with a plain-English meaning and a `#rrggbb` colour.
    - Frozen dataclass `Headline(units_raised, rules_found, bills_proven)` and `headline()` (`lru_cache`) using `load_units`, `autopsy_cards` and `_golden_cases`.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 10.2, 10.3, 10.4, 10.5_

  - [x] 2.3 Write property test for the autopsy cache fallback
    - **Property 5: The autopsy uses the cache when it has an entry and the static fallback when it has not.**
    - Draw a subset of unit names with `st.sets(st.sampled_from(UNIT_ORDER))`. Each example copies `golden/autopsy` into a `tempfile.TemporaryDirectory()` (no function-scoped fixture) and deletes the files of the chosen units.
    - Patch `make_client` and `client_from_settings` to raise, and assert the call still succeeds, in package order, with the right `source` per card.
    - Speed: `@settings(max_examples=30)`; the folder holds only eight small files.
    - **Validates: Requirements 3.2, 3.5, 3.6**

- [x] 3. Ghost hunt, ghost table, explanation and headline
  - [x] 3.1 Implement `run_hunt`
    - `_PORTS` is a `MappingProxyType` of `"port"` to `billing.generate_bill` and `"draft"` to `billing_draft.generate_bill`.
    - `run_hunt(which)` (`lru_cache`) raises `ValueError` for any other value, else returns `hunt(_PORTS[which], _golden_cases())`. No `oracle_runner` import.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 8.1_

  - [x] 3.2 Implement `ghost_table` and `hunt_headline`
    - `ghost_table(report, limit=20)`: sort by `(units, total)` of the Oracle bill, else the Python bill (stable, same key as `hunt._size`, not importing the private name); take `max(limit, 0)` rows; keys exactly `GHOST_COLUMNS` in order; money through `rs`; "no bill" and "n/a" when Oracle wrote none; tariff through `TARIFF_LABELS.get(tariff, tariff)`; units as `format(units.normalize(), ",f")`.
    - `hunt_headline(report)`: "No ghosts. All N bills match Oracle to the paisa." or "n ghost(s) found. M of N bills match Oracle, but these n do not.", with the ghost count written without a thousands separator.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 15.2, 15.3_

  - [x] 3.3 Implement `explain_ghost`
    - Branch A: `ghost.oracle is None` gives text containing "no bill".
    - Branch B: half-rupee rounding. Implement `_before_rounding(bill)` (sum of enrg, fix, fpa, ed, gst, tv, lps, mirroring pkb line 193) and `_half_rupee_pre_total(ghost)`; the text names both totals and the unrounded total through `rs`, and uses the words "half" and "round()".
    - Branch C: other differences, listing each differing field with the plain label map from the design (`due_dt` as ISO date, `units` as a plain number, the rest through `rs`).
    - No programming words other than `round()`; all money through `rs`.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 3.4 Write property tests for `run_hunt`
    - Do NOT hunt the full `golden/cases.json` inside a property. Build a small tuple of hand-built or first-few `GoldenCase` values once at module level, patch `views._golden_cases` to return it (monkeypatch inside the test body or `unittest.mock.patch`), and call `run_hunt.cache_clear()` before and after.
    - **Property 6: Hunts equal the library hunt and are repeatable.** Over `st.sampled_from(["port", "draft"])` with `@settings(max_examples=10)`: `run_hunt(kind)` equals `hunt(port_function(kind), small_cases)`, `checked` equals the small case count, and a second call returns an equal report. The full-file equality with the real golden file stays in `tests/test_ui.py` (`test_draft_hunt_matches_the_library_hunt`).
    - **Property 7: Unknown hunts are rejected.** Text filtered to exclude "port" and "draft"; `ValueError`.
    - **Validates: Requirements 5.1, 5.3, 5.4, 16.2**

  - [x] 3.5 Write property tests for `ghost_table`
    - Strategy: a composite that builds small `HuntReport` values of 0 to 30 ghosts from `bill_inputs()`, the real port's bill as Oracle's bill (or `None`), and a Python bill made with `dataclasses.replace(bill, total=bill.total + delta)`; tariff drawn from `st.one_of(st.sampled_from(["A1", "A2"]), st.text())`. Never call `run_hunt` here.
    - **Property 8: The ghost table is limited, ordered and shaped**, including the empty report and `limit` of 0.
    - **Property 9: Ghost table cells are written for people**, including the one-rupee "Difference" and the tariff labels.
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 16.3**

  - [x] 3.6 Write property tests for `explain_ghost`
    - Half-rupee strategy: even `n` between 2000 and 10**6, six parts of at most 1000.00 each (cents), energy charge set so the sum is exactly `n + 0.50`; Oracle total `n + 1`, Python total `n`, only `total` differs.
    - **Property 10: A half-rupee ghost is explained with both totals and the unrounded total.**
    - **Property 11: A missing Oracle bill is explained.**
    - **Property 12: Every ghost gets a plain-English explanation** (non-empty, no jargon words "Decimal", "NULL", "None", "quantize", "NO_DATA_FOUND", "OTHERS", same text on a second call).
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 16.1**

  - [x] 3.7 Write property test for `hunt_headline`
    - **Property 13: The hunt headline states the ghost count.** Reuse the small-report strategy from 3.5.
    - **Validates: Requirements 15.2, 15.3**

- [x] 4. Safe-text helpers
  - [x] 4.1 Implement `md_escape`, `pill_html`, `category_colour` and `citation`
    - `md_escape` backslash-escapes `\ ` * _ ~ $ [ ] < >` and leaves other text unchanged.
    - `pill_html(text, colour)` validates `^#[0-9a-fA-F]{6}$` (else `ValueError`), uses `html.escape` on the text, and returns the single fixed-template `span`.
    - `category_colour`: error red, tax and surcharge amber, data teal, anything else purple, using `graph.THEME`.
    - `citation(rule)`: "Code line 52" or "Code lines 49, 50" (sorted).
    - _Requirements: 9.3, 9.5, 12.3, 12.4, 13.2_

  - [x] 4.2 Write property tests for the safe-text helpers
    - **Property 14: Page text is escaped and pills keep their text.** Cover `md_escape` round trip and no unescaped special, `pill_html` unescape equality, single `span` tag, colour present, `ValueError` for bad colours, and `citation` containing every cited line number.
    - **Validates: Requirements 9.3, 9.5, 12.3, 13.2**

- [x] 5. Theme and cloud requirements
  - [x] 5.1 Create `.streamlit/config.toml`
    - `[theme]` with `base = "dark"`, `primaryColor = "#9b6bd6"`, `backgroundColor = "#1a1423"`, `secondaryBackgroundColor = "#2a2038"`, `textColor = "#e8e0f0"`. Check that none of it is git-ignored.
    - _Requirements: 9.1, 9.2_

  - [x] 5.2 Create the root `requirements.txt`
    - One runtime line: `streamlit>=1.40` (the same floor as `pyproject.toml`). Do not add `oracledb`, `mcp`, `anthropic`, `openai`, test libraries or `-e .`. Leave the `oracledb==3.4.0` pin in `pyproject.toml` untouched.
    - _Requirements: 8.1, 8.2_

- [x] 6. Streamlit page
  - [x] 6.1 Implement `app/streamlit_app.py`
    - `sys.path` bootstrap for `<repo>/src` before any `gravedigger` import (fall back to `Path.cwd() / "src"` when `__file__` is undefined); imports of the project limited to `gravedigger.ui.views`; `st.set_page_config(page_title="Grave Digger", page_icon="🪦", layout="wide")` first.
    - `main()` called unconditionally at the bottom, catching `FileNotFoundError` and `ValueError` from the first Views call with `st.error` and `st.stop()`.
    - Header: title, `TAGLINE`, CI badge as Markdown, three `st.metric` values from `headline()` (units raised, rules found, Oracle bills proven with thousands separators).
    - Four tabs (Autopsy, Graph, Resurrect, Prove), each starting with the one-sentence opener from the design.
    - Autopsy: one `st.expander` per card (label holds the unit name), `STATIC_NOTE` via `st.caption` for static cards, `md_escape` on summary and rule text, category pill and `citation` beside each rule, dropped rules greyed out with their reason.
    - Graph: `st.graphviz_chart(graph_dot())` and the legend as pills plus text; `unsafe_allow_html=True` only on pill calls.
    - Resurrect: `st.selectbox(..., key="resurrect_unit")` over `UNIT_ORDER`, two code blocks side by side (`sql` and `python`).
    - Prove: buttons with keys `hunt_port` and `hunt_draft`; the click sets `st.session_state["hunt_shown"]`, and the result is drawn from that state on every rerun: `st.success` for no ghosts, else `st.error`, then `explain_ghost(report.smallest)` in `st.info`, then `st.dataframe(ghost_table(report), hide_index=True)`.
    - No `oracledb`, LLM or `oracle_runner` import; no logic beyond layout.
    - _Requirements: 8.1, 8.2, 8.4, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 11.1, 11.2, 11.3, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 13.1, 13.2, 13.3, 14.1, 14.2, 14.3, 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7_

- [x] 7. Acceptance gate
  - [x] 7.1 Run the approved acceptance tests and fix the code until they pass
    - Command: `.venv\Scripts\Activate.ps1; pytest tests/test_ui.py`.
    - Fix failures in `src/gravedigger/ui/views.py`, `app/streamlit_app.py` or the theme file only. Never edit `tests/test_ui.py`.
    - _Requirements: 1 to 16 (acceptance contract)_

- [x] 8. Property-test speed check
  - [x] 8.1 Measure `tests/test_ui_properties.py` under the CI profile and fix slow properties
    - Command: `$env:HYPOTHESIS_PROFILE = "ci"; pytest tests/test_ui_properties.py --durations=10`.
    - Target: the whole file finishes in under 30 seconds. For every property in the slowest-ten list that needs it, shrink the inputs (smaller reports, smaller generated `BillInput` values) or add an explicit `@settings(max_examples=...)` cap. Confirm that no property calls `run_hunt` on the real `golden/cases.json` or starts `AppTest`.
    - Re-run until the target is met, and record the final duration in the task notes. Also confirm the file passes under the default `dev` profile.
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

- [x] 9. Kiro log
  - [x] 9.1 Add an entry to `docs/kiro-log.md`
    - Append (UTF-8, LF) a short entry for the `ui` spec: requirements, design and tasks flow, the choice of `lru_cache` in Views over `st.cache_data`, the `session_state` approach for hunt results, the root `requirements.txt` for Community Cloud, and the property-test speed constraint with the measured time from 8.1. No secrets, no real client data.
    - _Requirements: none (project documentation)_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise. Run `tests/test_ui.py` and `tests/test_ui_properties.py` (CI profile) and the rest of the suite.

## Notes

- Property tests are written as non-optional sub-tasks here because the speed constraint and the 30-second target are part of this feature's acceptance. Every one of the 14 design properties has its own sub-task or sits in a sub-task with its number named.
- Property 6 deliberately uses a small patched case set to respect the "no full hunt in a property" rule. The full-file hunt equality is still checked by the approved `tests/test_ui.py`.
- Requirements 10 to 15 (page layout) are covered by the existing AppTest examples in `tests/test_ui.py`, run in task 7.1, not by properties.
- Each task references specific requirements for traceability.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "5.1", "5.2"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "2.1"] },
    { "id": 3, "tasks": ["1.4", "2.2"] },
    { "id": 4, "tasks": ["2.3", "3.1"] },
    { "id": 5, "tasks": ["3.2"] },
    { "id": 6, "tasks": ["3.3", "3.4"] },
    { "id": 7, "tasks": ["3.5", "4.1"] },
    { "id": 8, "tasks": ["3.6"] },
    { "id": 9, "tasks": ["3.7", "6.1"] },
    { "id": 10, "tasks": ["4.2"] },
    { "id": 11, "tasks": ["7.1"] },
    { "id": 12, "tasks": ["8.1"] },
    { "id": 13, "tasks": ["9.1"] }
  ]
}
```
