"""Shared test settings.

Hypothesis profiles (pick with HYPOTHESIS_PROFILE=ci):
  dev = 200 examples (default, used by the Kiro on-save hook)
  ci  = 2000 examples, fixed seed, no deadline
Tests marked @pytest.mark.oracle are skipped when no Oracle settings are available.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hypothesis import settings

from gravedigger.config import setting

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY = REPO_ROOT / "legacy"

settings.register_profile("dev", max_examples=200)
settings.register_profile("ci", max_examples=2000, derandomize=True, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


def pytest_collection_modifyitems(config, items):
    if setting("ORACLE_DSN"):
        return
    skip = pytest.mark.skip(reason="ORACLE_DSN not set: Oracle tests skipped")
    for item in items:
        if "oracle" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def legacy_sources() -> tuple[str, str]:
    """(package spec text, package body text) of the synthetic BILLING_PKG."""
    return (
        (LEGACY / "billing_pkg.pks").read_text(encoding="utf-8"),
        (LEGACY / "billing_pkg.pkb").read_text(encoding="utf-8"),
    )
