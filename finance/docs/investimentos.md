# Investimentos

Design documentation for the investment tracking system. Workflow infrastructure lives in `3-resources/tools/sb-os/finance/workflows/sb-bookkeeper/investimentos/`, ledgers in `.user/finance/bookkeeper/ledgers/investimentos/`, config in `.user/finance/bookkeeper/config/`.

> **This doc is partially outdated and scheduled for rewrite.** When this doc disagrees with the implementation, the implementation wins — ledger CSVs in `.user/finance/bookkeeper/ledgers/investimentos/`, parsers in `3-resources/tools/sb-os/finance/scripts/investimentos/parsers/`, and the dashboard documentation in `3-resources/tools/sb-os/finance/docs/financial-dashboard.md` are authoritative.

## Architecture

```
Spreadsheet CSVs (historical)     Source files (ongoing)
        │                                │
        ▼                                ▼
  import_*.py scripts              parsers/ (Phase 2)
        │                                │
        └──────────┬─────────────────────┘
                   ▼
         .user/finance/bookkeeper/ledgers/investimentos/
         ├── orders.csv          (variable income trades)
         ├── proventos.csv       (dividends, JCP, rendimentos)
         ├── balcao.csv          (fixed income + fund transactions)
         └── crypto.csv          (crypto trades)
                   │
                   ▼
            calculate.py (Phase 2)
                   │
                   ▼
            positions.json → Dashboard (Phase 3)
```

Ledgers are append-only CSVs. Each row has a `source` column identifying data origin. Position state is computed from ledgers on every run — never stored as authoritative data.

## Ledger Schemas

### orders.csv

| Column | Type | Description |
|--------|------|-------------|
| `date` | YYYY-MM-DD | Trade date |
| `side` | C/V | Compra or Venda |
| `ticker` | string | e.g. VALE3, BRK.B, NEXG11 |
| `quantity` | int | Number of shares/units |
| `price` | float | Unit price in original currency |
| `currency` | BRL/USD | Original currency |
| `total_brl` | float | Total in BRL |
| `total_original` | float | Total in original currency |
| `fees_exchange` | float | Bolsa/emolumentos |
| `fees_brokerage` | float | Corretagem |
| `fees_irrf` | float | IRRF on source |
| `broker` | string | clear/guide/safra/avenue |
| `asset_type` | string | acao/fii/etf/fiagro/opcao |
| `market` | string | vista/opcao_flexivel/opc |
| `source` | string | Data origin identifier |

### proventos.csv

| Column | Type | Description |
|--------|------|-------------|
| `date` | YYYY-MM-DD | Payment date |
| `type` | string | dividendo/jcp/rendimento/fracao |
| `ticker` | string | Asset ticker |
| `quantity` | float | Shares at ex-date |
| `value_per_unit` | float | Per-share value |
| `gross_value` | float | Gross total |
| `irrf` | float | IRRF withheld |
| `net_value` | float | Net received |
| `broker` | string | Broker ID |
| `source` | string | Data origin |

### balcao.csv

| Column | Type | Description |
|--------|------|-------------|
| `date` | YYYY-MM-DD | Settlement date |
| `operation` | string | aplicacao/resgate/juros/irrf/iof |
| `product_id` | string | Canonical ID from assets.json |
| `product_type` | string | cra/deb/lca/fia_br/fim_br/firf/di/tesouro/coe |
| `amount` | float | Positive=inflow, negative=outflow |
| `broker` | string | Broker ID |
| `source` | string | Data origin |

### crypto.csv

| Column | Type | Description |
|--------|------|-------------|
| `date` | YYYY-MM-DD | Trade date |
| `operation` | string | compra/venda/swap/recebimento/envio/rewards/referral |
| `buy_asset` | string | Asset received (BTC, ETH, BRL) |
| `buy_quantity` | float | Amount received |
| `sell_asset` | string | Asset given (BRL, BTC, ETH) |
| `sell_quantity` | float | Amount given |
| `price_brl` | float | BRL market value of the trade |
| `fee_pct` | float | Fee percentage |
| `fee_amount` | float | Fee value |
| `fee_currency` | string | Fee denomination |
| `exchange` | string | bipa/mercado_bitcoin/binance |
| `source` | string | Data origin |

## Config Files

### assets.json

Unified registry of all assets across 4 sections: `variable_income`, `fixed_income`, `funds`, `crypto`. Each asset is keyed by a canonical ID.

Fixed income and fund assets have an `aliases` array mapping bank statement names (formal, cryptic) to the user-friendly canonical name. Import scripts and parsers use alias matching to resolve product names.

### investment-sources.json

Broker/exchange configuration. Each source has: `name`, `type` (corretora/banco/exchange), `status` (active/closed/migrated). Migrated sources have `migrated_to` and `migration_date` fields.

## Design Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | 4 separate ledger CSVs | Different schemas per asset class |
| D2 | Append-only with source column | Auditable trail, re-import safe |
| D3 | aliases in assets.json | Central name mapping for fixed income |
| D4 | Broker migration in config | Historical data preserves original broker |
| D5 | Fixed income uses snapshots | Accrual not computable from transactions |
| D6 | Phase 1 import, Phase 2 parsers | Spreadsheet data already structured |
| D7 | Crypto buy/sell asset pair | Handles fiat↔crypto and crypto↔crypto |
| D8 | Crypto per-asset IRR in BRL, partitioned per (asset, exchange) | Flows from `crypto.csv:price_brl`; terminal = `quantity × current_price_brl` (exchanges quote BRL natively). `_build_position_flows` keys each crypto leg by the composite `"{asset}@{exchange}"` (exchange normalized: `bipa` → `bipa`; everything else → `mercado_bitcoin`) — matching the per-exchange position split in `position_calculator`. Keying by bare currency would hand every exchange-split position the currency's full flow history but only its partial terminal, producing double-counted flows and a strongly negative IRR bias (the BTC ×2 defect, 2026-06-05). `_build_position_entry` looks up a crypto position's flows by `f"{pos.id}@{pos.broker}"` (pos.broker carries the normalized exchange). XIRR label also uses the composite key. Each leg of a crypto↔crypto swap registers as a synthetic BRL flow at its implied BRL value. Resulting IRR reflects BRL-equivalent timing of swaps, not pure native-asset return — read with care for swap-heavy positions. |
| D9 | Per-asset IRR terminal anchored at snapshot date (balcão) | Balcão positions anchor the XIRR terminal at the snapshot's own `price_date`, not the cut date — cut-date anchoring implies 0% return across the staleness window and understates IRR (a 38-day-stale snapshot cost -36bp in the motivating case). Listed/crypto keep cut-date anchoring (prices fetched fresh at cut); portfolio + per-class IRR keep cut-date anchoring (mixed positions need one common anchor). |
| D10 | Per-asset IRR flows bridged across corporate renames | `_bridge_rename_flows` in `calculate.py` remaps per-ticker flows along the `conversao`/`incorporacao`/`fusao`/`cisao` chain so the surviving ticker carries the original cost history. Cisão splits flows dated on/before the action by `ratio_to / (ratio_from + ratio_to)` — the same fraction `_apply_corporate_action` applies to cost basis, so flows and cost stay consistent to the cent. Without bridging, renamed positions have no outflow under their own ticker and render `irr: null` (motivating cases: EMBJ3, AMOB3). **FM-3 reconciliation (D12):** the original D10 statement "Per-class IRR deliberately unbridged" is superseded by D12. Class-level flows ARE now bridged via the same `_bridge_rename_flows` call (bucketing is unaffected — old/new tickers bucket identically via assets.csv — but the D12 `current` variant's membership test requires pre-rename flows to appear under the surviving ticker). See "Per-Asset IRR Flow Bridging Across Renames (D10)" section for full details. |
| D11 | Stable FX fallback for closed-ticker USD flows | `get_ticker_fx_rate` falls back per-ticker lots → account `weighted_avg_rate` → `last_nonzero_avg_rate` (persisted by `process_transfer_out` at the moment a full repatriation zeroes the live average). Per-class IRR flow conversion (`_to_brl`, `calculate.py`) reaches FX 1.0 only when no `avenue_fx.csv` history exists at all, and then warns on stderr once per ticker — never silently. Pre-fix, a full liquidation+repatriation of the Avenue account would have silently converted every closed-ticker USD flow at FX 1.0 against a real BRL terminal (rv_eua chip +4,03% → +6,70% in the regression sim). |
| D12 | `summary.irr` carries two variants: all-time and current (approved 2026-06-05) | Eliminates survivors-vs-lifetime ambiguity found in the rv-eua TIR investigation — user sees both "how has my capital performed since inception" (all-time) and "how is what I hold today performing" (current). Extending the existing `summary.irr` store (ME gate [R] reuse — no new store). All-time semantics: money-weighted XIRR over every flow ever recorded, with three semantic changes vs the pre-D12 single variant: (a) balcão buckets include closed/matured/redeemed products (full flows, redemption is the natural terminal, no cut-date anchor needed); (b) balcão code-migration synthetic seeds are injected for EVERY migrated product, not only active ones; (c) class-level flows are bridged across corporate renames via `_bridge_rename_flows` (D10) before bucketing. Current variant: only flows belonging to open positions at the cut (position-scoped, not lot-scoped); `flow_count` differs; buckets with zero current flows emit `irr: null, flow_count: 0`. Bridging now matters at class level for the current-variant membership test (EMBR3 buys must count as flows of the open EMBJ3). **Supersedes the D10 statement "Per-class IRR deliberately unbridged"** — that statement is now false; see D10 FM-3 reconciliation note in the Design Decisions table and in "Per-Asset IRR Flow Bridging" section. |

## Source Data Reference

Source files (historical, archived) live in `4-archives/sb-os/finance-module/bookeeper/investments/historical-data/` (read-only reference):

| Folder | Content | Used by |
|--------|---------|---------|
| `ok-spreadsheet-data/` | 6 CSVs from Google Sheets (historical through ~Aug 2023) | Phase 1 import scripts |
| `ok-bipa-data/` | 3 Bipa CSV extratos (Jan 2024 → Apr 2026) | Phase 2 Bipa parser |
| `ok-safra-data/` | Safra Detalhes/Informe PDFs + brokerage notes | Phase 2 Safra parser |
| `ok-xp-data/` | XP account statement CSV (Nov 2023 → Apr 2026) | Phase 2 one-time import |
| `ok-avenue-data/` | Avenue trade confirmation PDFs | Phase 2 (low priority) |
| `avenue-historical-fx/` | 21 Recibos/Contratos de Câmbio PDFs (2020-10 → 2024-03) + parsed `processed/avenue_fx.csv` | `avenue_fx.py` parser → `avenue_fx.csv` ledger |
| `avenue-app-activity-2026-06/` | Avenue app activity screenshots (Jan–Mar 2024) | Evidence for the 2026-06 `orders.csv` date corrections + USD balance validation |
| `print-screens/` | Spreadsheet screenshots for reference | Design reference |

Additional archived source outside `historical-data/`: `4-archives/personal/finance/avenue-investment-extracts-2021-2022/` — 7 Avenue "Conta de Investimentos" statement CSV exports (Data transação, Data liquidação, Descrição, Valor, Saldo) covering 2020-10 → 2023-12 with no gaps.

**USD dividends (Avenue) — reconciled and closed.** The USD dividend history is a closed set: no current USD holding pays dividends (last payer ICLN sold 2024-01-05). On 2026-06-03 all USD provento rows were reconciled against the statement CSVs above: 3 duplicate rows deleted (Jan-2021 phantoms of the Jan-2022 payments), 1 ticker corrected (2022-01-03 US$ 54.58 was a blank-ticker credit in the statement, attributed to KWEB — the only unaccounted distribution-payer; the manual entry had mis-attributed it to BRK.B, which pays no dividends), 1 missing payment added (CVS 2022-08-02), and `gross_value`/`withholding_tax` populated from the statements' gross + imposto lines (previously gross=net, wh=0). The 30 surviving USD rows are statement-verified; new USD dividends only become possible if a dividend-paying US asset is bought again — in that case parse the statement CSV export rather than manual entry.

## Broker Migration

Guide Investimentos was acquired by Safra. All Guide positions migrated to Safra during 2024. In ledger data, historical transactions preserve `broker: guide`. The position calculator (Phase 2) resolves `guide` → `safra` for positions after the migration date.

## Corporate Actions

`corporate_actions.csv` schema: `date,action_type,ticker,new_ticker,ratio_from,ratio_to,broker,source,notes`.

`action_type` enum:

| Value | Meaning | Effect on position |
|-------|---------|--------------------|
| `grupamento` | Reverse split | `quantity *= ratio_to / ratio_from`, cost unchanged |
| `desdobramento` | Forward split | Same as grupamento |
| `bonificacao` | Bonus shares | `quantity *= (1 + ratio)`, cost unchanged |
| `conversao` | Ticker rename / merger conversion | Move qty + cost to `new_ticker` using ratio, zero out original |
| `incorporacao` | Merger (absorbed company) | Same as conversao |
| `fusao` | Merger (new entity) | Same as conversao |
| `cisao` | Spin-off | Split qty and cost between original and `new_ticker` |
| `expiracao` | Option / subscription right expired worthless | Zero quantity. Cost stays, realized as loss. Use `ratio_from=1, ratio_to=0`. |

Position calculator interleaves orders + corporate_actions chronologically (orders first on same date, actions with tiebreak=1).

After every corporate action, positions with `type ∈ {acao, opcao, direito_subscricao, bdr, fii}` are **floored** to integer shares. B3 does not issue fractional shares — any fractional residue produced by a ratio (e.g. cisão 1.151363666, grupamento 50:1) is auctioned and the proceeds credited as cash via a `Fração em Ativos` or `Leilão de Fração` proventos row. Both route to proventos with `type=fracao`; neither affects qty. Example: VAMO3→AMOB3 cisão 1500×1.151363666=1727.045, B3 credits 1727 + auctions 0.045 (cash); later grupamento 50:1 gives 1727/50=34.54, B3 credits 34 + auctions 0.54 (cash) — final AMOB3 qty = 34, fraction proceeds visible as two `fracao` rows on the proventos ledger.

### Per-Asset IRR Flow Bridging Across Renames (D10)

Orders and proventos record flows under the ticker of the day. After a rename, the surviving position's flow list lacks the original cost chain (EMBJ3 sees only post-rename flows; the buys live under EMBR3), so `compute_xirr` returns `None` for want of an outflow. `_bridge_rename_flows` (`calculate.py`, called at the end of `_build_position_flows`) remaps flows so per-asset XIRR sees the full chain:

| Action | Flow treatment |
|--------|----------------|
| `conversao` / `incorporacao` / `fusao` (with `new_ticker`) | The old ticker's ENTIRE flow history moves to the new ticker — the old position ceases to exist, so every flow recorded under it belongs to the same economic position. |
| `cisao` (with `new_ticker`) | Flows dated **on/before** the action date split between parent and spin-off: `ratio_to / (ratio_from + ratio_to)` to the spin-off, complement stays — the SAME fraction `_apply_corporate_action` applies to cost basis, so flows and cost basis tell one story (AMOB3's bridged buys sum exactly to its split cost basis). Flows after the action date stay with whichever ticker recorded them. |
| `grupamento` / `desdobramento` / `bonificacao` / `expiracao` / `ajuste` | No `new_ticker`, no flow impact — skipped. |

Actions apply chronologically, so multi-hop chains (A→B→C) land on the final ticker. A cisão row with unfilled ratios (`ratio_from`/`ratio_to` ≤ 0, flagged for research) is skipped, mirroring the position calculator's guard.

**Scope.** Per-asset IRR and per-class IRR. `_bridge_rename_flows` is called before `_compute_portfolio_irr` bucketing (D12). Bucketing is unaffected — old/new tickers resolve to the same bucket via assets.csv — but the D12 `current` variant's membership test must see pre-rename flows under the surviving ticker (EMBR3 buys count as flows of the open EMBJ3). The original D10 statement "Per-class IRR deliberately unbridged" is superseded by D12; bridging at class level is not a no-op once a `current`-only filter is applied. Closed renamed positions (e.g. ARZZ3→AZZA3, fully sold) get bridged flow lists too, but produce no position entry, so nothing renders in the `current` variant.

### Currency Model (Variable Income & Crypto)

`portfolio.json` emits per-position money fields in two parallel shapes:

| Field | Currency | Source |
|-------|----------|--------|
| `current_price` | native (USD for Avenue, BRL for B3 / BR crypto) | yfinance/brapi/CoinGecko return in local currency |
| `avg_cost` | native | `cost_basis / quantity` |
| `cost_basis` | native | sum of order totals in native currency (USD for Avenue orders) |
| `current_value` | native | `quantity × current_price` |
| `pnl_absolute` | native | `current_value − cost_basis` |
| `total_dividends`, `total_dividends_ttm` | native | summed from proventos (native) |
| `cost_basis_brl` | BRL | FX engine (historical weighted FX per ticker) with live USD/BRL fallback |
| `current_value_brl` | BRL | `current_value × spot_usd_brl` for USD positions; same as `current_value` for BRL |
| `pnl_absolute_brl` | BRL | `current_value_brl − cost_basis_brl` |
| `total_dividends_brl` | BRL | `total_dividends × spot_usd_brl` for USD positions |

Consumers aggregating across currencies (dashboards, reports) MUST read the `*_brl` variants. Per-position displays SHOULD read native fields so the user sees the unit they actually bought in.

**FX engine event ordering.** `fx_engine.build_fx_state` replays `avenue_fx.csv` + USD orders + USD proventos sorted by `(date, intra-day tier)`. Tiers process inflows before outflows within a date — `transfer_in` (0), provento (1), sell (2), buy (3), `transfer_out` (4) — because same-day settlement at the broker is atomic. Without tiers, CSV row order could process a buy before same-day sells and produce a false-negative USD balance dip (observed 2022-07-15).

**Closed-ticker FX fallback (per-class IRR, D11).** Flows of tickers with no active lots (the closed 2021-22 Avenue cohort) convert via `get_ticker_fx_rate`'s fallback chain: per-ticker weighted lots → account-level `weighted_avg_rate` → `FXState.last_nonzero_avg_rate`. The last is persisted by `process_transfer_out` at the moment a full repatriation exhausts the transfer tranches and zeroes the live average (a transfer_out backed by sale proceeds can exceed the outstanding tranche total), so closed-ticker flows keep a stable historical rate after the USD account closes. If no rate exists anywhere (empty `avenue_fx.csv` while USD flows exist), `_to_brl` (`calculate.py`) converts at 1.0 and warns on stderr (`[irr_calculator] class-flow FX: …`), once per ticker per run — a degenerate conversion is never silent. Trailing USD proventos received after a full repatriation convert at the same persisted rate.

### Crypto Per-Asset IRR

Per-asset XIRR for crypto positions is computed in **BRL**, per **(asset, exchange)** pair — matching the per-exchange position split in `position_calculator`.

**Flow partitioning by composite key.** `_build_position_flows` keys each crypto leg by `"{asset}@{exchange}"` (exchange normalized via `_normalize_crypto_exchange`: `bipa` stays `bipa`; `binance`, `mb`, and any other value map to `mercado_bitcoin`). `_build_position_entry` looks up flows by `f"{pos.id}@{pos.broker}"` — `pos.broker` carries the normalized exchange for crypto positions. Keying by bare currency (`BTC`) would hand every exchange-split position the currency's full flow history but only its partial terminal, producing double-counted flows and a strongly negative IRR bias. The composite key partitions flows correctly to their exchange-split position.

**Convention.** Each crypto trade leg in `crypto.csv` carries a `price_brl` field captured at the moment of the trade. `_build_position_flows` registers each leg as a synthetic BRL cash flow at that implied BRL value. Terminal value is `quantity × current_price`, where current price is fetched in BRL from CoinGecko (crypto exchanges in Brazil quote natively in BRL). Both flows and terminal are BRL → XIRR is currency-consistent.

**Inter-exchange transfer convention (envio/recebimento).** A transfer row (`operation ∈ {envio, recebimento}`) with `price_brl` set registers as a synthetic sale at the sender position and a synthetic purchase at the receiver position, both at the transfer-date BRL mark. The two legs cancel at currency/bucket level — a transfer is never a BRL entry/exit of the asset as a whole. No such rows exist in the ledger today; this is the convention for when they appear.

**Unpriced-row warning.** A non-`ajuste` crypto row with `price_brl <= 0` carries no flow. For each affected `(asset, exchange)` pair, `calculate.py` emits one warning per run to stderr (format: `[irr_calculator] crypto unpriced: BTC@bipa — N non-ajuste row(s) with price_brl<=0 carry no flow; per-exchange IRR may be skewed`). `ajuste` rows are intentional quantity-only adjustments and remain silent. Current ledger state: BTC@bipa has 4 early-2024 rows (~0.000332 BTC total) with `price_brl<=0`; these are immaterial and the warning is expected.

**What this measures and what it doesn't.**

| Captures | Does NOT capture |
|----------|------------------|
| BRL-equivalent timing of buys, sells, and inter-asset swaps | Pure native-asset return (BTC-on-BTC, ETH-on-ETH) |
| BRL appreciation/depreciation of the holding through both price and FX | Performance separated from BRL/USD or BRL/native FX moves |
| Realized P&L on positions that have been swapped or liquidated | — |

A heavy swap history (e.g. BTC→ETH→USDT→BTC) produces a per-asset IRR that reflects when BRL value entered and left the asset, not how the underlying coin performed against itself. This is intentional: the user funds the portfolio in BRL and consumes it in BRL, so BRL is the IRR currency of record.

**Why not native-asset IRR.** A native-asset XIRR would require capturing every leg in the asset's own units, with terminal in the same units. Inter-asset swaps would need to register as zero-sum events (out in coin A, in in coin B at swap parity), which destroys the relationship between flows and BRL. The result would only be meaningful for positions that are never swapped — a tiny subset of activity. Out of scope.

**Aggregate (per-class) crypto IRR.** Mirrors per-asset: BRL flows, BRL terminal. The `crypto` bucket in both `summary.irr.per_class` (all-time) and `summary.irr.current.per_class` (open positions only) is therefore a true BRL return on crypto exposure. Crypto tickers from `crypto.csv` are forced into the `crypto` bucket regardless of `assets.csv` coverage, preserving the prior behavior where crypto legs never fall into `other`.

**Per-bucket vs per-asset residual (gate_10).** The crypto bucket's all-time IRR (+27.40% cut 2026-06-05) diverges materially from the simple average of per-asset per-exchange IRRs (+9.93%), a 17.46pp delta. This residual is **structural and expected** — same survivorship-composition pattern as `rv_br`:

- The `crypto` per-class bucket is a lifetime money-weighted XIRR over the whole crypto class, including the fully liquidated alt-coin cohort (ETH/XRP/BNB/USDT/NMR/STX/ADA/DOT/LINK swaps and sales, realized gains, zero terminal at the cut).
- The per-asset simple average covers only the two surviving BTC per-exchange positions (BTC@mercado_bitcoin, BTC@bipa), equal-weighted.

The `current` variant eliminates this gap: `summary.irr.current.per_class.crypto` equals the XIRR over merged BTC flows with total BTC terminal (+9.52% verified cut 2026-06-05), matching the simple average of the two surviving positions. The 17.46pp divergence is not a data defect — `gate_bucket_divergence` (gate #10) handles it automatically: `crypto` is an **informational bucket** in that gate (module constant `_INFORMATIONAL_BUCKETS`). Its section and divergence still print (marked "informational — not counted") but NEVER trigger a gate failure. No manual acceptance step is required.

### rf_balcao IRR Band and Band Exemptions (gate_9)

`gate_irr_sanity.py` (gate #9) applies a **strict band check** on every rf_balcao position: an annualized IRR outside the configured band `[expected_return_pct_min, expected_return_pct_max]` (default 7–15%, read from `investment_rules.sanity_bands.rf_balcao` in `standing-rules.yaml`) is a gate failure — exit 1, auto-halt before snapshot.

**Band exemptions.** Legitimate mark-to-market cases whose current IRR falls outside the band for a documented structural reason are registered in `investment_rules.sanity_bands.rf_balcao.band_exempt_ids` (a list of `{id, reason}` entries in `standing-rules.yaml`). Exempt positions:

- **Skip the band check only** — they are never counted as a band violation.
- Print a visible `EXEMPT` note when their IRR is outside the band (the skip is loud, never silent).
- **Still subject to the strict checks** — `|irr| > 200%` and `irr_quality` missing on a valued balcão position still fail for exempt positions.

Current exempt ids (2026-06-05): `cra_ipca_klabin_350`, `deb_neoenergia_370`, and the Marfrig CRA — all Oct/2019-vintage papers bought at the real-rate cycle low and marked today on a ~7.8% real curve, producing IRRs verifiably below 7% by construction.

The audit event `trigger_context.band_exempt_skips` records how many exemptions fired on each gate run.

### Per-Asset IRR Terminal Anchoring (Balcão)

Snapshot-valued (balcão) positions anchor the per-asset XIRR terminal at the snapshot's own `price_date`, not at the cut date (D9).

**Why.** The terminal value IS the snapshot value — dated information. Anchoring it at the cut date stretches the same value across the staleness window, implying 0% return over `snapshot_age_days` and understating IRR; the staler the snapshot, the bigger the drag. Motivating case: a CRA at cut with a 38-day-stale snapshot reported 4.41% under cut-date anchoring vs 4.77% at the snapshot date.

**Semantics.** A balcão position's `irr` reads as "XIRR through its latest mark" and does not change with the cut date while the underlying data is unchanged. A flow dated after the snapshot (e.g. a coupon between snapshot and cut) still enters the flow list — XIRR handles unordered dated flows; the terminal stays at the snapshot date.

**Scope.** Listed and crypto positions keep the cut-date anchor — their prices are fetched fresh at the cut, so terminal date = cut date is exact. Portfolio-level and per-class IRR (`summary.irr.total`, `summary.irr.per_class`, and the D12 `summary.irr.current` variants) also keep cut-date anchoring: they mix positions with different snapshot dates and need one common terminal anchor; per-class terminals sum `current_value_brl` at the cut. For the `current` variant, `terminal_value` per bucket is shared with the all-time variant (only open positions carry value at the cut).

### Per-Class IRR Buckets and the `'other'` Discard

`_irr_class_bucket` (`calculate.py`) maps every ticker/product_id to one of the 5 class buckets — `rv_br`, `rv_eua`, `rf_balcao`, `fundos`, `crypto` — from its assets.csv metadata (`asset_class`, `type`, `currency`). An id that resolves to none of the five (almost always a ticker missing from assets.csv) falls into `'other'`, and `_compute_portfolio_irr` DROPS the `'other'` bucket from `summary.irr.per_class` — those flows still count in the portfolio-level IRR, but vanish from the class breakdown.

Because that discard is silent by construction, `calculate.py` emits a stderr warning per offending ticker when building `flows_by_class`, in the `[irr_calculator]` pattern: `class:other: {ticker} — N flow(s) totalling R$ X` — with a small materiality threshold (`_IRR_OTHER_WARN_MIN_ABS_BRL`, R$ 50 absolute total per ticker) so cent-sized residues don't add noise. Motivating case: the AZZA3 leak — 8 tickers absent from assets.csv kept R$ 5k+ of flows out of `rv_br` for months with no signal (2026-06-05). Fix path for a warned ticker: add it to assets.csv via `upsert_assets.py` and regenerate.

### Summary IRR — Two Variants (D12)

`portfolio.json` `summary.irr` carries two variants sharing the same bucket structure (`rv_br`, `rv_eua`, `rf_balcao`, `fundos`, `crypto`):

#### Schema

```json
{
  "summary": {
    "irr": {
      "total": 0.1081,
      "per_class": {
        "rv_br":     { "irr": 0.0543, "terminal_value": ..., "flow_count": 1306 },
        "rv_eua":    { "irr": 0.0398, "terminal_value": ..., "flow_count": 86 },
        "rf_balcao": { "irr": 0.1189, "terminal_value": ..., "flow_count": 90 },
        "fundos":    { "irr": 0.1416, "terminal_value": ..., "flow_count": 24 },
        "crypto":    { "irr": 0.2742, "terminal_value": ..., "flow_count": 88 }
      },
      "current": {
        "total": 0.1173,
        "per_class": {
          "rv_br":     { "irr": 0.2944, "terminal_value": ..., "flow_count": 156 },
          "rv_eua":    { "irr": 0.0750, "terminal_value": ..., "flow_count": 14 },
          "rf_balcao": { "irr": 0.0838, "terminal_value": ..., "flow_count": 47 },
          "fundos":    { "irr": 0.1416, "terminal_value": ..., "flow_count": 24 },
          "crypto":    { "irr": 0.0955, "terminal_value": ..., "flow_count": 32 }
        }
      }
    }
  }
}
```

`total` and `per_class` are the legacy (all-time) keys — shape unchanged. `current` is the new block added by D12, mirroring the legacy shape exactly. Snapshots without `summary.irr.current` are legacy portfolios; consumers check for key presence.

#### All-time variant (`summary.irr.total` + `summary.irr.per_class`)

Money-weighted XIRR over every flow ever recorded. Three semantic changes landed with D12:

| Semantic change | Detail |
|----------------|--------|
| Balcão buckets include closed products | Closed/matured/redeemed products' full flows are included. Redemption is the natural terminal — closed positions' flows balance themselves; no cut-date terminal anchor is needed. |
| Balcão code-migration seeds for all migrated products | Synthetic seeds injected for every migrated product (same convention as per-asset path), not only active ones. |
| Class-level flows bridged across corporate renames | `_bridge_rename_flows` (D10) applies before bucketing. Bucketing is unaffected (old/new tickers resolve to the same bucket via assets.csv), but the current-variant membership test requires pre-rename flows under the surviving ticker. |

#### Current variant (`summary.irr.current`)

XIRR over flows whose rename-bridged ticker/product_id belongs to an open position in the cut's position entries. Eliminates survivors-vs-lifetime ambiguity.

| Rule | Detail |
|------|--------|
| Position-scoped, not lot-scoped | A partial sell of an open position keeps that position's flows in scope. |
| `terminal_value` per bucket | Shared with the all-time variant — only open positions carry value at the cut. |
| `flow_count` | Differs from all-time (only open-position flows counted). |
| Zero-flow bucket | Emits `irr: null, flow_count: 0`. |
| Crypto forced to `crypto` bucket | Crypto tickers from `crypto.csv` land in `crypto` regardless of `assets.csv` coverage. |
| Legacy fallback | Portfolios without `summary.irr.current` render without "current" display — no `irr: null` injection needed. |

#### Verified reference values (cut 2026-06-05)

| Bucket | All-time | Current | All-time flows | Current flows |
|--------|----------|---------|----------------|---------------|
| total | +10.81% | +11.73% | — | — |
| rv_br | +5.43% | +29.44% | 1306 | 156 |
| rv_eua | +3.98% | +7.50% | 86 | 14 |
| fundos | +14.16% | +14.16% | 24 | 24 |
| rf_balcao | +11.89% | +8.38% | 90 | 47 |
| crypto | +27.42% | +9.55% | 88 | 32 |

`rf_balcao` current (47 flows / +8.38%) reproduces the previous active-only chip exactly, confirming semantic continuity for that bucket.

### Yield on Cost (YoC)

`portfolio.json` emits two YoC fields per variable-income position, both computed against `cost_basis` so they work without live prices:

| Field | Formula | What it measures |
|-------|---------|------------------|
| `yoc_lifetime` | `sum(income_proventos) / cost_basis` | Cumulative cash yield on invested capital since first purchase. Grows monotonically with holding period — not comparable across positions with very different tenures. |
| `yoc_ttm` | `sum(income_proventos in last 365 days before cut_date) / cost_basis` | Running yield over the trailing 12 months. Comparable across positions. For positions held <12 months, shows partial-period yield (no annualization). |

Income proventos = `type ∈ {dividendo, jcp, rendimento, juros, bonificacao_dinheiro}`. Excludes `fracao` (cash from auctioned fractional residues — not investment income).

`cost_basis` is in the position's native currency; `total_dividends` is summed from `net_value` on proventos rows. For USD positions, both numerator and denominator are USD — YoC is currency-consistent by construction.

No separate `dividend_yield` field (TTM yield / current price) is emitted — it would require live prices and the two YoC flavors above satisfy the user's need for a price-independent metric.

### Price Fetching

`price_fetcher.py` populates `current_price`, `price_date`, and `price_changes` on each variable-income and crypto position. Strategy:

| Asset class / type | Primary source | Fallback | Notes |
|--------------------|---------------|----------|-------|
| `variable_income` BRL (B3) | yfinance with `.SA` suffix | brapi.dev | One library for both markets simplifies code paths. |
| `variable_income` USD (Avenue) | yfinance bare ticker | — | Multi-class tickers normalized: `BRK.B` → `BRK-B`. |
| `crypto` | CoinGecko (BRL quote) | — | Prices returned in BRL. |
| `type=opcao` | **skip** | — | No reliable free API for B3 options. Always `price_source="missing"`. |
| `type=direito_subscricao` | **skip** | — | No reliable free API for subscription rights. Always `price_source="missing"`. |
| `fixed_income` / `funds` | — | — | Handled via balance snapshots, not API (see Tier A/B/C strategy in plan). |

`price_changes` windows (1d / 30d / 90d / 180d / 365d / YTD) come from 13 months of yfinance daily closes with `auto_adjust=True`. Calendar-day lookups (nearest trading day ≤ target). Brapi fallback provides only `1d`. Missing windows are omitted from the dict, not zero-filled.

Market indicators (`IBOVESPA`, `SP500`, `USD_BRL`, `BTC_BRL`) fetched via yfinance in a single batch call.

### Balance Snapshot Import (Tier A)

`balance-snapshots.csv` (schema: `date,product_id,balance,source`) holds month-end valuations for fixed income and funds. The position calculator joins each position to its latest snapshot to populate `current_value`, `price_source='snapshot'`, and `price_date`.

`import_balance_snapshots.py` is the entry point. It runs a parser against a source statement and writes three downstream effects with idempotent dedup:

| Output | Target ledger | Dedup key |
|--------|---------------|-----------|
| `balance_snapshots` (from "Saldo Atual" rows) | `balance-snapshots.csv` | `(date, product_id)` |
| `balcao` (real transactions like Aplicação/Resgate) | `balcao.csv` | `(date, operation, product_id, amount)` |
| `balcao_seeds` (synthetic carry-forward from "Saldo Anterior") | `balcao.csv` | applied ONLY when the product has no balcao history dated strictly before the seed date — bootstraps cost basis for funds that pre-date our visibility window |

Seed semantics: a "Saldo Anterior" row represents the carrying balance at the statement's start. For a fund first seen mid-2026, the only honest cost-basis baseline available is that opening balance. Seeds use `source='safra_fundos_seed'` so they're distinguishable in the ledger.

Currently wired parsers:

| Parser | Source | Outputs |
|--------|--------|---------|
| `safra_fundos` | Safra fund statement CSV (block-per-fund format) | `balcao` (real Aplicação/Resgate), `balance_snapshots` (Saldo Atual rows), `balcao_seeds` (Saldo Anterior carry-forward, applied only when no prior history predates the seed), `assets` (fund metadata: name, type, cnpj, manager) |
| `safra_titulos` | Safra fixed income titles CSV ("Títulos Renda Fixa - Emissão própria e de terceiros") | `balance_snapshots`, `balcao_seeds` (real Data Aplicação as the seed date — honest cost basis), `assets` (RF metadata: issuer, indexer, rate, indexer_pct, application_date, maturity_date) |

Future broker statements add their own parsers and register under `PARSERS` in `import_balance_snapshots.py`.

### RF and Fund Metadata in `assets.csv`

`assets.csv` (master registry at `.user/finance/bookkeeper/data/assets.csv`) is the single source of truth for all asset metadata. Class-specific columns coexist with empty values for non-applicable rows. Decision 2026-04-26: `asset_info.csv` retired — see plan §Scope changes (assets / asset_info consolidation).

| Column | Class | Use |
|--------|-------|-----|
| `issuer` | RF | Emissor / Devedor (e.g., "REDE D OR SAO LUIZ S A") |
| `indexer` | RF | `CDI`, `IPCA`, `PRE`, `SELIC` |
| `rate` | RF | Spread/coupon rate (e.g., `1.2`, `4.35`) |
| `indexer_pct` | RF | % do indexador (`100` for "100% CDI", `0` for prefixed) |
| `application_date` | RF | Data Aplicação (YYYY-MM-DD) |
| `maturity_date` | RF | Vencimento / Repactuação (YYYY-MM-DD) |
| `cnpj` | Funds | CNPJ (XX.XXX.XXX/XXXX-XX) |
| `manager` | Funds | Gestora |

`calculate.py` passes RF fields through to `portfolio.json` for any position with at least one populated RF metadata field.

**Write paths for `assets.csv`.** Two write paths feed `assets.csv`:

1. **Parser-side (automated, during import):** parsers that output asset metadata (e.g., `safra_fundos_movimentacoes.py`, `safra_rf_movimentacoes.py`) call the internal `upsert_assets()` helper in `import_balance_snapshots.py`, which merges new metadata by `id` and preserves existing values.
2. **Agent-side (standalone, registered tool):** `upsert_assets.py` (`scripts/investimentos/upsert_assets.py`) is the canonical agent-side write path for asset-metadata rows. It accepts an input CSV in the destination schema, defaults to `--dry-run`, and requires explicit `--apply` to write. It enforces field-ownership via `_field_ownership.yaml` + `lib/field_ownership.py`: `curated` fields (e.g., `name`, `active`, `sector`) are insert-only for parsers and agent actors (never overwritten on update by them); the reserved `user` actor (`--actor user`) may update curated fields under explicit user direction (e.g. `upsert_assets.py <csv> --actor user --apply`); `source_bound` fields are parser-owned regardless of actor and are NOT unlocked by `actor=user`; `derived` fields are overwritable. Unknown input columns trigger a `field_ownership_unknown` audit event and abort. On `--apply`, emits `track_write` + `docs_potentially_stale` audit events and writes atomically with rows sorted alphabetically by `id`.

`name` is a `curated` field (enforced by `_field_ownership.yaml`): parsers populate it on first registration (using whatever raw label the broker statement provides), but subsequent re-imports never overwrite it. To correct a name, run `upsert_assets.py <csv> --actor user --apply` — the `user` actor is the only actor permitted to update curated fields on existing rows; do not edit `assets.csv` directly for tool-managed rows, and never touch parsers. Suggested RF naming convention: `{Tipo} {Emissor}` where Tipo ∈ {`Deb. Inc.` (incentivada), `Deb.` (comum), `CRA`, `CRI`, `LCA`, `LCI`}, Emissor capitalized without `S/A` / `S.A.` / `Ltda` suffixes. For CRAs issued through securitizadoras (Eco, Vert, Virgo), use the underlying devedor — not the securitizadora.

### Options and Subscription Rights

Agents processing B3 extracts must identify options and subscription rights to generate `expiracao` entries when no sale appears by expiration date.

#### Standard Option Code Structure

Format: `AAAAXNN` (5 letters + 2 digits, 7 chars) — for very liquid underlyings with short tickers, `AAAAAXNN` (6 + 2 = 8) or longer variants occur.

| Segment | Meaning |
|---------|---------|
| First 4–5 letters | Underlying asset base (same as spot ticker root, e.g. `PETR`, `VALE`, `BBDC`, `SIMH`) |
| Series letter (one letter after base) | Encodes call/put + expiration month (table below) |
| Trailing digits | Strike price × 10 or × 100 depending on the series; typically `strike_reais = digits / 100` for strikes under R$100 |

#### Series Letter → Month + Type

| Letter | Call (compra) | Put (venda) |
|--------|---------------|-------------|
| A | Jan | — |
| B | Feb | — |
| C | Mar | — |
| D | Apr | — |
| E | May | — |
| F | Jun | — |
| G | Jul | — |
| H | Aug | — |
| I | Sep | — |
| J | Oct | — |
| K | Nov | — |
| L | Dec | — |
| M | — | Jan |
| N | — | Feb |
| O | — | Mar |
| P | — | Apr |
| Q | — | May |
| R | — | Jun |
| S | — | Jul |
| T | — | Aug |
| U | — | Sep |
| V | — | Oct |
| W | — | Nov |
| X | — | Dec |

#### Expiration Day

Standard monthly options expire on the **third Monday of the series month**. If that Monday is a B3 holiday, expiration rolls to the next business day.

#### Examples

| Code | Parsed |
|------|--------|
| `PETRI34` | PETR call, Sept expiration, strike R$34.00 |
| `VALEO48` | VALE put, March expiration, strike R$48.00 |
| `BBDCF26` | BBDC call, June expiration, strike R$26.00 |
| `SIMHA600` | SIMH call, January expiration, strike R$6.00 (600 / 100) |

#### Year Inference

The ticker itself does NOT encode the year — only the month. When classifying an options trade, infer the year as follows:

1. Start from the trade date.
2. Find the next occurrence of the series month that is ≥ trade month.
3. If that month has already passed for the trade date's year, roll to the next year.

Example: `SIMHA600` bought on 2024-09-25. Series A = January. Next January after Sep 2024 = Jan 2025. Expiration = 3rd Monday of January 2025 = **2025-01-20**.

#### Subscription Rights & Warrants (not options)

Codes like `EMBRG730W4`, `NEXG12`, `SIMH1`, `VAMO1`, `GMAT1` are NOT options — they are subscription rights, receipts, or interim tickers.

| Pattern | Meaning |
|---------|---------|
| `{UNDERLYING}1` | Subscription right (direito de subscrição) — temporary ticker giving right to buy new shares at a set price. Trades briefly, then exercised or expires. |
| `{UNDERLYING}2` | Subscription receipt (recibo de subscrição) — issued after exercise, later converted to the common ticker. |
| `{UNDERLYING}G{DIGITS}W{DIGIT}` | Subscription warrant / bonus-in-shares right (direito de bonificação). Trades briefly, then exercised or expires. |
| `{UNDERLYING}E{DIGITS}` | Subscription receipt (recibo de subscrição em dinheiro), e.g. `EMBJE780`. Later converted to the common ticker. |

These instruments ALWAYS resolve to one of: exercised into the underlying (corporate action = `conversao`), expired worthless (corporate action = `expiracao`), or sold on the market (regular `V` order).

#### Operational Use

When processing B3 extracts:

1. Classify any ticker matching `AAAA+[A-X]+NN` as `asset_type=opcao`.
2. Classify subscription rights/warrants as `asset_type=direito_subscricao`.
3. If an option or subscription right appears in `orders.csv` with only a `C` (buy) and no matching `V` (sell) by expiration date + 1 business day, append an `expiracao` row to `corporate_actions.csv` with `ratio_from=1`, `ratio_to=0`, dated on the expected expiration.
4. `position_calculator.py` handles `expiracao` by zeroing `quantity` and `cost_basis` (cost realized as loss).
