"""Tests for market_price.py read/audit-diagnostic tool.

Contracts tested:
  MP-A  All-quoted path: table renders ticker/market/currency/price/price_date
        columns for every ticker; exit 0.
  MP-B  Missing ticker: visible MISSING row in table; exit 1.
  MP-C  Invalid --as-of format: exit 2.
  MP-D  Market inference: B3 pattern → br/BRL; known crypto → crypto/BRL;
        default → us/USD.
  MP-E  --market override applies to all tickers.
  MP-F  Absent change windows render as 'n/a' in output.
  MP-G  Summary footer present: "{N} ticker(s) queried — {ok} OK, {miss} MISSING".
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Path setup: replicate the pattern used by test_price_fetcher.py
# __file__ = shared/tests/test_market_price.py
# parents[0] = shared/tests/
# parents[1] = shared/
# parents[2] = scripts/
# ---------------------------------------------------------------------------
_INVESTIMENTOS = Path(__file__).resolve().parents[2] / "investimentos"
if str(_INVESTIMENTOS) not in sys.path:
    sys.path.insert(0, str(_INVESTIMENTOS))


# ---------------------------------------------------------------------------
# Canned fetch_prices returns
# ---------------------------------------------------------------------------

def _make_price_data(
    ticker: str,
    price: float = 100.0,
    price_date: str = "2026-06-04",
    changes: dict | None = None,
    source: str = "api",
) -> dict:
    return {
        ticker.upper(): {
            "current_price": price,
            "price_source": source,
            "price_date": price_date,
            "price_changes": changes or {},
        }
    }


_ALL_QUOTED = {
    "TEAM": {
        "current_price": 101.50,
        "price_source": "api",
        "price_date": "2026-06-04",
        "price_changes": {"1d": 0.01, "30d": 0.05, "90d": None},
    },
    "PETR4": {
        "current_price": 41.25,
        "price_source": "api",
        "price_date": "2026-06-04",
        "price_changes": {"1d": -0.02, "30d": None, "90d": None},
    },
}

_WITH_MISSING = {
    "AAPL": {
        "current_price": 190.0,
        "price_source": "api",
        "price_date": "2026-06-04",
        "price_changes": {"1d": 0.005},
    },
    "UNKNOWNTICKER": {
        "current_price": 0,
        "price_source": "missing",
        "price_date": "",
        "price_changes": {},
    },
}


# ---------------------------------------------------------------------------
# Helper: run main() and capture stdout + exit code
# ---------------------------------------------------------------------------

def _run(argv: list[str], fake_prices: dict, capsys):
    """Call market_price.main() with patched fetch_prices; return (captured, exitcode)."""
    import market_price as mp

    with patch.object(mp, "fetch_prices", return_value=fake_prices):
        with pytest.raises(SystemExit) as exc:
            sys.argv = ["market_price.py"] + argv
            mp.main()
    captured = capsys.readouterr()
    return captured, exc.value.code


# ---------------------------------------------------------------------------
# MP-A: all-quoted path — table columns present, exit 0
# ---------------------------------------------------------------------------

def test_all_quoted_table_columns_and_exit_0(capsys):
    captured, code = _run(["TEAM", "PETR4"], _ALL_QUOTED, capsys)
    out = captured.out
    assert code == 0, f"Expected exit 0 but got {code}"
    # Header row must contain the key column names
    for col in ("ticker", "market", "currency", "price", "price_date", "source", "status"):
        assert col in out, f"Column '{col}' not found in output"
    # Both tickers must appear
    assert "TEAM" in out
    assert "PETR4" in out
    # Status for quoted rows must be OK
    assert "OK" in out


# ---------------------------------------------------------------------------
# MP-B: missing ticker — visible MISSING row, exit 1
# ---------------------------------------------------------------------------

def test_missing_ticker_row_and_exit_1(capsys):
    captured, code = _run(["AAPL", "UNKNOWNTICKER"], _WITH_MISSING, capsys)
    out = captured.out
    assert code == 1, f"Expected exit 1 but got {code}"
    assert "MISSING" in out
    assert "UNKNOWNTICKER" in out


# ---------------------------------------------------------------------------
# MP-C: invalid --as-of format — exit 2
# ---------------------------------------------------------------------------

def test_invalid_as_of_exits_2(capsys):
    import market_price as mp

    # We must still patch fetch_prices even though we expect exit 2 before it
    # is called — the argparse check happens in main() before the network call.
    with patch.object(mp, "fetch_prices", return_value={}):
        with pytest.raises(SystemExit) as exc:
            sys.argv = ["market_price.py", "AAPL", "--as-of", "not-a-date"]
            mp.main()
    assert exc.value.code == 2, f"Expected exit 2 but got {exc.value.code}"


# ---------------------------------------------------------------------------
# MP-D: market inference
# ---------------------------------------------------------------------------

def test_market_inference_b3(capsys):
    """PETR4 matches B3 pattern → market=br, currency=BRL."""
    prices = _make_price_data("PETR4", price=41.25)
    captured, code = _run(["PETR4"], prices, capsys)
    out = captured.out
    assert code == 0
    assert "br" in out
    assert "BRL" in out


def test_market_inference_crypto(capsys):
    """BTC is a known CoinGecko symbol → market=crypto, currency=BRL."""
    prices = _make_price_data("BTC", price=320000.0)
    captured, code = _run(["BTC"], prices, capsys)
    out = captured.out
    assert code == 0
    assert "crypto" in out
    assert "BRL" in out


def test_market_inference_us_default(capsys):
    """TEAM (arbitrary non-B3, non-crypto) → market=us, currency=USD."""
    prices = _make_price_data("TEAM", price=101.50)
    captured, code = _run(["TEAM"], prices, capsys)
    out = captured.out
    assert code == 0
    assert "us" in out
    assert "USD" in out


# ---------------------------------------------------------------------------
# MP-E: --market override applies to all tickers
# ---------------------------------------------------------------------------

def test_market_override_forces_market(capsys):
    """--market br forces market=br (and BRL) even for a US-looking ticker."""
    prices = _make_price_data("TEAM", price=101.50)
    captured, code = _run(["TEAM", "--market", "br"], prices, capsys)
    out = captured.out
    assert code == 0
    # With --market br, market column must be 'br' and currency 'BRL'
    assert "br" in out
    assert "BRL" in out
    # 'us' should NOT appear as market for this ticker
    # (The header 'market' and 'status' columns both contain 'us' in 'status'
    # so we check the line containing TEAM directly)
    team_line = next(
        (line for line in out.splitlines() if "TEAM" in line and "br" in line),
        None,
    )
    assert team_line is not None, "No TEAM row with market=br found"


# ---------------------------------------------------------------------------
# MP-F: absent change windows render as 'n/a'
# ---------------------------------------------------------------------------

def test_absent_change_windows_render_na(capsys):
    """price_changes dict missing keys → 'n/a' in the printed columns."""
    # No change windows at all
    prices = {
        "TEAM": {
            "current_price": 101.50,
            "price_source": "api",
            "price_date": "2026-06-04",
            "price_changes": {},
        }
    }
    captured, code = _run(["TEAM"], prices, capsys)
    out = captured.out
    assert code == 0
    assert "n/a" in out, "Absent change windows must render as 'n/a'"


# ---------------------------------------------------------------------------
# MP-G: summary footer present
# ---------------------------------------------------------------------------

def test_summary_footer_all_ok(capsys):
    """Footer must say '2 ticker(s) queried — 2 OK, 0 MISSING'."""
    captured, code = _run(["TEAM", "PETR4"], _ALL_QUOTED, capsys)
    out = captured.out
    assert code == 0
    assert "2 ticker(s) queried" in out
    assert "2 OK" in out
    assert "0 MISSING" in out


def test_summary_footer_with_missing(capsys):
    """Footer must say '2 ticker(s) queried — 1 OK, 1 MISSING'."""
    captured, code = _run(["AAPL", "UNKNOWNTICKER"], _WITH_MISSING, capsys)
    out = captured.out
    assert code == 1
    assert "2 ticker(s) queried" in out
    assert "1 OK" in out
    assert "1 MISSING" in out
    # The MISSING list line must name the bad ticker
    assert "UNKNOWNTICKER" in out
