"""Position calculator for investment portfolio.

Aggregates orders into positions, applies corporate actions chronologically,
handles fixed income (net flows + snapshots), and crypto positions.
Supports --cut-date filtering for historical snapshots.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


VAULT_ROOT = _find_vault_root()

LEDGER_DIR = VAULT_ROOT / ".user" / "finance" / "bookkeeper" / "ledgers" / "investimentos"
ASSETS_PATH = VAULT_ROOT / ".user" / "finance" / "bookkeeper" / "data" / "assets.csv"
CORRECTIONS_DIR = VAULT_ROOT / ".user" / "finance" / "bookkeeper" / "config" / "corrections"


@dataclass
class Position:
    id: str
    name: str = ''
    asset_class: str = ''
    type: str = ''
    broker: str = ''
    currency: str = 'BRL'
    sector: str = ''
    quantity: float = 0.0
    cost_basis: float = 0.0  # Total cost (BRL for BR, USD for US)
    total_dividends: float = 0.0         # Lifetime: all income-type proventos (excludes fracao)
    total_dividends_ttm: float = 0.0      # Trailing 12 months ending at cut_date
    # Fixed income specific
    net_flow: float = 0.0  # Sum of all balcao amounts (signed)
    # Per-operation breakdown — RF/funds via balcão
    aplicado_total: float = 0.0       # Σ |amount| where operation = aplicacao
    juros_amort_total: float = 0.0    # Σ amount where operation ∈ {juros, amortizacao}
    resgates_total: float = 0.0       # Σ amount where operation ∈ {resgate, vencimento}
    impostos_total: float = 0.0       # Σ |amount| where operation ∈ {irrf, iof}
    # Snapshot
    current_value: float | None = None
    price_source: str = ''
    price_date: str = ''
    # IRR quality flag — only populated for balcão positions.
    # Values: complete | seed_only | short_window | unverified | ''
    irr_quality: str = ''

    @property
    def avg_cost(self) -> float:
        if self.quantity > 0:
            return self.cost_basis / self.quantity
        return 0.0


def load_csv(filepath: Path, cut_date: str = None) -> list[dict]:
    """Load CSV, optionally filtering by date <= cut_date."""
    if not filepath.exists():
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    if cut_date:
        rows = [r for r in rows if r.get('date', '') <= cut_date]
    return rows


def load_assets() -> dict[str, dict]:
    """Load assets.csv into lookup dict by id."""
    assets = {}
    if not ASSETS_PATH.exists():
        return assets
    with open(ASSETS_PATH, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            assets[row['id']] = row
    return assets


# Listed asset types — valued via quantity * current_price.
_LISTED_TYPES = {'acao', 'fii', 'bdr', 'opcao', 'etf', 'stock_us', 'etf_us',
                 'direito_subscricao'}

# Balcão asset types — RF + investment funds, valued via balcão flows + snapshot.
_BALCAO_TYPES = {'cra', 'deb', 'lca', 'lci', 'cdb', 'cdb_mp', 'tesouro', 'lc', 'cri', 'rf',
                 'fia_br', 'fia_usa', 'fim_br', 'firf_br', 'fidc', 'coe', 'di'}


def _resolve_valuation_method(product_type: str) -> str:
    """Derive how a position is valued from its product type.

    'price'  → quantity * current_price (listed equities, ETFs, FIIs, options)
    'balcao' → aplicado / juros_amort / resgates from balcão flows + snapshot
    'crypto' → quantity * BRL price (crypto exchanges quote in BRL natively)

    Decoupled from asset_class (which drives the donut grouping in Carteira):
    non-DI funds render in the Balcão view (valuation_method='balcao') but
    classify as 'variable_income' for the donut.
    """
    if product_type in _LISTED_TYPES:
        return 'price'
    if product_type in _BALCAO_TYPES:
        return 'balcao'
    if product_type == 'crypto':
        return 'crypto'
    return ''


# Proventos types counted as income for YoC (Yield on Cost). Excludes 'fracao'
# (cash residue from auctioned fractional shares — not investment income).
_INCOME_PROVENTO_TYPES = {'dividendo', 'jcp', 'rendimento', 'juros', 'bonificacao_dinheiro'}

# RF balcão operation buckets — drive the per-operation breakdown on Position.
_RF_INCOME_OPS = {'juros', 'amortizacao'}
_RF_REDEMPTION_OPS = {'resgate', 'vencimento'}
_RF_TAX_OPS = {'irrf', 'iof'}


def load_code_migrations() -> dict[str, list[dict]]:
    """Load code_migrations.csv → dict[product_id, list[migration_dict]].

    A code migration happens when a broker re-codes the same asset (same CNPJ)
    into a different internal code, recording the swap as a pair of
    resgate(s) + aplicacao(s) in the movements file. The amounts are NOT
    real cash flows — the money never left the user's custody. They must be
    filtered out of IRR flows, aplicado_total, and net_flow, and replaced
    with a synthetic seed at the migration boundary representing the
    accumulated balance carried forward from the closed code.

    Schema: product_id, from_dates (pipe-separated), from_total,
            to_dates (pipe-separated), to_total, source, note.
    The synthetic seed is injected on the latest from_date with amount =
    -from_total (an aplicacao-equivalent).
    """
    path = CORRECTIONS_DIR / 'code_migrations.csv'
    if not path.exists():
        return {}
    out: dict[str, list[dict]] = {}
    with open(path, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            pid = (row.get('product_id') or '').strip()
            if not pid:
                continue
            from_dates = {d.strip() for d in (row.get('from_dates') or '').split('|') if d.strip()}
            to_dates = {d.strip() for d in (row.get('to_dates') or '').split('|') if d.strip()}
            seed_date = max(from_dates) if from_dates else (row.get('migration_date') or '').strip()
            out.setdefault(pid, []).append({
                'from_dates': from_dates,
                'from_total': float(row.get('from_total') or 0),
                'to_dates': to_dates,
                'to_total': float(row.get('to_total') or 0),
                'seed_date': seed_date,
            })
    return out


def _dedup_cross_source_balcao(balcao: list[dict]) -> list[dict]:
    """Drop b3 / b3_manual rows that duplicate a safra_movimentacoes row.

    Both the b3_parser and the safra_rf_movimentacoes parser emit juros /
    amortizacao events for the same custodied RF assets (CRAs, debentures).
    When both sources record identical (date, operation, product_id,
    abs(amount)), safra_movimentacoes wins — it comes directly from the
    custodian — and the b3 / b3_manual duplicate is dropped.

    Pure cross-source dedup: does not collapse two rows from the same
    source. Does not touch any source other than b3* when a matching
    safra_movimentacoes row exists.
    """
    SAFRA = 'safra_movimentacoes'

    def _key(row: dict):
        try:
            amt = round(abs(float(row.get('amount') or 0)), 2)
        except (TypeError, ValueError):
            return None
        return (row.get('date', ''),
                (row.get('operation') or '').lower(),
                row.get('product_id', ''),
                amt)

    safra_keys: set[tuple] = set()
    for row in balcao:
        if (row.get('source') or '').strip() == SAFRA:
            k = _key(row)
            if k is not None:
                safra_keys.add(k)

    out = []
    for row in balcao:
        source = (row.get('source') or '').strip()
        if source == SAFRA:
            out.append(row)
            continue
        if source in ('b3', 'b3_manual'):
            k = _key(row)
            if k is not None and k in safra_keys:
                continue
        out.append(row)
    return out


def load_balcao(cut_date: str = None) -> list[dict]:
    """Load balcao.csv and apply cross-source dedup.

    Use this instead of `load_csv(LEDGER_DIR / 'balcao.csv', ...)` in any
    consumer that reasons about cash flows — keeps b3 vs safra_movimentacoes
    duplicates from double-counting juros / amortizacao / resgates.
    """
    return _dedup_cross_source_balcao(load_csv(LEDGER_DIR / 'balcao.csv', cut_date))


def is_migration_phantom(product_id: str, date_s: str, operation: str,
                         migrations: dict[str, list[dict]]) -> bool:
    """True if this balcão row is a phantom flow from a code migration.

    Filters resgates on `from_dates` and aplicacoes on `to_dates`. Other
    operations on those dates (come_cotas, juros) are real and pass through.
    """
    op = (operation or '').lower()
    for m in migrations.get(product_id, []):
        if op in _RF_REDEMPTION_OPS and date_s in m['from_dates']:
            return True
        if op == 'aplicacao' and date_s in m['to_dates']:
            return True
    return False

# Provento types that should NEVER appear in proventos.csv for RF assets —
# they belong in balcao.csv as juros/amortizacao operations.
_RF_FORBIDDEN_PROVENTO_TYPES = {'juros', 'amortizacao'}


def _validate_no_rf_in_proventos(proventos: list[dict], assets: dict[str, dict]):
    """Fail fast if RF tickers appear in proventos.csv with juros/amortizacao type.

    The b3_parser routes PAGAMENTO DE JUROS and AMORTIZAÇÃO for RF assets to
    balcao.csv. If they end up in proventos.csv, position_calculator can't
    match them to the RF position (positions are keyed by product_id, not
    ticker), producing wrong P&L and ghost rows in the proventos view.
    """
    violations = []
    for r in proventos:
        ticker = r.get('ticker', '')
        ptype = (r.get('type') or '').lower()
        if ptype not in _RF_FORBIDDEN_PROVENTO_TYPES:
            continue
        meta = assets.get(ticker, {})
        if (meta.get('asset_class') or '').lower() == 'fixed_income':
            violations.append((r.get('date', ''), ticker, ptype))
    if violations:
        msg = ['RF entries found in proventos.csv (should be in balcao.csv):']
        for d, t, p in violations[:10]:
            msg.append(f'  {d}  {t}  type={p}')
        if len(violations) > 10:
            msg.append(f'  ... and {len(violations) - 10} more')
        msg.append('')
        msg.append('Run: 3-resources/tools/sb-os/finance/scripts/migrations/2026-05-01-migrate-rf-juros.py')
        raise ValueError('\n'.join(msg))


def calculate_positions(cut_date: str = None) -> list[Position]:
    """Calculate all positions from ledger data.

    Returns list of Position objects with non-zero holdings.
    """
    assets = load_assets()

    # Load ledger data
    orders = load_csv(LEDGER_DIR / 'orders.csv', cut_date)
    proventos = load_csv(LEDGER_DIR / 'proventos.csv', cut_date)
    balcao = load_balcao(cut_date)
    crypto = load_csv(LEDGER_DIR / 'crypto.csv', cut_date)
    corp_actions = load_csv(LEDGER_DIR / 'corporate_actions.csv', cut_date)
    snapshots = load_csv(LEDGER_DIR / 'balance-snapshots.csv', cut_date)

    # Validate ledger consistency before computing positions.
    _validate_no_rf_in_proventos(proventos, assets)

    positions: dict[str, Position] = {}

    # --- Variable Income: interleave orders + corporate actions by date ---
    # Corporate actions MUST be applied chronologically with surrounding trades
    # because qty at event time depends on prior buys/sells.
    events = []
    for row in orders:
        events.append((row.get('date', ''), 0, 'order', row))
    for row in corp_actions:
        # Corp actions fire after same-date orders (sort tiebreaker=1)
        events.append((row.get('date', ''), 1, 'corp', row))
    events.sort(key=lambda e: (e[0], e[1]))

    for _date, _tier, kind, row in events:
        if kind == 'order':
            ticker = row['ticker']
            pos = _get_or_create(positions, ticker, assets)
            qty = float(row.get('quantity', 0) or 0)
            total = float(row.get('total', 0) or 0)
            row_type = (row.get('asset_type') or '').strip().lower()
            if not pos.asset_class and row_type in _LISTED_TYPES:
                pos.asset_class = 'variable_income'
            if not pos.type and row_type:
                pos.type = row_type

            if row['side'] == 'C':
                pos.quantity += qty
                pos.cost_basis += abs(total)
            else:
                if pos.quantity > 0:
                    sell_ratio = min(qty / pos.quantity, 1.0)
                    pos.cost_basis -= pos.cost_basis * sell_ratio
                pos.quantity -= qty

            pos.broker = row.get('broker', pos.broker)
            pos.currency = row.get('currency', pos.currency)
        else:
            _apply_corporate_action(positions, row, assets)

    # --- Proventos: accumulate income per ticker (lifetime + TTM) ---
    # Only income-type proventos contribute to YoC. TTM window = 365 days
    # before cut_date (or today if cut_date not provided).
    from datetime import date, timedelta
    window_end = date.fromisoformat(cut_date) if cut_date else date.today()
    window_start = (window_end - timedelta(days=365)).isoformat()
    for row in proventos:
        ticker = row['ticker']
        ptype = (row.get('type') or '').strip().lower()
        if ticker not in positions:
            continue
        if ptype not in _INCOME_PROVENTO_TYPES:
            continue  # skip fracao and other non-income flows
        net_val = float(row.get('net_value', 0) or 0)
        positions[ticker].total_dividends += net_val
        if row.get('date', '') >= window_start:
            positions[ticker].total_dividends_ttm += net_val

    # --- Fixed Income: balcao net flows ---
    # Per-operation breakdown so the dashboard can render aplicado, juros+amort,
    # resgates, impostos as separate columns. net_flow remains the signed sum
    # so P&L = current_value + net_flow stays an algebraic identity.
    # Side state for irr_quality: track seed presence, source mix, first-flow
    # date and row count per balcão position so we can label IRR reliability
    # after the loop completes.
    has_seed: dict[str, bool] = {}
    only_spreadsheet: dict[str, bool] = {}
    balcao_row_count: dict[str, int] = {}
    first_flow_date: dict[str, str] = {}

    # Code-migration phantoms must be filtered before earliest_real_flow is
    # computed — otherwise the phantom resgate date wins as "earliest real"
    # and pollutes downstream seed-supersession logic.
    migrations = load_code_migrations()

    # Pre-compute earliest non-seed flow date per pid. Seeds (`*_seed` source)
    # represent the carrying balance at a statement period start; when real
    # flows already predate (or match) the seed date, the seed double-counts
    # cost basis and must be excluded from net_flow / aplicado_total / IRR.
    # Mirrors the same filter in calculate.py:_build_position_flows.
    earliest_real_flow: dict[str, str] = {}
    for row in balcao:
        pid = row.get('product_id', '')
        if not pid:
            continue
        source = (row.get('source') or '').strip()
        if source.endswith('_seed'):
            continue
        date_s = row.get('date', '')
        if is_migration_phantom(pid, date_s, row.get('operation', ''), migrations):
            continue
        if date_s and (pid not in earliest_real_flow or date_s < earliest_real_flow[pid]):
            earliest_real_flow[pid] = date_s

    for row in balcao:
        pid = row['product_id']
        pos = _get_or_create(positions, pid, assets)
        operation = (row.get('operation') or '').lower()
        amount = float(row.get('amount', 0) or 0)
        source = (row.get('source') or '').strip()
        date_s = row.get('date', '')

        # Filter code-migration phantoms (resgates/aplicacoes that represent
        # broker re-coding of the same CNPJ, not real cash flow).
        if is_migration_phantom(pid, date_s, operation, migrations):
            continue

        # Skip superseded seeds entirely — they don't contribute to net_flow,
        # aplicado_total, IRR flows, or the seed_only quality flag.
        is_seed = source.endswith('_seed')
        if is_seed and pid in earliest_real_flow and earliest_real_flow[pid] <= date_s:
            continue

        pos.net_flow += amount
        balcao_row_count[pid] = balcao_row_count.get(pid, 0) + 1
        if is_seed:
            has_seed[pid] = True
        if source == 'spreadsheet':
            only_spreadsheet[pid] = only_spreadsheet.get(pid, True)
        else:
            only_spreadsheet[pid] = False
        if date_s and (pid not in first_flow_date or date_s < first_flow_date[pid]):
            first_flow_date[pid] = date_s
        if operation == 'aplicacao':
            pos.aplicado_total += abs(amount)
        elif operation in _RF_INCOME_OPS:
            pos.juros_amort_total += amount
        elif operation in _RF_REDEMPTION_OPS:
            pos.resgates_total += amount
        elif operation in _RF_TAX_OPS:
            pos.impostos_total += abs(amount)
        pos.broker = row.get('broker', pos.broker)
        if not pos.type:
            pos.type = row.get('product_type', '')
        if not pos.asset_class:
            pos.asset_class = _infer_class(pos.type)

    # --- Code migration synthetic seeds ---
    # For each migration, inject a synthetic aplicacao at the migration
    # boundary representing the accumulated balance carried forward from
    # the closed code. Without this, IRR loses its anchor (no initial
    # outlay) and net_flow wildly overstates apparent P&L.
    for pid, mlist in migrations.items():
        if pid not in positions:
            continue
        pos = positions[pid]
        for m in mlist:
            seed_amount = -float(m['from_total'])  # outflow (aplicacao-equivalent)
            if seed_amount == 0:
                continue
            pos.aplicado_total += abs(seed_amount)
            pos.net_flow += seed_amount
            seed_date = m['seed_date']
            balcao_row_count[pid] = balcao_row_count.get(pid, 0) + 1
            if seed_date and (pid not in first_flow_date or seed_date < first_flow_date[pid]):
                first_flow_date[pid] = seed_date

    # --- Balance Snapshots: latest snapshot per product ---
    snapshot_map: dict[str, dict] = {}
    for row in snapshots:
        pid = row['product_id']
        if pid not in snapshot_map or row['date'] > snapshot_map[pid]['date']:
            snapshot_map[pid] = row

    for pid, snap in snapshot_map.items():
        if pid in positions:
            positions[pid].current_value = float(snap.get('balance', 0) or 0)
            positions[pid].price_source = 'snapshot'
            positions[pid].price_date = snap.get('date', '')

    # --- Crypto ---
    # Crypto positions are scoped per (ticker, exchange). The user holds the
    # same asset (e.g. BTC) on multiple exchanges and wants per-broker positions
    # surfaced in the dashboard. Positions are keyed by f"{ticker}@{exchange}"
    # in the dict; Position.id stays the bare ticker so price_fetcher hits one
    # quote per ticker regardless of how many exchanges hold it.
    for row in crypto:
        buy_asset = row.get('buy_asset', '')
        sell_asset = row.get('sell_asset', '')
        buy_qty = float(row.get('buy_quantity', 0) or 0)
        sell_qty = float(row.get('sell_quantity', 0) or 0)
        price_brl = float(row.get('price_brl', 0) or 0)
        exchange = _normalize_crypto_exchange(row.get('exchange', ''))

        if buy_asset and buy_asset != 'BRL':
            pos = _get_or_create_crypto(positions, buy_asset, exchange, assets)
            pos.quantity += buy_qty
            pos.cost_basis += price_brl

        if sell_asset and sell_asset != 'BRL':
            pos = _get_or_create_crypto(positions, sell_asset, exchange, assets)
            if pos.quantity > 0:
                sell_ratio = min(sell_qty / pos.quantity, 1.0)
                pos.cost_basis -= pos.cost_basis * sell_ratio
            pos.quantity -= sell_qty

    # --- IRR quality flag for balcão positions ---
    # Priority: seed_only > unverified > short_window > complete.
    # Only labels balcão positions (RF + funds via balcao.csv).
    from datetime import date as _date
    cut = _date.fromisoformat(cut_date) if cut_date else _date.today()
    for pid, pos in positions.items():
        method = _resolve_valuation_method(pos.type)
        if method != 'balcao' and method != '':
            continue
        if pid not in balcao_row_count:
            continue
        if has_seed.get(pid):
            pos.irr_quality = 'seed_only'
            continue
        if balcao_row_count[pid] == 1 and only_spreadsheet.get(pid):
            pos.irr_quality = 'unverified'
            continue
        first = first_flow_date.get(pid, '')
        if first:
            try:
                window_days = (cut - _date.fromisoformat(first)).days
                if window_days < 90:
                    pos.irr_quality = 'short_window'
                    continue
            except ValueError:
                pass
        pos.irr_quality = 'complete'

    # --- Filter: only non-zero positions ---
    # Negative quantities on listed assets always mean a missing corporate action
    # or an unrecorded issuance (rights, bonus, subscription). Drop them and emit
    # a warning — never surface as "real" positions in the dashboard.
    # Assets marked active=false in assets.csv are dropped unconditionally —
    # for closed RF/funds whose ledger entries (juros only, no vencimento)
    # would otherwise leak into the "Sem valoração" bucket forever.
    result = []
    warnings = []
    for pos in positions.values():
        asset_meta = assets.get(pos.id, {})
        if (asset_meta.get('active') or '').strip().lower() == 'false':
            continue
        method = _resolve_valuation_method(pos.type)
        is_listed = method in ('price', 'crypto')
        is_rf = method == 'balcao' or not method

        if is_listed:
            # 1e-6 absorbs floating-point noise from chained crypto swap math
            # (e.g. USDT residue at -3e-7 from compounded sell ratios). Real
            # missing-corp-action gaps are always > 1e-6 (whole-share units).
            if pos.quantity > 1e-6:
                result.append(pos)
            elif pos.quantity < -1e-6:
                warnings.append(
                    f"[position_calculator] NEGATIVE qty dropped: {pos.id} "
                    f"qty={pos.quantity} broker={pos.broker} — likely missing corp action"
                )
        elif is_rf and (abs(pos.net_flow) > 1.0 or pos.current_value):
            result.append(pos)

    if warnings:
        import sys
        for w in warnings:
            print(w, file=sys.stderr)

    return result


def _get_or_create(positions: dict[str, Position], asset_id: str,
                   assets: dict[str, dict]) -> Position:
    """Get existing position or create from assets.csv lookup."""
    if asset_id not in positions:
        asset_meta = assets.get(asset_id, {})
        positions[asset_id] = Position(
            id=asset_id,
            name=asset_meta.get('name', ''),
            asset_class=asset_meta.get('asset_class', ''),
            type=asset_meta.get('type', ''),
            sector=asset_meta.get('sector', ''),
            currency=asset_meta.get('currency', 'BRL'),
            broker=asset_meta.get('current_broker', ''),
        )
    return positions[asset_id]


def _normalize_crypto_exchange(raw: str) -> str:
    """Bipa stays bipa; everything else (binance, mb, blank) → mercado_bitcoin.

    User rule: Bipa was their only non-MB exchange and only existed from 2024
    on. Any historical row labeled binance/mb/empty was Mercado Bitcoin.
    """
    return 'bipa' if (raw or '').strip().lower() == 'bipa' else 'mercado_bitcoin'


def _get_or_create_crypto(positions: dict[str, Position], ticker: str,
                          exchange: str, assets: dict[str, dict]) -> Position:
    """Get/create a crypto position keyed by (ticker, exchange).

    The dict key is composite (`f"{ticker}@{exchange}"`) so the same ticker
    held on multiple exchanges yields separate Position objects. Position.id
    stays as the bare ticker — price lookups dedupe by id downstream.
    """
    key = f"{ticker}@{exchange}"
    if key not in positions:
        asset_meta = assets.get(ticker, {})
        positions[key] = Position(
            id=ticker,
            name=asset_meta.get('name', ''),
            asset_class='crypto',
            type='crypto',
            sector=asset_meta.get('sector', ''),
            currency='BRL',
            broker=exchange,
        )
    return positions[key]


# B3 types that CANNOT be fractional — residues after corporate actions
# are settled in cash via "Fração em Ativos" proventos, so we floor qty
# on the position after every event.
_B3_INTEGER_TYPES = {'acao', 'opcao', 'direito_subscricao', 'bdr', 'fii'}


def _maybe_round_b3_integer(pos: 'Position'):
    """Floor listed-B3-integer positions to whole shares.

    B3 issues cash proventos for fractional residues after corporate actions
    (cisão, grupamento, desdobramento, bonificação). The broker credits the
    floor of the resulting qty to the user's custody and auctions the fraction
    (Leilão de Fração / Fração em Ativos), crediting the proceeds as cash on
    the proventos ledger. The position's listed qty must therefore be the
    floor of the computed value — never rounded, never the raw fraction.
    """
    if (pos.type or '').strip().lower() in _B3_INTEGER_TYPES:
        # Floor, not round. E.g. grupamento 50:1 on 1727 shares → 34.54 → 34
        # (the 0.54 is auctioned, not retained). math.floor via int() for
        # non-negative qty; negatives have already been dropped upstream.
        pos.quantity = float(int(pos.quantity))


def _apply_corporate_action(positions: dict[str, Position],
                            action: dict, assets: dict[str, dict]):
    """Apply a corporate action to positions."""
    ticker = action['ticker']
    action_type = action['action_type']
    new_ticker = action.get('new_ticker', '').strip()
    ratio_from = float(action.get('ratio_from', 0) or 0)
    ratio_to = float(action.get('ratio_to', 0) or 0)

    if ticker not in positions:
        return  # No position to act on

    pos = positions[ticker]

    # expiracao is the one action where ratio_to=0 is legitimate (option / right
    # expired worthless). Handle it before the "flagged for research" guard below.
    if action_type == 'expiracao':
        pos.quantity = 0
        return

    # ajuste is a manual zeroing of a position — used when the ledger has a
    # negative qty from missing upstream data (unrecorded subscription, bonus,
    # or buy) and the user explicitly accepts the gap rather than reconstructing
    # the missing transaction. Clears both qty and cost basis so the position
    # disappears from results without triggering the negative-qty warning.
    if action_type == 'ajuste':
        pos.quantity = 0
        pos.cost_basis = 0
        return

    # Skip if ratio not yet filled (flagged for research)
    if ratio_from == 0 or ratio_to == 0:
        return

    ratio = ratio_to / ratio_from

    if action_type in ('grupamento', 'desdobramento'):
        pos.quantity = pos.quantity * ratio
        _maybe_round_b3_integer(pos)
        # Cost basis unchanged

    elif action_type == 'bonificacao':
        pos.quantity = pos.quantity * (1 + ratio)
        _maybe_round_b3_integer(pos)
        # Cost basis unchanged (free shares)

    elif action_type in ('conversao', 'incorporacao', 'fusao'):
        if new_ticker:
            new_pos = _get_or_create(positions, new_ticker, assets)
            new_pos.quantity += pos.quantity * ratio
            new_pos.cost_basis += pos.cost_basis
            _maybe_round_b3_integer(new_pos)
            # Remove old position
            pos.quantity = 0
            pos.cost_basis = 0

    elif action_type == 'cisao':
        if new_ticker:
            new_pos = _get_or_create(positions, new_ticker, assets)
            new_pos.quantity = pos.quantity * ratio
            _maybe_round_b3_integer(new_pos)
            # Split cost proportionally
            cost_new = pos.cost_basis * ratio_to / (ratio_from + ratio_to)
            new_pos.cost_basis = cost_new
            pos.cost_basis -= cost_new


def _infer_class(product_type: str) -> str:
    """Infer asset_class from product_type when assets.csv has no entry.

    DI funds (type='di') are 'fixed_income' to match the donut grouping in
    Carteira (rule: fundo DI = RF, demais = RV). All other fund types are
    'variable_income'. RF tradicional → 'fixed_income'.
    """
    rf_types = {'cra', 'deb', 'lca', 'lci', 'cdb', 'cdb_mp', 'tesouro', 'lc', 'cri', 'rf', 'di'}
    fund_types = {'fia_br', 'fia_usa', 'fim_br', 'firf_br', 'fidc', 'coe'}
    if product_type in rf_types:
        return 'fixed_income'
    if product_type in fund_types:
        return 'variable_income'
    return ''
