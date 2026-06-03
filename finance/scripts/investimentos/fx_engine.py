"""Avenue FX engine — weighted average + FIFO lot tracking.

Stateless: reprocesses avenue_fx.csv + USD orders + USD proventos
chronologically to compute BRL equivalents for all USD positions.
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


@dataclass
class Lot:
    """A purchase lot for FIFO tracking."""
    ticker: str
    date: str
    quantity: float
    price_usd: float
    fx_rate: float  # BRL/USD rate at time of purchase

    @property
    def cost_brl(self) -> float:
        return self.quantity * self.price_usd * self.fx_rate


@dataclass
class FXState:
    """Running state of the FX engine."""
    usd_balance: float = 0.0
    weighted_avg_rate: float = 0.0
    lots: list[Lot] = field(default_factory=list)  # FIFO lots per ticker
    # BRL-equivalent records for USD proventos, computed at the ticker's
    # weighted FX rate at dividend time (PRD §"Dividendos USD").
    provento_brl_records: list[dict] = field(default_factory=list)
    # FIFO tranches from transfer_in events; consumed by process_transfer_out
    # to correctly shift weighted_avg_rate after withdrawals (D10).
    transfer_lots: list[dict] = field(default_factory=list)

    def process_transfer_in(self, usd_amount: float, fx_rate: float):
        """BRL → USD transfer. Increases USD balance, updates weighted avg.

        If prior balance is non-positive (overdrawn or zero), the inflow's
        rate becomes the new average — there's no prior USD pool to weight
        against. This guards against rate distortion when an inflow rescues
        a negative balance (PRD §"Outras regras" allows transient negatives).
        """
        new_balance = self.usd_balance + usd_amount
        if new_balance > 0:
            if self.usd_balance <= 0:
                # Prior balance non-positive: incoming rate replaces avg.
                # Clear any stale transfer tranches before recording this one.
                self.transfer_lots = []
                self.weighted_avg_rate = fx_rate
            else:
                self.weighted_avg_rate = (
                    (self.usd_balance * self.weighted_avg_rate
                     + usd_amount * fx_rate)
                    / new_balance
                )
        self.usd_balance = new_balance
        if usd_amount > 0:
            self.transfer_lots.append({'usd': usd_amount, 'fx_rate': fx_rate})

    def process_transfer_out(self, usd_amount: float):
        """USD → BRL transfer. FIFO-consumes transfer tranches (D10).

        Consumes USD from the earliest transfer_in tranche first, then
        recomputes weighted_avg_rate from the remaining tranches.
        """
        self.usd_balance -= usd_amount

        # FIFO-consume transfer tranches
        remaining = usd_amount
        new_transfer_lots = []
        for tranche in self.transfer_lots:
            if remaining <= 0:
                new_transfer_lots.append(tranche)
                continue
            if tranche['usd'] <= remaining:
                remaining -= tranche['usd']
                # Entire tranche consumed — drop it
            else:
                new_transfer_lots.append({
                    'usd': tranche['usd'] - remaining,
                    'fx_rate': tranche['fx_rate'],
                })
                remaining = 0
        self.transfer_lots = new_transfer_lots

        # Recompute weighted_avg_rate from remaining tranches
        total_usd = sum(t['usd'] for t in self.transfer_lots)
        if total_usd > 0:
            self.weighted_avg_rate = (
                sum(t['usd'] * t['fx_rate'] for t in self.transfer_lots)
                / total_usd
            )
        elif self.usd_balance <= 0:
            self.weighted_avg_rate = 0.0

    def process_provento(self, ticker: str, date: str, usd_amount: float) -> float:
        """USD dividend/income received. Per PRD §"Dividendos USD":

        - BRL equivalent = usd_amount × ticker's weighted FX rate
        - usd_balance increases by usd_amount
        - weighted_avg_rate recomputed using the ticker's rate as the
          incoming credit's effective rate

        Falls back to account-level weighted_avg_rate if the ticker has no
        active lots (handled by get_ticker_fx_rate). Returns BRL equivalent.
        """
        ticker_rate = self.get_ticker_fx_rate(ticker)
        brl_equivalent = usd_amount * ticker_rate

        new_balance = self.usd_balance + usd_amount
        if new_balance > 0:
            if self.usd_balance <= 0:
                # Same rescue case as process_transfer_in: no prior pool to weight.
                self.weighted_avg_rate = ticker_rate
            else:
                self.weighted_avg_rate = (
                    (self.usd_balance * self.weighted_avg_rate
                     + usd_amount * ticker_rate)
                    / new_balance
                )
        self.usd_balance = new_balance

        self.provento_brl_records.append({
            'date': date,
            'ticker': ticker,
            'usd_amount': usd_amount,
            'fx_rate_used': ticker_rate,
            'brl_equivalent': brl_equivalent,
        })
        return brl_equivalent

    def get_provento_brl(self, date: str, ticker: str,
                         usd_amount: float) -> float | None:
        """Look up the BRL equivalent of a USD provento.

        Matches the first record with same date, ticker, and usd_amount
        (within ±0.005 tolerance for float comparison). Returns None if
        no record exists — caller decides on fallback.
        """
        for rec in self.provento_brl_records:
            if (rec['date'] == date
                    and rec['ticker'] == ticker
                    and abs(rec['usd_amount'] - usd_amount) < 0.005):
                return rec['brl_equivalent']
        return None

    def process_buy(self, ticker: str, date: str, quantity: float, price_usd: float):
        """Buy a US asset. Creates a FIFO lot at current weighted avg rate."""
        total_usd = quantity * price_usd
        self.usd_balance -= total_usd
        self.lots.append(Lot(
            ticker=ticker, date=date, quantity=quantity,
            price_usd=price_usd, fx_rate=self.weighted_avg_rate,
        ))

    def process_sell(self, ticker: str, quantity: float) -> float:
        """Sell a US asset using FIFO. Returns BRL cost basis of sold lots."""
        remaining = quantity
        cost_brl = 0.0
        new_lots = []

        for lot in self.lots:
            if lot.ticker != ticker:
                new_lots.append(lot)
                continue
            if remaining <= 0:
                new_lots.append(lot)
                continue

            if lot.quantity <= remaining:
                # Consume entire lot
                cost_brl += lot.cost_brl
                remaining -= lot.quantity
            else:
                # Partial consumption
                consumed_cost = (remaining / lot.quantity) * lot.cost_brl
                cost_brl += consumed_cost
                lot.quantity -= remaining
                remaining = 0
                new_lots.append(lot)

        self.lots = new_lots
        # Proceeds go back to USD balance (handled by caller if needed)
        return cost_brl

    def get_ticker_fx_rate(self, ticker: str) -> float:
        """Weighted average FX rate for a ticker's active lots."""
        total_qty = 0.0
        weighted_sum = 0.0
        for lot in self.lots:
            if lot.ticker == ticker and lot.quantity > 0:
                total_qty += lot.quantity
                weighted_sum += lot.quantity * lot.fx_rate
        if total_qty > 0:
            return weighted_sum / total_qty
        return self.weighted_avg_rate  # Fallback to account-level avg

    def get_ticker_cost_brl(self, ticker: str) -> float:
        """Total BRL cost basis for a ticker from active lots."""
        return sum(lot.cost_brl for lot in self.lots
                   if lot.ticker == ticker and lot.quantity > 0)

    def get_ticker_quantity(self, ticker: str) -> float:
        """Total quantity for a ticker from active lots."""
        return sum(lot.quantity for lot in self.lots
                   if lot.ticker == ticker and lot.quantity > 0)


def _intraday_tier(evt: dict) -> int:
    """Intra-day processing tier: inflows before outflows within a date.

    Same-day settlement at the broker is atomic, so processing buys before
    same-day sells (an artifact of CSV row order) produces false-negative
    USD balance dips (e.g. 2022-07-15: 1 buy + 8 sells). Tiers mirror
    position_calculator's orders/corp-actions tiebreaker pattern:
    transfer_in (0) → provento (1) → sell (2) → buy (3) → transfer_out (4).
    """
    if evt['type'] == 'fx':
        return 0 if evt['operation'] == 'transfer_in' else 4
    if evt['type'] == 'provento':
        return 1
    if evt['type'] == 'order':
        return 3 if evt['side'] == 'C' else 2
    return 5


def load_events(cut_date: str = None) -> list[dict]:
    """Load all USD events (FX transfers, USD orders, USD proventos),
    sorted by (date, intra-day tier).

    Shared by build_fx_state and the trace_fx_balance diagnostic so both
    always replay the exact same event stream.
    """
    events = []

    # Load FX transfers
    fx_rows = _load_csv(LEDGER_DIR / 'avenue_fx.csv', cut_date)
    for row in fx_rows:
        events.append({
            'date': row['date'],
            'type': 'fx',
            'operation': row['operation'],
            'usd': float(row.get('usd_amount', 0) or 0),
            'brl': float(row.get('brl_amount', 0) or 0),
            'fx_rate': float(row.get('fx_rate', 0) or 0),
        })

    # Load USD orders
    orders = _load_csv(LEDGER_DIR / 'orders.csv', cut_date)
    for row in orders:
        if row.get('currency') != 'USD':
            continue
        events.append({
            'date': row['date'],
            'type': 'order',
            'side': row['side'],
            'ticker': row['ticker'],
            'quantity': float(row.get('quantity', 0) or 0),
            'price': float(row.get('price', 0) or 0),
            'total': float(row.get('total', 0) or 0),
        })

    # Load USD proventos (dividends)
    proventos = _load_csv(LEDGER_DIR / 'proventos.csv', cut_date)
    for row in proventos:
        if row.get('currency') != 'USD':
            continue
        events.append({
            'date': row['date'],
            'type': 'provento',
            'ticker': row['ticker'],
            'amount_usd': float(row.get('net_value', 0) or 0),
        })

    # Sort by (date, intra-day tier) — inflows before outflows within a
    # date; stable sort preserves file order within the same tier.
    events.sort(key=lambda e: (e['date'], _intraday_tier(e)))
    return events


def apply_event(state: FXState, evt: dict) -> None:
    """Apply a single event from load_events to the FX state."""
    if evt['type'] == 'fx':
        if evt['operation'] == 'transfer_in':
            state.process_transfer_in(evt['usd'], evt['fx_rate'])
        elif evt['operation'] == 'transfer_out':
            state.process_transfer_out(evt['usd'])

    elif evt['type'] == 'order':
        if evt['side'] == 'C':
            state.process_buy(evt['ticker'], evt['date'],
                              evt['quantity'], evt['price'])
        else:
            state.process_sell(evt['ticker'], evt['quantity'])
            # Add proceeds back to USD balance
            state.usd_balance += evt['total']

    elif evt['type'] == 'provento':
        # USD dividend: ticker-weighted FX, balance update, BRL record.
        state.process_provento(evt['ticker'], evt['date'], evt['amount_usd'])


def build_fx_state(cut_date: str = None) -> FXState:
    """Build FX state by processing all USD events chronologically.

    Reads avenue_fx.csv, USD orders, and USD proventos, sorts by
    (date, intra-day tier), and processes in order.
    """
    state = FXState()
    for evt in load_events(cut_date):
        apply_event(state, evt)
    return state


def _load_csv(filepath: Path, cut_date: str = None) -> list[dict]:
    if not filepath.exists():
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    if cut_date:
        rows = [r for r in rows if r.get('date', '') <= cut_date]
    return rows
