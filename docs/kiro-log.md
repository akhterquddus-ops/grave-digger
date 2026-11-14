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
