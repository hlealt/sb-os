#!/usr/bin/env python3
"""Categorize normalized transactions into the new caixa/competência schema.

Usage:
    python categorize.py <processed_dir> <config_folder> [output_folder]

    processed_dir:  Normalized CSVs for the month (e.g., .user/finance/bookkeeper/ledgers/expenses/2026-04)
    config_folder:  Path to bookkeeper config (e.g., .user/finance/bookkeeper/config)
    output_folder:  Optional. Where to write transactions.csv.
                    Defaults to processed_dir/categorized/ if omitted.

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
     and reimbursement_mappings subcategory; Pass 1 may add/edit.)

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
from lib.standing_rules import RuleFireCounter, load_standing_rules
from lib.suppliers import detect_supplier, load_suppliers, SupplierIndex


# Output schema — order MUST match data-model.md §1 exactly.
CATEGORIZED_COLUMNS = NORMALIZED_COLUMNS + [
    "category",
    "match_confidence",
    "recurrence",
    "data_caixa",
    "data_competencia",
    "supplier_canonical",
    "tags",
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
    """Return the subcategory if present (dict-form), else empty string.

    In the new schema, subcategory is gone as a column — the value, when
    present, becomes a tag in the output `tags` column.
    """
    if isinstance(value, dict):
        return value.get("subcategory", "") or ""
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

def detect_interaccount_transfers(transactions: list[dict]) -> tuple[dict, list[dict]]:
    """Detect transfers between own accounts.

    See pre-redesign behavior: same-currency exact match → auto-classify as
    `intercontas`; cross-currency (Wise funding pattern) → flag for user
    review. Logic identical to the legacy implementation.
    """
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

        FOREX_VENDORS = ["WISE", "REMESSA ONLINE", "WESTERN UNION", "TRANSFERWISE"]
        NOISE_PATTERNS = ["RESERVA", "CAPITAL DE GIRO", "RENDIMENTO", "REMUNERACAO"]

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
                    if any(noise in desc_b for noise in NOISE_PATTERNS):
                        continue

                    score = 0
                    if any(fv in desc_b for fv in FOREX_VENDORS):
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

def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "sb-os.json").exists() or (parent / ".obsidian").exists():
            return parent
    raise RuntimeError("Vault root not found (looking for sb-os.json or .obsidian)")


def _format_tags(tags: list[str]) -> str:
    """Render a tag list as the semicolon-separated CSV column form."""
    return ";".join(t for t in tags if t)


def main():
    if len(sys.argv) < 3:
        print("Usage: python categorize.py <processed_dir> <config_folder> [output_folder]")
        sys.exit(1)

    normalized_dir = Path(sys.argv[1])
    config_folder = Path(sys.argv[2])
    output_folder = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    if not normalized_dir.exists():
        print(f"ERROR: Processed folder not found: {normalized_dir}")
        print("Run normalize.py first.")
        sys.exit(1)

    # categories.json lives in .user/finance/bookkeeper/config/ (consumed by both bookkeeper and dashboard).
    vault_root = _find_vault_root()
    bookkeeper_config = vault_root / ".user" / "finance" / "bookkeeper" / "config"
    categories_path = bookkeeper_config / "categories.json"
    categories_config = load_json(categories_path)
    self_transfer_patterns = categories_config.get("self_transfer_patterns", [])
    reimbursement_mappings = categories_config.get("reimbursement_mappings", {})
    recurrence_rules = categories_config.get("recurrence_rules", {})
    value_based_mappings = categories_config.get("value_based_mappings", [])

    # Standing-rules registry (declarative source of truth — fail loud if absent).
    standing_rules = load_standing_rules(bookkeeper_config)
    rule_set_version = (standing_rules.get("_meta") or {}).get("rule_set_version")
    rule_counter = RuleFireCounter()

    suppliers_path = config_folder / "suppliers.json"
    supplier_index: SupplierIndex | None = None
    if suppliers_path.exists():
        supplier_index = load_suppliers(suppliers_path)

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

    # Step 1: detect inter-account transfers
    auto_pairs, cross_currency = detect_interaccount_transfers(all_transactions)

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

        row = {col: tx.get(col, "") for col in NORMALIZED_COLUMNS}
        row["category"] = category
        row["match_confidence"] = match_confidence
        row["recurrence"] = recurrence
        row["data_caixa"] = data_caixa_str
        row["data_competencia"] = data_competencia_str
        row["supplier_canonical"] = supplier_canonical or ""  # NEVER 'Outros'
        row["tags"] = _format_tags(seed_tags)

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

    with audit.track_write(
        output_file,
        materiality="high",
        action="overwrite",
        event_type="ledger_write",
        source_function="categorize.main",
        trigger_context={"input_dir": str(normalized_dir)},
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
