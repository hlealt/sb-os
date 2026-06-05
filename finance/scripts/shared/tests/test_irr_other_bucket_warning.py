"""Tests for the per-class IRR 'other' bucket warning in calculate.py.

Contracts tested:
  OTH-A  _warn_other_bucket_flows: material ticker → stderr warning with
         ticker, flow count and absolute total
  OTH-B  _warn_other_bucket_flows: ticker below the R$ 50 materiality
         threshold → silent
  OTH-C  _warn_other_bucket_flows: empty input → silent
  OTH-D  _compute_portfolio_irr integration: unknown ticker's flows routed
         to 'other' emit the warning; mapped tickers do not

Motivation: the AZZA3 leak — `_compute_portfolio_irr` discards the 'other'
bucket silently, so a ticker missing from assets.csv vanishes from per-class
IRR with no signal (finance-system task 2026-06-05).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the investimentos directory is importable.
# __file__ = shared/tests/test_irr_other_bucket_warning.py
_INVESTIMENTOS = Path(__file__).resolve().parents[2] / "investimentos"
if str(_INVESTIMENTOS) not in sys.path:
    sys.path.insert(0, str(_INVESTIMENTOS))


# ---------------------------------------------------------------------------
# OTH-A: material ticker → warning
# ---------------------------------------------------------------------------

def test_material_other_flows_warn(capsys):
    import calculate

    calculate._warn_other_bucket_flows({'GHOST3': [-3000.0, 3500.0]})

    err = capsys.readouterr().err
    assert "class:other" in err
    assert "GHOST3" in err
    assert "2 flow" in err
    assert "6,500.00" in err


# ---------------------------------------------------------------------------
# OTH-B: below materiality threshold → silent
# ---------------------------------------------------------------------------

def test_sub_threshold_other_flows_silent(capsys):
    import calculate

    calculate._warn_other_bucket_flows({'TINY11': [1.08]})

    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# OTH-C: empty input → silent
# ---------------------------------------------------------------------------

def test_no_other_flows_silent(capsys):
    import calculate

    calculate._warn_other_bucket_flows({})

    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# OTH-D: integration — _compute_portfolio_irr wires the accumulation
# ---------------------------------------------------------------------------

def test_compute_portfolio_irr_warns_on_other_bucket(capsys, monkeypatch):
    import calculate

    assets = {
        'VALE3': {'asset_class': 'variable_income', 'currency': 'BRL',
                  'type': 'acao'},
    }

    def fake_load_csv(path, cut_date=None):
        if Path(path).name == 'orders.csv':
            return [
                # Unknown ticker → bucket 'other', material
                {'ticker': 'GHOST3', 'side': 'C', 'total': '3000',
                 'date': '2024-01-10'},
                {'ticker': 'GHOST3', 'side': 'V', 'total': '3500',
                 'date': '2025-01-10'},
                # Mapped ticker → bucket rv_br, no warning
                {'ticker': 'VALE3', 'side': 'C', 'total': '1000',
                 'date': '2024-01-10'},
            ]
        return []  # crypto.csv

    monkeypatch.setattr(calculate, 'load_csv', fake_load_csv)
    monkeypatch.setattr(calculate, 'load_balcao', lambda cut_date=None: [])
    monkeypatch.setattr(calculate, 'load_code_migrations', lambda: {})

    proventos = [
        # Unknown ticker, sub-threshold → accumulated but silent
        {'ticker': 'TINY11', 'net_value': '1.08', 'currency': 'BRL',
         'date': '2024-06-01'},
    ]

    calculate._compute_portfolio_irr(
        positions=[], proventos=proventos, total_value=0.0,
        cut_date='2026-06-05', assets=assets, position_entries=[],
        fx_state=None)

    err = capsys.readouterr().err
    other_lines = [l for l in err.splitlines() if 'class:other' in l]
    assert len(other_lines) == 1
    assert 'GHOST3' in other_lines[0]
    assert 'VALE3' not in err
    assert 'TINY11' not in err
