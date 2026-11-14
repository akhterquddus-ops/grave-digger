---
inclusion: always
---
# Tech stack and conventions

## Stack
- Python 3.12, src layout, package `gravedigger` in `src/gravedigger`.
- UI: Streamlit (`app/streamlit_app.py`), deployed to Streamlit Community Cloud.
- Tests: pytest + Hypothesis.
- Oracle: Oracle Database Free in Docker (`gvenzl/oracle-free` slim image) locally
  and as a GitHub Actions service. Driver: `python-oracledb` in THIN mode
  (no Instant Client).
- MCP: Python MCP server in `mcp_server/oracle_server.py` (MCP SDK 2.x, `MCPServer`).
  Tools: run_sql (read-only), describe_object, run_plsql (rolled back by default).
  Use them to check legacy behaviour against the real database before writing specs.
- Dependency graph: Graphviz DOT strings rendered with `st.graphviz_chart`.

## Code rules
- Money is ALWAYS `decimal.Decimal`, never float. Construct from strings.
- Rounding mirrors Oracle ROUND: `ROUND_HALF_UP` (halves away from zero).
  Never use Python's built-in `round()` on money.
- Type hints everywhere. Data types are frozen dataclasses.
- One Python function per legacy unit; keep the legacy name in the docstring.
- Small, pure functions; no global state.
- Config from environment variables or the git-ignored `.env` (see `gravedigger/config.py`):
  ORACLE_DSN, ORACLE_USER, APP_USER_PASSWORD (app connection), LLM_API_KEY.
  ORACLE_PASSWORD is the SYS password for the Docker container only; the app never uses it.
  Never hard-code secrets. Never commit `.env`.

## Developer environment
- Windows 11, PowerShell 5.1. Give commands in PowerShell syntax.
- Project root: C:\Akhtar-Works\grave-digger. Virtual env in `.venv`, created with `py -3.12`
  (NOT Conda's python). Activate: `.venv\Scripts\Activate.ps1`. Install: `pip install -e ".[dev]"`.
- Oracle: `docker compose up -d` (container gd-oracle, Oracle AI Database 26ai Free, FREEPDB1).
- Write files as UTF-8 WITHOUT BOM.
- Smart App Control is ON. Keep oracledb pinned at 3.4.0 (newer wheels are blocked). If a new
  dependency fails with 'An Application Control policy has blocked this file', pin an older,
  widely used version instead of upgrading.
- Line endings LF (see .gitattributes).

## Testing
- Equivalence tests compare EVERY field of the bill, exactly.
- Hypothesis profiles: `dev` = 200 examples (used by the on-save hook),
  `ci` = 2000 examples, fixed seed.
- Tests that need Oracle are marked `@pytest.mark.oracle` and skipped when
  ORACLE_DSN is not set.
