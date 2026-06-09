"""Price fetcher for investment portfolio.

Strategy:
- yfinance primary for BR (`.SA` suffix) AND US (bare). One library, both markets.
- brapi.dev fallback for B3 tickers when yfinance returns no data.
- CoinGecko for crypto.
- Skip entirely for `type ∈ {opcao, direito_subscricao}` — no free API covers
  these reliably. Emits `price_source="missing"` so the dashboard renders `—`.

Historical mode (`as_of_date` set):
- yfinance: `start`/`end` anchored to `as_of_date`; `series.iloc[-1]` = last
  trading day on or before `as_of_date`.
- BRAPI: attempts the `/api/quote/{ticker}/history` endpoint (undocumented).
  If the endpoint is unavailable or returns no data for the requested date,
  returns `price_source="missing"` and emits a D13 alert — does NOT
  substitute a live price.
- CoinGecko: `/coins/{id}/history?date=DD-MM-YYYY`.
- When `as_of_date is None`, live behavior is preserved byte-for-byte.

D13 alerts (per-ticker, `materiality=high`):
- Emitted when a historical fetch fails (provider has no historical endpoint
  or returned no data for the requested date).
- Console warning to stderr + audit event (best-effort, never raises).

Delisted signal (E28, additive):
- When a yfinance ticker has historically traded but returns no recent data,
  the result carries `price_source='missing'` (dashboard contract unchanged)
  PLUS an additive `delisted: True` flag. The dashboard ignores unknown keys
  so this is safe. The market_price CLI surfaces it as status='DELISTED'.

Returns, per ticker:
    {
        'current_price': float (in native currency — BRL for B3, USD for Avenue, BRL for crypto),
        'price_source':  'api' | 'missing',
        'price_date':    'YYYY-MM-DD',
        'price_changes': { '1d','30d','90d','180d','365d','ytd': float (fractional) },
        # additive, optional, never present unless True:
        'delisted':      True   # only set when likely-delisted; dashboard ignores it
    }
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


VAULT_ROOT = _find_vault_root()

try:
    import requests
except ImportError:
    requests = None

try:
    import yfinance as yf
except ImportError:
    yf = None


# ---------------------------------------------------------------------------
# BRAPI token loader
# ---------------------------------------------------------------------------

def _load_brapi_token() -> str | None:
    """Resolve BRAPI_TOKEN: OS env first, then vault .user/config/env/.env.

    Returns the token string if found, or None if absent. Never raises.
    """
    # 1. OS environment
    token = os.environ.get('BRAPI_TOKEN')
    if token:
        return token.strip() or None

    # 2. .user/config/env/.env at vault root
    env_path = VAULT_ROOT / '.user' / 'config' / 'env' / '.env'
    try:
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('BRAPI_TOKEN='):
                    value = line[len('BRAPI_TOKEN='):]
                    return value.strip() or None
    except (OSError, IOError):
        pass
    return None


# Asset types with no reliable free-tier price source. Always 'missing'.
_UNPRICEABLE_TYPES = {'opcao', 'direito_subscricao'}

# ---------------------------------------------------------------------------
# Delisted detection threshold (E28, additive signal)
# ---------------------------------------------------------------------------
# A ticker is "likely delisted" when yfinance returns historical data (it
# existed) but no trade within the last _DELISTED_STALE_DAYS calendar days.
# This is heuristic — it catches CYBR (acquired/delisted) without false-
# positives on thinly-traded small-caps that still trade.
_DELISTED_STALE_DAYS = 90


# ---------------------------------------------------------------------------
# D13 alert helper
# ---------------------------------------------------------------------------

def _emit_price_alert(ticker: str, reason: str, as_of_date: str) -> None:
    """Emit a D13 per-ticker historical-price alert (materiality=high).

    Console warning to stderr + audit event. Never raises.
    """
    print(
        f"[price_fetcher] WARNING: historical price unavailable for {ticker} "
        f"as_of={as_of_date} — {reason}",
        file=sys.stderr,
    )
    try:
        # Shared audit module lives one directory up, under shared/lib.
        _shared = Path(__file__).resolve().parents[1] / "shared"
        if str(_shared) not in sys.path:
            sys.path.insert(0, str(_shared))
        from lib import audit
        audit.emit(
            "price_fetch_alert",
            source_function="price_fetcher._emit_price_alert",
            materiality="high",
            summary={
                "ticker": ticker,
                "as_of_date": as_of_date,
                "reason": reason,
            },
            trigger_context={"as_of_date": as_of_date},
            _stack_depth=3,
        )
    except Exception:
        pass  # audit is best-effort; never block price fetching


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_prices(
    tickers: list[dict],
    fx_rate_usd_brl: float = 5.0,
    as_of_date: str | None = None,
) -> dict:
    """Fetch prices for a list of position dicts.

    Args:
        tickers: List of dicts with 'id', 'currency', 'asset_class', 'type' keys.
        fx_rate_usd_brl: Current USD/BRL rate (not applied here — prices returned
            in native currency; calculate.py handles conversion).
        as_of_date: ISO date string ('YYYY-MM-DD'). When set, fetches historical
            end-of-day prices anchored to this date. When None, fetches live prices
            (preserves existing behavior exactly).

    Returns:
        Dict keyed by ticker id with price info (see module docstring).
    """
    results: dict = {}

    br_stocks: list[str] = []   # B3 variable_income
    us_stocks: list[str] = []   # Avenue (currency=USD)
    crypto: list[str] = []
    unpriceable: list[str] = []

    for t in tickers:
        tid = t['id']
        ttype = (t.get('type') or '').strip().lower()
        if ttype in _UNPRICEABLE_TYPES:
            unpriceable.append(tid)
            continue
        if t.get('asset_class') == 'crypto':
            crypto.append(tid)
        elif t.get('currency') == 'USD':
            us_stocks.append(tid)
        elif t.get('asset_class') == 'variable_income':
            br_stocks.append(tid)
        # fixed_income / funds: handled via balance snapshots, not API.

    # --- yfinance primary (both BR and US) ---
    if yf is not None:
        if br_stocks:
            results.update(_fetch_yfinance(br_stocks, suffix='.SA', as_of_date=as_of_date))
        if us_stocks:
            results.update(_fetch_yfinance(us_stocks, suffix='', as_of_date=as_of_date))

    # --- brapi.dev fallback for any BR ticker still missing ---
    br_missing = [t for t in br_stocks if t not in results]
    if br_missing and requests is not None:
        results.update(_fetch_brapi(br_missing, as_of_date=as_of_date))

    # --- CoinGecko for crypto ---
    if crypto and requests is not None:
        results.update(_fetch_coingecko(crypto, as_of_date=as_of_date))

    # --- Mark unpriceable + anything still missing ---
    for tid in unpriceable:
        results[tid] = _missing_result()
    for t in tickers:
        if t['id'] not in results:
            results[t['id']] = _missing_result()

    return results


def _missing_result() -> dict:
    return {
        'current_price': 0,
        'price_source': 'missing',
        'price_date': '',
        'price_changes': {},
    }


# ---------------------------------------------------------------------------
# yfinance fetcher
# ---------------------------------------------------------------------------

def _fetch_yfinance(
    tickers: list[str],
    suffix: str = '',
    as_of_date: str | None = None,
) -> dict:
    """Fetch prices + price_changes via yfinance.

    Live mode (as_of_date=None): downloads 13 months of daily closes,
    derives current price from series.iloc[-1].

    Historical mode (as_of_date set): downloads start=(as_of_date minus
    14 months), end=(as_of_date + 1 day), derives price from series.iloc[-1]
    which is the last trading day on or before as_of_date.
    """
    if not yf or not tickers:
        return {}

    # yfinance normalizes multi-class US tickers with '-' (e.g., BRK.B → BRK-B).
    # Skip the dot→dash transform for tickers that are already yfinance-native
    # format: those starting with '^' (index), those with '=' (FX/futures),
    # or those with a dot followed by a 2+-character uppercase market suffix
    # like '.SA', '.NYB', '.IL' (exchange codes).  Single-letter share-class
    # suffixes like '.B' in BRK.B are NOT exchange codes — they must be
    # converted to '-' (BRK.B → BRK-B) per yfinance convention.
    import re as _re
    _YF_NATIVE_PATTERN = _re.compile(r'[\^=]|\.(?=[A-Z]{2,})')

    def _to_yf(t: str) -> str:
        if suffix:
            return t + suffix
        # Preserve yfinance-native symbols (indices, FX, exchange-suffixed).
        if _YF_NATIVE_PATTERN.search(t):
            return t
        return t.replace('.', '-')

    yf_syms = [_to_yf(t) for t in tickers]
    sym_to_id = dict(zip(yf_syms, tickers))

    try:
        if as_of_date is not None:
            cut = datetime.strptime(as_of_date, '%Y-%m-%d').date()
            start = (cut - timedelta(days=430)).strftime('%Y-%m-%d')  # ~14 months back
            end = (cut + timedelta(days=1)).strftime('%Y-%m-%d')       # exclusive upper bound
            data = yf.download(
                yf_syms,
                start=start,
                end=end,
                interval='1d',
                progress=False,
                threads=False,
                auto_adjust=True,
            )
        else:
            data = yf.download(
                yf_syms,
                period='13mo',
                interval='1d',
                progress=False,
                threads=False,
                auto_adjust=True,
            )
    except Exception:
        return {}

    import pandas as pd  # noqa: local import — yfinance pulls pandas in anyway

    results: dict = {}
    today = date.today()

    # Track which yf symbols had NO data (may be delisted).
    no_data_syms: list[str] = list(yf_syms)  # start with all; remove those with data

    if data is not None and not data.empty:
        # Normalize: multi-ticker batch returns multi-level cols; single ticker flat.
        # Use 'Close' (auto_adjust=True already adjusts for splits/dividends).
        if isinstance(data.columns, pd.MultiIndex):
            closes = data['Close']
        else:
            closes = data[['Close']].rename(columns={'Close': yf_syms[0]})

        for yf_sym in yf_syms:
            tid = sym_to_id[yf_sym]
            if yf_sym not in closes.columns:
                continue
            series = closes[yf_sym].dropna()
            if series.empty:
                continue
            # Has data — remove from no_data_syms
            no_data_syms.remove(yf_sym)

            last_price = float(series.iloc[-1])
            last_date_obj = series.index[-1].to_pydatetime().date()
            last_date = last_date_obj.strftime('%Y-%m-%d')

            # E28 delisted detection — stale last-trade path (additive, live mode).
            # If last trade is older than _DELISTED_STALE_DAYS in live mode, flag
            # as delisted (e.g. a ticker that stopped trading but isn't 404 yet).
            result: dict = {
                'current_price': round(last_price, 4),
                'price_source': 'api',
                'price_date': last_date,
                'price_changes': _compute_changes(series),
            }
            if as_of_date is None and (today - last_date_obj).days > _DELISTED_STALE_DAYS:
                result['delisted'] = True

            results[tid] = result

    # E28 delisted detection — no-history path (live mode only).
    # For tickers with NO price history from yfinance (batch returned empty or
    # ticker column was all-NaN), check if yfinance fast_info metadata indicates
    # the ticker existed (shares != 0). If so, it's likely delisted (acquired /
    # taken private), not merely unknown. Emit a missing result + delisted flag.
    #
    # RESTRICTION (E28-fix): this heuristic applies ONLY to US (bare) tickers —
    # never to B3 (.SA-suffixed) tickers. A B3 ticker that yfinance cannot price
    # falls through to the brapi.dev fallback (_fetch_brapi). If brapi also
    # can't price it, the result stays plain MISSING (no delisted flag). The
    # stale-last-trade path above (had data, last trade too old) is unchanged
    # and still flags delisted for any market — it is reliable evidence.
    if as_of_date is None and no_data_syms and yf is not None:
        for yf_sym in no_data_syms:
            tid = sym_to_id[yf_sym]
            if tid in results:
                continue
            # Skip the delisted heuristic for B3 tickers — they fall through
            # to brapi.dev instead; brapi is the correct rescue path for .SA.
            if yf_sym.endswith('.SA'):
                continue
            try:
                fast = yf.Ticker(yf_sym).fast_info
                shares = getattr(fast, 'shares', None)
                if shares and float(shares) > 0:
                    # Has metadata but no price → likely delisted.
                    mr = _missing_result()
                    mr['delisted'] = True
                    results[tid] = mr
            except Exception:
                pass  # Silently skip — caller will mark as missing

    return results


def _compute_changes(series) -> dict:
    """Compute fractional price_changes at standard windows from a close series."""
    if series is None or len(series) == 0:
        return {}
    last = float(series.iloc[-1])
    last_dt = series.index[-1].to_pydatetime().date()

    def _pct_at_offset(days: int):
        target = last_dt - timedelta(days=days)
        # index nearest <= target
        mask = series.index.date <= target
        if not mask.any():
            return None
        prev = float(series[mask].iloc[-1])
        if prev == 0:
            return None
        return round((last - prev) / prev, 4)

    def _ytd():
        jan1 = date(last_dt.year, 1, 1)
        mask = series.index.date >= jan1
        if not mask.any():
            return None
        first_of_year = float(series[mask].iloc[0])
        if first_of_year == 0:
            return None
        return round((last - first_of_year) / first_of_year, 4)

    changes = {}
    for key, days in (('1d', 1), ('30d', 30), ('90d', 90),
                      ('180d', 180), ('365d', 365)):
        v = _pct_at_offset(days)
        if v is not None:
            changes[key] = v
    ytd = _ytd()
    if ytd is not None:
        changes['ytd'] = ytd
    return changes


# ---------------------------------------------------------------------------
# BRAPI fetcher
# ---------------------------------------------------------------------------

def _fetch_brapi(
    tickers: list[str],
    as_of_date: str | None = None,
) -> dict:
    """Fetch BR stock prices from brapi.dev.

    Live mode (as_of_date=None): current quote endpoint, no price_changes
    beyond 1d.

    Historical mode (as_of_date set): attempts the BRAPI history endpoint
    (`/api/quote/{ticker}/history?interval=1d&start=...&end=...`). This
    endpoint is undocumented on BRAPI's free tier. If it is unavailable or
    returns no data for the requested date, each affected ticker is returned
    as `price_source='missing'` and a D13 alert is emitted — live prices are
    NEVER silently substituted.
    """
    if not requests or not tickers:
        return {}

    if as_of_date is not None:
        return _fetch_brapi_historical(tickers, as_of_date)

    # --- Live mode ---
    ticker_str = ','.join(tickers)
    url = f'https://brapi.dev/api/quote/{ticker_str}'

    # A1: authenticate with BRAPI_TOKEN when available (OS env → .env fallback).
    # brapi.dev accepts the token as ?token=<TOKEN>. Degrade gracefully if absent.
    brapi_token = _load_brapi_token()
    if brapi_token:
        url = f'{url}?token={brapi_token}'

    results: dict = {}

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {}

    today_str = datetime.now().strftime('%Y-%m-%d')
    for item in data.get('results', []):
        symbol = item.get('symbol', '')
        price = item.get('regularMarketPrice', 0)
        change_1d = item.get('regularMarketChangePercent', 0) or 0
        results[symbol] = {
            'current_price': round(float(price), 4),
            'price_source': 'api',
            'price_date': today_str,
            'price_changes': {'1d': round(change_1d / 100, 4)} if change_1d else {},
        }
    return results


def _fetch_brapi_historical(tickers: list[str], as_of_date: str) -> dict:
    """Attempt BRAPI history endpoint per ticker; emit D13 alert on failure."""
    results: dict = {}
    cut = datetime.strptime(as_of_date, '%Y-%m-%d').date()
    # Request a 5-day window ending on as_of_date to catch weekends/holidays.
    start_str = (cut - timedelta(days=5)).strftime('%Y-%m-%d')
    end_str = as_of_date

    # A1: load token once for all tickers in this batch.
    brapi_token = _load_brapi_token()
    token_param = f'&token={brapi_token}' if brapi_token else ''

    for ticker in tickers:
        url = (
            f'https://brapi.dev/api/quote/{ticker}/history'
            f'?interval=1d&start={start_str}&end={end_str}{token_param}'
        )
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            historical = (
                data.get('results', [{}])[0].get('historicalDataPrice', [])
                if data.get('results') else []
            )
            # Find last entry on or before as_of_date.
            best = None
            for entry in historical:
                entry_date_str = entry.get('date', '')
                if entry_date_str and entry_date_str <= as_of_date:
                    if best is None or entry_date_str > best['date']:
                        best = entry
            if best and best.get('close'):
                results[ticker] = {
                    'current_price': round(float(best['close']), 4),
                    'price_source': 'api',
                    'price_date': best['date'],
                    'price_changes': {},
                }
                continue
            # No usable data found.
            _emit_price_alert(
                ticker,
                "BRAPI history endpoint returned no data for the requested date range",
                as_of_date,
            )
        except Exception as exc:
            _emit_price_alert(
                ticker,
                f"BRAPI history endpoint unavailable: {exc}",
                as_of_date,
            )
        # Fall through: mark missing (do NOT substitute live price).
        results[ticker] = _missing_result()

    return results


# ---------------------------------------------------------------------------
# CoinGecko fetcher
# ---------------------------------------------------------------------------

def _fetch_coingecko(
    tickers: list[str],
    as_of_date: str | None = None,
) -> dict:
    """Fetch crypto prices from CoinGecko (prices in BRL).

    Live mode (as_of_date=None): simple/price endpoint with 24h change.

    Historical mode (as_of_date set): `/coins/{id}/history?date=DD-MM-YYYY`
    per coin. Returns only `current_price` and `price_date` (no price_changes —
    CoinGecko history endpoint does not provide historical change windows).
    Emits a D13 alert if a ticker is not in the known CoinGecko ID map or
    the history endpoint returns no data.
    """
    if not requests or not tickers:
        return {}

    cg_map = {
        'BTC': 'bitcoin', 'ETH': 'ethereum', 'BNB': 'binancecoin',
        'ADA': 'cardano', 'DOT': 'polkadot', 'LINK': 'chainlink',
        'XRP': 'ripple', 'STX': 'blockstack', 'NMR': 'numeraire',
        'USDT': 'tether',
    }

    if as_of_date is not None:
        return _fetch_coingecko_historical(tickers, as_of_date, cg_map)

    # --- Live mode (E28-fix: simple/price for current_price/price_date/1d;
    #     market_chart ONLY for longer windows 30d/90d/180d/365d/ytd) ---
    #
    # Pre-E28 behavior restored: current_price is live spot from simple/price
    # (the dashboard relied on this). market_chart supplies the period windows.
    # If simple/price fails per-ticker, fall back to market_chart last value
    # so we don't lose the price entirely.
    results: dict = {}
    today_str = datetime.now().strftime('%Y-%m-%d')

    # Step 1: batch-fetch live spot prices + 24h change from simple/price.
    spot_data: dict = {}  # cg_id → {price, change_1d}
    all_ids = [cg_map.get(t, t.lower()) for t in tickers]
    ids_str = ','.join(all_ids)
    try:
        url = (f'https://api.coingecko.com/api/v3/simple/price'
               f'?ids={ids_str}&vs_currencies=brl&include_24hr_change=true')
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for cg_id in all_ids:
            if cg_id in data:
                spot_data[cg_id] = {
                    'price': data[cg_id].get('brl', 0),
                    'change_1d': data[cg_id].get('brl_24h_change', 0) or 0,
                }
    except Exception:
        pass  # Step 2 market_chart will supply the price as fallback

    # Step 2: per-ticker, fetch market_chart for the longer windows.
    # Merge: current_price/price_date = simple/price (live spot);
    #        price_changes = {1d} from simple/price + {30d,90d,180d,365d,ytd}
    #        from market_chart series.
    for ticker in tickers:
        cg_id = cg_map.get(ticker, ticker.lower())
        spot = spot_data.get(cg_id)

        # Fetch market_chart series for period window computation.
        chart_result = _fetch_coingecko_market_chart(cg_id, ticker, today_str)

        if spot and spot['price']:
            # Primary path: simple/price supplies current_price + 1d.
            price = round(float(spot['price']), 4)
            change_1d = spot['change_1d']
            price_changes: dict = {}
            if change_1d:
                price_changes['1d'] = round(change_1d / 100, 4)
            # Overlay longer windows from market_chart (30d/90d/180d/365d/ytd).
            if chart_result:
                for window in ('30d', '90d', '180d', '365d', 'ytd'):
                    v = chart_result.get('price_changes', {}).get(window)
                    if v is not None:
                        price_changes[window] = v
            results[ticker] = {
                'current_price': price,
                'price_source': 'api',
                'price_date': today_str,
                'price_changes': price_changes,
            }
        elif chart_result:
            # Fallback: simple/price failed; use market_chart last value.
            # Keep all windows that market_chart computed (includes 1d from series).
            results[ticker] = chart_result

    return results


def _fetch_coingecko_market_chart(
    cg_id: str,
    ticker: str,
    today_str: str,
) -> dict | None:
    """Fetch 400-day daily closes via CoinGecko market_chart endpoint.

    Returns a price result with full period_changes, or None on failure
    (caller falls back to simple/price).
    """
    if not requests:
        return None
    try:
        # CoinGecko free tier allows up to 365 days on market_chart.
        # 365 days provides enough history for all standard windows
        # (1d/30d/90d/180d/365d/ytd) via _compute_changes().
        url = (
            f'https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart'
            f'?vs_currency=brl&days=365'
        )
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        prices_raw = data.get('prices', [])  # [[timestamp_ms, price], ...]
        if not prices_raw:
            return None

        # Build a pandas Series with DatetimeIndex from the raw timestamps.
        import pandas as pd
        ts = [p[0] for p in prices_raw]
        vals = [float(p[1]) for p in prices_raw]
        idx = pd.to_datetime(ts, unit='ms', utc=True).tz_localize(None)
        series = pd.Series(vals, index=idx)
        series = series[~series.index.duplicated(keep='last')].sort_index()
        series = series.dropna()
        if series.empty:
            return None

        last_price = float(series.iloc[-1])
        last_date = series.index[-1].strftime('%Y-%m-%d')
        return {
            'current_price': round(last_price, 4),
            'price_source': 'api',
            'price_date': last_date,
            'price_changes': _compute_changes(series),
        }
    except Exception:
        return None


def _fetch_coingecko_historical(
    tickers: list[str],
    as_of_date: str,
    cg_map: dict,
) -> dict:
    """Fetch CoinGecko historical price per coin via /coins/{id}/history."""
    results: dict = {}
    # CoinGecko history endpoint expects DD-MM-YYYY.
    try:
        cut = datetime.strptime(as_of_date, '%Y-%m-%d')
        cg_date_str = cut.strftime('%d-%m-%Y')
    except ValueError:
        for ticker in tickers:
            _emit_price_alert(ticker, f"Invalid as_of_date format: {as_of_date}", as_of_date)
            results[ticker] = _missing_result()
        return results

    for ticker in tickers:
        cg_id = cg_map.get(ticker, ticker.lower())
        url = (
            f'https://api.coingecko.com/api/v3/coins/{cg_id}/history'
            f'?date={cg_date_str}&localization=false'
        )
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            market_data = data.get('market_data', {})
            price = market_data.get('current_price', {}).get('brl')
            if price:
                results[ticker] = {
                    'current_price': round(float(price), 4),
                    'price_source': 'api',
                    'price_date': as_of_date,
                    'price_changes': {},
                }
                continue
            _emit_price_alert(
                ticker,
                "CoinGecko /history returned no BRL price for the requested date",
                as_of_date,
            )
        except Exception as exc:
            _emit_price_alert(
                ticker,
                f"CoinGecko /history endpoint error: {exc}",
                as_of_date,
            )
        results[ticker] = _missing_result()

    return results


# ---------------------------------------------------------------------------
# Market indicators
# ---------------------------------------------------------------------------

def fetch_market_indicators(as_of_date: str | None = None) -> dict:
    """Fetch market indicators (IBOVESPA, S&P500, USD/BRL, BTC/BRL).

    Uses yfinance for index and FX data to stay consistent with the primary
    price source. Falls back to brapi.dev for BR-specific lookups if yfinance
    fails.

    When as_of_date is set, fetches historical end-of-day values anchored to
    that date. When None, fetches live values (preserves existing behavior).
    """
    indicators: dict = {}
    if yf is None:
        return indicators

    # Map: indicator key → yfinance symbol. BTC_BRL comes from CoinGecko —
    # yfinance's BTC-BRL pair is unreliable/delisted.
    yf_indicators = {
        'IBOVESPA': '^BVSP',
        'SP500':    '^GSPC',
        'USD_BRL':  'BRL=X',
    }

    try:
        syms = list(yf_indicators.values())
        if as_of_date is not None:
            cut = datetime.strptime(as_of_date, '%Y-%m-%d').date()
            start = (cut - timedelta(days=10)).strftime('%Y-%m-%d')
            end = (cut + timedelta(days=1)).strftime('%Y-%m-%d')
            data = yf.download(syms, start=start, end=end, interval='1d',
                               progress=False, threads=False, auto_adjust=True)
        else:
            data = yf.download(syms, period='5d', interval='1d',
                               progress=False, threads=False, auto_adjust=True)
    except Exception:
        return indicators

    if data is None or data.empty:
        return indicators

    import pandas as pd
    if isinstance(data.columns, pd.MultiIndex):
        closes = data['Close']
    else:
        closes = data[['Close']].rename(columns={'Close': syms[0]})

    for key, sym in yf_indicators.items():
        if sym not in closes.columns:
            continue
        series = closes[sym].dropna()
        if len(series) < 2:
            continue
        last = float(series.iloc[-1])
        prev = float(series.iloc[-2])
        change_1d = (last - prev) / prev if prev else 0
        indicators[key] = {
            'value': round(last, 4),
            'change_1d': round(change_1d, 4),
        }

    # BTC/BRL via CoinGecko
    if requests is not None:
        if as_of_date is not None:
            try:
                cut = datetime.strptime(as_of_date, '%Y-%m-%d')
                cg_date_str = cut.strftime('%d-%m-%Y')
                resp = requests.get(
                    f'https://api.coingecko.com/api/v3/coins/bitcoin/history'
                    f'?date={cg_date_str}&localization=false',
                    timeout=10,
                )
                if resp.ok:
                    market_data = resp.json().get('market_data', {})
                    price = market_data.get('current_price', {}).get('brl')
                    if price:
                        indicators['BTC_BRL'] = {
                            'value': round(float(price), 2),
                            'change_1d': 0,
                        }
            except Exception:
                pass
        else:
            try:
                resp = requests.get(
                    'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=brl&include_24hr_change=true',
                    timeout=10,
                )
                if resp.ok:
                    btc = resp.json().get('bitcoin', {})
                    price = btc.get('brl')
                    change = btc.get('brl_24h_change', 0)
                    if price:
                        indicators['BTC_BRL'] = {
                            'value': round(float(price), 2),
                            'change_1d': round(float(change) / 100, 4) if change else 0,
                        }
            except Exception:
                pass

    return indicators
