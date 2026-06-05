# Data Model — Expenses Redesign (2026-05)

> **Status:** In build per `1-projects/finance-automation/expenses-redesign/expenses-redesign-plan.md` (Phase 1, task `p1-1`).
> **Authoring convention:** This file is the SINGLE SOURCE OF TRUTH for the new schema. Every Phase 2+ consumer (categorize.py, normalize.py, lib/* modules, bookkeeper workflow steps, dashboard, backfill workflow) reads this file. No consumer redefines schema — they reference here.
> **Scope:** Gastos (expenses) only. Investments (`investimentos/`, `inv-*.js`) are out of scope.

---

## 1. CSV Schema (categorized output)

The categorized CSV (`.user/finance/bookkeeper/ledgers/fechamento/{YYYY-MM}/transactions.csv`) is the contract between `categorize.py` (and the one-shot `backfill.py`) and the dashboard. The new schema replaces the existing 16-column shape (12 normalized + 4 categorized) with **19 columns**: 12 normalized (unchanged), 3 retained from the previous categorized layer (`category`, `match_confidence`, `recurrence`), 4 new (`data_caixa`, `data_competencia`, `supplier_canonical`, `tags`), 1 dropped (`subcategory`).

### 1.1 Normalized columns (preserved from current schema, written by parsers)

| # | Column | Type | Source / Producer | Semantics |
|---|--------|------|-------------------|-----------|
| 1 | `date` | `YYYY-MM-DD` | parser → normalize.py | Original transaction date as reported by the bank/parser. Equals incurred date for non-CC; equals purchase date for CC purchases; equals invoice payment date for CC invoice/fatura totals. **NOT a basis date** — `data_caixa` and `data_competencia` are derived from this plus context. Preserved for audit only. |
| 2 | `description` | string | parser | Original raw description from bank statement. Preserved verbatim (case + accents). |
| 3 | `amount` | float | parser | BRL value. Positive = credit/income, negative = debit/expense. Foreign-currency parsers convert to BRL using `exchange_rate`. |
| 4 | `balance` | float \| empty | parser | Running balance when bank provides it (extratos only). Empty for faturas. |
| 5 | `bank` | string | parser | `bank_id` from `banks.json` (e.g., `bradesco_extrato`, `santander_fatura`). |
| 6 | `source_type` | `extrato` \| `fatura` \| `Cash` | parser / agent | Source document class. `Cash` is set by the agent in step-05 for manual cash entries. |
| 7 | `currency` | ISO code | parser | `BRL` for native, `USD`/`EUR`/`PYG`/etc. for foreign. Default `BRL`. |
| 8 | `original_ref` | string \| empty | parser | Bank reference/document number when available. |
| 9 | `installment_current` | int \| empty | parser | Parcela atual (e.g., 3 of "3/7"). Empty for non-installment. |
| 10 | `installment_total` | int \| empty | parser | Total parcelas (e.g., 7 of "3/7"). Empty for non-installment. |
| 11 | `original_amount` | float \| empty | parser | Foreign-currency value before conversion (when `currency` ≠ BRL). |
| 12 | `exchange_rate` | float \| empty | parser | BRL per unit of foreign currency at the time of the transaction. |

### 1.2 Categorized columns (4 retained / 4 new / 1 dropped)

| # | Column | Status | Type | Source / Producer | Semantics |
|---|--------|--------|------|-------------------|-----------|
| 13 | `category` | retained | string | categorize.py + agent | Category from `categories.json` (e.g., `moradia`, `alimentacao`). Sentinel `a_identificar` when no match. Single value. |
| — | `subcategory` | **DROPPED** | — | — | Replaced by `tags` (cross-cutting, multi-value). Removed from new schema entirely. Old data is re-mapped by the backfill workflow. |
| 14 | `match_confidence` | retained | `exact` \| `partial` \| `none` | categorize.py | How the supplier was matched against `suppliers.json`. `exact` = full-string alias hit OR self-transfer/reimbursement/value-based layer fired; `partial` = substring alias hit; `none` = no alias matched. |
| 15 | `recurrence` | retained | `recorrente` \| `pontual` \| empty | categorize.py | Recurrence classification. Empty for `intercontas`/`ignorar`/`a_identificar`. |
| 16 | **`data_caixa`** | **NEW** | `YYYY-MM-DD` | accrual.py (via categorize.py) | **IMMUTABLE.** The day money actually moved. For non-CC: `= date`. For CC purchases (single or installment parcela): the invoice payment date of the invoice the parcela appears in (per-invoice, NOT per-purchase). For reimbursements: the day the reimbursement was received. NEVER mutated by code paths that compute `data_competencia`. |
| 17 | **`data_competencia`** | **NEW** | `YYYY-MM-DD` | accrual.py + agent (via step-05 review) | Analytical attribution date. Default = `data_caixa`. Auto-rules override only for CC: CC single → original purchase date (= `date`); CC installment → original purchase month (collapsed across all parcelas of that purchase, regardless of which invoice they appear in). Manual rules apply for reimbursements (cross-month) and movable boundary-day suppliers (Pass 2 of review queue). |
| 18 | **`supplier_canonical`** | **NEW** | string \| empty | suppliers.py (via categorize.py) | Normalized supplier name from `suppliers.json` longest-first/first-match-wins alias detection. Empty when no alias hit. **STORAGE LAYER NEVER HOLDS "Outros"** — the dashboard render layer applies the R$200 rolling-3-month rollup to "Outros" at presentation time only (T6). |
| 19 | **`tags`** | **NEW** | string (semicolon-separated) | tags.py + agent | Zero-or-more cross-cutting tags from `tags.json`. Representation: semicolon-separated tokens, no spaces around the separator. Empty string = no tags. Examples: `""`, `"tennis"`, `"tennis;reembolsavel"`, `"egito;trip-2026"`. **See §1.3 for representation decision.** |

### 1.3 Decision: `tags` column representation = semicolon-separated

**Choice.** Semicolon-separated tokens (e.g., `tennis;reembolsavel`).

**Alternatives considered.**

| Option | Pros | Cons |
|--------|------|------|
| JSON array (`["tennis","reembolsavel"]`) | Self-describing; tooling-friendly; unambiguous | Requires JSON-aware quoting in CSV (escaped quotes around the entire field); breaks naive `split(",")` consumers; the dashboard's existing `csv-parser.js` does not parse JSON-in-cells |
| Pipe-separated (`tennis\|reembolsavel`) | No CSV escaping needed | `\|` is rare but appears occasionally in raw bank descriptions; Markdown collisions when rendered in reports; user-facing field renders awkwardly |
| **Semicolon-separated (`tennis;reembolsavel`)** | **No CSV escaping needed; never appears in tag tokens (validated by `tags.py.is_valid_token`); legible in raw CSV; trivially split with `split(";")`** | Forbids `;` inside a tag token (acceptable — tag tokens are identifiers, kebab-case ASCII) |

**Rationale.** Smallest blast radius: works with the dashboard's existing CSV parser (`csv-parser.js` splits on `,` and respects quoted strings; semicolons inside an unquoted field pass through untouched), works with Python's `csv.DictReader` (default), and stays human-readable when grepping a CSV by hand. Reversibility is high — if a future case needs richer tag metadata (e.g., per-tag confidence, source pass), we add a sidecar column `tags_meta` rather than reshape `tags`. **Hard rule:** tag tokens MUST be lowercase kebab-case ASCII and MUST NOT contain `;` — enforced by `tags.py.is_valid_token` (see §5.3).

---

## 2. Dictionary: `categories.json`

**Path:** `.user/finance/bookkeeper/config/categories.json`.
**Status:** Existing file. Extended by p1-9 with `movable_hint` per category. All other fields preserved unchanged.

### 2.1 Top-level shape (preserved)

| Key | Type | Purpose |
|-----|------|---------|
| `categories` | object (string → object) | Category definitions (display) |
| `value_based_mappings` | array of object | Disambiguates generic vendors by amount (preserved as-is) |
| `recurrence_rules` | object | `default_by_category`, `installments_override`, `vendor_overrides` (preserved as-is) |
| `self_transfer_patterns` | array of string | Self-transfer detection (preserved as-is) |
| `reimbursement_mappings` | object | Reimbursement vendor → category map (preserved as-is). The `tag` key on dict-form entries (e.g., `{"category": "saude", "tag": "reembolso"}`) surfaces in the output `tags` column. The legacy `subcategory` key is no longer read (migration shim removed at expenses-backfill retirement). |

> **Removed in Phase 6 merge:** `vendor_mappings` was the legacy two-layer category-attribution dictionary. It has been folded into `suppliers.json` — supplier identity, default category, and default tags now live in a single source. See §3.4.

### 2.2 Per-category extension: `movable_hint`

Each category in `categories` gains a `movable_hint` field with one of three values. The hint drives the DEFAULT for new suppliers under that category and the bookkeeper's prompt behavior in Pass 2 of the review queue (T1).

```json
{
  "categories": {
    "moradia": {
      "description": "Despesas fixas de moradia",
      "movable_hint": "movable"
    },
    "alimentacao": {
      "description": "Supermercados, restaurantes, delivery",
      "movable_hint": "non-movable"
    },
    "saude": {
      "description": "Consultas, exames, medicamentos",
      "movable_hint": "mixed"
    }
  }
}
```

**Allowed values and prompt behavior** (per spec T1):

| `movable_hint` | Default for new supplier under this category | Pass 2 boundary prompt for suppliers with this hint and no explicit `movable` flag |
|----------------|----------------------------------------------|------------------------------------------------------------------------------------|
| `movable` | `movable: true` | Skip — flag is auto-set; prompt only fires when supplier is in boundary day window (per T5) |
| `mixed` | none (no default) | **Always surface** — bookkeeper must explicitly set `movable` on the supplier before classifier proceeds |
| `non-movable` | `movable: false` | Skip — prompt never fires for this supplier in any window |

**Seeding guidance from T1** (full mapping decided in p1-9):

| Category | Seed `movable_hint` | Reason |
|----------|---------------------|--------|
| `moradia` | `movable` | Utilities, condo, internet — invoiced on movable due dates |
| `alimentacao` | `non-movable` | Day-of-purchase categories; movable accrual would distort daily-life flow |
| `saude` | `mixed` | Some recurring (plano de saúde — movable) + some pontual (consultas — non-movable) |
| `seguros` | `movable` | Periodic billing, can shift between months |
| `assinaturas` | `non-movable` | Monthly auto-charge, shift is irrelevant for analysis |
| `dev-tools` | `non-movable` | Same as assinaturas |
| `transporte` | `non-movable` | Daily-life category |
| `esportes` | `mixed` | Mensalidades (movable) + equipamento (non-movable) |
| `festas`, `viagem*`, `lazer`, `compras`, `casa`, `presentes`, `tecer` | `non-movable` | Pontual / event-bound by definition |
| `receitas`, `intercontas`, `ignorar`, `a_identificar`, `venda` | `non-movable` | Not subject to accrual — boundary prompt nonsensical |

### 2.3 Migration / preservation notes

- The `subcategory` field that historically appeared in some `vendor_mappings` and `reimbursement_mappings` entries (e.g., `{"category": "saude", "subcategory": "reembolsavel"}`) is REMOVED from the schema. Subcategories are re-mapped to **tags** — `default_tags` on the supplier (suppliers.json) for vendor-driven cases, or surfaced as a tag at categorize.py-time for reimbursement-mappings cases.
- `value_based_mappings`, `recurrence_rules`, `self_transfer_patterns`, `reimbursement_mappings` remain in `categories.json`. `vendor_mappings` was REMOVED in the Phase 6 single-layer merge — its rows were folded into `suppliers.json` (see §3.4).

---

## 3. Dictionary: `suppliers.json`

**Path:** `.user/finance/bookkeeper/config/suppliers.json`.
**Status:** New file (created empty by p1-7, populated by the bookkeeper Pass 1 review queue and the one-shot backfill).

### 3.1 Shape

```json
{
  "version": 1,
  "suppliers": {
    "uber": {
      "canonical": "Uber",
      "aliases": ["UBER", "UBER * PENDING", "PAYU*AR*UBER"],
      "movable": false,
      "default_category": "transporte",
      "notes": "All Uber rides; PAYU*AR*UBER is the Argentina-routed variant"
    },
    "claro_movel": {
      "canonical": "Claro",
      "aliases": ["CONTA DE TELEFONE", "CLARO"],
      "movable": true,
      "default_category": "moradia",
      "notes": "Mobile + landline bundle, varies between days 1-5 of the month"
    }
  }
}
```

### 3.2 Per-supplier fields

| Field | Type | Required | Semantics |
|-------|------|----------|-----------|
| `canonical` | string | yes | Display name written to `supplier_canonical` column on a hit. Mixed-case allowed (this is the user-facing label). |
| `aliases` | array of string | yes (≥1) | Substring patterns matched against `description` (case-insensitive, accent-sensitive). At LEAST one alias is required (a supplier with no aliases never matches). |
| `movable` | boolean | yes | The supplier-level movable flag (T1). When set, overrides the category `movable_hint`'s default. |
| `default_category` | string | yes | Category written to the `category` column on a supplier-layer hit. Single source of category attribution post-Phase-6 merge — no `vendor_mappings` fallback. |
| `default_tags` | array of string | optional | Tags auto-applied to the `tags` column when this supplier resolves a row. Each token MUST satisfy `^[a-z0-9][a-z0-9-]*$` (validated at load). Trip-context tags (e.g., `argentina-feb26`) are NOT placed here — they apply per-transaction during the trip month. Default tags are reserved for vendor-intrinsic labels (e.g., `reembolsavel`, `imoveis`, `desapego`). |
| `notes` | string | optional | Free-form human notes; never read by code. |

**Top-level keys:**

| Field | Type | Semantics |
|-------|------|-----------|
| `version` | int | Schema version. v1 = the schema in this document. Increment on breaking changes. |
| `suppliers` | object (slug → supplier) | Slug is a stable identifier (lowercase kebab-case). The slug is NOT used for matching — it's a stable ID for editing/scripting. Matching uses `aliases`. |

### 3.3 Matching rules (T6)

`suppliers.py` performs alias detection with two invariants:

1. **Longest-first ordering.** At load time, all aliases (across all suppliers) are flattened into a single list, sorted by length descending. Ensures `IFD*ARCOS DOURADOS` (a McDonald's franchise variant) matches before the shorter `IFD*` (which would also match but is too generic).
2. **First-match-wins.** Iteration stops on the first alias that is a substring of `description.upper()`. The supplier owning that alias is returned. No accumulation, no multi-supplier rows.

**Outcome:**

| Description matches… | `supplier_canonical` written | `match_confidence` |
|----------------------|------------------------------|--------------------|
| Full alias = `description.upper()` | `<canonical>` | `exact` |
| Alias is a substring of `description.upper()` | `<canonical>` | `partial` |
| No alias matches | empty string | `none` |

### 3.4 Single-layer model (post-Phase-6 merge)

**Choice.** `suppliers.json` owns the full supplier dimension: identity (`canonical`, `aliases`), behavior (`movable`), category attribution (`default_category`), and intrinsic tags (`default_tags`). The legacy two-layer arrangement (suppliers.json on top of vendor_mappings) was collapsed in Phase 6.

| Layer | Owns |
|-------|------|
| `suppliers.json` | Supplier identity, `movable`, `default_category`, `default_tags` |
| `categories.json.value_based_mappings` | Amount-disambiguated category attribution (e.g., the same generic "PAGAMENTO DE CONTA ITAÚ UNIBANCO" maps to different categories by amount) — orthogonal to supplier identity |
| `categories.json.reimbursement_mappings` | Reimbursement vendors → category, with optional `tag` surfaced in the `tags` column |
| `categories.json.self_transfer_patterns` | Self-transfer (intercontas/ignorar) detection |

**Lookup order in `categorize.py`:**

1. Self-transfer detection (`self_transfer_patterns`) — short-circuit to `ignorar` (skipped when description also matches a known reimburser).
2. Reimbursement detection (`reimbursement_mappings`) — short-circuit; the dict-form `tag` key populates the `tags` column.
3. Value-based mappings (`value_based_mappings`) — sets `category` if amount is within ±5%; supplier still resolved separately for display.
4. **Supplier alias detection (`suppliers.py`)** — sets `supplier_canonical`, `category` (from `default_category`), `tags` (from `default_tags`), `movable` flag.
5. No supplier hit → `category: a_identificar`, bookkeeper Pass 1 surfaces it.

**`match_confidence`** is the supplier-layer confidence (`exact` | `partial` | `none`) when the supplier layer fires; `exact` when a higher-priority layer (1–3) fires.

**Rationale.** Single source of truth for the supplier dimension eliminates the dual-confidence ambiguity (one column = one source) and removes the cognitive load of debugging supplier resolution across two files. Migration was tractable because the supplier-walk in Phase 5 had already populated suppliers.json with every merchant seen in 2026-Q1.

---

## 4. Dictionary: `tags.json`

**Path:** `.user/finance/bookkeeper/config/tags.json`.
**Status:** New file (created empty by p1-8).

### 4.1 Shape

```json
{
  "version": 1,
  "tags": {
    "tennis": {
      "label": "Tennis",
      "added": "2026-05-02",
      "notes": "Cross-cutting — appears under esportes (lessons, equipment) and shopping (shoes)"
    },
    "reembolsavel": {
      "label": "Reembolsável",
      "added": "2026-05-02",
      "notes": "Health expenses pending insurance reimbursement"
    },
    "egito": {
      "label": "Egito 2026",
      "added": "2026-05-02",
      "notes": "Liveaboard trip, May 2026"
    }
  },
  "rejected": [
    {
      "token": "natalia",
      "date": "2026-05-02",
      "reason": "Personal name — not a meaningful slice; merge into existing supplier instead",
      "return_count": 1
    }
  ]
}
```

### 4.2 Accepted tag entry fields

| Field | Type | Required | Semantics |
|-------|------|----------|-----------|
| `label` | string | yes | User-facing display label (mixed-case allowed, free-form). Token (the dictionary key) MUST be lowercase kebab-case ASCII (validated by `tags.py.is_valid_token`). |
| `added` | `YYYY-MM-DD` | yes | Date of acceptance. |
| `notes` | string | optional | Free-form human notes; never read by code. |

### 4.3 Rejected tag entry fields

The `rejected` array is an APPEND-ONLY log of tokens the user rejected during Pass 1 of the review queue, plus a return counter for re-surfacing per T7.

| Field | Type | Required | Semantics |
|-------|------|----------|-----------|
| `token` | string | yes | The exact lowercase kebab-case token the user rejected. |
| `date` | `YYYY-MM-DD` | yes | Date of FIRST rejection. |
| `reason` | string | yes | Free-form rationale captured during the review prompt. Helps decide on re-surface. |
| `return_count` | int | yes | Increments by 1 each time the SAME token is proposed again post-rejection (`tags.py.record_return`). When `return_count` reaches 3, the queue re-surfaces the token to the user with the original reason and asks "this came back — reconsider?" (T7). |

**Re-surface threshold.** A rejected token re-surfaces when `return_count >= 3`. If accepted on re-surface, the entry is removed from `rejected` and added to `tags`. If rejected again, `return_count` continues to increment but does NOT re-surface again until it crosses the next multiple of 3 (i.e., 6, 9, …) — `tags.py` owns this counter.

### 4.4 Acceptance / merge / rejection flow (T7)

| User answer at Pass 1 prompt | `tags.py` action |
|------------------------------|------------------|
| "Will this slice future analysis?" → yes, no merge available | Add to `tags` dict; write tag token to the transaction's `tags` column |
| "Does an existing tag cover this?" → yes, name an existing | Write the EXISTING tag token to the transaction; do NOT add a new entry. Token in original raw description is implicitly merged. |
| "Neither" → reject | Append entry to `rejected` array with `return_count: 1`; do NOT write any tag to the transaction |

---

## 5. Lib module contracts

All five modules live under `3-resources/tools/sb-os/finance/scripts/shared/lib/`. Both `categorize.py` (Phase 2) and `backfill.py` (Phase 5) MUST import from these — no duplication. Functions are PURE wherever possible (input → output, no I/O); side effects (file writes, prompts) live in callers.

### 5.1 `lib/accrual.py` — caixa + competência computation

**Purpose.** Compute `data_caixa` and `data_competencia` for a transaction, given context. Core of the cash-vs-accrual split.

**Functions.**

```python
def compute_data_caixa(
    transaction: dict,
    invoice_payment_date: date | None = None,
) -> date:
    """Compute the immutable cash-flow date for a transaction.

    Rules (per spec §Auto-accrual + §Behavior matrix):
      - source_type == 'fatura' (CC purchase, single or installment parcela):
          REQUIRES invoice_payment_date → use invoice_payment_date.
          (Per-invoice, NOT per-purchase. All parcelas in a single invoice
           share one data_caixa = the invoice's payment date.)
      - source_type == 'extrato' or 'Cash':
          use transaction['date'].
      - Reimbursements: caller passes the received-date as transaction['date'];
        this function does not need special-case logic.

    Invariants:
      - data_caixa is IMMUTABLE — the returned value MUST NEVER be mutated by
        any code path that subsequently computes data_competencia.
      - For CC fatura rows, invoice_payment_date is REQUIRED. Raises ValueError
        if absent.
    Pure. No file I/O.
    """

def compute_data_competencia(
    transaction: dict,
    data_caixa: date,
    *,
    original_purchase_date: date | None = None,
    manual_override: date | None = None,
) -> date:
    """Compute the analytical attribution date for a transaction.

    Rules:
      - manual_override is not None → manual_override (caller-provided after
        Pass 2 boundary or reimbursement prompt).
      - source_type == 'fatura' AND installment_total >= 2:
          REQUIRES original_purchase_date → all parcelas collapse to the first
          day of original_purchase_date's month
          (or original_purchase_date itself per p1-2's chosen precision —
          the column is a date, the spec says "month", so we use the original
          date itself; the dashboard groups by year-month).
      - source_type == 'fatura' AND installment_total < 2 (single CC purchase):
          REQUIRES original_purchase_date → use original_purchase_date.
      - source_type == 'extrato' or 'Cash':
          DEFAULT = data_caixa (skip-default per Q13a; no silent push).
      - Reimbursement (caller-detected): if manual_override absent, use
        data_caixa (the received date). Manual override fires when caller's
        accrual prompt linked the reimbursement to its original expense.

    Invariants:
      - NEVER mutates data_caixa. Returned date may equal data_caixa or differ.
      - For CC installment, EVERY parcela of the same purchase MUST return
        the same data_competencia (collapse to original purchase month).
        The function is deterministic on its inputs; the caller is
        responsible for passing identical original_purchase_date for all
        parcelas of the same purchase.
    Pure. No file I/O.
    """
```

### 5.2 `lib/suppliers.py` — alias detection + render-time rollup

**Purpose.** Resolve `supplier_canonical` from raw `description` via alias dictionary (T6). Provide render-time rollup helper for the dashboard (T6).

**Functions.**

```python
def load_suppliers(suppliers_json_path: Path) -> SupplierIndex:
    """Load suppliers.json and return an indexed structure.

    Returns a SupplierIndex with:
      - aliases sorted by length DESCENDING (longest first)
      - lookup methods that respect first-match-wins
    """

def detect_supplier(
    description: str,
    index: SupplierIndex,
) -> tuple[str | None, str]:
    """Find the canonical supplier for a transaction description.

    Returns (canonical_name | None, match_confidence).
      - If full alias == description.upper(): ('<canonical>', 'exact')
      - If alias is a substring of description.upper(): ('<canonical>', 'partial')
      - No match: (None, 'none')

    Iterates aliases longest-first; stops at the FIRST hit (no accumulation).
    Pure. No file I/O after load.
    """

def get_supplier_movable(
    canonical: str,
    index: SupplierIndex,
    category_hint: str = "non-movable",
) -> bool:
    """Resolve the movable flag for a supplier.

    Rules (per T1):
      - If the supplier exists in the index, return its 'movable' field
        (explicitly set by the user).
      - If not (new/unknown supplier), apply the category_hint default:
        movable → True; non-movable → False; mixed → raise UnresolvedMovableError
        (caller MUST surface to user before Pass 2 boundary checks fire).

    Pure. No file I/O.
    """

def rollup_outros(
    transactions: list[dict],
    rolling_3_month_window_end: date,
    threshold_brl: float = 200.0,
) -> dict[str, str]:
    """Render-time rollup helper (T6).

    Inputs:
      - transactions: full list of transactions across the rolling 3-month
        window ending on rolling_3_month_window_end (inclusive).
      - threshold_brl: rollup threshold (default R$200).

    Output: dict mapping supplier_canonical → display_name, where
    display_name is either the supplier_canonical (sum >= threshold) or
    'Outros' (sum < threshold OR supplier_canonical is empty/None).

    Invariants:
      - 'Outros' is NEVER written to the storage layer (CSV column).
        This function is presentation-time only. The dashboard calls it
        per render; results are not persisted.
      - The rollup is computed across ALL categories (per-supplier sum).
    Pure. No file I/O.
    """
```

### 5.3 `lib/tags.py` — accept / merge / reject + re-surface

**Purpose.** Manage the tags dictionary lifecycle (T7).

**Functions.**

```python
def is_valid_token(token: str) -> bool:
    """True iff token is lowercase kebab-case ASCII without ';'.

    Regex: ^[a-z0-9][a-z0-9-]*$
    Rejects empty, uppercase, spaces, semicolons, accents, special chars.
    Pure. No file I/O.
    """

def load_tags(tags_json_path: Path) -> TagIndex:
    """Load tags.json and return TagIndex with accepted + rejected lookup."""

def accept_tag(
    token: str,
    label: str,
    notes: str,
    today: date,
    index: TagIndex,
) -> TagIndex:
    """Add a new accepted tag. Returns updated index.

    Raises ValueError if token is not valid (is_valid_token).
    Raises ValueError if token already exists in index.tags.
    Removes token from index.rejected if present (acceptance on re-surface).
    Pure (input → output). Caller persists via save_tags.
    """

def merge_tag(
    proposed_token: str,
    existing_token: str,
    today: date,
    index: TagIndex,
) -> TagIndex:
    """Merge proposed_token into existing_token.

    No new entry is added; the proposed token is implicitly absorbed into the
    existing one. The transaction caller writes existing_token to the
    transaction's tags column. Returns index unchanged structurally; logs a
    note via the existing tag's notes field if not already present.

    Raises ValueError if existing_token not in index.tags.
    Pure. Caller persists.
    """

def reject_tag(
    token: str,
    reason: str,
    today: date,
    index: TagIndex,
) -> TagIndex:
    """Reject a tag. Returns updated index.

    If token already in index.rejected: increment its return_count by 1
    (per T7). The caller checks the new return_count: if it crossed a
    multiple of 3 (3, 6, 9, …), the caller MUST re-surface the token to
    the user before recording the rejection.

    If token NOT in index.rejected: append entry with return_count=1.

    Raises ValueError if token is in index.tags (already accepted —
    cannot reject without first removing).
    Raises ValueError if token is not valid (is_valid_token).
    Pure. Caller persists.
    """

def should_resurface(
    token: str,
    index: TagIndex,
) -> bool:
    """True iff token is in rejected AND return_count is a non-zero multiple
    of 3 (3, 6, 9, …). Caller checks BEFORE calling reject_tag again.

    Pure. No file I/O.
    """

def save_tags(index: TagIndex, tags_json_path: Path) -> None:
    """Persist index to disk. Side-effecting boundary."""

def parse_tag_column(value: str) -> list[str]:
    """Split semicolon-separated tag column into a list of tokens.

    Empty string → []. No trimming (tokens never have surrounding spaces).
    Pure. No file I/O.
    """

def serialize_tag_column(tokens: list[str]) -> str:
    """Join a list of tokens with ';'. Inverse of parse_tag_column.

    Validates each token via is_valid_token; raises ValueError on any invalid
    token. Pure. No file I/O.
    """
```

### 5.4 `lib/boundary.py` — boundary-day detection + movable resolution

**Purpose.** Detect transactions in the boundary window AND resolve whether they need a Pass 2 prompt (T5).

**Functions.**

```python
def is_boundary_day(d: date) -> bool:
    """True iff d.day is in [1..5] OR in [last_day_of_month-4 .. last_day_of_month].

    Edge case: shorter months (Feb 28/29) — last_day_of_month is computed
    per-month via calendar.monthrange.

    Pure. No file I/O.
    """

def needs_boundary_prompt(
    transaction: dict,
    supplier_movable: bool,
    data_caixa: date,
) -> bool:
    """True iff is_boundary_day(data_caixa) AND supplier_movable AND
    source_type != 'fatura'.

    Why exclude 'fatura': CC transactions already have data_caixa pinned to
    invoice payment date (boundary becomes coincidental, not analytical);
    accrual collapse is governed by accrual.compute_data_competencia, not
    boundary prompts.

    Pure. No file I/O.
    """
```

### 5.5 `lib/queue.py` — two-pass review queue model

**Purpose.** Build and traverse the two-pass review queue (T5). Pass 1 resolves unknowns (cat, supplier, tag); Pass 2 fires boundary prompts only for `supplier.movable == true` rows AFTER Pass 1 is complete.

**Functions.**

```python
def build_pass_1_queue(
    transactions: list[dict],
    suppliers_index: SupplierIndex,
    categories_data: dict,
    tags_index: TagIndex,
) -> list[QueueItem]:
    """Build Pass 1 queue: items with unknown category, unknown supplier, or
    proposed-but-unconfirmed tag.

    Each QueueItem has:
      - transaction_id (stable row identifier)
      - item_type: 'category' | 'supplier' | 'tag'
      - context: enough fields to render the prompt
      - pre_filled_suggestion (optional)

    Items are GROUPED by item_type (T2 — batch by item type for fast clearance).

    Pure. No file I/O.
    """

def build_pass_2_queue(
    transactions: list[dict],
    suppliers_index: SupplierIndex,
) -> list[QueueItem]:
    """Build Pass 2 queue: ONLY items where boundary.needs_boundary_prompt is True.

    PRECONDITION: Pass 1 MUST be complete — every transaction must have a
    resolved supplier (so supplier.movable is known). Raises QueueOrderingError
    if any transaction lacks a resolved supplier_canonical AND a supplier with
    'movable' resolved.

    Each QueueItem has:
      - transaction_id
      - item_type: 'boundary'
      - context: data_caixa, supplier_canonical, current data_competencia
      - prompt_default: 'keep' (skip-default per Q13a)

    Pure. No file I/O.
    """

def apply_pass_1_resolution(
    transactions: list[dict],
    item: QueueItem,
    user_answer: dict,
) -> list[dict]:
    """Apply a user's Pass 1 answer to the in-memory transactions list.

    For 'category' items: set transaction['category'] for all matching rows.
    For 'supplier' items: set supplier_canonical + match_confidence for all
      matching rows; record movable on supplier (caller persists to suppliers.json).
    For 'tag' items: append/merge token to transaction['tags'] for matching rows.

    Returns updated transactions. Pure (input → output).
    """

def apply_pass_2_resolution(
    transactions: list[dict],
    item: QueueItem,
    user_answer: dict,
) -> list[dict]:
    """Apply a user's Pass 2 boundary answer.

    user_answer is one of:
      - {'action': 'keep'}  → leave data_competencia = data_caixa (default).
      - {'action': 'move', 'new_date': date}
        → set data_competencia = new_date; data_caixa unchanged.

    Invariants:
      - data_caixa NEVER mutated.
      - Only one transaction is updated per QueueItem (boundary is per-row).

    Pure (input → output).
    """
```

---

## 6. Hard invariants (verbatim and derived from spec)

These invariants MUST be preserved by every consumer. Tests in p2-3 verify each.

| # | Invariant | Source | Enforcement |
|---|-----------|--------|-------------|
| 1 | `data_caixa` is IMMUTABLE — no code path that computes `data_competencia` may mutate it | Spec §"Invariant"; Shape.md Constraints | accrual.compute_data_competencia signature returns a NEW date; never assigns to transaction['data_caixa'] |
| 2 | CC installment competência collapses to the ORIGINAL purchase month | Spec §"Behavior matrix" — Mar 10 3× installments → all parcelas → Mar | accrual.compute_data_competencia receives `original_purchase_date` and emits the same value for every parcela of the same purchase |
| 3 | CC `data_caixa` is per-invoice (NOT per-purchase) | Spec R2 reinforced; Shape.md Constraints | accrual.compute_data_caixa uses `invoice_payment_date` for source_type='fatura'; all rows in one invoice share one date |
| 4 | Reimbursement caixa NEVER moves | Spec Q12 hard invariant | The only caller-supplied override is `data_competencia` (manual_override). data_caixa stays = received date always |
| 5 | Skip-default leaves `data_competencia = data_caixa` | Spec Q13a | accrual.compute_data_competencia returns data_caixa when no auto-rule and no manual_override apply |
| 6 | "Outros" is presentation-only — NEVER stored as `supplier_canonical` | Spec T6 + Shape.md Constraints | suppliers.rollup_outros documents this; categorize.py NEVER writes "Outros" to the CSV |
| 7 | Tag tokens are lowercase kebab-case ASCII without `;` | This document §1.3 + §5.3 | tags.is_valid_token regex ^[a-z0-9][a-z0-9-]*$ enforced on accept and serialize |
| 8 | Pass 2 fires ONLY after Pass 1 is complete | Spec T5 | queue.build_pass_2_queue raises QueueOrderingError if any tx lacks resolved supplier |
| 9 | Boundary prompt ONLY when `supplier.movable == True` AND `data_caixa.day ∈ [1..5] ∪ [last-4..last]` | Spec T5 | boundary.needs_boundary_prompt enforces both conditions |

---

## 7. Behavior matrix (verbatim from spec)

The four canonical scenarios — the truth table tests verify against. Reproduced verbatim from `1-projects/finance-automation/expenses-redesign-2026-05-02.md` §R3.

| Scenario | TODAY (single mixed view) | NEW caixa | NEW competência |
|----------|----------------------------|-----------|-----------------|
| Apr 12 purchase, paid May 10 invoice (single CC) | April | **May 10** | April 12 |
| Mar 10 purchase, 3× installments paid Apr 10 / May 10 / Jun 10 (CC installment) | **Mar / Apr / May** (each parcela in the month its invoice refers to) | **Apr 10 / May 10 / Jun 10** | **Mar / Mar / Mar** (all parcelas collapse to original purchase) |
| Apr 5 utility bill, debit account (non-CC, non-boundary or skip-default) | April 5 | **April 5** | **April 5** (= caixa, skip-default) |
| Apr 30 reimbursement received for a March expense (manual accrual applied) | April | **April 30** (caixa never moves — Q12) | **March** (manual override links to original-expense month) |

**Implications.**
- For single CC purchases: today's view ≈ NEW competência (off only by line-item date precision).
- For installments: BOTH axes shift. Today's spread (Mar/Apr/May) ≠ NEW caixa (Apr/May/Jun) ≠ NEW competência (Mar/Mar/Mar).
- The collapse to original purchase month under NEW competência is a real analytical gain (the "see full impact of an installment in the month committed" use case).
- Invoice payment day ≈ day 10 of month-after-expenses (user's payment habit).

---

## 8. Open executor decisions (resolved)

The three open executor decisions from `phase-1/p1-1.task.md` §Phase: Understand, with chosen resolutions and rationale. Also captured in `shape.md` Decisions and Discoveries.

### 8.1 Schema column model — ADD `data_caixa` + `data_competencia` alongside `date`

**Choice.** Keep `date` (column 1, audit-only) AND add `data_caixa` + `data_competencia` (columns 16–17, basis dates).

**Alternative considered.** Repurpose `date` as `data_caixa` and add only `data_competencia`.

**Rationale.** Smallest blast radius and clearest reversibility:

| Dimension | Repurpose `date` | **Add alongside** |
|-----------|------------------|-------------------|
| Parser changes | All 8 parsers must change `date` semantics | None — parsers keep emitting `date` as today |
| Audit trail | Lost — original transaction date no longer visible without re-parsing | **Preserved** — `date` is immutable raw |
| Reversibility if redesign reverts | Hard — parsers re-instrumented | **Trivial — drop two columns** |
| CC fatura rows (today `date` = parser date, often the purchase date inside a fatura) | `date` semantically inconsistent (sometimes purchase, sometimes invoice payment) — would need a parser-time decision | `date` stays as parser emits; `data_caixa` derived by accrual.py |

The two new columns are derived; the audit column is preserved. Storage cost is two ISO date strings per row — negligible.

### 8.2 Single-layer supplier model (post-Phase-6 merge)

**Choice.** `suppliers.json` owns the entire supplier dimension: identity, `movable`, `default_category`, and `default_tags`. `vendor_mappings` was removed from `categories.json`. Lookup order in §3.4.

**Original arrangement (pre-Phase-6).** Stacked: `suppliers.json` owned identity + `movable`; `vendor_mappings` (~165 entries) owned category attribution. Phase-2-era rationale was minimum blast radius — supplier addition was purely additive on top of an already-working dictionary.

**Why merged.** After Phase 5 backfill populated `suppliers.json` with every merchant seen in 2026-Q1, the two layers held redundant information. The dual-confidence column (`match_confidence`) was ambiguous — readers could not tell which layer's confidence they were looking at. A vendor → category change required edits in two files. Single-source eliminates those frictions; the `default_tags` field absorbs the legacy `subcategory` data without a separate compat shim.

**Migration shape.** Each `vendor_mappings` entry was classified mechanically: already covered by an existing supplier alias (no action), subcategory data needing `default_tags` (lift to supplier), category conflict with the supplier's `default_category` (per-entry user resolution), or orphan vendor pattern (added as alias on existing supplier or new supplier). Trip-context tags (e.g., `paraguai`, `egito`, `curitiba`) intentionally do NOT live in `default_tags` — they apply at transaction time during the trip month, not as a supplier-intrinsic property.

### 8.3 `tags` column representation — semicolon-separated

**Choice.** Semicolon-separated tokens with no spaces (e.g., `tennis;reembolsavel`).

**Alternatives considered.** JSON array; pipe-separated. Trade-offs in §1.3.

**Rationale.** Smallest blast radius — works with the dashboard's existing `csv-parser.js` (no JSON-in-cell escaping), works with Python `csv.DictReader`, stays human-readable in the raw CSV. Reversibility is high — adding a sidecar column for richer per-tag metadata is non-breaking. Hard rule: tag tokens MUST be lowercase kebab-case ASCII without `;` (§1.3, §5.3, §6 invariant 7).

---

## 9. Invoice payment date surface (p2-2)

**Status.** Authoritative — categorize.py joins fatura rows to invoice payment date via this surface.

**Choice.** **Option B — extend `fatura_totals.json` into a per-fatura metadata file.**

`normalize.py` writes `{data_folder}/processed/fatura_totals.json` with one entry per fatura input file. Each entry now carries a `payment_date` field (ISO `YYYY-MM-DD`). categorize.py reads this file and joins fatura rows by `bank` (the row's `bank` field equals the JSON key, which is the parser's `bank_id`).

### 9.1 File shape

```json
{
  "santander_fatura": {
    "bank_name": "Santander — Fatura Cartão Visa",
    "total": 18734.75,
    "file": "fatura-santander.pdf",
    "payment_date": "2026-04-10"
  },
  "mp_fatura": {
    "bank_name": "Mercado Pago — Fatura Cartão",
    "total": 9727.55,
    "file": "fatura-mercado-pago.pdf",
    "payment_date": "2026-04-10"
  }
}
```

### 9.2 Resolution rules in `normalize.py`

For each fatura input file, normalize.py resolves `payment_date` in this order (first hit wins):

| # | Source | Detail |
|---|--------|--------|
| 1 | Parser-supplied | If the parser implements `extract_payment_date(filepath, password=None) -> date | None` and returns a non-None value, normalize.py uses it. (Parsers MAY add this method; the BaseParser default returns `None`.) |
| 2 | Folder convention | Otherwise, normalize.py derives payment_date from the month folder name: `data_folder.name = "YYYY-MM"` → payment_date = day 10 of the FOLLOWING month (the user's habitual invoice-due day). E.g., a file under `2026-03/raw/` → `2026-04-10`. |

The folder convention is the documented default until parsers add `extract_payment_date`. It matches the user's payment habit (R3 — "invoice payment day ≈ day 10 of month-after-expenses"). When a parser wants per-fatura precision (the actual due/paid date varies), it overrides via method 1.

### 9.3 Consumer rules in `categorize.py`

| Step | Action |
|------|--------|
| 1 | Read `{processed_dir}/fatura_totals.json` (if present); build dict `bank_id -> payment_date`. |
| 2 | For every input row with `source_type == "fatura"`, look up `payment_date` by the row's `bank` field. |
| 3 | If payment_date missing → raise (categorize.py refuses to compute `data_caixa` for a CC row without an invoice payment date — this is a data-integrity error per spec invariant 3). |
| 4 | Pass payment_date as `invoice_payment_date` to `lib.accrual.compute_data_caixa`. |
| 5 | After writing `transactions.csv`, `_update_months_json` updates the `fechamento/months.json` manifest. **Fail-loud guard (J2, 2026-06-05):** the function writes only when the `transactions.csv` output path sits under a `fechamento/{YYYY-MM}/` layout. Off-layout (e.g., a custom `output_folder`), the manifest update is **skipped with a stderr warning** (`[categorize] months.json not updated: …`) and nothing is written — never a silent skip, never a misdirected write into an arbitrary grandparent directory. Canonical `fechamento/` layout behavior is unchanged. |

### 9.4 Rationale (smallest blast radius)

| Dimension | A — per-row column | **B — `fatura_totals.json`** | C — filename convention only |
|-----------|---------------------|-------------------------------|-------------------------------|
| Files touched in this batch | `normalize.py` + `utils.py` (NORMALIZED_COLUMNS bump) + 4 fatura parsers | **`normalize.py` only** | `normalize.py` only (similar footprint to B) |
| Per-fatura precision | Yes (each row carries its date) | Yes (one date per fatura, joined by bank) | No (heuristic — wrong when user pays off-cycle) |
| Reversibility | Hard — schema change ripples through dashboard | **Trivial — delete the field** | Trivial |
| Authoritative failure mode | Parser bug → all rows of that fatura wrong | **JSON missing entry → categorize.py raises (loud)** | Heuristic mismatch silently wrong |
| Future per-parser precision | Already there | **Hookable via `extract_payment_date`** | Requires re-architecting |

Option B keeps the surface in one place (`fatura_totals.json`, already a normalize.py output), gives categorize.py a deterministic join key, and provides a clear extension point (`extract_payment_date` per parser) without forcing parser rewrites in this batch. Failure is loud (missing key → raise), not silent (wrong heuristic).

---

## 10. Cross-references

| What | Where |
|------|-------|
| Source spec (T1–T8 + behavior matrix) | `1-projects/finance-automation/expenses-redesign-2026-05-02.md` |
| Plan + architectural constraints | `1-projects/finance-automation/expenses-redesign/expenses-redesign-plan.md` |
| Shape (decisions + discoveries) | `1-projects/finance-automation/expenses-redesign/shape.md` |
| Current bookkeeper architecture (pre-redesign reference) | `3-resources/tools/sb-os/finance/docs/bookkeeper.md` |
| Current categories.json | `.user/finance/bookkeeper/config/categories.json` |
| Dashboard knowledge file (Phase 4 guard) | `3-resources/tools/sb-os/finance/docs/financial-dashboard.md` |
