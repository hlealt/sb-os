"""Regression tests for the portfolio.json rate_type discriminator (p3-9 / S8).

Contracts tested:
  P3-9-A  classify_rate_type returns 'prefixed' for a flat-rate position
          (indexer PRE / empty, rate > 0).
  P3-9-B  classify_rate_type returns 'spread' for index+spread (e.g. IPCA+3.7%,
          including the neutral indexer_pct=100.0 default safra_titulos writes).
  P3-9-C  classify_rate_type returns 'percent_of_indexer' for % of an index
          (e.g. 110% CDI, no spread).
  P3-9-D  classify_rate_type fails loud (ValueError) on an unclassifiable /
          contradictory combination — never a silent default.
  P3-9-E  _build_position_entry emits rate_type on a real RF position and a
          real prefixed position from the live assets.csv shapes.
  P3-9-F  _build_position_entry omits rate_type for a metadata-less RF row
          (all rate fields blank) — additive, no false fail-loud.

Units match assets.csv / safra_titulos (`_parse_ptbr`): rate is the literal
annual percent (14.35, 3.7), indexer_pct is the literal percent (100.0, 110.0)
— never a 0.06 fraction nor a 1.10 ratio.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the investimentos directory is importable.
_INVESTIMENTOS = Path(__file__).resolve().parents[2] / "investimentos"
if str(_INVESTIMENTOS) not in sys.path:
    sys.path.insert(0, str(_INVESTIMENTOS))

from calculate import classify_rate_type, _build_position_entry
from position_calculator import Position


# ---------------------------------------------------------------------------
# classify_rate_type — pure classification
# ---------------------------------------------------------------------------

def test_prefixed_no_index_flat_rate():
    # cra_pre_refrescos_bandeirantes_1435: indexer=PRE, rate=14.35, pct empty
    assert classify_rate_type('PRE', '14.35', '') == 'prefixed'


def test_prefixed_empty_indexer():
    assert classify_rate_type('', '12.0', '') == 'prefixed'


def test_spread_ipca_plus_with_neutral_pct():
    # deb_neoenergia_370: indexer=IPCA, rate=3.7, indexer_pct=100.0 (neutral)
    assert classify_rate_type('IPCA', '3.7', '100.0') == 'spread'


def test_spread_cdi_plus_with_neutral_pct():
    # deb_cdi_rede_d_or_sao_luiz_120: indexer=CDI, rate=1.2, indexer_pct=100.0
    assert classify_rate_type('CDI', '1.2', '100.0') == 'spread'


def test_spread_empty_pct():
    # Spread with no indexer_pct recorded at all.
    assert classify_rate_type('IPCA', '5.45', '') == 'spread'


def test_percent_of_indexer_110_cdi():
    # 110% CDI: indexer=CDI, no spread rate, indexer_pct=110.0
    assert classify_rate_type('CDI', '', '110.0') == 'percent_of_indexer'


def test_percent_of_indexer_below_100():
    # 95% of CDI — multiplier < 100, still percent_of_indexer.
    assert classify_rate_type('CDI', '0', '95.0') == 'percent_of_indexer'


def test_fail_loud_indexed_no_spread_no_multiplier():
    # Real index but nothing meaningful: no spread, multiplier is the neutral
    # 100 default → cannot tell what the rate actually is. Must fail loud.
    with pytest.raises(ValueError):
        classify_rate_type('CDI', '', '100.0')


def test_fail_loud_prefixed_shape_with_no_rate():
    with pytest.raises(ValueError):
        classify_rate_type('PRE', '', '')


def test_fail_loud_contradictory_spread_and_multiplier():
    # A spread rate AND a non-neutral multiplier is contradictory.
    with pytest.raises(ValueError):
        classify_rate_type('IPCA', '3.7', '110.0')


# ---------------------------------------------------------------------------
# _build_position_entry — integration on RF (balcao) positions
# ---------------------------------------------------------------------------

def _make_rf_position(asset_id):
    pos = Position(id=asset_id, name='', asset_class='fixed_income', type='deb',
                   broker='safra', currency='BRL')
    pos.aplicado_total = 1000.0
    pos.net_flow = -1000.0
    pos.current_value = 1100.0
    pos.price_source = 'snapshot'
    pos.price_date = '2026-05-27'
    return pos


def test_entry_emits_rate_type_spread():
    pos = _make_rf_position('deb_neoenergia_370')
    assets = {'deb_neoenergia_370': {
        'indexer': 'IPCA', 'rate': '3.7', 'indexer_pct': '100.0',
        'issuer': 'NEOENERGIA SA', 'currency': 'BRL',
    }}
    entry = _build_position_entry(pos, {}, None, 5.0, assets, {}, '2026-05-27')
    assert entry['rate_type'] == 'spread'
    assert entry['indexer'] == 'IPCA'


def test_entry_emits_rate_type_prefixed():
    pos = _make_rf_position('cra_pre_refrescos_bandeirantes_1435')
    pos.type = 'cra'
    assets = {'cra_pre_refrescos_bandeirantes_1435': {
        'indexer': 'PRE', 'rate': '14.35', 'indexer_pct': '', 'currency': 'BRL',
    }}
    entry = _build_position_entry(pos, {}, None, 5.0, assets, {}, '2026-05-27')
    assert entry['rate_type'] == 'prefixed'


def test_entry_omits_rate_type_when_metadata_blank():
    # Legacy RF row with no rate metadata (e.g. aplicacoes_renda_fixa).
    pos = _make_rf_position('aplicacoes_renda_fixa')
    pos.type = 'rf'
    assets = {'aplicacoes_renda_fixa': {
        'indexer': '', 'rate': '', 'indexer_pct': '', 'currency': 'BRL',
    }}
    entry = _build_position_entry(pos, {}, None, 5.0, assets, {}, '2026-05-27')
    assert 'rate_type' not in entry
