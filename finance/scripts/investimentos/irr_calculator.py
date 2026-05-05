"""IRR (XIRR) calculator for investment portfolio.

Computes XIRR using dated cash flows from ledger data.
Uses scipy.optimize for XIRR (numpy-financial's irr() is for regular periods).
"""

import sys
from datetime import datetime
from scipy.optimize import brentq

# Sanity-check thresholds for compute_xirr warnings.
# Annualized rates above 200% almost always reflect a short window or a
# missing-flow issue rather than a real return. Windows under 90 days
# produce extreme annualization on small price moves.
_IRR_WARN_ABS_RATE = 2.0
_IRR_WARN_MIN_WINDOW_DAYS = 90


def compute_xirr(cash_flows: list[tuple[str, float]],
                 terminal_value: float = 0,
                 terminal_date: str = None,
                 label: str = None,
                 expect_positive: bool = False) -> float | None:
    """Compute XIRR from dated cash flows.

    Args:
        cash_flows: List of (date_str, amount) tuples.
                    Negative = outflow (buys), positive = inflow (sells, dividends).
        terminal_value: Current portfolio value (positive, as final inflow).
        terminal_date: Date for terminal value. Defaults to today.
        label: Optional identifier (e.g. ticker, "portfolio") used only in
               sanity-check warnings emitted to stderr. When None, warnings
               are silenced.
        expect_positive: When True and the computed rate is negative, emit
               a stderr warning. Use for BR RF tradicional (CRA, DEB, LCA,
               CDB, Tesouro etc.) where a non-defaulted instrument should
               not yield a negative nominal IRR — negatives almost always
               indicate missing flows or a snapshot issue.

    Returns:
        Annualized IRR as a decimal (0.12 = 12%), or None if can't compute.
    """
    if not cash_flows:
        return None

    if terminal_date is None:
        terminal_date = datetime.now().strftime('%Y-%m-%d')

    # Build (date, amount) list
    flows = []
    for date_str, amount in cash_flows:
        if amount == 0:
            continue
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            flows.append((dt, amount))
        except (ValueError, TypeError):
            continue

    # Add terminal value
    if terminal_value != 0:
        try:
            dt = datetime.strptime(terminal_date, '%Y-%m-%d')
            flows.append((dt, terminal_value))
        except (ValueError, TypeError):
            pass

    if len(flows) < 2:
        return None

    # Need at least one negative and one positive
    has_neg = any(a < 0 for _, a in flows)
    has_pos = any(a > 0 for _, a in flows)
    if not has_neg or not has_pos:
        return None

    # Sort by date
    flows.sort(key=lambda x: x[0])
    base_date = flows[0][0]
    last_date = flows[-1][0]
    window_days = (last_date - base_date).days

    # Convert to day fractions
    amounts = [a for _, a in flows]
    days = [(d - base_date).days / 365.25 for d, _ in flows]

    # XIRR: find rate where NPV = 0
    # NPV(r) = Σ amount_i / (1 + r)^day_i
    def npv(rate):
        return sum(a / (1 + rate) ** d for a, d in zip(amounts, days))

    try:
        result = brentq(npv, -0.99, 10.0, maxiter=500)
        rate = round(result, 6)
    except (ValueError, RuntimeError):
        # Try wider bounds
        try:
            result = brentq(npv, -0.5, 5.0, maxiter=500)
            rate = round(result, 6)
        except (ValueError, RuntimeError):
            return None

    if label:
        if window_days < _IRR_WARN_MIN_WINDOW_DAYS:
            print(f"[irr_calculator] {label}: short window "
                  f"({window_days}d < {_IRR_WARN_MIN_WINDOW_DAYS}d) — "
                  f"IRR={rate*100:.2f}% may be unreliable",
                  file=sys.stderr)
        if abs(rate) > _IRR_WARN_ABS_RATE:
            print(f"[irr_calculator] {label}: extreme IRR "
                  f"({rate*100:.2f}%, |rate| > {_IRR_WARN_ABS_RATE*100:.0f}%) — "
                  f"likely missing flows or short window over {window_days}d",
                  file=sys.stderr)
        if expect_positive and rate < 0:
            print(f"[irr_calculator] {label}: negative IRR on RF tradicional "
                  f"({rate*100:.2f}%) — no default known; check for missing "
                  f"flows (juros, amortização, snapshot) in balcao.csv",
                  file=sys.stderr)
    return rate
