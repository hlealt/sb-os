#!/usr/bin/env python3
"""Categorize normalized transactions into the new caixa/competência schema.

Usage:
    python categorize.py <processed_dir> <config_folder> [output_folder] [--force]

    processed_dir:  Normalized CSVs for the month (e.g., .user/finance/bookkeeper/ledgers/expenses/2026-04)
    config_folder:  Path to bookkeeper config (e.g., .user/finance/bookkeeper/config)
    output_folder:  Optional. Where to write transactions.csv.
                    Defaults to processed_dir/categorized/ if omitted.
    --force:        Overwrite an existing transactions.csv (freeze gate; a month
                    whose transactions.csv already exists is treated as closed).

Reads:
  - All normalized CSVs from `<processed_dir>/*.csv`.
  - `<processed_dir>/fatura_totals.json` — per-fatura `payment_date`
    (data-model §9, Option B). Required for any row with `source_type='fatura'`.
  - `<config_folder>/categories.json` — categories taxonomy,
    `value_based_mappings`, `recurrence_rules`, `self_transfer_patterns`,
    `reimbursement_mappings`. (Vendor → category attribution lives in
    suppliers.json now — single layer.)
  - `<config_folder>/suppliers.json` — supplier identity, `default_category`,
    `default_tags`. Single source of truth for supplier resolution AND
    category attribution (post-Phase-6 merge; see expenses-data.md §3.4).

Writes:
  - `<output_folder>/transactions.csv` with the 19-column schema declared in
    `expenses-data.md` §1.

Classification primitives are imported from `lib/`:
  - `lib.accrual` — compute_data_caixa, compute_data_competencia
  - `lib.suppliers` — load_suppliers, detect_supplier
  - (`lib.tags` is consumed by the bookkeeper Pass 1 workflow, not by this
     script. categorize.py emits `tags` seeded from `supplier.default_tags`
     and the reimbursement_mappings `tag` key; Pass 1 may add/edit.)

Hard invariants enforced here (data-model §6):
  - `data_caixa` is computed once and never mutated by competência logic.
  - CC fatura rows REQUIRE an invoice payment date (raise on missing).
  - "Outros" is NEVER written to `supplier_canonical` — that's render-time only.
"""

import csv
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from utils import NORMALIZED_COLUMNS
from lib import audit
from lib.accrual import compute_data_caixa, compute_data_competencia
from lib.standing_rules import (
    RuleFireCounter,
    load_standing_rules,
    # B2-SR1 consumers (p2-11…p2-16)
    apply_name_canonicalization,
    apply_tag_application_rules,
    is_family_canonical,
    load_competencia_rules,
    load_family_canonicals,
    load_name_canonicalization,
    load_tag_application_rules,
    load_tag_semantics,
    validate_expenses_schema,
    validate_tag_amount_sign,
    # B2-SR2 consumers (p2-17…p2-22)
    load_tag_coverage,
    load_cross_month_propagation,
    load_pass_2_rules,
    load_cash_expense,
    load_investment_rules,
    load_rf_naming,
    # B2-SR3 consumers (p2-23…p2-28)
    load_yoc,
    load_options_rules,
    load_gates,
    load_batch_ui,
    load_file_conventions,
    load_communication,
)
from lib.suppliers import detect_supplier, load_suppliers, SupplierIndex


# Output schema — order MUST match data-model.md §1 exactly.
# `manual_override` (p2-10 / decision S5): boolean column re-stamped from the
# append-only corrections log `config/corrections/manual-overrides.csv` on every
# regeneration. The corrections log is the durable source of truth; this column
# is the read/output representation only.
CATEGORIZED_COLUMNS = NORMALIZED_COLUMNS + [
    "category",
    "match_confidence",
    "recurrence",
    "data_caixa",
    "data_competencia",
    "supplier_canonical",
    "tags",
    "manual_override",
]


# ---------------------------------------------------------------------------
# Config / IO helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_fatura_payment_dates(processed_dir: Path) -> dict[str, date]:
    """Read processed/fatura_totals.json and return {bank_id: payment_date}.

    Returns empty dict if the file is absent (no fatura inputs this month).
    Per data-model §9: missing payment_date for a fatura row is a data
    integrity error — categorize.py raises when it encounters such a row.
    """
    totals_file = processed_dir / "fatura_totals.json"
    if not totals_file.exists():
        return {}
    raw = load_json(totals_file)
    out: dict[str, date] = {}
    for bank_id, entry in raw.items():
        pd = entry.get("payment_date")
        if pd:
            out[bank_id] = date.fromisoformat(pd)
    return out


# ---------------------------------------------------------------------------
# Manual-override provenance (p2-10 / decision S5)
# ---------------------------------------------------------------------------

def _tx_amount_key(amount) -> str:
    """Normalize an amount to a canonical key string.

    Row identity uses `amount` (a parser-emitted float). `-4.12` and `-4.120`
    are the same transaction — normalize via float() so trailing-zero / format
    drift between the ledger row and the corrections file does not break the
    join. Unparseable amounts fall back to the stripped raw string (stable for
    identical raw values).
    """
    try:
        return repr(float(amount))
    except (ValueError, TypeError):
        return str(amount).strip()


def tx_identity(tx: dict) -> tuple[str, str, str]:
    """Composite row-identity key for a transaction: (date, description, amount).

    This is the SAME scheme p2-23 documents for transactions.csv row
    identification (the row carries no native tx_id). The three parts are
    immutable raw fields — `date`, `description`, `amount` are parser-emitted
    and never mutated by categorize logic — so an override re-binds to the same
    row across regenerations. p3-2 (cross-month reimbursement override / S4)
    reuses this identity.
    """
    return (
        str(tx.get("date", "")).strip(),
        str(tx.get("description", "")).strip(),
        _tx_amount_key(tx.get("amount", "")),
    )


def load_manual_overrides(corrections_dir: Path) -> dict[tuple[str, str, str], dict]:
    """Load manual-overrides.csv keyed by composite row identity (p2-10 / S5).

    The corrections log is the durable source of truth for manual classification
    overrides. categorize.py re-stamps its result onto each regenerated
    transactions.csv row (the `manual_override` column + the overridden category).

    Returns {(tx_date, tx_description, tx_amount_key): override_row}. Fail-soft:
    a missing file means "no overrides" (empty dict), per the corrections
    convention. A present-but-malformed file (missing required identity columns)
    raises — a corrections log that cannot be read is a fail-loud condition, not
    a silent default.
    """
    path = corrections_dir / "manual-overrides.csv"
    if not path.exists():
        return {}
    out: dict[tuple[str, str, str], dict] = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"tx_date", "tx_description", "tx_amount", "override_category"}
        fields = set(reader.fieldnames or [])
        if not required.issubset(fields):
            raise RuntimeError(
                f"CORRECTIONS ERROR (p2-10): {path} is missing required "
                f"column(s) {sorted(required - fields)}. Expected header: "
                f"tx_date,tx_description,tx_amount,override_category,"
                f"override_tags,month,added_at,source,note"
            )
        for row in reader:
            key = (
                str(row.get("tx_date", "")).strip(),
                str(row.get("tx_description", "")).strip(),
                _tx_amount_key(row.get("tx_amount", "")),
            )
            # Last row wins on duplicate identity (append-only revoke pattern:
            # a later row supersedes an earlier one for the same transaction).
            out[key] = row
    return out


# ---------------------------------------------------------------------------
# Category / tag attribution
# ---------------------------------------------------------------------------

def _category_only(value) -> str:
    """Extract the category from a reimbursement_mappings or value_based_mappings value.

    Both layers historically supported dict-form `{"category": ..., "subcategory": ...}`.
    Pure string entries are returned as-is.
    """
    if isinstance(value, dict):
        return value["category"]
    return value


def _value_subcategory(value) -> str:
    """Return the tag if present (dict-form), else empty string.

    Config key is `tag` (renamed from the legacy `subcategory` fossil).
    The value populates the `tags` column in the output — never a subcategory column.
    """
    if isinstance(value, dict):
        return value.get("tag", "") or value.get("subcategory", "") or ""
    return ""


def _resolve_supplier(
    description: str,
    supplier_index: SupplierIndex | None,
) -> tuple[str, str]:
    """Resolve (canonical, confidence) without forcing category attribution.

    Used when the category came from the reimbursement or value-based layer
    but we still want the canonical supplier name for display.
    """
    if supplier_index is None or not description:
        return "", "none"
    canonical, confidence = detect_supplier(description, supplier_index)
    return canonical or "", confidence


def categorize_transaction(
    description: str,
    self_transfer_patterns: list,
    reimbursement_mappings: dict,
    supplier_index: SupplierIndex | None,
    amount: float = 0.0,
    value_based_mappings: list | None = None,
    rule_counter: "RuleFireCounter | None" = None,
) -> tuple[str, str, str, list[str]]:
    """Match a transaction to (category, match_confidence, supplier_canonical, tags).

    Lookup order (single-layer, post-Phase-6 merge):
      1. Self-transfer (intercontas/ignorar) — unless the description also
         matches a known reimburser (PIX from CARE PLUS etc. is a
         reimbursement, not a transfer).
      2. Reimbursement mappings — explicit refund handlers; dict-form value
         `{category, subcategory}` surfaces the subcategory as a tag.
      3. Value-based mapping — disambiguates ambiguous descriptions by amount.
      4. Supplier resolution (suppliers.json) — owns identity, default_category,
         and default_tags. Single source of category attribution for the
         majority of rows.
      5. Fallback — `a_identificar`.

    `match_confidence` is `exact` when layers 1–3 fire; otherwise the
    supplier layer's value (`exact` | `partial` | `none`).
    """
    desc_upper = description.upper().strip()

    # 1. Self-transfer
    for pattern in self_transfer_patterns:
        if pattern.upper() in desc_upper:
            is_reimbursement = any(
                rp.upper() in desc_upper for rp in reimbursement_mappings
            )
            if not is_reimbursement:
                if rule_counter is not None:
                    rule_counter.record("self_transfer")
                return "ignorar", "exact", "", []

    # 2. Reimbursements (subcategory → tag)
    for pattern, value in reimbursement_mappings.items():
        if pattern.upper() in desc_upper:
            cat = _category_only(value)
            sub = _value_subcategory(value)
            tags = [sub] if sub else []
            canonical, _ = _resolve_supplier(description, supplier_index)
            if rule_counter is not None:
                rule_counter.record("reimbursement")
            return cat, "exact", canonical, tags

    # 3. Value-based mappings
    if value_based_mappings and amount != 0.0:
        abs_amount = abs(amount)
        for rule in value_based_mappings:
            vendor_pattern = rule["vendor"].upper()
            if vendor_pattern in desc_upper:
                ref = rule["amount"]
                if ref * 0.95 <= abs_amount <= ref * 1.05:
                    cat_value = rule.get("category", "a_identificar")
                    cat = _category_only(cat_value)
                    sub = _value_subcategory(cat_value)
                    tags = [sub] if sub else []
                    canonical, _ = _resolve_supplier(description, supplier_index)
                    if rule_counter is not None:
                        rule_counter.record("value_based_splits")
                    return cat, "exact", canonical, tags

    # 4. Supplier resolution
    if supplier_index is None:
        if rule_counter is not None:
            rule_counter.record("fallback_a_identificar")
        return "a_identificar", "none", "", []
    canonical, confidence = detect_supplier(description, supplier_index)
    if not canonical:
        if rule_counter is not None:
            rule_counter.record("fallback_a_identificar")
        return "a_identificar", "none", "", []
    supplier = supplier_index.find_by_canonical(canonical)
    if supplier is None:
        if rule_counter is not None:
            rule_counter.record("vendor_mappings_unknown_canonical")
        return "a_identificar", confidence, canonical, []
    if rule_counter is not None:
        rule_counter.record("vendor_mappings")
    return (
        supplier.get("default_category", "a_identificar") or "a_identificar",
        confidence,
        canonical,
        list(supplier.get("default_tags", []) or []),
    )


def classify_recurrence(
    description: str,
    category: str,
    installment_current: str,
    installment_total: str,
    recurrence_rules: dict,
) -> str:
    """Classify a transaction as recorrente or pontual.

    Logic preserved from the pre-redesign script:
      1. Categories intercontas/ignorar → empty
      2. Vendor overrides (highest priority — beat installments)
      3. Installments → installments_override (default 'pontual')
      4. Category default
    """
    skip_categories = {"intercontas", "ignorar"}
    if category in skip_categories:
        return ""

    vendor_overrides = recurrence_rules.get("vendor_overrides", {})
    desc_upper = description.upper().strip()
    sorted_overrides = sorted(vendor_overrides.items(), key=lambda x: len(x[0]), reverse=True)
    for vendor, recurrence in sorted_overrides:
        if vendor.upper() in desc_upper:
            return recurrence

    if installment_current and installment_total:
        try:
            if int(installment_total) >= 2:
                return recurrence_rules.get("installments_override", "pontual")
        except (ValueError, TypeError):
            pass

    base_category = category.split(":")[0] if ":" in category else category
    defaults = recurrence_rules.get("default_by_category", {})
    return defaults.get(base_category, "")


# ---------------------------------------------------------------------------
# Inter-account transfer detection (preserved from legacy)
# ---------------------------------------------------------------------------

def detect_interaccount_transfers(
    transactions: list[dict],
    forex_vendors: list[str] | None = None,
    noise_patterns: list[str] | None = None,
) -> tuple[dict, list[dict]]:
    """Detect transfers between own accounts.

    See pre-redesign behavior: same-currency exact match → auto-classify as
    `intercontas`; cross-currency (Wise funding pattern) → flag for user
    review. Logic identical to the legacy implementation.

    forex_vendors and noise_patterns are now read from config (p2-5); they
    default to the legacy hardcoded values when not supplied, preserving
    byte-equivalent behaviour for callers that do not pass config.
    """
    if forex_vendors is None:
        forex_vendors = ["WISE", "REMESSA ONLINE", "WESTERN UNION", "TRANSFERWISE"]
    if noise_patterns is None:
        noise_patterns = ["RESERVA", "CAPITAL DE GIRO", "RENDIMENTO", "REMUNERACAO"]

    auto_pairs: dict[int, str] = {}
    cross_currency: list[dict] = []

    by_date: dict[str, list[tuple[int, dict]]] = {}
    for i, tx in enumerate(transactions):
        d = tx.get("date", "")
        by_date.setdefault(d, []).append((i, tx))

    matched: set[int] = set()

    for d, txs in by_date.items():
        if len(txs) < 2:
            continue

        for _a_idx, (i, tx_a) in enumerate(txs):
            if i in matched:
                continue
            try:
                amount_a = float(tx_a.get("amount", 0))
            except (ValueError, TypeError):
                continue
            if amount_a == 0:
                continue
            bank_a = tx_a.get("bank", "")
            currency_a = tx_a.get("currency", "BRL")

            for _b_idx, (j, tx_b) in enumerate(txs):
                if j in matched or j == i:
                    continue
                try:
                    amount_b = float(tx_b.get("amount", 0))
                except (ValueError, TypeError):
                    continue
                bank_b = tx_b.get("bank", "")
                currency_b = tx_b.get("currency", "BRL")

                if (
                    currency_a == currency_b
                    and bank_a != bank_b
                    and abs(amount_a + amount_b) < 0.01
                ):
                    auto_pairs[i] = "intercontas"
                    auto_pairs[j] = "intercontas"
                    matched.add(i)
                    matched.add(j)
                    break

        for _a_idx, (i, tx_a) in enumerate(txs):
            if i in matched:
                continue
            desc_a = tx_a.get("description", "").upper()
            currency_a = tx_a.get("currency", "BRL")

            is_wise_funding = (
                "DINHEIRO ADICIONADO" in desc_a or "MONEY ADDED" in desc_a
            )
            if not is_wise_funding:
                continue

            try:
                amount_a = float(tx_a.get("amount", 0))
            except (ValueError, TypeError):
                continue

            candidates = []
            for _b_idx, (j, tx_b) in enumerate(txs):
                if j == i or j in matched:
                    continue
                currency_b = tx_b.get("currency", "BRL")
                bank_b = tx_b.get("bank", "")
                if bank_b == tx_a.get("bank", ""):
                    continue
                try:
                    amount_b = float(tx_b.get("amount", 0))
                except (ValueError, TypeError):
                    continue

                if currency_a != currency_b and amount_a > 0 and amount_b < 0:
                    desc_b = tx_b.get("description", "").upper()
                    if any(noise in desc_b for noise in noise_patterns):
                        continue

                    score = 0
                    if any(fv in desc_b for fv in forex_vendors):
                        score += 100
                    rate = abs(amount_b / amount_a) if amount_a != 0 else 0
                    if 3.0 <= rate <= 8.0:
                        score += 10

                    candidates.append({
                        "wise_idx": i,
                        "wise_tx": tx_a,
                        "other_idx": j,
                        "other_tx": tx_b,
                        "score": score,
                    })

            if candidates:
                candidates.sort(key=lambda c: c["score"], reverse=True)
                best = candidates[0]
                cross_currency.append({
                    "wise_idx": best["wise_idx"],
                    "wise_tx": best["wise_tx"],
                    "other_idx": best["other_idx"],
                    "other_tx": best["other_tx"],
                })

    return auto_pairs, cross_currency


# ---------------------------------------------------------------------------
# Per-row computation
# ---------------------------------------------------------------------------

def _parse_iso(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def compute_basis_dates(
    tx: dict,
    fatura_payment_dates: dict[str, date],
) -> tuple[date, date]:
    """Compute (data_caixa, data_competencia) for one transaction.

    Delegates to lib.accrual. For CC fatura rows, looks up the invoice
    payment date by the row's `bank` field; raises ValueError if absent
    (data integrity error per data-model §9.3).

    For CC fatura rows, original_purchase_date == transaction['date']
    (per data-model §1.1: parser-emitted `date` for CC = purchase date).
    For installments, every parcela of the same purchase shares the same
    `date`, so all parcelas naturally collapse to the same competência.
    """
    source_type = str(tx.get("source_type", "")).lower()
    if source_type == "fatura":
        bank_id = tx.get("bank", "")
        invoice_pd = fatura_payment_dates.get(bank_id)
        if invoice_pd is None:
            raise ValueError(
                f"fatura row from bank '{bank_id}' has no payment_date in "
                f"fatura_totals.json — cannot compute data_caixa "
                f"(data-model §9.3)"
            )
        purchase_date = _parse_iso(tx.get("date", ""))
        if purchase_date is None:
            raise ValueError(
                f"fatura row missing parseable 'date' (purchase date): {tx}"
            )
        d_caixa = compute_data_caixa(tx, invoice_payment_date=invoice_pd)
        d_comp = compute_data_competencia(
            tx, d_caixa, original_purchase_date=purchase_date,
        )
        return d_caixa, d_comp

    # extrato / Cash / blank → caixa = date, competência = caixa (skip-default).
    d_caixa = compute_data_caixa(tx)
    d_comp = compute_data_competencia(tx, d_caixa)
    return d_caixa, d_comp


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _update_months_json(transactions_csv: Path) -> None:
    """Automate months.json from a fechamento/ directory scan (p2-8 / Finding F).

    After writing transactions.csv, scans the parent directory of that file's
    parent for sibling month directories (YYYY-MM pattern) that contain a
    transactions.csv. Writes a sorted JSON array to fechamento/months.json.

    Example: if transactions_csv is
        .../fechamento/2026-03/transactions.csv
    this writes to
        .../fechamento/months.json

    Skips silently if the directory layout does not match the expected
    fechamento/ structure (e.g., custom output_folder paths in tests).
    Raises RuntimeError if the JSON write fails (fail-loud for data integrity).
    """
    import re
    month_dir = transactions_csv.parent          # e.g. .../fechamento/2026-03
    fechamento_dir = month_dir.parent            # e.g. .../fechamento

    if not fechamento_dir.is_dir():
        return  # unexpected layout — skip

    month_pattern = re.compile(r"^\d{4}-\d{2}$")
    closed_months: list[str] = sorted(
        d.name
        for d in fechamento_dir.iterdir()
        if d.is_dir()
        and month_pattern.match(d.name)
        and (d / "transactions.csv").exists()
    )

    months_json = fechamento_dir / "months.json"
    months_json.write_text(
        json.dumps(closed_months, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _validate_category_tag_separation(categories_config: dict) -> None:
    """V-B: assert no category name equals a tag name (DC-3-B enforcement).

    Loads tags.json from the same config directory as categories.json (resolved
    at call-site via the bookkeeper_config path). If tags.json is absent, skips
    silently (fail-soft: advisory-only tag registry may not exist in all envs).
    Emits a RuntimeError on collision so misconfigured categories.json is caught
    at startup, not silently emitted into ledger rows.
    """
    category_names = set(categories_config.get("categories", {}).keys())
    # tags.json is co-located with categories.json; resolved via single config resolver (p2-9).
    tags_path = _resolve_bookkeeper_config() / "tags.json"
    if not tags_path.exists():
        return
    with open(tags_path, "r", encoding="utf-8") as f:
        tags_data = json.load(f)
    tag_names = set(tags_data.get("tags", {}).keys())
    collisions = category_names & tag_names
    if collisions:
        raise RuntimeError(
            f"CONFIG ERROR (V-B): category name(s) collide with tag name(s): "
            f"{sorted(collisions)}. A tag name must not equal a category name. "
            f"Remove from categories.json or tags.json before running."
        )


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "sb-os.json").exists() or (parent / ".obsidian").exists():
            return parent
    raise RuntimeError("Vault root not found (looking for sb-os.json or .obsidian)")


def _resolve_bookkeeper_config() -> Path:
    """Single resolver for all bookkeeper config files (p2-9 / DC-4-B).

    All bookkeeper config reads route through here — no ad-hoc resolver
    paths in main(). Returns the config directory.

    Override for test isolation: set BOOKKEEPER_CONFIG_DIR to a path and this
    function returns that path, allowing tests to supply fixture config dirs
    without touching the real vault config.

    Raises RuntimeError if the directory does not exist (fail-loud).
    """
    import os
    override = os.environ.get("BOOKKEEPER_CONFIG_DIR")
    if override:
        path = Path(override)
    else:
        path = _find_vault_root() / ".user" / "finance" / "bookkeeper" / "config"
    if not path.exists():
        raise RuntimeError(
            f"Bookkeeper config directory not found: {path}. "
            "Expected at .user/finance/bookkeeper/config/ (or set BOOKKEEPER_CONFIG_DIR)."
        )
    return path


def _format_tags(tags: list[str]) -> str:
    """Render a tag list as the semicolon-separated CSV column form."""
    return ";".join(t for t in tags if t)


def main():
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv[1:]

    if len(args) < 2:
        print("Usage: python categorize.py <processed_dir> <config_folder> [output_folder] [--force]")
        sys.exit(1)

    normalized_dir = Path(args[0])
    config_folder = Path(args[1])
    output_folder = Path(args[2]) if len(args) > 2 else None

    if not normalized_dir.exists():
        print(f"ERROR: Processed folder not found: {normalized_dir}")
        print("Run normalize.py first.")
        sys.exit(1)

    # Single resolver for all bookkeeper config files (p2-9 / DC-4-B).
    # categories.json, suppliers.json, standing-rules.yaml all live in the
    # same bookkeeper config directory. The CLI <config_folder> arg is kept
    # for backward-compat but all reads now route through _resolve_bookkeeper_config().
    bookkeeper_config = _resolve_bookkeeper_config()

    categories_path = bookkeeper_config / "categories.json"
    categories_config = load_json(categories_path)
    self_transfer_patterns = categories_config.get("self_transfer_patterns", [])
    reimbursement_mappings = categories_config.get("reimbursement_mappings", {})
    recurrence_rules = categories_config.get("recurrence_rules", {})
    value_based_mappings = categories_config.get("value_based_mappings", [])

    # p2-5: FOREX_VENDORS and NOISE_PATTERNS lifted from hardcoded to config.
    # Read from categories.json::intercontas_auto_pair_config (fail-loud if key
    # present but malformed; graceful defaults when key absent for env compat).
    _intercontas_cfg = categories_config.get("intercontas_auto_pair_config") or {}
    forex_vendors: list[str] = _intercontas_cfg.get(
        "forex_vendors", ["WISE", "REMESSA ONLINE", "WESTERN UNION", "TRANSFERWISE"]
    )
    noise_patterns: list[str] = _intercontas_cfg.get(
        "noise_patterns", ["RESERVA", "CAPITAL DE GIRO", "RENDIMENTO", "REMUNERACAO"]
    )
    if not isinstance(forex_vendors, list) or not isinstance(noise_patterns, list):
        raise RuntimeError(
            "CONFIG ERROR (p2-5): intercontas_auto_pair_config.forex_vendors and "
            "noise_patterns must be lists in categories.json."
        )

    # V-B: namespace separation — no category name may equal a tag name.
    # Enforces the DC-3-B resolution: 'impostos' removed as a category (p2-3).
    _validate_category_tag_separation(categories_config)

    # Standing-rules registry (declarative source of truth — fail loud if absent).
    standing_rules = load_standing_rules(bookkeeper_config)
    rule_set_version = (standing_rules.get("_meta") or {}).get("rule_set_version")
    rule_counter = RuleFireCounter()

    # B2-SR1: load + validate all six pending_consumer sections at startup.
    # Each call raises StandingRulesError on missing/malformed config — fail-loud.
    validate_expenses_schema(standing_rules, CATEGORIZED_COLUMNS)           # p2-11
    _name_canon_cfg = load_name_canonicalization(standing_rules)            # p2-12
    _competencia_cfg = load_competencia_rules(standing_rules)               # p2-13
    _tag_semantics_cfg = load_tag_semantics(standing_rules)                 # p2-14
    _tag_app_rules_cfg = load_tag_application_rules(standing_rules)         # p2-15
    _family_cfg = load_family_canonicals(standing_rules)                    # p2-16

    # B2-SR2: load + validate six more sections at startup (fail-loud).
    # p2-17: tag_coverage — threshold gate (S7 pending; gate fails by default).
    _tag_coverage_cfg = load_tag_coverage(standing_rules)                   # p2-17
    # p2-18: cross_month_propagation — config-read only; runtime action in p3-2.
    _cross_month_cfg = load_cross_month_propagation(standing_rules)         # p2-18
    # p2-19: pass_2_rules — config-read + validate; dispatch is agent-driven.
    _pass_2_cfg = load_pass_2_rules(standing_rules)                         # p2-19
    # p2-20: cash_expense — config-read + validate.
    _cash_expense_cfg = load_cash_expense(standing_rules)                   # p2-20
    # p2-21: investment_rules — config-read + validate key sub-sections.
    _investment_rules_cfg = load_investment_rules(standing_rules)           # p2-21
    # p2-22: rf_naming — config-read + validate.
    _rf_naming_cfg = load_rf_naming(standing_rules)                         # p2-22
    rule_counter.record("b2_sr2_sections_loaded")

    # B2-SR3: load + validate six more sections at startup (fail-loud).
    # p2-23: yoc — config-read + validate; runtime calc in calculate.py.
    _yoc_cfg = load_yoc(standing_rules)                                     # p2-23
    # p2-24: options_rules — config-read + validate; runtime in position_calculator.py.
    _options_cfg = load_options_rules(standing_rules)                       # p2-24
    # p2-25: gates — config-read + validate; S7 thresholds are placeholders (fail-default).
    _gates_cfg = load_gates(standing_rules)                                 # p2-25
    # p2-26: batch_ui — config-read + validate; runtime_actor: bookkeeper agent (Phase 5).
    _batch_ui_cfg = load_batch_ui(standing_rules)                           # p2-26
    # p2-27: file_conventions — validates tag_column_separator == ';' (fail-loud on mismatch).
    _file_conv_cfg = load_file_conventions(standing_rules)                  # p2-27
    # p2-28: communication — config-read + validate; runtime_actor: bookkeeper agent.
    _communication_cfg = load_communication(standing_rules)                 # p2-28
    rule_counter.record("b2_sr3_sections_loaded")

    # suppliers.json now resolved via bookkeeper_config (p2-9 / DC-4-B).
    suppliers_path = bookkeeper_config / "suppliers.json"
    supplier_index: SupplierIndex | None = None
    if suppliers_path.exists():
        supplier_index = load_suppliers(suppliers_path)

    # Manual-override provenance log (p2-10 / S5). Durable source of truth for
    # manual classification fixes; re-stamped onto each row below. Fail-soft on
    # absence (no overrides); fail-loud on a malformed file (load raises).
    corrections_dir = bookkeeper_config / "corrections"
    manual_overrides = load_manual_overrides(corrections_dir)

    fatura_payment_dates = load_fatura_payment_dates(normalized_dir)

    # Read all normalized CSVs
    all_transactions: list[dict] = []
    for csv_file in sorted(normalized_dir.glob("*.csv")):
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row["_source_file"] = csv_file.name
                all_transactions.append(row)

    if not all_transactions:
        print("ERROR: No normalized transactions found.")
        sys.exit(1)

    # Step 1: detect inter-account transfers (forex_vendors/noise_patterns from config — p2-5)
    auto_pairs, cross_currency = detect_interaccount_transfers(
        all_transactions,
        forex_vendors=forex_vendors,
        noise_patterns=noise_patterns,
    )

    if auto_pairs:
        print(f"INTERCONTAS: {len(auto_pairs)} transactions auto-classified as inter-account transfers")
        for idx in sorted(auto_pairs.keys()):
            tx = all_transactions[idx]
            print(f"  {tx['date']}  {tx['bank']:20s}  {tx['amount']:>12s}  {tx['description'][:50]}")
        print()

    if cross_currency:
        print(f"CROSS-CURRENCY: {len(cross_currency)} potential inter-account pairs (need user review)")
        for pair in cross_currency:
            w = pair["wise_tx"]
            o = pair["other_tx"]
            print(f"  Wise: {w['date']} {w['currency']} {w['amount']:>10s}  {w['description'][:40]}")
            print(f"  Other: {o['date']} {o['currency']} {o['amount']:>10s}  {o['description'][:40]}")
            print()

    # Step 2: per-transaction classification
    categorized: list[dict] = []
    stats = {"total": 0, "categorized": 0, "uncategorized": 0,
             "by_category": {}, "by_recurrence": {}}

    # Unknowns surfacing buffers
    unknown_categories: list[dict] = []   # category == 'a_identificar'
    unknown_suppliers: list[dict] = []    # supplier_canonical == '' AND has expense
    # p2-10: rows whose freshly-classified category differs from a recorded
    # manual override. The override is PRESERVED (never silently rewritten);
    # the conflict is surfaced for the user to resolve.
    override_conflicts: list[dict] = []

    for i, tx in enumerate(all_transactions):
        description = tx.get("description", "")
        try:
            tx_amount = float(tx.get("amount", 0))
        except (ValueError, TypeError):
            tx_amount = 0.0

        # Classification
        rule_counter.observe_row()
        if i in auto_pairs:
            category = "intercontas"
            match_confidence = "exact"
            supplier_canonical, _ = _resolve_supplier(description, supplier_index)
            seed_tags: list[str] = []
            rule_counter.record("intercontas_auto_pair")
        else:
            category, match_confidence, supplier_canonical, seed_tags = (
                categorize_transaction(
                    description,
                    self_transfer_patterns,
                    reimbursement_mappings,
                    supplier_index,
                    amount=tx_amount,
                    value_based_mappings=value_based_mappings,
                    rule_counter=rule_counter,
                )
            )

        # Recurrence classification (preserved logic)
        recurrence = classify_recurrence(
            description,
            category,
            tx.get("installment_current", ""),
            tx.get("installment_total", ""),
            recurrence_rules,
        )

        # Basis dates (lib.accrual). Skip for intercontas/ignorar — they are
        # zeroed in reports anyway, but still need columns populated.
        try:
            d_caixa, d_comp = compute_basis_dates(tx, fatura_payment_dates)
            data_caixa_str = d_caixa.isoformat()
            data_competencia_str = d_comp.isoformat()
        except ValueError as e:
            # Loud failure for fatura-without-payment_date is right; for
            # malformed extrato dates, fall back to raw `date`.
            if "fatura" in str(e):
                raise
            data_caixa_str = tx.get("date", "")
            data_competencia_str = tx.get("date", "")

        # p2-12: apply name canonicalization to the resolved supplier name.
        if supplier_canonical:
            canonical_before = supplier_canonical
            supplier_canonical = apply_name_canonicalization(
                supplier_canonical, _name_canon_cfg
            )
            if supplier_canonical != canonical_before:
                rule_counter.record("name_canonicalization")

        # p2-13: competencia_rules — cc_installments sub-rule is already
        # implemented in accrual.py (the only deterministic sub-rule). Record
        # a fire when the rule's cc_installments path was exercised (fatura row
        # with installments). travel_anchors / supplier_fixed are agent-applied
        # (runtime_actor: agent).
        _source_type_lower = str(tx.get("source_type", "")).lower()
        _inst_total_raw = tx.get("installment_total", "")
        if _source_type_lower == "fatura":
            try:
                _inst_total = int(_inst_total_raw) if _inst_total_raw else 0
            except (ValueError, TypeError):
                _inst_total = 0
            if _inst_total >= 2:
                rule_counter.record("competencia_cc_installments")
            else:
                rule_counter.record("competencia_cc_single")

        # p2-14: validate tag amount-sign semantics on seed tags.
        for _t in seed_tags:
            if not validate_tag_amount_sign(_t, tx_amount, _tag_semantics_cfg):
                # Sign mismatch detected — log once; do not suppress the tag
                # (categorize.py never silently drops data).
                rule_counter.record("tag_semantics_sign_mismatch")
            else:
                rule_counter.record("tag_semantics_ok")

        # p2-15: apply declarative tag-application rules (Care Plus, automotive).
        seed_tags = apply_tag_application_rules(
            supplier_canonical or "",
            category,
            tx_amount,
            seed_tags,
            _tag_app_rules_cfg,
            rule_counter=rule_counter,
        )

        # p2-16: check family-canonical convention for PIX rows.
        if supplier_canonical and is_family_canonical(supplier_canonical, _family_cfg):
            rule_counter.record("family_canonical_applied")

        row = {col: tx.get(col, "") for col in NORMALIZED_COLUMNS}
        row["category"] = category
        row["match_confidence"] = match_confidence
        row["recurrence"] = recurrence
        row["data_caixa"] = data_caixa_str
        row["data_competencia"] = data_competencia_str
        row["supplier_canonical"] = supplier_canonical or ""  # NEVER 'Outros'
        row["tags"] = _format_tags(seed_tags)

        # p2-10 / S5: re-stamp manual overrides from the append-only corrections
        # log. The log is the durable source of truth; the `manual_override`
        # column is its read/output representation, re-derived on every run.
        override = manual_overrides.get(tx_identity(tx))
        if override is None:
            row["manual_override"] = "false"
        else:
            row["manual_override"] = "true"
            override_category = (override.get("override_category") or "").strip()
            # Conflict detection (fail-loud, never silent-rewrite): the
            # classifier's fresh category differs from the recorded override.
            if override_category and category != override_category:
                override_conflicts.append({
                    "date": row.get("date", ""),
                    "bank": row.get("bank", ""),
                    "amount": row.get("amount", ""),
                    "description": row.get("description", ""),
                    "classifier_category": category,
                    "override_category": override_category,
                })
            # Preserve the override value (category, and tags if specified).
            if override_category:
                row["category"] = override_category
                # Downstream stats + unknowns surfacing key off `category`;
                # re-point it to the stamped value so an overridden row counts
                # under its final category, not the classifier's discarded one.
                category = override_category
            override_tags = (override.get("override_tags") or "").strip()
            if override_tags:
                row["tags"] = override_tags

        categorized.append(row)

        # Unknowns surfacing
        if category == "a_identificar":
            unknown_categories.append(row)
        if (
            (not supplier_canonical)
            and category not in ("intercontas", "ignorar", "receitas", "venda")
            and tx_amount != 0.0
        ):
            unknown_suppliers.append(row)

        stats["total"] += 1
        if category == "a_identificar":
            stats["uncategorized"] += 1
        else:
            stats["categorized"] += 1
        stats["by_category"][category] = stats["by_category"].get(category, 0) + 1
        if recurrence:
            stats["by_recurrence"][recurrence] = stats["by_recurrence"].get(recurrence, 0) + 1

    # Write categorized CSV
    output_dir = output_folder if output_folder else normalized_dir / "categorized"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "transactions.csv"

    if output_file.exists() and not force:
        raise SystemExit(
            f"FREEZE GATE: {output_file} already exists.\n"
            f"This month appears to be closed. Pass --force to overwrite."
        )

    with audit.track_write(
        output_file,
        materiality="high",
        action="overwrite",
        event_type="ledger_write",
        source_function="categorize.main",
        trigger_context={"input_dir": str(normalized_dir), "forced": force},
    ):
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CATEGORIZED_COLUMNS)
            writer.writeheader()
            for row in categorized:
                writer.writerow({col: row.get(col, "") for col in CATEGORIZED_COLUMNS})

    rule_counter.emit_summary(
        source_function="categorize.main",
        rule_set_version=rule_set_version,
        trigger_context={"input_dir": str(normalized_dir)},
    )

    # p2-8: automate months.json from fechamento/ directory scan.
    # Scans the fechamento/ directory (sibling of the output_dir parent when
    # output_dir IS the fechamento/{YYYY-MM}/ folder) and writes months.json
    # with every month slug that has a transactions.csv. Eliminates the manual
    # update step and prevents silent month omission.
    _update_months_json(output_file)

    # p2-10 / S5: surface manual-override conflicts via the audit stream.
    # One summary event per run (consistent with the rule_fired summary). The
    # override values were already PRESERVED in the rows above — this only
    # records that a rule/alias change now disagrees with a recorded override,
    # so the user can resolve it. Audit emission never raises into the caller.
    if override_conflicts:
        audit.emit(
            "manual_override_conflict",
            source_function="categorize.main",
            destination=output_file,
            materiality="high",
            summary={
                "conflict_count": len(override_conflicts),
                "conflicts": override_conflicts,
            },
            trigger_context={"input_dir": str(normalized_dir)},
        )

    # ----- Report -----
    print("=" * 60)
    print("CATEGORIZE — Transaction Classifier (caixa/competência schema)")
    print("=" * 60)
    print(f"Input: {normalized_dir}")
    print(f"Output: {output_file}")
    if fatura_payment_dates:
        print("Fatura payment dates:")
        for bid, pd in sorted(fatura_payment_dates.items()):
            print(f"  {bid:25s} {pd.isoformat()}")
    print()
    print(f"Total transactions: {stats['total']}")
    print(f"Categorized:        {stats['categorized']}")
    print(f"Uncategorized:      {stats['uncategorized']}")
    print()

    # p2-10 / S5: manual-override conflicts — surfaced loud, never auto-applied.
    if override_conflicts:
        print("!" * 60)
        print(f"MANUAL-OVERRIDE CONFLICTS: {len(override_conflicts)}")
        print("!" * 60)
        print("A rule/alias change would reclassify a manually-overridden row.")
        print("The OVERRIDE was preserved (not rewritten). Resolve each row:")
        print("apply the new rule (append a new manual-overrides.csv row) OR")
        print("keep the override (leave it as-is).")
        for c in override_conflicts:
            print(
                f"  {c['date']}  {c['bank']:20s}  {c['amount']:>12s}  "
                f"{c['description']}"
            )
            print(
                f"      classifier wants '{c['classifier_category']}'  |  "
                f"override keeps '{c['override_category']}'"
            )
        print()

    print("Category breakdown:")
    for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
        marker = " <<<" if cat == "a_identificar" else ""
        print(f"  {cat:30s} {count:4d}{marker}")

    if stats["by_recurrence"]:
        print()
        print("Recurrence breakdown:")
        for rec, count in sorted(stats["by_recurrence"].items()):
            print(f"  {rec:30s} {count:4d}")

    if cross_currency:
        print()
        print("CROSS-CURRENCY PAIRS (need user confirmation):")
        print("-" * 60)
        for pair in cross_currency:
            w = pair["wise_tx"]
            o = pair["other_tx"]
            print(f"  Wise:  {w['date']}  {w['currency']:4s}  {w['amount']:>12s}  {w['description'][:45]}")
            print(f"  Match: {o['date']}  {o['currency']:4s}  {o['amount']:>12s}  {o['description'][:45]}")
            print()

    # ----- Pass 1 unknowns: structured sections (read by step-04) -----
    print()
    print("=" * 60)
    print("UNKNOWN CATEGORIES")
    print("=" * 60)
    print(f"Count: {len(unknown_categories)}")
    if unknown_categories:
        print("Sample (up to 20):")
        for tx in unknown_categories[:20]:
            print(f"  {tx['date']}  {tx['bank']:20s}  {tx['amount']:>12s}  {tx['description']}")

    print()
    print("=" * 60)
    print("UNKNOWN SUPPLIERS")
    print("=" * 60)
    print(f"Count: {len(unknown_suppliers)}")
    if unknown_suppliers:
        # Group by description to surface recurring unknowns first.
        by_desc: dict[str, list[dict]] = {}
        for tx in unknown_suppliers:
            by_desc.setdefault(tx["description"], []).append(tx)
        groups = sorted(by_desc.items(), key=lambda kv: -len(kv[1]))
        print("Sample (up to 20 distinct descriptions):")
        for desc, rows in groups[:20]:
            print(f"  [{len(rows):3d}x] {rows[0]['bank']:20s}  {desc}")

    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
