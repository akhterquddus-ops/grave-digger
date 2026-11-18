# How we used Kiro (running log)

| Date | Kiro feature | What we asked | What Kiro produced |
|---|---|---|---|
| 2026-11-13 | (setup) | Repo created | Folder skeleton, /.kiro at root |
| 2026-11-13 | Steering | Project rules for Kiro | product, tech, structure, migration-rules, legacy-style |
| 2026-11-13 | Agent + steering | Write synthetic BILLING_PKG (8 hidden rules, 6 seed customers) | legacy/schema.sql, billing_pkg.pks, billing_pkg.pkb; 1.83 credits; all 8 rules correct first try |
| 2026-11-13 | (Oracle) | Ran BILLING_PKG in Oracle AI Database 26ai Free (Docker) | 5/5 seed bills match an independent Python calculation to the paisa; 1006 fails silently as designed |
| 2026-11-14 | MCP | Asked why f_enrg_chg('A1',301) is so high, via grave-digger-oracle tools | 2 tool calls; found the >300 all-units cliff (6,622 vs 3,900 = +Rs 2,722 for 1 kWh); 0.49 credits |
| 2026-11-14 | Spec | autopsy-scanner: requirements, design, tasks from 26 acceptance tests | tokenizer.py, blocks.py, exhume.py, scanner.py; 26/26 green first full run; tests untouched; ~18 credits |
| 2026-11-14 | Spec (update) | Code review found 4 scanner gaps (DUAL, EXTRACT/TRIM FROM, datatype sizes, negative literals); added 11 edge tests | Kiro updated requirements + tasks and fixed scanner.py; 37/37 green |
| 2026-11-14 | Spec (update) | Code review found 4 scanner gaps (DUAL, EXTRACT/TRIM FROM, datatype sizes, negative literals); added 11 edge tests | Kiro added requirements 15-18 + task 6, fixed scanner.py; 37/37 green; 2.37 credits |
| 2026-11-14 | Spec | dependency-graph: requirements, design, tasks from 16 acceptance tests | 10 requirements; only graph.py planned; ~12 credits so far |
| 2026-11-14 | Spec | autopsy-explain: requirements started; Kiro paused because the test file was missing instead of guessing the contract | requirements.md; 2.87 credits |
| 2026-11-17 | Spec | autopsy-explain: requirements, design and tasks written with Kiro. Guardrail idea: every rule must cite live code lines with a fact, carry no line numbers in its text, and use only numbers found in the code; bad rules are kept with a reason. The cache stores the raw answer and re-checks it on every read. A static fallback covers a missing key or failed call | Spec complete (requirements.md, design.md, tasks.md); decisions: Anthropic claude-haiku-5-5 with forced tool_choice (fallback {"type":"any"} if the first real run gives a 400), OpenAI gpt-4o-mini as backup provider, no temperature because the cache gives repeatability |
| 2026-11-17 | (dependencies) | Pin LLM SDKs for autopsy-explain | anthropic==2.8.0 and openai==3.51.0 (jiter 0.19.0 comes with them); installed with no Application Control block because Smart App Control is now OFF on the laptop |
| 2026-11-17 | Spec (update) | First real Claude run (~1 cent). Guardrail too strict: dropped multi-line and boundary-number rules. Loosened test-first (at least one evidence line; c+1 / c-1 for comparisons; 0 allowed). Re-scored from cache, no API call | kept rules all anchored; 1 kept rule has wrong scope (p_gen_bill batch claim) -> prompt v2 next |
| 2026-11-17 | Spec (update) | First real Claude run (~1 cent). Guardrail too strict: dropped multi-line and boundary-number rules. Loosened test-first; re-scored from cache with no API call | all kept rules anchored; 1 kept rule had wrong scope -> prompt v2 |
| 2026-11-17 | Answer key | tests/test_autopsy_quality.py: 8 planted rules vs cached Claude autopsy | v1 prompt scores 8/8 |
| 2026-11-17 | Experiment | Prompt v2 (one fact per rule, cite only live lines) scored 4/8: empty rule lists for simple units. Reverted to v1 (8/8); kept the ELSE evidence fix | decision rule held: never trade coverage for wording |
| 2026-11-18 | Spec + MCP | resurrect-billing: 8 per-unit requirement sections; Kiro cross-checked 5 legacy calls in real Oracle via MCP before designing | billing.py port; 117 tests green |
| 2026-11-18 | Spec | resurrect-billing tasks run: port in billing.py; Kiro's review task caught wrong line numbers in its own spec and fixed docstrings to match the legacy file | 117 tests green; 17.19 credits |
| 2026-11-18 | Spec + MCP | prove-equivalence: before writing the design, Kiro dug up the real database through the grave-digger-oracle tools. It used probe customer keys 900001 and 209912, and checked the NUMBER limits of BILL_HDR | Findings written into the spec: a bill too big for a BILL_HDR column raises an overflow inside BILLING_PKG, WHEN OTHERS swallows it, and no row is written. Python must reproduce "no bill", not an error |
| 2026-11-18 | Spec + MCP | Date check in Oracle: asked what weekday Oracle gives for old dates | Oracle DATE uses the Julian calendar before 1582. 1000-03-01 is a Friday in Oracle and a Saturday in Python, so the Sunday due-date shift would disagree. A due date in year 9999 overflows and is swallowed the same way (no row) |
| 2026-11-18 | Spec | Order of work: requirements first, then design, then tasks, then code. Each requirement became a Hypothesis property before any test was run | Spec-driven order held: no test was written without a requirement behind it |
| 2026-11-18 | Decision | Keep the ghosts honest but the search sensible: generate only dates from 2000 to 2100, and set deadline=None in the dev and ci Hypothesis profiles (Oracle round trips are slow and a timing deadline would raise false alarms) | The Julian-calendar gap stays documented as a known limit, not hidden. Profiles: dev 200 examples, ci 2000 examples |
| 2026-11-18 | Tests (Oracle) | Ran the Oracle-marked tests against the real database | 8 oracle tests passed. The probe customer left no trace: all counts 0, BILL_HDR still 5 rows. The graveyard was left as we found it |
| 2026-11-18 | Property-based testing | prove-equivalence: Hypothesis ci profile, Python port vs real Oracle | 2,000 passing, 0 failing, ~10 s; 139 tests green |

## Ghost-hunt spec: results

- Tests passed: 154 (full suite, 0 failed, 0 skipped).
- Oracle tests: 10 passed, none skipped.
- Golden case count: 2006 (golden/cases.json).
- Draft ghost count: 65 of 2006 cases (1941 matched), as expected.
- Smallest_Ghost: tariff A2, load_kw 0.25, readings 0 to 98, mf 1, rdg_dt 2090-06-16 11:59:02, no FPA rate, no payment. Oracle total 3087, draft total 3086.
- No-trace check after the run (baseline before the run was identical): CUST_MST 0, MTR_RDG 0, PYMT 0, BILL_HDR probe 0, FPA_RT 209912 0, BILL_HDR all 5.
- Timing: the three property tests together take about 4.8 s, close to the 5 s budget.
| 2026-11-18 | Hooks | prove-on-save: PostFileSave hook (matcher 'resurrected') with an agent action. Kiro file hooks fire only on agent edits, so it acts as a guardrail: whenever Kiro changes the Python port, it must re-run the hunt against the 2,006 Oracle bills. Test edit: hook triggered, 40 passed, no ghosts, 0.28 credits, 12 s |
| 2026-11-18 | CI | GitHub Actions 'Prove': fresh Oracle AI Database Free, legacy package loaded with sqlplus (0 invalid objects, 5 seed bills), then the full suite with the Hypothesis ci profile (2,000 random bills vs real Oracle). The run fails if any test is skipped. Run #1 green in 2m 10s; README badge |
