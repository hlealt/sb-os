"""Tests for per-(asset, exchange) crypto flow partitioning in calculate.py.

Contracts tested:
  CEX-A  _build_position_flows: crypto flows keyed "{asset}@{exchange}" —
         same currency on two exchanges yields two independent flow lists;
         the bare-currency key does not exist
  CEX-B  exchange normalization: binance / mb / blank → mercado_bitcoin,
         bipa → bipa (delegates to _normalize_crypto_exchange)
  CEX-C  swap legs: both non-BRL assets key under the row's own exchange
  CEX-D  unpriced rows: non-ajuste row with price_brl<=0 carries no flow
         and warns on stderr; ajuste rows stay silent
  CEX-E  priced inter-exchange transfer (envio/recebimento pair): synthetic
         sale at the sender, purchase at the receiver — legs cancel at
         currency level
  CEX-F  _build_position_entry: crypto position IRR computed from its own
         (asset, exchange) flows only

Motivation: the BTC ×2 defect — flows keyed by bare currency handed every
exchange-split position the currency's FULL flow history paired with only
its partial terminal, biasing both IRRs strongly negative (pnl +65,8%/+32,8%
vs IRR −22,78%/−5,38%; finance-system task 2026-06-05).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the investimentos directory is importable.
# __file__ = shared/tests/test_crypto_exchange_flow_partition.py
_INVESTIMENTOS = Path(__file__).resolve().parents[2] / "investimentos"
if str(_INVESTIMENTOS) not in sys.path:
    sys.path.insert(0, str(_INVESTIMENTOS))


def _crypto_row(date, operation, buy_asset='', buy_qty='', sell_asset='',
                sell_qty='', price_brl='', exchange=''):
    return {
        'date': date, 'operation': operation,
        'buy_asset': buy_asset, 'buy_quantity': buy_qty,
        'sell_asset': sell_asset, 'sell_quantity': sell_qty,
        'price_brl': price_brl, 'exchange': exchange,
    }


def _build(crypto_rows, monkeypatch=None):
    import calculate
    if monkeypatch is not None:
        monkeypatch.setattr(calculate, 'load_code_migrations', lambda: {})
    return calculate._build_position_flows(
        orders=[], proventos=[], balcao=[], crypto=crypto_rows)


# ---------------------------------------------------------------------------
# CEX-A: per-exchange partitioning
# ---------------------------------------------------------------------------

def test_same_currency_two_exchanges_partitioned(monkeypatch):
    flows = _build([
        _crypto_row('2024-01-10', 'compra', buy_asset='BTC', buy_qty='0.01',
                    sell_asset='BRL', price_brl='4000', exchange='bipa'),
        _crypto_row('2021-05-10', 'compra', buy_asset='BTC', buy_qty='0.02',
                    sell_asset='BRL', price_brl='6000', exchange='binance'),
        _crypto_row('2022-03-10', 'venda', buy_asset='BRL',
                    sell_asset='BTC', sell_qty='0.01', price_brl='3500',
                    exchange='binance'),
    ], monkeypatch)

    assert flows['BTC@bipa'] == [('2024-01-10', -4000.0)]
    assert flows['BTC@mercado_bitcoin'] == [('2021-05-10', -6000.0),
                                            ('2022-03-10', 3500.0)]
    assert 'BTC' not in flows


# ---------------------------------------------------------------------------
# CEX-B: exchange normalization
# ---------------------------------------------------------------------------

def test_exchange_normalization(monkeypatch):
    flows = _build([
        _crypto_row('2021-01-10', 'compra', buy_asset='ETH',
                    sell_asset='BRL', price_brl='100', exchange='binance'),
        _crypto_row('2021-02-10', 'compra', buy_asset='ETH',
                    sell_asset='BRL', price_brl='200', exchange='mb'),
        _crypto_row('2021-03-10', 'compra', buy_asset='ETH',
                    sell_asset='BRL', price_brl='300', exchange=''),
        _crypto_row('2024-04-10', 'compra', buy_asset='ETH',
                    sell_asset='BRL', price_brl='400', exchange='Bipa'),
    ], monkeypatch)

    assert [a for _, a in flows['ETH@mercado_bitcoin']] == [-100.0, -200.0,
                                                            -300.0]
    assert flows['ETH@bipa'] == [('2024-04-10', -400.0)]


# ---------------------------------------------------------------------------
# CEX-C: swap legs key under the row's exchange
# ---------------------------------------------------------------------------

def test_swap_legs_keyed_per_exchange(monkeypatch):
    flows = _build([
        _crypto_row('2021-06-01', 'swap', buy_asset='ETH', buy_qty='1',
                    sell_asset='BTC', sell_qty='0.05', price_brl='9000',
                    exchange='binance'),
    ], monkeypatch)

    assert flows['ETH@mercado_bitcoin'] == [('2021-06-01', -9000.0)]
    assert flows['BTC@mercado_bitcoin'] == [('2021-06-01', 9000.0)]


# ---------------------------------------------------------------------------
# CEX-D: unpriced rows — warning for non-ajuste, silence for ajuste
# ---------------------------------------------------------------------------

def test_unpriced_non_ajuste_warns_and_carries_no_flow(capsys, monkeypatch):
    flows = _build([
        _crypto_row('2024-01-16', 'compra', buy_asset='BTC', buy_qty='5e-05',
                    sell_asset='BRL', price_brl='', exchange='bipa'),
        _crypto_row('2024-01-18', 'compra', buy_asset='BTC', buy_qty='1e-05',
                    sell_asset='BRL', price_brl='0', exchange='bipa'),
    ], monkeypatch)

    assert 'BTC@bipa' not in flows
    err = capsys.readouterr().err
    lines = [l for l in err.splitlines() if 'crypto unpriced' in l]
    assert len(lines) == 1
    assert 'BTC@bipa' in lines[0]
    assert '2 non-ajuste' in lines[0]


def test_ajuste_rows_stay_silent(capsys, monkeypatch):
    flows = _build([
        _crypto_row('2021-11-26', 'ajuste', buy_asset='BTC',
                    buy_qty='-4.1e-07', price_brl='', exchange='binance'),
    ], monkeypatch)

    assert flows == {}
    assert 'crypto unpriced' not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# CEX-E: priced inter-exchange transfer — synthetic sale/purchase pair
# ---------------------------------------------------------------------------

def test_priced_transfer_pair_cancels_at_currency_level(monkeypatch):
    flows = _build([
        _crypto_row('2025-02-01', 'envio', buy_asset='',
                    sell_asset='BTC', sell_qty='0.1', price_brl='50000',
                    exchange='mb'),
        _crypto_row('2025-02-01', 'recebimento', buy_asset='BTC',
                    buy_qty='0.1', sell_asset='', price_brl='50000',
                    exchange='bipa'),
    ], monkeypatch)

    # Sender books a synthetic sale; receiver a synthetic purchase.
    assert flows['BTC@mercado_bitcoin'] == [('2025-02-01', 50000.0)]
    assert flows['BTC@bipa'] == [('2025-02-01', -50000.0)]
    # Currency level: legs cancel — a transfer is never a BRL entry/exit.
    total = sum(a for key, fl in flows.items() if key.startswith('BTC@')
                for _, a in fl)
    assert total == 0.0


# ---------------------------------------------------------------------------
# CEX-F: _build_position_entry uses the composite key
# ---------------------------------------------------------------------------

def test_position_entry_irr_uses_own_exchange_flows():
    import calculate
    from position_calculator import Position

    pos = Position(id='BTC', name='Bitcoin', asset_class='crypto',
                   type='crypto', sector='', currency='BRL', broker='bipa')
    pos.quantity = 0.01
    pos.cost_basis = 1000.0

    position_flows = {
        # Own flows: one buy, one year before terminal.
        'BTC@bipa': [('2025-06-05', -1000.0)],
        # Foreign flows that MUST NOT leak into this position's IRR.
        'BTC@mercado_bitcoin': [('2020-01-01', -99999.0)],
    }
    price_data = {'BTC': {'current_price': 110000.0, 'price_source': 'api',
                          'price_date': '2026-06-05', 'price_changes': {}}}

    entry = calculate._build_position_entry(
        pos, price_data, fx_state=None, usd_brl_rate=5.0, assets={},
        position_flows=position_flows, terminal_date='2026-06-05')

    # terminal = 0.01 × 110000 = 1100; single -1000 flow one year out → ~10%
    assert entry['irr'] is not None
    assert 0.09 < entry['irr'] < 0.11
