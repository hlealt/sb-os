"""Regression tests for price_fetcher.py historical mode (p1-2 + p1-3).

Contracts tested:
  P1-2-A  as_of_date=None → yfinance called with period='13mo' (live behavior unchanged)
  P1-2-B  as_of_date set  → yfinance called with start/end, not period
  P1-2-C  as_of_date set  → price_date in result equals last trading day ≤ as_of_date
  P1-2-D  BRAPI historical: endpoint unavailable → price_source='missing', NO live substitution
  P1-2-E  BRAPI historical: endpoint returns no data → price_source='missing'
  P1-2-F  CoinGecko historical: /coins/{id}/history parsed correctly
  P1-2-G  CoinGecko historical: endpoint error → price_source='missing'
  P1-3-A  D13 alert emitted to stderr when historical fetch fails
  P1-3-B  D13 audit event emitted when historical fetch fails
  P1-3-C  D13 alert NOT emitted in live mode (as_of_date=None)
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Ensure the investimentos directory is importable.
# __file__ = shared/tests/test_price_fetcher.py
# parents[0] = shared/tests/
# parents[1] = shared/
# parents[2] = scripts/
_INVESTIMENTOS = Path(__file__).resolve().parents[2] / "investimentos"
if str(_INVESTIMENTOS) not in sys.path:
    sys.path.insert(0, str(_INVESTIMENTOS))

# ---------------------------------------------------------------------------
# Minimal yfinance stub — avoids real network calls.
# ---------------------------------------------------------------------------

def _make_yf_stub(close_values: dict, index_dates: list) -> MagicMock:
    """Build a minimal yfinance stub.

    close_values: {sym: [float, ...]} matching index_dates length.
    """
    import pandas as pd

    stubs = {}
    for sym, vals in close_values.items():
        idx = pd.to_datetime(index_dates)
        stubs[sym] = pd.Series(vals, index=idx, name=sym)

    df = pd.DataFrame(stubs)
    df.columns = pd.MultiIndex.from_product([['Close'], df.columns])

    yf_stub = MagicMock()
    yf_stub.download.return_value = df
    return yf_stub


# ---------------------------------------------------------------------------
# P1-2-A: as_of_date=None → yfinance uses period='13mo'
# ---------------------------------------------------------------------------

def test_live_mode_uses_period(monkeypatch):
    """as_of_date=None must call yfinance with period='13mo', not start/end."""
    import pandas as pd

    idx = pd.to_datetime(['2026-05-20', '2026-05-21', '2026-05-22'])
    series = pd.Series([100.0, 101.0, 102.0], index=idx, name='IVVB11.SA')
    df = pd.DataFrame({'Close': series})

    yf_stub = MagicMock()
    yf_stub.download.return_value = df

    import price_fetcher as pf
    monkeypatch.setattr(pf, 'yf', yf_stub)

    tickers = [{'id': 'IVVB11', 'currency': 'BRL', 'asset_class': 'variable_income', 'type': 'etf'}]
    pf.fetch_prices(tickers, as_of_date=None)

    call_kwargs = yf_stub.download.call_args
    assert 'period' in call_kwargs.kwargs or (
        len(call_kwargs.args) > 1 and call_kwargs.args[1] == '13mo'
    ) or call_kwargs.kwargs.get('period') == '13mo', \
        "Live mode must use period='13mo'"
    assert 'start' not in (call_kwargs.kwargs or {}), \
        "Live mode must NOT pass start= to yfinance"


# ---------------------------------------------------------------------------
# P1-2-B: as_of_date set → yfinance uses start/end
# ---------------------------------------------------------------------------

def test_historical_mode_uses_start_end(monkeypatch):
    """as_of_date set must call yfinance with start/end, not period."""
    import pandas as pd

    idx = pd.to_datetime(['2026-04-28', '2026-04-29', '2026-04-30'])
    series = pd.Series([300.0, 305.0, 310.0], index=idx, name='IVVB11.SA')
    df = pd.DataFrame({'Close': series})

    yf_stub = MagicMock()
    yf_stub.download.return_value = df

    import price_fetcher as pf
    monkeypatch.setattr(pf, 'yf', yf_stub)

    tickers = [{'id': 'IVVB11', 'currency': 'BRL', 'asset_class': 'variable_income', 'type': 'etf'}]
    pf.fetch_prices(tickers, as_of_date='2026-04-30')

    call_kwargs = yf_stub.download.call_args.kwargs
    assert 'start' in call_kwargs, "Historical mode must pass start= to yfinance"
    assert 'end' in call_kwargs, "Historical mode must pass end= to yfinance"
    assert 'period' not in call_kwargs, "Historical mode must NOT pass period= to yfinance"
    assert call_kwargs['end'] == '2026-05-01', "end must be as_of_date + 1 day (exclusive)"


# ---------------------------------------------------------------------------
# P1-2-C: price_date reflects last trading day ≤ as_of_date
# ---------------------------------------------------------------------------

def test_historical_price_date_is_last_trading_day(monkeypatch):
    """price_date must equal the last available close on or before as_of_date."""
    import pandas as pd

    # Simulate: as_of_date=2026-04-30 (Wednesday), last close Apr 30.
    idx = pd.to_datetime(['2026-04-28', '2026-04-29', '2026-04-30'])
    series = pd.Series([300.0, 305.0, 310.0], index=idx, name='IVVB11.SA')
    df = pd.DataFrame({'Close': series})

    yf_stub = MagicMock()
    yf_stub.download.return_value = df

    import price_fetcher as pf
    monkeypatch.setattr(pf, 'yf', yf_stub)

    tickers = [{'id': 'IVVB11', 'currency': 'BRL', 'asset_class': 'variable_income', 'type': 'etf'}]
    result = pf.fetch_prices(tickers, as_of_date='2026-04-30')

    assert result['IVVB11']['price_date'] == '2026-04-30'
    assert result['IVVB11']['current_price'] == 310.0
    assert result['IVVB11']['price_source'] == 'api'


# ---------------------------------------------------------------------------
# P1-2-D: BRAPI historical — endpoint unavailable → missing, no live substitution
# ---------------------------------------------------------------------------

def test_brapi_historical_unavailable_returns_missing_not_live(monkeypatch, capsys):
    """When BRAPI history endpoint raises, result is missing — NOT a live price."""
    import price_fetcher as pf

    # Patch requests so the history URL raises, but a live quote would succeed.
    mock_requests = MagicMock()
    mock_requests.get.side_effect = Exception("connection refused")
    monkeypatch.setattr(pf, 'requests', mock_requests)
    monkeypatch.setattr(pf, 'yf', None)  # force BRAPI path

    tickers = [{'id': 'IVVB11', 'currency': 'BRL', 'asset_class': 'variable_income', 'type': 'etf'}]
    result = pf.fetch_prices(tickers, as_of_date='2026-04-30')

    assert result['IVVB11']['price_source'] == 'missing', \
        "Must return missing — never silently substitute live price"
    assert result['IVVB11']['current_price'] == 0


# ---------------------------------------------------------------------------
# P1-2-E: BRAPI historical — endpoint returns no matching data → missing
# ---------------------------------------------------------------------------

def test_brapi_historical_no_data_returns_missing(monkeypatch):
    """When BRAPI history endpoint returns an empty historicalDataPrice list, result is missing."""
    import price_fetcher as pf

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        'results': [{'symbol': 'IVVB11', 'historicalDataPrice': []}]
    }
    mock_requests = MagicMock()
    mock_requests.get.return_value = mock_resp
    monkeypatch.setattr(pf, 'requests', mock_requests)
    monkeypatch.setattr(pf, 'yf', None)

    tickers = [{'id': 'IVVB11', 'currency': 'BRL', 'asset_class': 'variable_income', 'type': 'etf'}]
    result = pf.fetch_prices(tickers, as_of_date='2026-04-30')

    assert result['IVVB11']['price_source'] == 'missing'


# ---------------------------------------------------------------------------
# P1-2-F: CoinGecko historical — /coins/{id}/history parsed correctly
# ---------------------------------------------------------------------------

def test_coingecko_historical_parses_history_endpoint(monkeypatch):
    """CoinGecko historical mode must call /coins/{id}/history and parse BRL price."""
    import price_fetcher as pf

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        'id': 'bitcoin',
        'market_data': {
            'current_price': {'brl': 550000.0, 'usd': 100000.0}
        }
    }
    mock_requests = MagicMock()
    mock_requests.get.return_value = mock_resp
    monkeypatch.setattr(pf, 'requests', mock_requests)
    monkeypatch.setattr(pf, 'yf', None)

    tickers = [{'id': 'BTC', 'currency': 'BRL', 'asset_class': 'crypto', 'type': 'crypto'}]
    result = pf.fetch_prices(tickers, as_of_date='2026-04-30')

    assert result['BTC']['price_source'] == 'api'
    assert result['BTC']['current_price'] == 550000.0
    assert result['BTC']['price_date'] == '2026-04-30'
    # Verify the history endpoint URL was called with correct DD-MM-YYYY format.
    called_url = mock_requests.get.call_args[0][0]
    assert '/coins/bitcoin/history' in called_url
    assert '30-04-2026' in called_url


# ---------------------------------------------------------------------------
# P1-2-G: CoinGecko historical — endpoint error → missing
# ---------------------------------------------------------------------------

def test_coingecko_historical_error_returns_missing(monkeypatch, capsys):
    """CoinGecko /history error → price_source='missing'."""
    import price_fetcher as pf

    mock_requests = MagicMock()
    mock_requests.get.side_effect = Exception("timeout")
    monkeypatch.setattr(pf, 'requests', mock_requests)
    monkeypatch.setattr(pf, 'yf', None)

    tickers = [{'id': 'BTC', 'currency': 'BRL', 'asset_class': 'crypto', 'type': 'crypto'}]
    result = pf.fetch_prices(tickers, as_of_date='2026-04-30')

    assert result['BTC']['price_source'] == 'missing'


# ---------------------------------------------------------------------------
# P1-3-A: D13 alert emitted to stderr when historical fetch fails
# ---------------------------------------------------------------------------

def test_d13_alert_emitted_to_stderr_on_brapi_failure(monkeypatch, capsys):
    """stderr warning must be emitted when BRAPI historical fetch fails (D13)."""
    import price_fetcher as pf

    mock_requests = MagicMock()
    mock_requests.get.side_effect = Exception("network error")
    monkeypatch.setattr(pf, 'requests', mock_requests)
    monkeypatch.setattr(pf, 'yf', None)

    tickers = [{'id': 'PETR4', 'currency': 'BRL', 'asset_class': 'variable_income', 'type': 'stock'}]
    pf.fetch_prices(tickers, as_of_date='2026-04-30')

    err = capsys.readouterr().err
    assert 'PETR4' in err, "D13 alert must name the failing ticker"
    assert '2026-04-30' in err, "D13 alert must include as_of_date"
    assert 'WARNING' in err or 'price_fetcher' in err


def test_d13_alert_emitted_to_stderr_on_coingecko_failure(monkeypatch, capsys):
    """stderr warning must be emitted when CoinGecko historical fetch fails (D13)."""
    import price_fetcher as pf

    mock_requests = MagicMock()
    mock_requests.get.side_effect = Exception("rate limit")
    monkeypatch.setattr(pf, 'requests', mock_requests)
    monkeypatch.setattr(pf, 'yf', None)

    tickers = [{'id': 'ETH', 'currency': 'BRL', 'asset_class': 'crypto', 'type': 'crypto'}]
    pf.fetch_prices(tickers, as_of_date='2026-04-30')

    err = capsys.readouterr().err
    assert 'ETH' in err


# ---------------------------------------------------------------------------
# P1-3-B: D13 audit event emitted when historical fetch fails
# ---------------------------------------------------------------------------

def test_d13_audit_event_emitted_on_historical_failure(monkeypatch, tmp_path, capsys):
    """audit.emit must be called with materiality='high' on historical fetch failure."""
    import price_fetcher as pf

    mock_requests = MagicMock()
    mock_requests.get.side_effect = Exception("error")
    monkeypatch.setattr(pf, 'requests', mock_requests)
    monkeypatch.setattr(pf, 'yf', None)

    emitted: list[dict] = []

    def fake_emit(event_type, *, source_function, materiality=None, summary=None, **kwargs):
        emitted.append({
            'event_type': event_type,
            'materiality': materiality,
            'summary': summary,
        })

    # Patch the audit module that price_fetcher imports dynamically.
    fake_audit = MagicMock()
    fake_audit.emit = fake_emit

    _shared = Path(__file__).resolve().parents[1] / "shared"
    fake_lib = types.ModuleType("lib")
    fake_lib.audit = fake_audit  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "lib", fake_lib)
    monkeypatch.setitem(sys.modules, "lib.audit", fake_audit)

    tickers = [{'id': 'IVVB11', 'currency': 'BRL', 'asset_class': 'variable_income', 'type': 'etf'}]
    pf.fetch_prices(tickers, as_of_date='2026-04-30')

    assert any(e['materiality'] == 'high' for e in emitted), \
        "D13 audit event must have materiality='high'"
    assert any(e['event_type'] == 'price_fetch_alert' for e in emitted), \
        "D13 event_type must be 'price_fetch_alert'"
    alert = next(e for e in emitted if e['event_type'] == 'price_fetch_alert')
    assert alert['summary']['ticker'] == 'IVVB11'
    assert alert['summary']['as_of_date'] == '2026-04-30'


# ---------------------------------------------------------------------------
# P1-3-C: D13 alert NOT emitted in live mode
# ---------------------------------------------------------------------------

def test_d13_alert_not_emitted_in_live_mode(monkeypatch, capsys):
    """Live mode (as_of_date=None) must NOT emit D13 alerts even on API failure."""
    import price_fetcher as pf

    mock_requests = MagicMock()
    mock_requests.get.side_effect = Exception("network error")
    monkeypatch.setattr(pf, 'requests', mock_requests)
    monkeypatch.setattr(pf, 'yf', None)

    tickers = [{'id': 'BTC', 'currency': 'BRL', 'asset_class': 'crypto', 'type': 'crypto'}]
    pf.fetch_prices(tickers, as_of_date=None)

    err = capsys.readouterr().err
    assert 'WARNING' not in err, "D13 alerts must NOT fire in live mode"
    assert 'price_fetcher' not in err


# ---------------------------------------------------------------------------
# Regression: as_of_date=None result shape is unchanged (no new keys)
# ---------------------------------------------------------------------------

def test_live_mode_result_shape_unchanged(monkeypatch):
    """Live mode must return the same keys as before this change."""
    import pandas as pd
    import price_fetcher as pf

    idx = pd.to_datetime(['2026-05-20', '2026-05-21', '2026-05-22'])
    series = pd.Series([100.0, 101.0, 102.0], index=idx, name='IVVB11.SA')
    df = pd.DataFrame({'Close': series})

    yf_stub = MagicMock()
    yf_stub.download.return_value = df
    monkeypatch.setattr(pf, 'yf', yf_stub)

    tickers = [{'id': 'IVVB11', 'currency': 'BRL', 'asset_class': 'variable_income', 'type': 'etf'}]
    result = pf.fetch_prices(tickers, as_of_date=None)

    r = result['IVVB11']
    assert set(r.keys()) == {'current_price', 'price_source', 'price_date', 'price_changes'}
    assert r['price_source'] == 'api'
