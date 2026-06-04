"""market_price: live and historical market-price quotes for arbitrary tickers.

Wraps price_fetcher.fetch_prices to expose arbitrary-ticker quoting as a
registered read CLI tool — resolves disputed market figures through the
tools-only invariant (thesis.md Step 2 Market-figure range rule).

Supports US equities (yfinance), B3 stocks (yfinance .SA + brapi fallback),
and crypto (CoinGecko, BRL-denominated). Live mode and historical mode
via --as-of YYYY-MM-DD.

This tool is READ-ONLY. It NEVER writes to any ledger or store.

Usage:
    python market_price.py TICKER [TICKER ...] [--as-of YYYY-MM-DD]
                           [--market us|br|crypto]

Examples:
    python market_price.py TEAM PETR4 BTC
    python market_price.py TEAM --as-of 2026-01-15
    python market_price.py PETR4 --market br

Market inference (applied when --market is absent):
    B3   — ticker matches ^[A-Z]{4}\\d{1,2}$ (e.g. PETR4, BBAS3, VALE3)
    crypto — ticker is a known CoinGecko symbol (BTC, ETH, BNB, …)
    US   — all other tickers (TEAM, AAPL, BRK.B, …)

Native currency printed explicitly:
    US    → USD
    B3    → BRL
    crypto → BRL

Exit codes:
    0  All tickers quoted successfully
    1  One or more tickers returned missing (API unavailable / unknown ticker)
    2  Usage error (bad --as-of format, conflicting flags)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Import price_fetcher from the same directory (plain relative import safe
# when invoked as `python investimentos/market_price.py` from scripts dir,
# or directly from this directory).
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from price_fetcher import fetch_prices  # noqa: E402


# ---------------------------------------------------------------------------
# CoinGecko known symbols (kept in sync with price_fetcher._fetch_coingecko)
# ---------------------------------------------------------------------------
_CRYPTO_SYMBOLS = frozenset({
    'BTC', 'ETH', 'BNB', 'ADA', 'DOT', 'LINK', 'XRP', 'STX', 'NMR', 'USDT',
})

# B3 ticker pattern: exactly 4 uppercase letters followed by 1-2 digits.
_B3_PATTERN = re.compile(r'^[A-Z]{4}\d{1,2}$')


# ---------------------------------------------------------------------------
# Market inference
# ---------------------------------------------------------------------------

def _infer_market(ticker: str) -> str:
    """Return 'br', 'crypto', or 'us' for the given ticker."""
    if ticker.upper() in _CRYPTO_SYMBOLS:
        return 'crypto'
    if _B3_PATTERN.match(ticker.upper()):
        return 'br'
    return 'us'


def _ticker_to_position(ticker: str, market: str) -> dict:
    """Build the position dict fetch_prices expects from a ticker + market."""
    t = ticker.upper()
    if market == 'br':
        return {'id': t, 'currency': 'BRL', 'asset_class': 'variable_income', 'type': 'acao'}
    if market == 'crypto':
        return {'id': t, 'currency': 'BRL', 'asset_class': 'crypto', 'type': 'crypto'}
    # us
    return {'id': t, 'currency': 'USD', 'asset_class': 'variable_income', 'type': 'stock_us'}


def _native_currency(market: str) -> str:
    return 'USD' if market == 'us' else 'BRL'


# ---------------------------------------------------------------------------
# Formatting helpers (mirror style of position_table.py)
# ---------------------------------------------------------------------------

def _fmt_price(v: Optional[float], decimals: int = 4) -> str:
    if v is None or v == 0:
        return 'n/a'
    return f'{v:.{decimals}f}'


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return 'n/a'
    return f'{v * 100:+.2f}%'


# ---------------------------------------------------------------------------
# Core: build and print the results table
# ---------------------------------------------------------------------------

def _build_rows(
    tickers: list[str],
    markets: dict[str, str],
    price_data: dict,
) -> list[dict]:
    rows = []
    for ticker in tickers:
        t = ticker.upper()
        market = markets[ticker]
        currency = _native_currency(market)
        info = price_data.get(t, {})

        source = info.get('price_source', 'missing')
        price_raw = info.get('current_price', 0) if source != 'missing' else None
        price_date = info.get('price_date', '') or ''
        changes = info.get('price_changes', {}) if source != 'missing' else {}

        row = {
            'ticker': t,
            'market': market,
            'currency': currency,
            'price': _fmt_price(price_raw),
            'price_date': price_date or 'n/a',
            'source': source,
            '1d': _fmt_pct(changes.get('1d')) if changes.get('1d') is not None else 'n/a',
            '30d': _fmt_pct(changes.get('30d')) if changes.get('30d') is not None else 'n/a',
            '90d': _fmt_pct(changes.get('90d')) if changes.get('90d') is not None else 'n/a',
            '180d': _fmt_pct(changes.get('180d')) if changes.get('180d') is not None else 'n/a',
            '365d': _fmt_pct(changes.get('365d')) if changes.get('365d') is not None else 'n/a',
            'ytd': _fmt_pct(changes.get('ytd')) if changes.get('ytd') is not None else 'n/a',
            'status': 'OK' if source == 'api' else 'MISSING',
        }
        rows.append(row)
    return rows


def _print_table(rows: list[dict], as_of: Optional[str]) -> None:
    mode_label = f"  as-of: {as_of}" if as_of else "  mode: live"
    print(f"\n  market_price — {mode_label}\n")

    cols = ['ticker', 'market', 'currency', 'price', 'price_date', 'source',
            '1d', '30d', '90d', '180d', '365d', 'ytd', 'status']
    headers = ['ticker', 'market', 'currency', 'price', 'price_date', 'source',
               '1d', '30d', '90d', '180d', '365d', 'ytd', 'status']

    widths = {c: len(h) for c, h in zip(cols, headers)}
    for row in rows:
        for c in cols:
            widths[c] = max(widths[c], len(str(row[c])))

    sep = '  '.join('-' * widths[c] for c in cols)
    header_line = '  '.join(h.ljust(widths[c]) for c, h in zip(cols, headers))
    print(f'  {header_line}')
    print(f'  {sep}')
    for row in rows:
        line = '  '.join(str(row[c]).ljust(widths[c]) for c in cols)
        print(f'  {line}')
    print(f'  {sep}')

    n_ok = sum(1 for r in rows if r['status'] == 'OK')
    n_missing = len(rows) - n_ok
    print(f'\n  {len(rows)} ticker(s) queried — {n_ok} OK, {n_missing} MISSING')
    if n_missing:
        missing_list = [r['ticker'] for r in rows if r['status'] == 'MISSING']
        print(f'  MISSING: {", ".join(missing_list)}')
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Quote live or historical market prices for arbitrary tickers.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'tickers',
        nargs='+',
        metavar='TICKER',
        help='One or more ticker symbols (e.g. TEAM PETR4 BTC)',
    )
    parser.add_argument(
        '--as-of',
        metavar='YYYY-MM-DD',
        help='Historical mode: fetch end-of-day price on or before this date',
    )
    parser.add_argument(
        '--market',
        choices=['us', 'br', 'crypto'],
        help='Override market for ALL tickers in this invocation (us|br|crypto)',
    )

    args = parser.parse_args()

    # Validate --as-of format
    as_of: Optional[str] = None
    if args.as_of:
        try:
            from datetime import datetime as _dt
            _dt.strptime(args.as_of, '%Y-%m-%d')
            as_of = args.as_of
        except ValueError:
            print(
                f'ERROR: --as-of must be YYYY-MM-DD, got: {args.as_of!r}',
                file=sys.stderr,
            )
            sys.exit(2)

    # Resolve market per ticker
    markets: dict[str, str] = {}
    for raw in args.tickers:
        t = raw.upper()
        markets[raw] = args.market if args.market else _infer_market(t)

    # Build position list for fetch_prices (uses uppercase IDs throughout)
    positions = [_ticker_to_position(raw, markets[raw]) for raw in args.tickers]

    # Fetch — fetch_prices returns dict keyed by uppercase ticker id
    price_data = fetch_prices(positions, as_of_date=as_of)

    # Build and print table
    rows = _build_rows(args.tickers, markets, price_data)
    _print_table(rows, as_of)

    # Exit code: 0 = all OK, 1 = any missing
    any_missing = any(r['status'] == 'MISSING' for r in rows)
    sys.exit(1 if any_missing else 0)


if __name__ == '__main__':
    main()
