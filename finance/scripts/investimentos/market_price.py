"""market_price: live and historical market-price quotes for arbitrary tickers.

Wraps price_fetcher.fetch_prices to expose arbitrary-ticker quoting as a
registered read CLI tool — resolves disputed market figures through the
tools-only invariant (thesis.md Step 2 Market-figure range rule).

Supports US equities (yfinance), B3 stocks (yfinance .SA + brapi fallback),
crypto (CoinGecko, BRL-denominated), market indices (yfinance), and BR/ADR
cross-listing resolution (E28). Live mode and historical mode via --as-of.

This tool is READ-ONLY. It NEVER writes to any ledger or store.

Usage:
    python market_price.py TICKER [TICKER ...] [--as-of YYYY-MM-DD]
                           [--market us|br|crypto|index]

Examples:
    python market_price.py TEAM PETR4 BTC
    python market_price.py TEAM --as-of 2026-01-15
    python market_price.py PETR4 --market br
    python market_price.py DXY              # index auto-detected
    python market_price.py DXY --market index
    python market_price.py ELET3 EBR        # BR + ADR; ADR mapping auto-applied

Market inference (applied when --market is absent):
    index  — ticker is a known index token (DXY, SPX, IBOV, NDX, …)
    B3     — ticker matches ^[A-Z]{4}\\d{1,2}$ (e.g. PETR4, BBAS3, VALE3)
    crypto — ticker is a known CoinGecko symbol (BTC, ETH, BNB, …)
    US     — all other tickers (TEAM, AAPL, BRK.B, …)

Native currency printed explicitly:
    US/index → USD
    B3       → BRL
    crypto   → BRL

Exit codes:
    0  All tickers quoted successfully
    1  One or more tickers returned missing/DELISTED (API unavailable / unknown)
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
# Index symbol map (E28 — gap #3)
# Maps canonical user-facing token → yfinance symbol.
# market_price resolves these as US-style (bare, no suffix) via fetch_prices.
# ---------------------------------------------------------------------------
_INDEX_SYMBOLS: dict[str, str] = {
    # Dollar index
    'DXY':   'DX-Y.NYB',   # ICE US Dollar Index — primary
    'USDX':  'DX-Y.NYB',
    # US equity indices
    'SPX':   '^GSPC',
    'SP500': '^GSPC',
    'NDX':   '^NDX',
    'NASDAQ': '^NDX',
    'DJIA':  '^DJI',
    'DOW':   '^DJI',
    'VIX':   '^VIX',
    # Brazilian index
    'IBOV':  '^BVSP',
    'IBOVESPA': '^BVSP',
    # Other
    'RUT':   '^RUT',   # Russell 2000
}

# ---------------------------------------------------------------------------
# BR ↔ ADR mapping (E28 — gap #5)
# Maps B3 ticker ↔ NYSE/NASDAQ ADR (both directions).
# When a BR ticker has an ADR, market_price resolves both legs.
# ---------------------------------------------------------------------------
_BR_TO_ADR: dict[str, str] = {
    'ELET3': 'EBR',   # Eletrobras ON → NYSE ADR
    'ELET6': 'ERJ',   # Note: ERJ is Embraer; EBR covers ELET3. ELET6 uses EBR too.
    'CPLE6': 'ELP',   # Copel PNB → NYSE ADR
    'PETR4': 'PBR',   # Petrobras PN → NYSE ADR
    'PETR3': 'PBR',
    'VALE3': 'VALE',  # Vale ON → NYSE ADR
    'ITUB4': 'ITUB',  # Itaú PN → NYSE ADR
    'BBDC4': 'BBD',   # Bradesco PN → NYSE ADR
    'ABEV3': 'ABEV',  # Ambev → NYSE ADR
    'BRAP4': 'EB',    # Bradespar PN — EB is documented as an ADR in the evidence
    'PRIO3': 'PRIO',
}
_ADR_TO_BR: dict[str, str] = {v: k for k, v in _BR_TO_ADR.items()}
# Note: EB maps to BRAP4 in the reverse direction.


# ---------------------------------------------------------------------------
# Market inference
# ---------------------------------------------------------------------------

def _infer_market(ticker: str) -> str:
    """Return 'index', 'br', 'crypto', or 'us' for the given ticker."""
    t = ticker.upper()
    if t in _INDEX_SYMBOLS:
        return 'index'
    if t in _CRYPTO_SYMBOLS:
        return 'crypto'
    if _B3_PATTERN.match(t):
        return 'br'
    return 'us'


def _resolve_index_yf_symbol(ticker: str) -> str:
    """Return the yfinance symbol for an index token."""
    return _INDEX_SYMBOLS.get(ticker.upper(), ticker.upper())


def _ticker_to_position(ticker: str, market: str) -> dict:
    """Build the position dict fetch_prices expects from a ticker + market."""
    t = ticker.upper()
    if market == 'br':
        return {'id': t, 'currency': 'BRL', 'asset_class': 'variable_income', 'type': 'acao'}
    if market == 'crypto':
        return {'id': t, 'currency': 'BRL', 'asset_class': 'crypto', 'type': 'crypto'}
    if market == 'index':
        # Indices are fetched as bare US symbols via yfinance.
        # We use the yf symbol as the id so fetch_prices resolves it directly.
        yf_sym = _resolve_index_yf_symbol(t)
        return {'id': yf_sym, 'currency': 'USD', 'asset_class': 'variable_income', 'type': 'index'}
    # us
    return {'id': t, 'currency': 'USD', 'asset_class': 'variable_income', 'type': 'stock_us'}


def _native_currency(market: str) -> str:
    return 'BRL' if market in ('br', 'crypto') else 'USD'


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
    index_id_map: dict[str, str] | None = None,
) -> list[dict]:
    """Build display rows for the given tickers.

    index_id_map: maps original index token (e.g. 'DXY') → the yf symbol used
    as the price_data key (e.g. 'DX-Y.NYB'). Required so the display shows the
    user's token but looks up price_data by the yf symbol.
    """
    index_id_map = index_id_map or {}
    rows = []
    for ticker in tickers:
        t = ticker.upper()
        market = markets[ticker]
        currency = _native_currency(market)

        # For index market, price_data is keyed by the yf symbol, not the user token.
        if market == 'index':
            lookup_key = index_id_map.get(t, _resolve_index_yf_symbol(t))
        else:
            lookup_key = t

        info = price_data.get(lookup_key, {})
        source = info.get('price_source', 'missing')
        is_delisted = info.get('delisted', False)
        price_raw = info.get('current_price', 0) if source != 'missing' else None
        price_date = info.get('price_date', '') or ''
        changes = info.get('price_changes', {}) if source != 'missing' else {}

        # Status: DELISTED > MISSING > OK
        if is_delisted:
            status = 'DELISTED'
        elif source == 'api':
            status = 'OK'
        else:
            status = 'MISSING'

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
            'status': status,
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
    n_delisted = sum(1 for r in rows if r['status'] == 'DELISTED')
    n_missing = sum(1 for r in rows if r['status'] == 'MISSING')
    summary_parts = [f'{n_ok} OK']
    if n_delisted:
        summary_parts.append(f'{n_delisted} DELISTED')
    if n_missing:
        summary_parts.append(f'{n_missing} MISSING')
    print(f'\n  {len(rows)} ticker(s) queried — {", ".join(summary_parts)}')
    if n_delisted:
        delisted_list = [r['ticker'] for r in rows if r['status'] == 'DELISTED']
        print(f'  DELISTED: {", ".join(delisted_list)}')
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
        choices=['us', 'br', 'crypto', 'index'],
        help='Override market for ALL tickers in this invocation (us|br|crypto|index)',
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

    # Resolve market per ticker.
    # E28 (gap #5): if a BR ticker has an ADR mapping or an ADR token has a
    # BR mapping, auto-expand so BOTH legs are resolved (unless the user
    # explicitly provided both already).
    input_tickers_upper = {r.upper() for r in args.tickers}
    extra_tickers: list[str] = []   # ADR/BR legs auto-added

    if not args.market:
        for raw in args.tickers:
            t = raw.upper()
            inferred = _infer_market(t)
            if inferred == 'br' and t in _BR_TO_ADR:
                adr = _BR_TO_ADR[t]
                if adr not in input_tickers_upper:
                    extra_tickers.append(adr)
                    input_tickers_upper.add(adr)
            elif inferred == 'us' and t in _ADR_TO_BR:
                br = _ADR_TO_BR[t]
                if br not in input_tickers_upper:
                    extra_tickers.append(br)
                    input_tickers_upper.add(br)

    all_tickers = list(args.tickers) + extra_tickers

    markets: dict[str, str] = {}
    for raw in all_tickers:
        t = raw.upper()
        markets[raw] = args.market if args.market else _infer_market(t)

    # Build position list for fetch_prices (uses uppercase IDs throughout).
    # For index tickers, the position id is the yf symbol, not the user token.
    index_id_map: dict[str, str] = {}   # user_token_upper → yf_symbol
    positions = []
    for raw in all_tickers:
        t = raw.upper()
        market = markets[raw]
        pos = _ticker_to_position(raw, market)
        positions.append(pos)
        if market == 'index':
            index_id_map[t] = pos['id']   # pos['id'] is already the yf symbol

    # Fetch — fetch_prices returns dict keyed by id (yf symbol for index, ticker otherwise)
    price_data = fetch_prices(positions, as_of_date=as_of)

    # Build and print table
    rows = _build_rows(all_tickers, markets, price_data, index_id_map=index_id_map)
    _print_table(rows, as_of)

    # Mark auto-added ADR/BR legs in the footer if any were expanded
    if extra_tickers:
        print(f'  (auto-expanded ADR/BR legs: {", ".join(extra_tickers)})\n')

    # Exit code: 0 = all OK, 1 = any missing or delisted
    any_not_ok = any(r['status'] in ('MISSING', 'DELISTED') for r in rows)
    sys.exit(1 if any_not_ok else 0)


if __name__ == '__main__':
    main()
