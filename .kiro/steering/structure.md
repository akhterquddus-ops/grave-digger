---
inclusion: always
---
# Repo structure

    .kiro/steering/        project rules (this folder)
    .kiro/specs/<unit>/    one spec per legacy unit: requirements.md, design.md, tasks.md
    .kiro/hooks/           agent hooks (prove-on-save)
    .kiro/settings/        mcp.json
    legacy/                synthetic legacy PL/SQL: schema.sql, billing_pkg.pks, billing_pkg.pkb
    src/gravedigger/
      exhume.py            load + split PL/SQL into units
      autopsy/             scanner.py, graph.py, explain.py
      resurrected/         billing.py = the Python port
      prove/               strategies.py, oracle_runner.py, compare.py, ghosts.py
      report.py            migration certificate
    app/streamlit_app.py   public UI (Exhume, Autopsy, Resurrect, Prove, Certificate)
    mcp/oracle_server.py   MCP tools: run_sql (read-only), run_plsql, describe_object
    tests/                 pytest + Hypothesis
    golden/                cases.json (Oracle results snapshot), ghosts.json
    docs/kiro-log.md       running log for the "How we used Kiro" write-up

## Naming
- Python: snake_case modules and functions, PascalCase dataclasses.
- Spec folders are named after the legacy unit, e.g. .kiro/specs/f_enrg_chg/
- Never put legacy (synthetic) code outside legacy/.
