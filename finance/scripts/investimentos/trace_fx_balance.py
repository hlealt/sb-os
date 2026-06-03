"""trace_fx_balance: per-event USD balance trace for the Avenue FX engine.

Default (verbose) mode: replays the exact event stream fx_engine.build_fx_state
processes (via fx_engine.load_events / apply_event) and prints:
  - event count by type
  - every negative-balance period (entry event, min, recovery event,
    and each event that occurred while the balance was negative)
  - final engine state (usd_balance, weighted_avg_rate, per-ticker lots)

--strict mode: exits non-zero if the USD balance ever drops below -EPS at
any point in the replay. This is the verification gate for the invariant
"fx_state.usd_balance >= 0 across the full history" (finance-system task:
Avenue negative-balance investigation).

This tool is READ-ONLY. It NEVER writes to any ledger.

Usage:
    python trace_fx_balance.py [--strict] [--eps EPS]

Exit codes (verbose):  0 always (informational report)
Exit codes (--strict): 0 = balance never negative, 1 = negative period found
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fx_engine import FXState, apply_event, load_events

DEFAULT_EPS = 0.005  # half a cent — tolerates float residue


def describe(evt: dict) -> str:
    if evt['type'] == 'fx':
        return f"fx {evt['operation']} usd={evt['usd']:.2f} rate={evt['fx_rate']:.4f}"
    if evt['type'] == 'order':
        side = 'BUY' if evt['side'] == 'C' else 'SELL'
        return (f"order {side} {evt['ticker']} qty={evt['quantity']} "
                f"px={evt['price']} total={evt['total']:.2f}")
    return f"provento {evt['ticker']} usd={evt['amount_usd']:.2f}"


def trace(eps: float) -> tuple[FXState, list[dict]]:
    """Replay all events; return final state and negative-balance periods."""
    events = load_events()
    state = FXState()
    neg_periods: list[dict] = []
    current: dict | None = None

    print(f"events: {len(events)} "
          f"(fx={sum(1 for e in events if e['type'] == 'fx')}, "
          f"orders={sum(1 for e in events if e['type'] == 'order')}, "
          f"proventos={sum(1 for e in events if e['type'] == 'provento')})")

    for evt in events:
        before = state.usd_balance
        apply_event(state, evt)
        after = state.usd_balance

        was_neg = before < -eps
        is_neg = after < -eps
        if is_neg and not was_neg:
            current = {'start': evt['date'], 'min': after,
                       'min_date': evt['date'], 'events': []}
        if is_neg and current is not None:
            current['events'].append((evt['date'], describe(evt), after))
            if after < current['min']:
                current['min'] = after
                current['min_date'] = evt['date']
        if was_neg and not is_neg and current is not None:
            current['end'] = evt['date']
            current['recovery'] = describe(evt)
            neg_periods.append(current)
            current = None

    if current is not None:
        current['end'] = '(never recovered)'
        current['recovery'] = '-'
        neg_periods.append(current)

    return state, neg_periods


def report(state: FXState, neg_periods: list[dict]) -> None:
    print(f"\nnegative periods: {len(neg_periods)}")
    for i, p in enumerate(neg_periods, 1):
        print(f"\n--- period {i}: {p['start']} -> {p.get('end')} | "
              f"min {p['min']:.2f} on {p['min_date']}")
        print(f"    recovered via: {p.get('recovery')}")
        for d, desc, bal in p['events']:
            print(f"    {d}  {desc:<58} bal={bal:>10.2f}")

    print(f"\nfinal: usd_balance={state.usd_balance:.2f} "
          f"weighted_avg_rate={state.weighted_avg_rate:.4f}")
    active = sorted({l.ticker for l in state.lots if l.quantity > 0})
    print(f"active tickers: {len(active)}")
    for t in active:
        print(f"  {t}: qty={state.get_ticker_quantity(t):.4f} "
              f"cost_brl={state.get_ticker_cost_brl(t):.2f} "
              f"avg_fx={state.get_ticker_fx_rate(t):.4f}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Per-event USD balance trace for the Avenue FX engine.")
    parser.add_argument('--strict', action='store_true',
                        help='exit 1 if the USD balance ever goes negative')
    parser.add_argument('--eps', type=float, default=DEFAULT_EPS,
                        help=f'negativity tolerance (default {DEFAULT_EPS})')
    args = parser.parse_args()

    state, neg_periods = trace(args.eps)
    report(state, neg_periods)

    if args.strict and neg_periods:
        print(f"\nSTRICT: FAIL — {len(neg_periods)} negative period(s)",
              file=sys.stderr)
        return 1
    if args.strict:
        print("\nSTRICT: PASS — usd_balance >= 0 across full history")
    return 0


if __name__ == '__main__':
    sys.exit(main())
