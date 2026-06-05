"""Validation gate #10 — bucket IRR divergence gate (p4-24).

Tier: P3. Wraps bucket_sanity_check.py with a pass/fail exit code.

For each IRR bucket (rv_br, rv_eua, rf_balcao, fundos, crypto):
  - Computes simple average of per-asset IRRs.
  - Compares against the stored portfolio bucket IRR.
  - If |delta| > threshold (default 5%), emits gate_fail and exits 1.

The 5% threshold is an evidence-based value (p2-15 gate #10), not an S7
threshold — no config source; hardcoded as default but overridable via
--threshold CLI arg.

Informational buckets (2026-06-05): the crypto bucket is reported but NEVER
counted as a gate failure — its divergence is expected by construction. The
stored crypto bucket IRR is a lifetime BRL XIRR including realized flows of
closed/swapped coins, while the simple average covers only open positions'
per-asset IRRs (BRL swap-timing convention); the gap is unbounded under swap
activity. See docs/investimentos.md § Crypto Per-Asset IRR.

Auto-halt: exits non-zero on divergence; surfaces per-asset breakdown.
User decides whether to investigate further — no auto-loop.

Usage:
    python gate_bucket_divergence.py [--portfolio-path PATH]
                                     [--bucket BUCKET]
                                     [--threshold FLOAT]

Exit codes:
    0   Pass — all checked buckets within threshold
    1   Fail — one or more buckets diverge beyond threshold
    2   Error — portfolio.json not found
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import audit

# Resolve investimentos scripts directory for bucket_sanity_check import.
_INVESTIMENTOS_DIR = Path(__file__).resolve().parent.parent / "investimentos"
sys.path.insert(0, str(_INVESTIMENTOS_DIR))
import bucket_sanity_check as bsc

_GATE_NAME = "gate_10_bucket_divergence"
_DEFAULT_THRESHOLD = 0.05

# Buckets whose bucket-vs-simple-average divergence is EXPECTED by construction
# and therefore reported as informational, never counted toward gate failure.
# crypto: stored bucket IRR = lifetime BRL XIRR including closed/swapped coins;
# simple average = open positions only (BRL swap-timing convention). The two
# measure different things and their gap is unbounded under swap activity.
# Decision 2026-06-05 (investments-mgmt: IRR-gates deferred-items
# investigation); convention in docs/investimentos.md § Crypto Per-Asset IRR.
_INFORMATIONAL_BUCKETS = frozenset({"crypto"})


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


def check_divergences(portfolio: dict, target_bucket: str | None, threshold: float) -> int:
    """Return count of buckets exceeding threshold. Prints the full report.

    Reuses bucket_sanity_check.check_buckets for the actual computation.
    Buckets in _INFORMATIONAL_BUCKETS are reported but never counted.
    """
    return bsc.check_buckets(portfolio, target_bucket, threshold,
                             informational_buckets=_INFORMATIONAL_BUCKETS)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Gate #10: bucket IRR divergence — fail if |delta| > threshold."
    )
    parser.add_argument("--portfolio-path", help="Override portfolio.json path")
    parser.add_argument(
        "--bucket",
        choices=list(bsc._ALL_BUCKETS),
        help="Narrow to one bucket (default: check all)"
    )
    parser.add_argument(
        "--threshold", type=float, default=_DEFAULT_THRESHOLD,
        help=f"Divergence threshold as decimal (default {_DEFAULT_THRESHOLD} = 5%%)"
    )
    args = parser.parse_args()

    portfolio_path = Path(args.portfolio_path) if args.portfolio_path else _default_portfolio_path()

    if not portfolio_path.exists():
        print(f"ERROR: portfolio.json not found: {portfolio_path}", file=sys.stderr)
        return 2

    try:
        with open(portfolio_path, encoding="utf-8") as f:
            portfolio = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: could not read portfolio.json: {exc}", file=sys.stderr)
        return 2

    divergences = check_divergences(portfolio, args.bucket, args.threshold)
    passed = divergences == 0

    audit.emit_gate(
        _GATE_NAME,
        metric="bucket_divergence_count",
        value=float(divergences),
        threshold=0.0,
        passed=passed,
        source_function="gate_bucket_divergence.main",
        trigger_context={
            "portfolio_path": str(portfolio_path),
            "threshold": args.threshold,
            "bucket": args.bucket or "all",
            "informational_buckets": sorted(_INFORMATIONAL_BUCKETS),
        },
    )

    if passed:
        print(f"gate_10 PASS — no bucket divergences above {args.threshold * 100:.1f}%")
        return 0

    print(
        f"gate_10 FAIL — {divergences} bucket(s) exceed {args.threshold * 100:.1f}% divergence",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
