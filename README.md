# Grave Digger 🪦⚡

> **Legacy billing code never dies. It just haunts you.**

Grave Digger raises legacy utility-billing code from the dead. It reads an old Oracle PL/SQL package, explains in plain English what it really does, maps what depends on what, ports it to modern Python, and **proves** the port is correct: property-based tests bill thousands of random customers in Oracle and in Python, and the bills must match to the paisa.

Built with [Kiro](https://kiro.dev) for **Kiroween 2026** (Resurrection category).

**Status:** in development (Nov 13 – Dec 3, 2026).

## Quick start (Windows, PowerShell)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
docker compose up -d          # Oracle AI Database Free (needs a .env, see gravedigger/config.py)
pytest -q
```

## What's inside

| Folder | What it is |
|---|---|
| `legacy/` | A **synthetic** 2000s-style billing package (`BILLING_PKG`), written in Nov 2026 for this project. Fictional names and rates. |
| `src/gravedigger/` | Exhume, Autopsy, Resurrect, Prove |
| `mcp_server/` | MCP tools that let Kiro query the legacy database |
| `.kiro/` | Kiro steering, specs and hooks used to build this project |

---

An open-source project by **AsaanDigital Applications**, Islamabad. MIT licensed.
