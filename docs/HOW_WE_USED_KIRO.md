# How we used Kiro

Grave Digger was built with Kiro from the first commit (Nov 13, 2026) to the live app (Nov 18). Kiro wrote the legacy package, the scanner, the Python port, the proof and the app. Every stage went through a Kiro spec, and Kiro checked its own work against a real Oracle database through our own MCP server.

The full day-by-day record, with credits used per step, is in [kiro-log.md](kiro-log.md). Everything Kiro used is in the [`/.kiro`](../.kiro) folder at the root of the repo.

## At a glance

| Kiro feature | Where | What it did for this project |
|---|---|---|
| Specs | `.kiro/specs/` (7 specs) | One spec per stage: requirements, then design, then tasks, then code |
| Steering | `.kiro/steering/` (5 files) | Kept every session on the same rules: Decimal money, Oracle rounding, plain English, no real data |
| MCP | `mcp_server/oracle_server.py` | Our own Oracle MCP server, so Kiro could ask the legacy database questions before writing code |
| Hooks | `.kiro/hooks/prove-on-save.json` | Re-proves the port every time Kiro edits it |
| Property-based testing | `tests/` (Hypothesis) | 2,000 random bills billed by Oracle and by Python on every push; must match to the paisa |

## Specs: one per stage

We built Grave Digger as seven specs, in this order:

| Spec | What it built | Result |
|---|---|---|
| autopsy-scanner | Reads PL/SQL into units, finds constants, tables, branches and error handlers | 26 acceptance tests green on the first full run; 11 edge tests added after review, 37/37 |
| dependency-graph | The map of who calls what and which tables are read or written | Risky unit (`p_gen_bill`, which swallows every error) drawn in red |
| autopsy-explain | Plain-English business rules from Claude, with a guardrail | Finds all 8 rules we planted in the legacy code (8/8) |
| resurrect-billing | The Python port, one requirement section per legacy unit | Port with `LEGACY QUIRK` notes that cite the legacy lines |
| prove-equivalence | Python vs real Oracle on random bills | 2,000 random bills, 0 mismatches |
| ghost-hunt | A snapshot of 2,006 Oracle bills, so the hosted app can prove ports with no database | Real port: 0 ghosts. Deliberately wrong draft: 65 ghosts |
| ui | The four-tab public app | Live at https://grave-digger.streamlit.app |

**How we worked with specs.** For each stage, acceptance tests were written first, outside Kiro, as the contract. Kiro then wrote requirements, design and tasks from those tests and built the code. Kiro was told never to change an existing test file, and it never did; it was free to add new tests, and often did.

**Moments worth telling:**

- **Kiro refused to guess.** When the autopsy-explain test file was missing, Kiro paused and said so, instead of inventing a contract.
- **Kiro reviewed itself.** In resurrect-billing, the review task found wrong line numbers in Kiro's own spec and fixed the docstrings to match the legacy file.
- **Kiro asked first.** In ui, Kiro listed the decisions it was unsure about (what to show when Oracle wrote no bill, how to install the app in the cloud) and waited for answers before building.

## Steering: the same rules in every session

Five steering files hold the rules that every Kiro session follows:

- `product.md`: what Grave Digger is, who it is for, plain English in everything users see.
- `tech.md`: Python 3.12, the venv, how to reach Oracle, which settings come from `.env`.
- `structure.md`: where code, tests and specs live.
- `migration-rules.md`: the rules of a faithful port. Money is `Decimal`, never `float`. Rounding is half up like Oracle's `ROUND`, never Python's `round()`. Legacy quirks are kept and labelled, not fixed.
- `legacy-style.md` (only for files under `legacy/`): how the synthetic 2004-style PL/SQL should look.

The migration rules mattered most. The bug at the heart of our demo (Python's `round()` rounds half to the even number) is exactly what that file forbids. Kiro never used `round()` in the port.

## MCP: Kiro questions the legacy database before it writes code

We wrote our own MCP server (`mcp_server/oracle_server.py`) with three tools: `run_sql` (read-only), `describe_object`, and `run_plsql` (always rolled back unless told otherwise). Kiro used them to dig into the legacy database itself:

- **Found the cliff.** Asked why 301 units costs so much, Kiro called the legacy function and found that above 300 units every unit is charged Rs 22: one extra unit adds Rs 2,722.
- **Cross-checked before porting.** In resurrect-billing, Kiro ran 5 legacy calls in Oracle before writing the design.
- **Found traps that would have caused false alarms.** Before designing the proof, Kiro probed Oracle and found that Oracle dates use the Julian calendar before 1582 (1000-03-01 is a Friday in Oracle and a Saturday in Python), that a due date in year 9999 overflows silently, and that a bill too large for the `BILL_HDR` columns is swallowed with no row written. These went into the spec, so the random bills stay inside what both systems can represent.

## Hooks: Kiro must re-prove its own edits

The `prove-on-save` hook runs when a file under `resurrected/` is saved. It asks Kiro to run the ghost hunt against the 2,006 Oracle bills and report any ghost in plain English.

We learned that Kiro's file hooks fire only when **Kiro** edits a file, not when a person saves it. So we made that the point: the hook is a guardrail on the AI. Kiro cannot change the Python port without proving it again. A test edit triggered the hook in 12 seconds for 0.28 credits: 40 passed, no ghosts.

## Property-based testing: the proof

Hypothesis generates random customers and meter readings, weighted towards the edges where legacy code breaks: exactly 300 and 301 units, meter rollover, a Sunday due date, payment at 10 AM on the due date, a missing fuel-price rate. Each customer is billed by the real PL/SQL in Oracle and by the Python port, and every field must match.

- Locally and on every push (GitHub Actions with a fresh Oracle database): **2,000 random bills, 0 mismatches.** The run fails if any test is skipped, so the badge can only be green if the whole proof ran.
- Kiro turned each requirement into a Hypothesis property before writing code. In the ui spec, one of those properties found a real bug in Kiro's own code (an error message that escaped unusual characters in a name).

## The ghost: why the proof matters

A first-draft port that uses Python's `round()` matches all five seed bills from the old system. Most teams would ship it. The ghost hunt finds 65 bills out of 2,006 where it is one rupee off: the bill adds up to Rs 3,086.50 before rounding, Oracle rounds half up to 3,087, and `round()` gives 3,086. The live app shows this on the Prove tab.

## Feedback for the Kiro team

- **Specs worked best with tests written first.** Giving Kiro a test file as the contract produced specs that matched what we wanted on the first try, and Kiro respected "do not modify the tests" throughout.
- **File hooks and manual saves.** We expected a save from the editor to fire a file hook. The docs say file hooks respond only to agent changes; a short note in the hook form would save other users the same confusion.
- **One glitch.** Once, a spec's `tasks.md` was saved as an empty file (0 bytes) even though Kiro had shown the task list. Asking Kiro to regenerate it fixed it.

All legacy code in this project is synthetic, written for Grave Digger in November 2026 in the style of the 2000s. No real utility code or customer data was used.
