"""Run the explainer once over the eight units of the legacy BILLING_PKG.

With an API key set, units without a cache file are explained by the real LLM
provider and saved to golden/autopsy (about one cent per full run). A second run
finds every cache file and makes no LLM call. Without a key, the script prints the
cached explanations when all eight exist, and otherwise exits before any call.

Run only after approval:  .venv\\Scripts\\python.exe scripts\\explain_sample.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from gravedigger.autopsy.explain import (  # noqa: E402
    Explanation,
    _source_hash,
    client_from_settings,
    explain,
)
from gravedigger.autopsy.scanner import scan  # noqa: E402
from gravedigger.exhume import Unit, load_package  # noqa: E402

LEGACY_DIR = REPO_ROOT / "legacy"
CACHE_DIR = REPO_ROOT / "golden" / "autopsy"


def _has_cache(unit: Unit) -> bool:
    """True when the cache folder holds a file for this unit's source."""
    pattern = f"{unit.name}-{_source_hash(unit)}-*.json"
    return CACHE_DIR.is_dir() and any(CACHE_DIR.glob(pattern))


def _print_explanation(out: Explanation) -> None:
    print("=" * 72)
    print(f"{out.unit}  [source: {out.source}]")
    print(f"Summary: {out.summary or '(none)'}")
    print(f"Kept rules ({len(out.rules)}):")
    for rule in out.rules:
        lines = ", ".join(str(n) for n in rule.lines)
        print(f"  - [{rule.category}] {rule.text} (lines {lines})")
    print(f"Dropped rules ({len(out.dropped)}):")
    for item in out.dropped:
        lines = ", ".join(str(n) for n in item.rule.lines) or "none"
        print(f"  - {item.rule.text} (lines {lines})")
        print(f"    Reason: {item.reason}")


def main() -> int:
    spec_text = (LEGACY_DIR / "billing_pkg.pks").read_text(encoding="utf-8")
    body_text = (LEGACY_DIR / "billing_pkg.pkb").read_text(encoding="utf-8")
    package = load_package(spec_text, body_text)

    client = client_from_settings()
    if client is None and not all(_has_cache(u) for u in package.units):
        print(
            "LLM_API_KEY is not set and the cache in golden/autopsy is incomplete. "
            "Set LLM_API_KEY in the environment or .env, then run again."
        )
        return 1

    for unit in package.units:
        facts = scan(unit)
        out = explain(unit, facts, client=client, cache_dir=CACHE_DIR)
        _print_explanation(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
