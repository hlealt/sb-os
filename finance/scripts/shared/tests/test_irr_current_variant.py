"""Tests for the all-time vs current per-class IRR variants in calculate.py (D12).

Contracts tested:
  CUR-A  closed equity ticker: flows enter the all-time variant only;
         the current variant sees open-position flows exclusively
  CUR-B  partial sell of an open position: the sell flow STAYS in the
         current variant (position-scoped filter, not lot-scoped)
  CUR-C  balcão closed product (aplicacao→resgate, inactive): included in
         all-time rf_balcao, excluded from current
  CUR-D  rename bridging: flows recorded under the pre-rename ticker count
         as current-variant flows of the open renamed position, and do NOT
         leak into the 'other' bucket
  CUR-E  schema: legacy keys (`total`, `per_class`) keep their shape; the
         `current` block mirrors it; terminal_value is shared per bucket
  CUR-F  balcão code-migration seed of an inactive product: all-time only
  CUR-G  crypto ref missing from assets.csv: flows forced into the crypto
         bucket (never 'other')

Motivation: eliminate the survivors-vs-lifetime ambiguity of summary IRRs —
the user sees both "how has my capital performed since inception" (all-time)
and "how is what I hold today performing" (current). Finance-system task
2026-06-05; rv-eua-tir-investigation.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the investimentos directory is importable.
# __file__ = shared/tests/test_irr_current_variant.py
_INVESTIMENTOS = Path(__file__).resolve().parents[2] / "investimentos"
if str(_INVESTIMENTOS) not in sys.path:
    sys.path.insert(0, str(_INVESTIMENTOS))


_ASSETS = {
    'VALE3': {'asset_class': 'variable_income', 'currency': 'BRL',
              'type': 'acao'},
    'CLOSED3': {'asset_class': 'variable_income', 'currency': 'BRL',
                'type': 'acao'},
    'NEW3': {'asset_class': 'variable_income', 'currency': 'BRL',
             'type': 'acao'},
    'cra_open': {'asset_class': 'fixed_income', 'currency': 'BRL',
                 'type': 'cra'},
    'cra_closed': {'asset_class': 'fixed_income', 'currency': 'BRL',
                   'type': 'cra'},
    'fund_closed': {'asset_class': 'fixed_income', 'currency': 'BRL',
                    'type': 'firf_br'},
    'BTC': {'asset_class': 'crypto', 'currency': 'BRL', 'type': 'crypto'},
}


def _patch_loaders(monkeypatch, calculate, *, orders=None, balcao=None,
                   crypto=None, corp_actions=None, migrations=None):
    def fake_load_csv(path, cut_date=None):
        name = Path(path).name
        if name == 'orders.csv':
            return orders or []
        if name == 'crypto.csv':
            return crypto or []
        if name == 'corporate_actions.csv':
            return corp_actions or []
        return []

    monkeypatch.setattr(calculate, 'load_csv', fake_load_csv)
    monkeypatch.setattr(calculate, 'load_balcao',
                        lambda cut_date=None: balcao or [])
    monkeypatch.setattr(calculate, 'load_code_migrations',
                        lambda: migrations or {})


def _run(calculate, *, total_value, entries, proventos=None):
    return calculate._compute_portfolio_irr(
        positions=[], proventos=proventos or [], total_value=total_value,
        cut_date='2026-06-05', assets=_ASSETS, position_entries=entries,
        fx_state=None)


# ---------------------------------------------------------------------------
# CUR-A: closed equity flows → all-time only
# ---------------------------------------------------------------------------

def test_closed_equity_in_all_time_only(monkeypatch):
    import calculate

    _patch_loaders(monkeypatch, calculate, orders=[
        {'ticker': 'VALE3', 'side': 'C', 'total': '1000',
         'date': '2024-01-10'},
        {'ticker': 'CLOSED3', 'side': 'C', 'total': '2000',
         'date': '2023-01-10'},
        {'ticker': 'CLOSED3', 'side': 'V', 'total': '2600',
         'date': '2024-06-10'},
    ])

    result = _run(calculate, total_value=1500.0,
                  entries=[{'id': 'VALE3', 'current_value_brl': 1500.0}])

    assert result['per_class']['rv_br']['flow_count'] == 3
    assert result['current']['per_class']['rv_br']['flow_count'] == 1
    # Current = VALE3 only: -1000 (2024-01-10) → 1500 at cut.
    assert result['current']['per_class']['rv_br']['irr'] is not None
    assert result['current']['per_class']['rv_br']['irr'] != \
        result['per_class']['rv_br']['irr']
    assert result['current']['total'] == \
        result['current']['per_class']['rv_br']['irr']


# ---------------------------------------------------------------------------
# CUR-B: partial sell of an open position stays in current
# ---------------------------------------------------------------------------

def test_partial_sell_of_open_position_stays_in_current(monkeypatch):
    import calculate

    _patch_loaders(monkeypatch, calculate, orders=[
        {'ticker': 'VALE3', 'side': 'C', 'total': '1000',
         'date': '2024-01-10'},
        {'ticker': 'VALE3', 'side': 'V', 'total': '300',
         'date': '2025-01-10'},
    ])

    result = _run(calculate, total_value=900.0,
                  entries=[{'id': 'VALE3', 'current_value_brl': 900.0}])

    assert result['current']['per_class']['rv_br']['flow_count'] == 2
    assert result['per_class']['rv_br']['flow_count'] == 2


# ---------------------------------------------------------------------------
# CUR-C: closed balcão product → all-time rf_balcao only
# ---------------------------------------------------------------------------

def test_closed_balcao_product_in_all_time_only(monkeypatch):
    import calculate

    _patch_loaders(monkeypatch, calculate, balcao=[
        {'product_id': 'cra_open', 'date': '2024-01-02',
         'operation': 'aplicacao', 'amount': '-10000', 'source': 'safra'},
        {'product_id': 'cra_open', 'date': '2025-01-02',
         'operation': 'juros', 'amount': '500', 'source': 'safra'},
        {'product_id': 'cra_closed', 'date': '2023-01-02',
         'operation': 'aplicacao', 'amount': '-5000', 'source': 'safra'},
        {'product_id': 'cra_closed', 'date': '2024-01-02',
         'operation': 'resgate', 'amount': '6000', 'source': 'safra'},
    ])

    result = _run(calculate, total_value=11000.0,
                  entries=[{'id': 'cra_open', 'current_value_brl': 11000.0}])

    assert result['per_class']['rf_balcao']['flow_count'] == 4
    assert result['current']['per_class']['rf_balcao']['flow_count'] == 2
    # All-time rate folds in the closed product's realized +20%;
    # both variants share the open positions' terminal.
    assert result['per_class']['rf_balcao']['terminal_value'] == \
        result['current']['per_class']['rf_balcao']['terminal_value']
    assert result['per_class']['rf_balcao']['irr'] is not None
    assert result['current']['per_class']['rf_balcao']['irr'] is not None


# ---------------------------------------------------------------------------
# CUR-D: rename bridging feeds the current variant, never 'other'
# ---------------------------------------------------------------------------

def test_rename_bridged_flows_count_as_current(monkeypatch, capsys):
    import calculate

    _patch_loaders(
        monkeypatch, calculate,
        orders=[
            # OLD3 is absent from assets.csv — unbridged it would land in
            # 'other' AND be invisible to the current variant.
            {'ticker': 'OLD3', 'side': 'C', 'total': '1000',
             'date': '2022-01-10'},
        ],
        corp_actions=[
            {'date': '2024-01-01', 'action_type': 'conversao',
             'ticker': 'OLD3', 'new_ticker': 'NEW3'},
        ])

    result = _run(calculate, total_value=1500.0,
                  entries=[{'id': 'NEW3', 'current_value_brl': 1500.0}])

    assert result['per_class']['rv_br']['flow_count'] == 1
    assert result['current']['per_class']['rv_br']['flow_count'] == 1
    assert result['current']['per_class']['rv_br']['irr'] is not None
    assert 'class:other' not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# CUR-E: schema — legacy keys unchanged, current mirrors
# ---------------------------------------------------------------------------

def test_schema_legacy_keys_and_current_block(monkeypatch):
    import calculate

    _patch_loaders(monkeypatch, calculate, orders=[
        {'ticker': 'VALE3', 'side': 'C', 'total': '1000',
         'date': '2024-01-10'},
    ])

    result = _run(calculate, total_value=1500.0,
                  entries=[{'id': 'VALE3', 'current_value_brl': 1500.0}])

    assert set(result.keys()) == {'total', 'per_class', 'current'}
    assert set(result['current'].keys()) == {'total', 'per_class'}
    bucket = result['per_class']['rv_br']
    cur_bucket = result['current']['per_class']['rv_br']
    assert set(bucket.keys()) == {'irr', 'terminal_value', 'flow_count'}
    assert set(cur_bucket.keys()) == set(bucket.keys())
    # Single open position → the two variants coincide.
    assert bucket == cur_bucket
    assert result['total'] == result['current']['total']


# ---------------------------------------------------------------------------
# CUR-F: migration seed of an inactive product → all-time only
# ---------------------------------------------------------------------------

def test_migration_seed_inactive_product_all_time_only(monkeypatch):
    import calculate

    _patch_loaders(
        monkeypatch, calculate,
        balcao=[
            {'product_id': 'fund_closed', 'date': '2024-05-10',
             'operation': 'resgate', 'amount': '9000', 'source': 'safra'},
        ],
        migrations={'fund_closed': [{
            'from_dates': {'2023-05-10'}, 'from_total': 8000.0,
            'to_dates': {'2023-05-11'}, 'to_total': 8000.0,
            'seed_date': '2023-05-10',
        }]})

    result = _run(calculate, total_value=0.0, entries=[])

    assert result['per_class']['fundos']['flow_count'] == 2
    assert result['per_class']['fundos']['irr'] is not None
    assert result['per_class']['fundos']['irr'] > 0
    assert result['current']['per_class']['fundos']['flow_count'] == 0
    assert result['current']['per_class']['fundos']['irr'] is None


# ---------------------------------------------------------------------------
# CUR-G: crypto ref missing from assets.csv → crypto bucket, never 'other'
# ---------------------------------------------------------------------------

def test_crypto_ref_missing_from_assets_forced_into_crypto(monkeypatch, capsys):
    import calculate

    _patch_loaders(monkeypatch, calculate, crypto=[
        # GHOSTCOIN is not in assets.csv.
        {'date': '2023-01-05', 'buy_asset': 'GHOSTCOIN', 'sell_asset': 'BRL',
         'price_brl': '1000'},
        {'date': '2024-01-05', 'buy_asset': 'BRL', 'sell_asset': 'GHOSTCOIN',
         'price_brl': '1400'},
    ])

    result = _run(calculate, total_value=0.0, entries=[])

    assert result['per_class']['crypto']['flow_count'] == 2
    assert 'class:other' not in capsys.readouterr().err
