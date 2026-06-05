"""Portfolio calculator — generates portfolio.json from ledger data.

Usage:
    python calculate.py [--cut-date YYYY-MM-DD] [--no-prices]

Orchestrates: position calculator → FX engine → price fetcher →
IRR calculator → portfolio.json writer.
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


VAULT_ROOT = _find_vault_root()

sys.path.insert(0, str(Path(__file__).parent))
sys.path.append(str(Path(__file__).resolve().parents[1] / "shared"))

from position_calculator import (calculate_positions, load_csv, LEDGER_DIR,
                                 load_assets, _resolve_valuation_method,
                                 load_code_migrations, is_migration_phantom,
                                 load_balcao)
from fx_engine import build_fx_state
from price_fetcher import fetch_prices, fetch_market_indicators
from irr_calculator import compute_xirr
from lib import audit  # noqa: E402
from lib.safe_write import atomic_write_json  # noqa: E402

OUTPUT_DIR = VAULT_ROOT / ".user" / "finance" / "bookkeeper" / "ledgers" / "investimentos"
SNAPSHOTS_JSON = OUTPUT_DIR / 'snapshots.json'

# RF tradicional product types — non-defaulted instruments should not yield
# a negative nominal IRR in BR retail. Used to gate the expect_positive
# sanity-check on per-asset IRR. Funds (fia, fim, firf, fidc, coe, di) are
# excluded — they can legitimately go negative.
_RF_TRADICIONAL_TYPES = {'cra', 'deb', 'lca', 'lci', 'cdb', 'cdb_mp',
                         'tesouro', 'lc', 'cri', 'rf'}

# Investment-fund product types — drives the Fundos vs RF Balcão split for
# per-class IRR. type='di' is here even though asset_class='fixed_income'
# (open-ended cota; behaves like a fund for IRR purposes).
_FUND_TYPES = {'fia_br', 'fia_usa', 'fim_br', 'firf_br', 'fidc', 'coe', 'di'}

# Indexer tokens that mean "no index — flat prefixed rate". safra_titulos emits
# 'PRE' for prefixados; treat the no-index variants as the prefixed signal.
_PREFIXED_INDEXER_TOKENS = {'', 'PRE', 'PRÉ', 'PREFIXADO', 'PREFIXADA'}


def _parse_rate_field(raw) -> float:
    """Parse a rate / indexer_pct field from assets.csv to a float.

    assets.csv stores these as the literal percent written by safra_titulos
    (`_parse_ptbr`): rate '14.35' → 14.35 (annual %), indexer_pct '110.0' → 110.0
    (% of indexer). Empty / blank → 0.0. Same unit convention as the source —
    never a decimal fraction (0.06) nor a ratio (1.10).
    """
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def classify_rate_type(indexer, rate, indexer_pct) -> str:
    """Classify a fixed-income position into one of three Brazilian rate forms.

    Deterministic discriminator over the EXISTING assets.csv fields
    (`indexer`, `rate`, `indexer_pct`), conforming to the units safra_titulos
    writes (rate = annual %, e.g. 14.35; indexer_pct = % of indexer, e.g. 110.0;
    spread instruments carry the neutral default indexer_pct=100.0).

      prefixed            — flat annual rate, no index. indexer ∈ {'', PRE, PRÉ}
                            and rate > 0.
      spread              — index + spread (e.g. IPCA+3.7%). indexer is a real
                            index and rate > 0 (indexer_pct is the neutral
                            100.0 default or empty).
      percent_of_indexer  — % of an index (e.g. 110% CDI). indexer is a real
                            index, no spread rate, and indexer_pct ≠ 100 (and > 0).

    Fail-loud: a combination matching none of the three shapes raises
    ValueError. The caller MUST only invoke this for an RF position whose
    metadata is present (at least one of rate/indexer_pct populated); a
    metadata-less RF row (all three blank) is NOT classified and never reaches
    here.
    """
    idx = (indexer or '').strip()
    rate_v = _parse_rate_field(rate)
    pct_v = _parse_rate_field(indexer_pct)
    is_indexed = idx.upper() not in _PREFIXED_INDEXER_TOKENS

    if not is_indexed:
        # No index → must be a flat prefixed rate.
        if rate_v > 0:
            return 'prefixed'
        raise ValueError(
            f"rate_type unclassifiable (prefixed shape with no rate): "
            f"indexer={indexer!r} rate={rate!r} indexer_pct={indexer_pct!r}"
        )

    # Real index present.
    if rate_v > 0:
        # index + spread (e.g. IPCA+3.7%). indexer_pct is the 100.0 neutral
        # default (or empty) for spread instruments; a multiplier ≠ 100
        # alongside a spread is contradictory.
        if pct_v and pct_v != 100:
            raise ValueError(
                f"rate_type unclassifiable (spread rate AND multiplier ≠ 100): "
                f"indexer={indexer!r} rate={rate!r} indexer_pct={indexer_pct!r}"
            )
        return 'spread'

    if pct_v > 0 and pct_v != 100:
        # % of an index (e.g. 110% CDI), no spread.
        return 'percent_of_indexer'

    raise ValueError(
        f"rate_type unclassifiable (indexed position with no spread and no "
        f"meaningful multiplier): indexer={indexer!r} rate={rate!r} "
        f"indexer_pct={indexer_pct!r}"
    )


def _irr_class_bucket(asset_id: str, assets: dict[str, dict]) -> str:
    """Map an asset id to one of the 5 IRR class buckets.

    Returns: rv_br | rv_eua | rf_balcao | fundos | crypto | other
    """
    meta = assets.get(asset_id, {})
    asset_class = (meta.get('asset_class') or '').lower()
    typ = (meta.get('type') or '').lower()
    currency = (meta.get('currency') or 'BRL').upper()
    if asset_class == 'crypto' or typ == 'crypto':
        return 'crypto'
    if typ in _FUND_TYPES:
        return 'fundos'
    if typ in _RF_TRADICIONAL_TYPES:
        return 'rf_balcao'
    if asset_class == 'variable_income':
        return 'rv_eua' if currency == 'USD' else 'rv_br'
    return 'other'


def _filter_balcao_for_irr(balcao: list[dict], migrations: dict) -> list[dict]:
    """Drop balcão rows that should not contribute to IRR cash flows.

    Two filters applied per product_id:
    - Code-migration phantoms (resgate/aplicacao pairs that represent broker
      re-coding, not real cash flow). See `is_migration_phantom`.
    - Superseded seeds: `*_seed` rows whose product has any non-seed,
      non-migration flow on or before the seed date. The seed is a
      carry-forward snapshot; once real history backfills, the seed
      double-counts cost basis.

    Returns a new filtered list. Used by both per-asset (_build_position_flows)
    and aggregate (_compute_portfolio_irr) IRR pipelines so the totals stay
    consistent with per-asset rates.
    """
    earliest_real_flow: dict[str, str] = {}
    for row in balcao:
        pid = row.get('product_id', '')
        if not pid:
            continue
        source = (row.get('source') or '')
        if source.endswith('_seed'):
            continue
        date_s = row.get('date', '')
        if is_migration_phantom(pid, date_s, row.get('operation', ''), migrations):
            continue
        if date_s and (pid not in earliest_real_flow or date_s < earliest_real_flow[pid]):
            earliest_real_flow[pid] = date_s

    out = []
    for row in balcao:
        pid = row.get('product_id', '')
        if not pid:
            out.append(row)
            continue
        date_s = row.get('date', '')
        source = (row.get('source') or '')
        if is_migration_phantom(pid, date_s, row.get('operation', ''), migrations):
            continue
        if source.endswith('_seed') and pid in earliest_real_flow \
                and earliest_real_flow[pid] <= date_s:
            continue
        out.append(row)
    return out


def _build_position_flows(orders: list[dict], proventos: list[dict],
                          balcao: list[dict],
                          crypto: list[dict]) -> dict[str, list[tuple[str, float]]]:
    """Per-position cash flows for XIRR computation.

    Sign convention matches XIRR expectations:
      - Outflows (buys, applications): negative
      - Inflows (sells, dividends, juros, redemptions): positive

    Currency notes:
      - orders/proventos: native currency (USD for Avenue, BRL elsewhere) —
        terminal_value passed in matching native currency.
      - balcao: BRL.
      - crypto: BRL-marked via crypto.csv:price_brl. Each leg of a swap
        registers as a synthetic BRL flow at its implied BRL value at swap
        time. Per-asset IRR for crypto is therefore in BRL, with terminal
        computed as quantity × current_price (BRL, since crypto exchanges
        quote natively in BRL). Heavy crypto-to-crypto swap activity
        produces an IRR that reflects BRL-equivalent timing of swaps, not
        pure native-asset return — see investimentos.md for the convention.
    """
    flows: dict[str, list[tuple[str, float]]] = {}

    for row in orders:
        ticker = row.get('ticker', '')
        if not ticker:
            continue
        total = float(row.get('total', 0) or 0)
        signed = -abs(total) if row.get('side') == 'C' else abs(total)
        flows.setdefault(ticker, []).append((row.get('date', ''), signed))

    for row in proventos:
        ticker = row.get('ticker', '')
        if not ticker:
            continue
        net = float(row.get('net_value', 0) or 0)
        if net != 0:
            flows.setdefault(ticker, []).append((row.get('date', ''), abs(net)))

    migrations = load_code_migrations()
    for row in _filter_balcao_for_irr(balcao, migrations):
        pid = row.get('product_id', '')
        if not pid:
            continue
        amount = float(row.get('amount', 0) or 0)
        if amount == 0:
            continue
        flows.setdefault(pid, []).append((row.get('date', ''), amount))

    # Inject synthetic seeds for code migrations: an aplicacao-equivalent
    # outflow on the migration boundary representing the accumulated balance
    # carried forward from the closed code. Anchors XIRR — without this the
    # post-migration flows lack an initial outlay and the rate is unbounded.
    for pid, mlist in migrations.items():
        for m in mlist:
            seed_amount = -float(m['from_total'])
            if seed_amount == 0:
                continue
            flows.setdefault(pid, []).append((m['seed_date'], seed_amount))

    for row in crypto:
        price = float(row.get('price_brl', 0) or 0)
        if price <= 0:
            continue
        date_s = row.get('date', '')
        buy_asset = row.get('buy_asset', '')
        sell_asset = row.get('sell_asset', '')
        # Buy leg: position gained quantity → BRL outflow (negative).
        if buy_asset and buy_asset != 'BRL':
            flows.setdefault(buy_asset, []).append((date_s, -price))
        # Sell leg: position lost quantity → BRL inflow (positive).
        if sell_asset and sell_asset != 'BRL':
            flows.setdefault(sell_asset, []).append((date_s, price))

    return flows


def build_portfolio(cut_date: str = None, skip_prices: bool = False) -> dict:
    """Build the complete portfolio.json structure."""
    now = datetime.now()
    today = cut_date or now.strftime('%Y-%m-%d')

    # 1. Calculate positions
    positions = calculate_positions(cut_date)

    # 2. Build FX state for USD conversions
    fx_state = build_fx_state(cut_date)
    usd_brl_rate = fx_state.weighted_avg_rate or 5.0  # Fallback

    # 3. Fetch prices (unless skipped)
    # Dedupe by id: crypto positions are split per exchange, so the same
    # ticker (e.g. BTC) can appear in multiple Position objects. Fetch the
    # quote once per ticker; calculate.py applies it to every position with
    # that id when building entries below.
    price_data = {}
    indicators = {}
    if not skip_prices:
        seen_ids = set()
        ticker_list = []
        for p in positions:
            if _resolve_valuation_method(p.type) not in ('price', 'crypto'):
                continue
            if p.id in seen_ids:
                continue
            seen_ids.add(p.id)
            ticker_list.append({'id': p.id, 'currency': p.currency,
                                'asset_class': p.asset_class, 'type': p.type})
        if ticker_list:
            price_data = fetch_prices(ticker_list, usd_brl_rate, as_of_date=cut_date)
        indicators = fetch_market_indicators(as_of_date=cut_date)
        # Update USD/BRL from market data
        if 'USD_BRL' in indicators:
            usd_brl_rate = indicators['USD_BRL']['value'] or usd_brl_rate

    # 4. Load assets for metadata
    assets = load_assets()

    # 5. Load proventos for income data
    proventos = load_csv(LEDGER_DIR / 'proventos.csv', cut_date)

    # 5b. Pre-compute per-position cash flows for per-asset IRR
    position_flows = _build_position_flows(
        load_csv(LEDGER_DIR / 'orders.csv', cut_date),
        proventos,
        load_balcao(cut_date),
        load_csv(LEDGER_DIR / 'crypto.csv', cut_date),
    )

    # 6. Build position entries
    position_entries = []
    total_value = 0.0
    total_cost = 0.0
    alloc_by_class = {}
    alloc_by_broker = {}
    alloc_by_currency = {}

    for pos in positions:
        entry = _build_position_entry(pos, price_data, fx_state, usd_brl_rate, assets,
                                      position_flows, today)
        position_entries.append(entry)

        # Use BRL-normalised values for summary aggregation so USD positions
        # (Avenue) are converted to BRL before being added to totals.
        value = entry.get('current_value_brl', entry.get('current_value') or 0) or 0
        cost = entry.get('cost_basis_brl', entry.get('cost_basis') or 0) or 0
        total_value += value
        total_cost += cost

        # Allocations
        _add_allocation(alloc_by_class, pos.asset_class or 'other', value)
        _add_allocation(alloc_by_broker, pos.broker or 'unknown', value)
        _add_allocation(alloc_by_currency, pos.currency or 'BRL', value)

    # Compute allocation percentages
    _compute_pct(alloc_by_class, total_value)
    _compute_pct(alloc_by_broker, total_value)
    _compute_pct(alloc_by_currency, total_value)

    # 7. Compute IRR
    irr_data = _compute_portfolio_irr(positions, proventos, total_value,
                                      cut_date, assets, position_entries,
                                      fx_state)

    # 8. Build income section
    income = _build_income(proventos, positions, fx_state)

    # 9. Assemble portfolio.json
    portfolio = {
        'meta': {
            'generated_at': now.isoformat(),
            'cut_date': today,
            'fx_rate_usd_brl': round(usd_brl_rate, 4),
            'market_indicators': indicators,
        },
        'summary': {
            'total_value': round(total_value, 2),
            'total_cost': round(total_cost, 2),
            'total_pnl': round(total_value - total_cost, 2),
            'allocation_by_class': alloc_by_class,
            'allocation_by_broker': alloc_by_broker,
            'allocation_by_currency': alloc_by_currency,
            'irr': irr_data,
        },
        'positions': position_entries,
        'income': income,
    }

    return portfolio


def _build_position_entry(pos, price_data, fx_state, usd_brl_rate, assets,
                          position_flows: dict, terminal_date: str) -> dict:
    """Build a single position entry for portfolio.json."""
    asset_meta = assets.get(pos.id, {})
    valuation_method = _resolve_valuation_method(pos.type)
    entry = {
        'id': pos.id,
        'name': pos.name or asset_meta.get('name', ''),
        'asset_class': pos.asset_class,
        'type': pos.type,
        'valuation_method': valuation_method,
        'broker': pos.broker,
        'currency': pos.currency,
    }

    if valuation_method in ('price', 'crypto'):
        # Listed/crypto: use quantity + price.
        # Primary money fields (cost_basis, avg_cost, current_value, pnl_absolute,
        # total_dividends) are in the position's NATIVE currency — USD for
        # Avenue, BRL for B3 / BR crypto exchanges. BRL-normalized parallels
        # (*_brl) are emitted for summary aggregation across currencies.
        entry['quantity'] = round(pos.quantity, 8)

        prices = price_data.get(pos.id, {})
        current_price = prices.get('current_price', 0)
        entry['current_price'] = current_price
        entry['price_source'] = prices.get('price_source', 'missing')
        entry['price_date'] = prices.get('price_date', '')
        entry['price_changes'] = prices.get('price_changes', {})

        # --- Native currency fields ---
        native_cost = round(pos.cost_basis, 2)
        native_value = round(pos.quantity * current_price, 2)
        entry['cost_basis'] = native_cost
        entry['avg_cost'] = round(pos.avg_cost, 4) if pos.quantity > 0 else 0
        entry['current_value'] = native_value
        entry['pnl_absolute'] = round(native_value - native_cost, 2)
        entry['pnl_pct'] = round((native_value - native_cost) / native_cost, 4) if native_cost > 0 else 0
        entry['total_dividends'] = round(pos.total_dividends, 2)
        entry['total_dividends_ttm'] = round(pos.total_dividends_ttm, 2)
        entry['yoc_lifetime'] = round(pos.total_dividends / native_cost, 4) if native_cost > 0 else 0
        entry['yoc_ttm'] = round(pos.total_dividends_ttm / native_cost, 4) if native_cost > 0 else 0
        entry['sector'] = pos.sector or asset_meta.get('sector', '')

        # --- BRL-normalized parallels (for summary cards and cross-currency aggregation) ---
        if pos.currency == 'USD':
            # Cost from FX engine (historical weighted FX); current_value at spot USD/BRL.
            fx_cost = fx_state.get_ticker_cost_brl(pos.id)
            cost_brl = round(fx_cost, 2) if fx_cost > 0 else round(native_cost * usd_brl_rate, 2)
            value_brl = round(native_value * usd_brl_rate, 2)
            entry['cost_basis_brl'] = cost_brl
            entry['current_value_brl'] = value_brl
            entry['pnl_absolute_brl'] = round(value_brl - cost_brl, 2)
            entry['total_dividends_brl'] = round(pos.total_dividends * usd_brl_rate, 2)
        else:
            entry['cost_basis_brl'] = native_cost
            entry['current_value_brl'] = native_value
            entry['pnl_absolute_brl'] = entry['pnl_absolute']
            entry['total_dividends_brl'] = entry['total_dividends']

        # --- Returns decomposition (non-BRL positions only; p3-5 / D11) ---
        # BRL positions omit these fields entirely (not zeroed).
        # Price missing → emit null for all four (parallel to balcao null pattern).
        # Formula (cost-basis FX lens; Decision 2026-05-27 in shape.md):
        #   return_usd      = native_value − native_cost
        #   return_fx_brl   = native_cost × current_fx − cost_basis_brl
        #   return_total_brl = return_usd × current_fx + return_fx_brl
        # Identity: return_total_brl = native_value × current_fx − cost_basis_brl
        #                            = current_value_brl − cost_basis_brl
        #                            = pnl_absolute_brl  (exact, all lot structures)
        if pos.currency != 'BRL' and fx_state is not None:
            if prices.get('price_source') == 'missing' or current_price == 0:
                entry['return_usd'] = None
                entry['return_fx_brl'] = None
                entry['return_total_brl'] = None
                entry['funding_fx'] = None
            else:
                funding_fx = fx_state.get_ticker_fx_rate(pos.id)
                return_usd_val = round(native_value - native_cost, 2)
                return_fx_brl_val = round(native_cost * usd_brl_rate - cost_brl, 2)
                return_total_brl_val = round(return_usd_val * usd_brl_rate + return_fx_brl_val, 2)
                entry['return_usd'] = return_usd_val
                entry['return_fx_brl'] = return_fx_brl_val
                entry['return_total_brl'] = return_total_brl_val
                entry['funding_fx'] = round(funding_fx, 4)

        # IRR per-asset (native currency) — flows from orders + proventos.
        flows = position_flows.get(pos.id, [])
        if flows:
            terminal = native_value if native_value > 0 else 0
            entry['irr'] = compute_xirr(flows, terminal_value=terminal,
                                        terminal_date=terminal_date,
                                        label=pos.id)
        else:
            entry['irr'] = None

    elif valuation_method == 'balcao' or not valuation_method:
        # RF/Funds: balcão flows + snapshot. cost_basis = aplicado_total (true
        # outlay), so retorno% reflects capital actually invested. Per-operation
        # breakdown lets the dashboard render aplicado / juros+amort / resgates /
        # impostos as separate columns.
        entry['quantity'] = 0
        entry['aplicado_total'] = round(pos.aplicado_total, 2)
        entry['juros_amort_total'] = round(pos.juros_amort_total, 2)
        entry['resgates_total'] = round(pos.resgates_total, 2)
        entry['impostos_total'] = round(pos.impostos_total, 2)
        entry['net_flow'] = round(pos.net_flow, 2)
        entry['cost_basis'] = round(pos.aplicado_total, 2)

        if pos.current_value is not None:
            entry['current_value'] = round(pos.current_value, 2)
            entry['price_source'] = pos.price_source or 'snapshot'
            entry['price_date'] = pos.price_date
            age = 0
            if pos.price_date:
                try:
                    snap_dt = datetime.strptime(pos.price_date, '%Y-%m-%d')
                    age = (datetime.now() - snap_dt).days
                except ValueError:
                    pass
            entry['snapshot_age_days'] = age
        else:
            entry['current_value'] = None
            entry['price_source'] = 'missing'
            entry['price_date'] = ''

        # P&L = current_value + net_flow (algebraic identity:
        # current_value − aplicado + juros_amort + resgates − impostos).
        # Without a snapshot, P&L is undefined — surface as None for the
        # frontend's "Sem valoração" bucket.
        value = entry['current_value']
        if value is not None:
            pnl = value + pos.net_flow
            entry['pnl_absolute'] = round(pnl, 2)
            entry['pnl_pct'] = round(pnl / pos.aplicado_total, 4) if pos.aplicado_total > 0 else 0
        else:
            entry['pnl_absolute'] = None
            entry['pnl_pct'] = None

        entry['total_dividends'] = round(pos.total_dividends, 2)

        # IRR per-asset — flows from balcão (already signed correctly).
        # Terminal anchors at the snapshot's own date (price_date), not the
        # cut date: cut-date anchoring implies 0% return across the staleness
        # window and understates IRR — the staler the snapshot, the bigger
        # the drag (D9 in docs/investimentos.md). Listed/crypto positions
        # keep the cut-date anchor (prices are fetched fresh at cut), and
        # portfolio/per-class IRR keep cut-date anchoring (mixed positions
        # need one common terminal anchor).
        flows = position_flows.get(pos.id, [])
        if flows:
            terminal = entry['current_value'] if entry['current_value'] is not None else 0
            snapshot_terminal_date = entry.get('price_date') or terminal_date
            entry['irr'] = compute_xirr(flows, terminal_value=terminal,
                                        terminal_date=snapshot_terminal_date,
                                        label=pos.id,
                                        expect_positive=pos.type in _RF_TRADICIONAL_TYPES)
        else:
            entry['irr'] = None
        if pos.irr_quality:
            entry['irr_quality'] = pos.irr_quality

        # RF metadata (issuer, indexer, rate, indexer_pct, application_date, maturity_date)
        # passes through from assets.csv when present. Empty fields are omitted to keep
        # the JSON tight for funds and pre-existing RF rows that lack metadata.
        for k in ('issuer', 'indexer', 'rate', 'indexer_pct', 'application_date', 'maturity_date'):
            v = asset_meta.get(k, '')
            if v:
                entry[k] = v

        # rate_type discriminator (S8) — classify the rate form for RF positions
        # that carry rate metadata. Only fires for BRL fixed-income positions
        # with at least one of rate/indexer_pct populated; metadata-less RF rows
        # (all blank) get no rate_type. Fail-loud: an unclassifiable combination
        # raises (never a silent default / misclassification).
        rate_raw = asset_meta.get('rate', '')
        pct_raw = asset_meta.get('indexer_pct', '')
        if (pos.currency or 'BRL') == 'BRL' and (
                _parse_rate_field(rate_raw) or _parse_rate_field(pct_raw)):
            entry['rate_type'] = classify_rate_type(
                asset_meta.get('indexer', ''), rate_raw, pct_raw)

    return entry


def _add_allocation(alloc: dict, key: str, value: float):
    if key not in alloc:
        alloc[key] = {'value': 0, 'pct': 0}
    alloc[key]['value'] += value


def _compute_pct(alloc: dict, total: float):
    for key in alloc:
        alloc[key]['value'] = round(alloc[key]['value'], 2)
        alloc[key]['pct'] = round(alloc[key]['value'] / total, 4) if total else 0


def _compute_portfolio_irr(positions, proventos, total_value, cut_date,
                           assets, position_entries, fx_state) -> dict:
    """Compute XIRR for total portfolio and per asset class.

    Per-class buckets: rv_br, rv_eua, rf_balcao, fundos, crypto.

    Currency normalisation: all bucket and total flows are computed in BRL
    so they're consistent with the BRL terminal (current_value_brl). USD
    orders and proventos (Avenue) are converted via the ticker's weighted
    FX rate from fx_state — same rate the FX engine uses to compute each
    ticker's cost_basis_brl. This avoids the prior USD-flows × BRL-terminal
    mismatch that inflated rv_eua IRR by ~the USD/BRL trajectory.

    Active-position filter (balcão only): only balcão flows belonging to
    a position in `position_entries` contribute. Matured RFs (active=false
    in assets.csv) are filtered out by `position_calculator` and so don't
    appear in entries — their net-positive balcão flows (juros + vencimento
    > aplicacao) would otherwise leak into rf_balcao without a matching
    terminal anchor. Equities/crypto are NOT filtered: closed positions
    there represent realized buy→sell gains/losses that legitimately belong
    in the bucket's lifetime IRR, and their flows already balance (cost
    matched by sale proceeds), so no anchor problem exists.
    """
    # Collect all cash flows from orders + proventos
    orders = load_csv(LEDGER_DIR / 'orders.csv', cut_date)
    balcao = load_balcao(cut_date)
    crypto = load_csv(LEDGER_DIR / 'crypto.csv', cut_date)
    migrations = load_code_migrations()

    # Active position ids — drives the per-class flow gate. Includes every
    # entry built by `_build_position_entry` (which has already filtered
    # inactive assets in `position_calculator.calculate_positions`).
    active_ids = {entry.get('id', '') for entry in position_entries
                  if entry.get('id')}

    all_flows = []
    flows_by_class: dict[str, list[tuple[str, float]]] = {}

    def _add(bucket: str, date_str: str, amount: float):
        all_flows.append((date_str, amount))
        flows_by_class.setdefault(bucket, []).append((date_str, amount))

    def _to_brl(ticker: str, currency: str, native_amount: float) -> float:
        if currency != 'USD':
            return native_amount
        rate = fx_state.get_ticker_fx_rate(ticker) if fx_state else 0
        if not rate:
            rate = (fx_state.weighted_avg_rate if fx_state else 0) or 1.0
        return native_amount * rate

    for row in orders:
        ticker = row.get('ticker', '')
        total = float(row.get('total', 0) or 0)
        signed = -abs(total) if row['side'] == 'C' else abs(total)
        meta = assets.get(ticker, {})
        currency = (meta.get('currency') or 'BRL').upper()
        signed_brl = _to_brl(ticker, currency, signed)
        bucket = _irr_class_bucket(ticker, assets)
        _add(bucket, row['date'], signed_brl)

    for row in proventos:
        ticker = row.get('ticker', '')
        net = float(row.get('net_value', 0) or 0)
        currency = (row.get('currency') or 'BRL').upper()
        # Use fx_engine's per-ticker provento BRL conversion (same path the
        # income section uses) for USD; falls back to native for BRL.
        if currency == 'USD' and fx_state is not None:
            net_brl = fx_state.get_provento_brl(row.get('date', ''), ticker, abs(net))
            if net_brl is None:
                net_brl = _to_brl(ticker, currency, abs(net))
        else:
            net_brl = abs(net)
        bucket = _irr_class_bucket(ticker, assets)
        _add(bucket, row['date'], net_brl)

    for row in _filter_balcao_for_irr(balcao, migrations):
        pid = row.get('product_id', '')
        # Filter to active balcao positions only — see docstring.
        if pid not in active_ids:
            continue
        amount = float(row.get('amount', 0) or 0)
        bucket = _irr_class_bucket(pid, assets)
        _add(bucket, row.get('date', ''), amount)

    # Inject synthetic seeds for code migrations into the corresponding bucket.
    for pid, mlist in migrations.items():
        if pid not in active_ids:
            continue
        bucket = _irr_class_bucket(pid, assets)
        for m in mlist:
            seed_amount = -float(m['from_total'])
            if seed_amount == 0:
                continue
            _add(bucket, m['seed_date'], seed_amount)

    for row in crypto:
        # Crypto flows are already BRL-marked via crypto.csv:price_brl.
        # Both legs of a swap belong in the bucket regardless of whether
        # the coin is currently held — closed crypto positions represent
        # realized BRL gains/losses, same convention as equities.
        price = float(row.get('price_brl', 0) or 0)
        if price <= 0:
            continue
        date_s = row.get('date', '')
        buy_asset = row.get('buy_asset', '')
        sell_asset = row.get('sell_asset', '')
        if buy_asset and buy_asset != 'BRL':
            all_flows.append((date_s, -price))
            flows_by_class.setdefault('crypto', []).append((date_s, -price))
        if sell_asset and sell_asset != 'BRL':
            all_flows.append((date_s, price))
            flows_by_class.setdefault('crypto', []).append((date_s, price))

    total_irr = compute_xirr(all_flows, terminal_value=total_value,
                             terminal_date=cut_date, label='portfolio')

    # Terminal value per bucket — sum BRL-normalized current values from the
    # already-built position entries.
    terminal_by_class: dict[str, float] = {}
    for entry in position_entries:
        bucket = _irr_class_bucket(entry.get('id', ''), assets)
        v = entry.get('current_value_brl')
        if v is None:
            v = entry.get('current_value') or 0
        terminal_by_class[bucket] = terminal_by_class.get(bucket, 0.0) + (v or 0)

    per_class: dict[str, dict] = {}
    for bucket, flows in flows_by_class.items():
        if bucket == 'other':
            continue
        terminal = terminal_by_class.get(bucket, 0.0)
        rate = compute_xirr(flows, terminal_value=terminal,
                            terminal_date=cut_date, label=f'class:{bucket}')
        per_class[bucket] = {
            'irr': rate,
            'terminal_value': round(terminal, 2),
            'flow_count': len(flows),
        }

    return {
        'total': total_irr,
        'per_class': per_class,
    }


def _build_income(proventos: list[dict], positions: list, fx_state) -> dict:
    """Build income section from proventos data.

    USD proventos are converted to BRL using the ticker's weighted FX rate
    at dividend time (computed by fx_engine, per PRD §"Dividendos USD"),
    NOT the spot rate. Native-currency `total` fields are preserved; BRL
    equivalents live in parallel `total_brl` fields so cross-currency
    aggregation is correct without breaking native-currency consumers.
    """
    monthly: dict[str, dict] = {}
    by_ticker: dict[str, dict] = {}

    for row in proventos:
        date = row.get('date', '')
        month = date[:7] if len(date) >= 7 else ''
        ptype = row.get('type', 'other')
        net = float(row.get('net_value', 0) or 0)
        ticker = row.get('ticker', '')
        currency = row.get('currency', 'BRL')

        if currency == 'USD':
            brl_value = fx_state.get_provento_brl(date, ticker, net)
            if brl_value is None:
                # Defensive: USD provento not seen by fx_engine. Skip from BRL
                # aggregates rather than mixing native-USD into BRL totals.
                brl_value = 0.0
        else:
            brl_value = net

        if month:
            if month not in monthly:
                monthly[month] = {
                    'month': month, 'total': 0, 'total_brl': 0,
                    'by_type': {}, 'by_type_brl': {},
                }
            monthly[month]['total'] += net
            monthly[month]['total_brl'] += brl_value
            monthly[month]['by_type'][ptype] = monthly[month]['by_type'].get(ptype, 0) + net
            monthly[month]['by_type_brl'][ptype] = monthly[month]['by_type_brl'].get(ptype, 0) + brl_value

        if ticker:
            if ticker not in by_ticker:
                by_ticker[ticker] = {
                    'id': ticker, 'total': 0, 'total_brl': 0,
                    'currency': currency,
                }
            by_ticker[ticker]['total'] += net
            by_ticker[ticker]['total_brl'] += brl_value

    monthly_list = sorted(monthly.values(), key=lambda x: x['month'], reverse=True)
    for m in monthly_list:
        m['total'] = round(m['total'], 2)
        m['total_brl'] = round(m['total_brl'], 2)
        m['by_type'] = {k: round(v, 2) for k, v in m['by_type'].items()}
        m['by_type_brl'] = {k: round(v, 2) for k, v in m['by_type_brl'].items()}

    ticker_list = sorted(by_ticker.values(), key=lambda x: -abs(x['total_brl']))
    for t in ticker_list:
        t['total'] = round(t['total'], 2)
        t['total_brl'] = round(t['total_brl'], 2)

    return {
        'monthly_totals': monthly_list[:24],  # Last 24 months
        'by_ticker': ticker_list,
    }


def write_portfolio(portfolio: dict, cut_date: str = None, force: bool = False):
    """Write portfolio.json and optionally a dated snapshot.

    When cut_date is set, refuses to overwrite an existing dated snapshot
    unless force=True is explicitly passed (D14 immutability invariant).
    """
    # Write main portfolio.json
    output_path = OUTPUT_DIR / 'portfolio.json'
    with audit.track_write(
        output_path,
        materiality="high",
        action="overwrite",
        event_type="ledger_write",
        source_function="calculate.write_portfolio",
        trigger_context={"cut_date": cut_date} if cut_date else None,
    ):
        atomic_write_json(output_path, portfolio)
    print(f'Written: {output_path}')

    # If cut_date, also write dated snapshot
    if cut_date:
        snapshot_path = OUTPUT_DIR / f'portfolio-{cut_date}.json'

        # D14 immutability invariant: refuse to overwrite without --force
        if snapshot_path.exists() and not force:
            print(
                f'ERROR: Snapshot {snapshot_path.name} already exists. '
                f'Pass --force to overwrite an existing dated snapshot.',
                file=sys.stderr,
            )
            raise SystemExit(1)

        audit_action = "overwrite" if snapshot_path.exists() else "create"
        with audit.track_write(
            snapshot_path,
            materiality="high",
            action=audit_action,
            event_type="ledger_write",
            source_function="calculate.write_portfolio",
            trigger_context={"cut_date": cut_date, "snapshot": True, "force": force},
        ):
            atomic_write_json(snapshot_path, portfolio)
        print(f'Written: {snapshot_path}')

        # Update snapshots.json
        _update_snapshots_manifest(cut_date)


def _update_snapshots_manifest(cut_date: str):
    """Update snapshots.json with new entry."""
    snapshots = []
    if SNAPSHOTS_JSON.exists():
        with open(SNAPSHOTS_JSON, 'r', encoding='utf-8') as f:
            snapshots = json.load(f)

    if cut_date not in snapshots:
        snapshots.append(cut_date)
        snapshots.sort(reverse=True)

    with audit.track_write(
        SNAPSHOTS_JSON,
        materiality="medium",
        action="overwrite",
        event_type="state_write",
        source_function="calculate._update_snapshots_manifest",
        trigger_context={"cut_date": cut_date},
    ):
        atomic_write_json(SNAPSHOTS_JSON, snapshots)
    print(f'Updated: {SNAPSHOTS_JSON}')


def main():
    parser = argparse.ArgumentParser(description='Generate portfolio.json')
    parser.add_argument('--cut-date', help='Calculate positions as of this date (YYYY-MM-DD)')
    parser.add_argument('--no-prices', action='store_true',
                        help='Skip API price fetching (faster, for testing)')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite an existing dated snapshot (required to regenerate a past snapshot)')
    args = parser.parse_args()

    print(f'Calculating portfolio...')
    if args.cut_date:
        print(f'Cut date: {args.cut_date}')

    portfolio = build_portfolio(cut_date=args.cut_date, skip_prices=args.no_prices)

    # Summary
    s = portfolio['summary']
    print(f'\nPositions: {len(portfolio["positions"])}')
    print(f'Total value: {s["total_value"]:,.2f}')
    print(f'Total cost:  {s["total_cost"]:,.2f}')
    print(f'Total P&L:   {s["total_pnl"]:,.2f}')
    if s['irr']['total'] is not None:
        print(f'IRR (XIRR):  {s["irr"]["total"]*100:.2f}%')

    write_portfolio(portfolio, args.cut_date, force=args.force)


if __name__ == '__main__':
    main()
