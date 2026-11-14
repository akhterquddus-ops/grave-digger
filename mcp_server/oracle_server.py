"""Grave Digger Oracle MCP server.

Gives Kiro three tools to explore the legacy database while it writes specs
and ports code:

  run_sql          read-only SELECT / WITH queries (auto-approved in Kiro)
  describe_object  table columns, or PL/SQL source with line numbers (auto-approved)
  run_plsql        run an anonymous PL/SQL block and return DBMS_OUTPUT.
                   Rolled back by default; Kiro asks before each call.

Run by Kiro over stdio (see .kiro/settings/mcp.json). Connection settings come
from .env at the repo root (ORACLE_DSN, ORACLE_USER, APP_USER_PASSWORD).
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import re

import oracledb
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from gravedigger.config import oracle_params

MAX_ROWS = 200
MAX_OUTPUT_LINES = 500

server = MCPServer(
    name="grave-digger-oracle",
    instructions=(
        "Tools for the synthetic legacy billing schema (BILLING_PKG, CUST_MST, "
        "MTR_RDG, FPA_RT, PYMT, BILL_HDR) in a local Oracle Free database. "
        "Use run_sql for queries, describe_object to read a table or PL/SQL "
        "source with line numbers, and run_plsql to call legacy units."
    ),
)


def _connect() -> oracledb.Connection:
    try:
        return oracledb.connect(**oracle_params())
    except (oracledb.Error, RuntimeError) as exc:
        raise ToolError(f"Cannot connect to Oracle: {exc}. Is the container running? (docker compose up -d)") from exc


def _plain(value: object) -> object:
    """Make Oracle values JSON-friendly without losing precision."""
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat(sep=" ") if isinstance(value, dt.datetime) else value.isoformat()
    if isinstance(value, oracledb.LOB):
        return value.read()
    return value


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


def check_read_only(sql: str) -> str:
    """Return the cleaned statement, or raise ToolError if it is not a single SELECT/WITH."""
    body = _strip_sql_comments(sql).strip().rstrip(";").strip()
    if not re.match(r"(?is)^(select|with)\b", body):
        raise ToolError("run_sql only accepts a single SELECT or WITH query.")
    if ";" in body:
        raise ToolError("run_sql accepts one statement at a time (no ';' inside).")
    if re.search(r"(?is)\bfor\s+update\b", body):
        raise ToolError("SELECT ... FOR UPDATE is not allowed in run_sql.")
    return body


@server.tool()
def run_sql(query: str) -> str:
    """Run one read-only SELECT or WITH query against the legacy schema.

    Returns JSON: {"columns": [...], "rows": [[...]], "truncated": bool}.
    Numbers come back as exact strings (Oracle NUMBER), dates as ISO text.
    At most 200 rows are returned.
    """
    body = check_read_only(query)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            try:
                cur.execute(body)
            except oracledb.Error as exc:
                raise ToolError(str(exc)) from exc
            columns = [d[0] for d in cur.description]
            rows = cur.fetchmany(MAX_ROWS + 1)
        conn.rollback()
    truncated = len(rows) > MAX_ROWS
    return json.dumps(
        {
            "columns": columns,
            "rows": [[_plain(v) for v in r] for r in rows[:MAX_ROWS]],
            "truncated": truncated,
        },
        indent=1,
    )


@server.tool()
def describe_object(name: str) -> str:
    """Describe a table (columns) or a PL/SQL object (source with line numbers).

    Examples: describe_object("BILL_HDR"), describe_object("BILLING_PKG").
    For a package, both the spec and the body are returned, plus any compile errors.
    """
    obj = name.strip().upper()
    out: list[str] = []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT object_type, status FROM user_objects WHERE object_name = :n ORDER BY object_type",
                n=obj,
            )
            kinds = cur.fetchall()
            if not kinds:
                return f"No object named {obj} in schema {conn.username.upper()}."
            for kind, status in kinds:
                out.append(f"== {obj} ({kind}, {status}) ==")
                if kind == "TABLE":
                    cur.execute(
                        """SELECT column_name, data_type, data_length, data_precision,
                                  data_scale, nullable
                             FROM user_tab_columns WHERE table_name = :n ORDER BY column_id""",
                        n=obj,
                    )
                    for col, typ, length, prec, scale, nullable in cur:
                        if typ == "NUMBER" and prec is not None:
                            typ = f"NUMBER({prec},{scale})" if scale else f"NUMBER({prec})"
                        elif typ in ("VARCHAR2", "CHAR"):
                            typ = f"{typ}({length})"
                        out.append(f"  {col:<14} {typ:<14} {'NULL' if nullable == 'Y' else 'NOT NULL'}")
                else:
                    cur.execute(
                        "SELECT line, text FROM user_source WHERE name = :n AND type = :t ORDER BY line",
                        n=obj,
                        t=kind,
                    )
                    for line, text in cur:
                        out.append(f"{line:4d}| {text.rstrip()}")
            cur.execute(
                "SELECT type, line, position, text FROM user_errors WHERE name = :n ORDER BY sequence",
                n=obj,
            )
            errors = cur.fetchall()
            if errors:
                out.append("== COMPILE ERRORS ==")
                out.extend(f"  {t} line {ln}:{pos} {msg.strip()}" for t, ln, pos, msg in errors)
    return "\n".join(out)


@server.tool()
def run_plsql(block: str, commit: bool = False) -> str:
    """Run one anonymous PL/SQL block (BEGIN ... END;) and return its DBMS_OUTPUT.

    Changes are ROLLED BACK unless commit=True, so it is safe for exploring, e.g.
    BEGIN DBMS_OUTPUT.PUT_LINE(billing_pkg.f_enrg_chg('A1', 301)); END;
    """
    text = block.strip()
    if text.endswith("/"):
        text = text[:-1].rstrip()
    if not re.match(r"(?is)^(declare|begin)\b", _strip_sql_comments(text).strip()):
        raise ToolError("run_plsql expects an anonymous block starting with DECLARE or BEGIN.")
    lines: list[str] = []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.callproc("dbms_output.enable", [None])
            try:
                cur.execute(text)
            except oracledb.Error as exc:
                raise ToolError(str(exc)) from exc
            line_var = cur.var(str)
            status_var = cur.var(int)
            while len(lines) < MAX_OUTPUT_LINES:
                cur.callproc("dbms_output.get_line", (line_var, status_var))
                if status_var.getvalue() != 0:
                    break
                lines.append(line_var.getvalue() or "")
        if commit:
            conn.commit()
        else:
            conn.rollback()
    result = "\n".join(lines) if lines else "(no DBMS_OUTPUT)"
    return f"{result}\n-- {'committed' if commit else 'rolled back'}"


if __name__ == "__main__":
    server.run("stdio")
