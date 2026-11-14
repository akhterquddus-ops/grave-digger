"""Connection settings, read from environment variables or the repo's .env file.

.env is git-ignored. Keys:
  ORACLE_DSN         e.g. localhost:1521/FREEPDB1
  ORACLE_USER        the app user, e.g. gd
  APP_USER_PASSWORD  password of the app user
  ORACLE_PASSWORD    SYS password, used only by the Docker container (never by the app)
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def setting(key: str, default: str | None = None) -> str | None:
    """Environment variable first, then .env at the repo root, then the default."""
    if key in os.environ:
        return os.environ[key]
    return _read_dotenv(REPO_ROOT / ".env").get(key, default)


def oracle_params() -> dict[str, str]:
    """Keyword arguments for oracledb.connect(). Raises if something is missing."""
    params = {
        "dsn": setting("ORACLE_DSN"),
        "user": setting("ORACLE_USER"),
        "password": setting("APP_USER_PASSWORD"),
    }
    missing = [k for k, v in params.items() if not v]
    if missing:
        raise RuntimeError(
            f"Oracle settings missing: {missing}. Set ORACLE_DSN, ORACLE_USER and "
            "APP_USER_PASSWORD in the environment or in .env at the repo root."
        )
    return params  # type: ignore[return-value]
