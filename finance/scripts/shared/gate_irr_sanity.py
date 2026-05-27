"""Validation gate #9 — IRR sanity check with --strict exit code (p4-23).

Tier: P3. Wraps validate_calculate.py --strict with gate-event emission.

Violations detected (fail-loud):
  - |irr| > 200% for any position or class bucket
  - irr_quality missing on a balcão position with current_value
  - (S7-2) rf_balcao positions with annualized return outside [7%, 15%] band

The rf_balcao expected-return band is config-driven from:
  investment_rules.sanity_bands.rf_balcao.expected_return_pct_min
  investment_rules.sanity_bands.rf_balcao.expected_return_pct_max

Usage:
    python gate_irr_sanity.py [--portfolio-path PATH] [--config-dir PATH]

Exit codes:
    0   Pass — no IRR sanity violations
    1   Fail — one or more violations found
    2   Error — portfolio.json not found or config unreadable
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import audit, standing_rules as sr

# Resolve investimentos scripts directory so validate_calculate can be imported.
_INVESTIMENTOS_DIR = Path(__file__).resolve().parent.parent / "investimentos"
sys.path.insert(0, str(_INVESTIMENTOS_DIR))
import validate_calculate as vc

_GATE_NAME = "gate_9_irr_sanity"

# Fallbacks when config is unavailable.
_RF_BALCAO_MIN_FALLBACK = 7.0
_RF_BALCAO_MAX_FALLBACK = 15.0


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


def _default_portfolio_path() -> Path:
    override = os.environ.get("BOOKKEEPER_PORTFOLIO_PATH")
    if override:
        return Path(override)
    return (
        _find_vault_root()
        / ".user" / "finance" / "bookkeeper" / "ledgers" / "investimentos" / "portfolio.json"
    )


def _default_config_dir() -> Path:
    return _find_vault_root() / ".user" / "finance" / "bookkeeper" / "config"


def _load_rf_balcao_band(config_dir: Path) -> tuple[float, float]:
    """Return (min_pct, max_pct) for rf_balcao expected return from config.

    Values are in percent (e.g. 7.0 means 7%).
    Returns fallback values if config is unavailable.
    """
    try:
        rules = sr.load_standing_rules(config_dir)
        inv_rules = rules.get("investment_rules", {})
        if not isinstance(inv_rules, dict):
            return _RF_BALCAO_MIN_FALLBACK, _RF_BALCAO_MAX_FALLBACK
        bands = inv_rules.get("sanity_bands", {})
        rf = bands.get("rf_balcao", {}) if isinstance(bands, dict) else {}
        min_pct = rf.get("expected_return_pct_min")
        max_pct = rf.get("expected_return_pct_max")
        if (
            min_pct is not None and isinstance(min_pct, (int, float))
            and max_pct is not None and isinstance(max_pct, (int, float))
        ):
            return float(min_pct), float(max_pct)
    except sr.StandingRulesError:
        pass
    return _RF_BALCAO_MIN_FALLBACK, _RF_BALCAO_MAX_FALLBACK


# Bucket classification matching bucket_sanity_check.py
_RF_TYPES = {"cra", "deb", "lca", "lci", "cdb", "cdb_mp", "tesouro", "lc", "cri", "rf"}
_FUND_TYPES = {"fia_br", "fia_usa", "fim_br", "firf_br", "fidc", "coe", "di"}


def _is_rf_balcao(pos: dict) -> bool:
    typ = (pos.get("type") or "").lower()
    asset_class = (pos.get("asset_class") or "").lower()
    if asset_class == "crypto" or typ == "crypto":
        return False
    if typ in _FUND_TYPES:
        return False
    return typ in _RF_TYPES


def check_rf_balcao_band(
    portfolio: dict, min_pct: float, max_pct: float
) -> list[str]:
    """Return violation strings for rf_balcao positions outside [min_pct, max_pct]%.

    Compares each position's `irr` (annualized, stored as decimal) against the
    band converted to decimal. A position with irr=None is skipped (no data).
    """
    violations: list[str] = []
    for pos in portfolio.get("positions", []):
        if not _is_rf_balcao(pos):
            continue
        irr = pos.get("irr")
        if irr is None:
            continue
        irr_pct = irr * 100
        if irr_pct < min_pct or irr_pct > max_pct:
            violations.append(
                f"Position '{pos.get('id', '?')}' (rf_balcao): "
                f"IRR {irr_pct:+.2f}% is outside expected band [{min_pct:.0f}%, {max_pct:.0f}%]"
            )
    return violations


def run_gate(portfolio_path: Path, config_dir: Path) -> tuple[bool, list[str]]:
    """Run all gate #9 checks. Return (passed, violations)."""
    portfolio = vc.load_portfolio(portfolio_path)

    # validate_calculate.py strict checks.
    irr_v = vc._irr_violations(portfolio)
    qual_v = vc._quality_violations(portfolio)

    # rf_balcao band (S7-2).
    min_pct, max_pct = _load_rf_balcao_band(config_dir)
    band_v = check_rf_balcao_band(portfolio, min_pct, max_pct)

    all_violations = irr_v + qual_v + band_v
    return (len(all_violations) == 0), all_violations


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Gate #9: IRR sanity (--strict) + rf_balcao band check."
    )
    parser.add_argument("--portfolio-path", help="Override portfolio.json path")
    parser.add_argument("--config-dir", help="Override bookkeeper config dir")
    args = parser.parse_args()

    portfolio_path = Path(args.portfolio_path) if args.portfolio_path else _default_portfolio_path()
    config_dir = Path(args.config_dir) if args.config_dir else _default_config_dir()

    if not portfolio_path.exists():
        print(f"ERROR: portfolio.json not found: {portfolio_path}", file=sys.stderr)
        return 2

    try:
        passed, violations = run_gate(portfolio_path, config_dir)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: could not read portfolio.json: {exc}", file=sys.stderr)
        return 2

    violation_count = len(violations)

    audit.emit_gate(
        _GATE_NAME,
        metric="irr_violation_count",
        value=float(violation_count),
        threshold=0.0,
        passed=passed,
        source_function="gate_irr_sanity.main",
        trigger_context={"portfolio_path": str(portfolio_path)},
    )

    if violations:
        print(f"IRR sanity violations ({violation_count}):", file=sys.stderr)
        for msg in violations:
            print(f"  FAIL  {msg}", file=sys.stderr)
    else:
        print("IRR sanity: no violations.")

    if passed:
        print(f"gate_9 PASS — IRR sanity clean")
        return 0

    print(f"gate_9 FAIL — {violation_count} violation(s) found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
