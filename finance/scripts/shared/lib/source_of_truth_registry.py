"""Source-of-truth registry — the semantic-overlap reference for the ME gate.

The structural non-overlap (ME = mutual-exclusivity) gate needs a machine-
readable answer to one question: "does this logical concept ALREADY have a
canonical store somewhere in the finance system?" That answer lives in the
p2-7 sources-of-truth inventory
(`1-projects/finance-system/finance-system-v2-foundation/phase-2/inventories/p2-7-sources-of-truth.md`),
which catalogs 23 data domains (§1.1–§1.23), each with a canonical source and
the logical concept it owns.

This module transcribes that inventory into a registry the gate queries. It is
intentionally a hand-curated registry, NOT a heuristic that re-derives concepts
from filenames — the p2-7 inventory is the human-reviewed source of truth, and a
registry-driven check is auditable (every match points at a known §-numbered
entry) where a filename heuristic would be a guess.

Each entry declares:
  - concept:     the logical concept (one per data domain)
  - section:     the p2-7 §-number the concept came from (provenance)
  - canonical:   the canonical store that already owns the concept
  - keywords:    surface terms that name this concept in a store/config/path
                 (lowercased; matched against an edit's declared concept/keys)

The gate does a SEMANTIC lookup (does an edit's concept overlap a registered
concept?) — not a filesystem existence check. A genuinely new concept (no
keyword overlap with any registered entry) passes.

Adding a NEW canonical store for a genuinely new concept: append an entry here
in the SAME change, citing the p2-7 §-number (or a new inventory entry). The
gate's own definition-of-done for a justified-new store is "registry updated."
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegistryEntry:
    """One logical concept that already has a canonical store."""

    concept: str
    section: str
    canonical: str
    keywords: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# The 23-domain registry, transcribed from p2-7 §1.1–§1.23.
# Each `concept` is the logical thing stored; `canonical` is its existing
# single source of truth; `keywords` are the surface terms that signal "this
# edit is about that concept."
# ---------------------------------------------------------------------------

_REGISTRY: tuple[RegistryEntry, ...] = (
    RegistryEntry(
        concept="vendor to category mapping",
        section="1.1",
        canonical="config/suppliers.json::suppliers.{slug}.default_category",
        keywords=("vendor_category", "supplier_category", "default_category",
                  "vendor_mappings", "vendor to category", "supplier mapping"),
    ),
    RegistryEntry(
        concept="value-based category overrides",
        section="1.2",
        canonical="config/categories.json::value_based_mappings",
        keywords=("value_based", "value-based", "value_based_mappings",
                  "amount_based_category", "amount-based category"),
    ),
    RegistryEntry(
        concept="recurrence labels",
        section="1.3",
        canonical="config/categories.json::recurrence_rules",
        keywords=("recurrence", "recurrence_rules", "recorrente", "pontual",
                  "recurrence_overrides", "vendor_overrides"),
    ),
    RegistryEntry(
        concept="self-transfer patterns",
        section="1.4",
        canonical="config/categories.json::self_transfer_patterns",
        keywords=("self_transfer", "self-transfer", "self_transfer_patterns",
                  "intercontas"),
    ),
    RegistryEntry(
        concept="reimbursement mappings",
        section="1.5",
        canonical="config/categories.json::reimbursement_mappings",
        keywords=("reimbursement", "reimbursement_mappings", "reembolso"),
    ),
    RegistryEntry(
        concept="category taxonomy",
        section="1.6",
        canonical="config/categories.json::categories",
        keywords=("category_taxonomy", "categories", "category list",
                  "category names"),
    ),
    RegistryEntry(
        concept="normalized pre-categorization expense ledger",
        section="1.7",
        canonical="ledgers/expenses/{YYYY-MM}/{bank}_extrato.csv",
        keywords=("expenses_ledger", "extrato", "normalized expenses",
                  "expense ledger"),
    ),
    RegistryEntry(
        concept="categorized post-close expense ledger",
        section="1.8",
        canonical="ledgers/fechamento/{YYYY-MM}/transactions.csv",
        keywords=("fechamento", "transactions.csv", "categorized expenses",
                  "closed month", "months.json"),
    ),
    RegistryEntry(
        concept="fatura payment dates",
        section="1.9",
        canonical="ledgers/expenses/{YYYY-MM}/fatura_totals.json",
        keywords=("fatura_totals", "fatura payment", "fatura dates",
                  "fatura_payment_dates"),
    ),
    RegistryEntry(
        concept="investment event ledgers (orders/proventos/balcao/fx/crypto/corporate-actions)",
        section="1.10",
        canonical="ledgers/investimentos/{orders,proventos,balcao,avenue_fx,crypto,corporate_actions}.csv",
        keywords=("orders.csv", "proventos", "balcao", "avenue_fx",
                  "crypto.csv", "corporate_actions", "investment ledger",
                  "brokerage_fees"),
    ),
    RegistryEntry(
        concept="asset metadata registry",
        section="1.11",
        canonical="data/assets.csv",
        keywords=("assets.csv", "asset metadata", "asset registry",
                  "asset_class", "instrument metadata"),
    ),
    RegistryEntry(
        concept="field-ownership rules",
        section="1.12",
        canonical="config/_field_ownership.yaml",
        keywords=("field_ownership", "field-ownership", "_field_ownership",
                  "write-class", "can_write"),
    ),
    RegistryEntry(
        concept="computed investment positions snapshot",
        section="1.13",
        canonical="ledgers/investimentos/portfolio.json (+ portfolio-{date}.json, snapshots.json)",
        keywords=("portfolio.json", "portfolio snapshot", "positions",
                  "snapshots.json", "portfolio-"),
    ),
    RegistryEntry(
        concept="safra-imported balance snapshots",
        section="1.14",
        canonical="ledgers/investimentos/balance-snapshots.csv",
        keywords=("balance-snapshots", "balance_snapshots", "balance snapshot",
                  "safra balance"),
    ),
    RegistryEntry(
        concept="fx prices (current and historical)",
        section="1.15",
        canonical="price_fetcher.py::fetch_market_indicators -> portfolio.json::meta.fx_rate_usd_brl",
        keywords=("fx_rate", "fx price", "fx_rate_usd_brl", "usd_brl",
                  "exchange rate"),
    ),
    RegistryEntry(
        concept="equity/fund/crypto prices",
        section="1.16",
        canonical="price_fetcher.py -> portfolio.json::positions[].current_price",
        keywords=("current_price", "market price", "equity price",
                  "price_fetcher", "quote"),
    ),
    RegistryEntry(
        concept="asset name harmonization map",
        section="1.17",
        canonical="ledgers/investimentos/name_map.csv",
        keywords=("name_map", "name harmonization", "canonical name map",
                  "ticker map", "instrument name map"),
    ),
    RegistryEntry(
        concept="recurring-payment register",
        section="1.18",
        canonical="2-areas/finance/pagamentos-recorrentes.md (schedule) + categories.json::recurrence_rules (classifier)",
        keywords=("pagamentos-recorrentes", "recurring payment register",
                  "recurring payments", "payment schedule"),
    ),
    RegistryEntry(
        concept="supplier registry",
        section="1.19",
        canonical="config/suppliers.json",
        keywords=("suppliers.json", "supplier registry", "supplier list",
                  "fornecedores", "aliases"),
    ),
    RegistryEntry(
        concept="tag vocabulary",
        section="1.20",
        canonical="config/tags.json",
        keywords=("tags.json", "tag vocabulary", "tag list", "tag namespace"),
    ),
    RegistryEntry(
        concept="audit event stream",
        section="1.21",
        canonical="audit/events-{YYYY}.jsonl",
        keywords=("events-", "audit stream", "audit_events", "audit log",
                  "events.jsonl"),
    ),
    RegistryEntry(
        concept="bookkeeper config resolver path",
        section="1.22",
        canonical="config resolver (single resolver for all bookkeeper config files)",
        keywords=("config_resolver", "config resolver", "config_folder",
                  "find_vault_root config"),
    ),
    RegistryEntry(
        concept="manual-override / corrections side-ledger",
        section="1.23 / S5(p2-10)",
        canonical="config/corrections/*.csv (manual-overrides.csv, competencia-overrides.csv, category-migrations.csv, …)",
        keywords=("corrections", "manual-overrides", "manual_override",
                  "competencia-overrides", "category-migrations", "side-ledger",
                  "code_migrations"),
    ),
)


def all_entries() -> tuple[RegistryEntry, ...]:
    """Return the full registry (the 23 p2-7 domains)."""
    return _REGISTRY


def _normalize(text: str) -> str:
    """Lowercase + collapse separators so 'value_based', 'value-based',
    and 'Value Based' all compare equal at the token level."""
    out = []
    for ch in text.lower():
        out.append(ch if ch.isalnum() else " ")
    return " ".join("".join(out).split())


def find_overlaps(concept: str, *, extra_terms: list[str] | None = None) -> list[RegistryEntry]:
    """Return registry entries whose concept semantically overlaps `concept`.

    Matching is keyword-based against the registered `keywords` plus the
    registered `concept` text. `concept` is the edit's declared logical concept
    (e.g. "a new vendor->category dict"); `extra_terms` are additional signals
    the caller extracted (config keys, store name, target path basename).

    Overlap = any registered keyword (normalized) appears as a token-run inside
    the normalized haystack (the concept + extra_terms), OR the registered
    concept's own normalized text appears there. A concept with no overlap
    against any entry is genuinely new and returns an empty list.
    """
    terms = [concept] + (extra_terms or [])
    haystack = " " + " ".join(_normalize(t) for t in terms if t) + " "

    hits: list[RegistryEntry] = []
    for entry in _REGISTRY:
        signals = list(entry.keywords) + [entry.concept]
        for sig in signals:
            norm_sig = _normalize(sig)
            if not norm_sig:
                continue
            if f" {norm_sig} " in haystack:
                hits.append(entry)
                break
    return hits
