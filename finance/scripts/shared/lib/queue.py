"""Two-pass review queue model (spec T5).

Pass 1 — UNKNOWNS resolution. Items: unknown category, unknown supplier,
proposed-but-unconfirmed tag. Items are GROUPED by item_type so the
accountant can clear easy classes fast (T2 — ≤15s per-item target via
batching).

Pass 2 — BOUNDARY prompts. Built ONLY after Pass 1 completes — boundary
depends on supplier.movable, which Pass 1 resolves. `build_pass_2_queue`
raises `QueueOrderingError` if any transaction lacks a resolved supplier
or category. This makes silent misses impossible by construction.

Pure module: no file I/O. Apply functions return NEW transaction lists;
they do not mutate the input list.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from . import boundary
from .suppliers import SupplierIndex, UnresolvedMovableError, get_supplier_movable
from .tags import TagIndex, parse_tag_column, serialize_tag_column

Transaction = dict[str, Any]
ItemType = Literal["category", "supplier", "tag", "boundary"]


class QueueOrderingError(RuntimeError):
    """Raised when Pass 2 is built before Pass 1 has resolved all unknowns."""


@dataclass
class QueueItem:
    """A single item the user must resolve in the review queue.

    Fields:
      transaction_id  — stable index/key into the transactions list
      item_type       — one of 'category' | 'supplier' | 'tag' | 'boundary'
      context         — minimal dict the prompt renderer needs
      pre_filled_suggestion — optional pre-fill (e.g., supplier default_category)
      prompt_default  — only for boundary items; 'keep' per spec Q13a
    """

    transaction_id: int
    item_type: ItemType
    context: dict[str, Any] = field(default_factory=dict)
    pre_filled_suggestion: Any | None = None
    prompt_default: str | None = None


def _tx_date(tx: Transaction) -> date:
    """Sort key — prefer data_caixa, fall back to 'date'. Returns date.min on
    parse failure so unsortable rows still order deterministically."""
    for key in ("data_caixa", "date"):
        v = tx.get(key)
        if isinstance(v, date):
            return v
        if v:
            try:
                return date.fromisoformat(str(v))
            except ValueError:
                continue
    return date.min


def build_pass_1_queue(
    transactions: list[Transaction],
    suppliers_index: SupplierIndex,
    categories_data: dict[str, Any],
    tags_index: TagIndex,
) -> list[QueueItem]:
    """Build Pass 1 queue. Pure.

    For each transaction (indexed by position):
      - emit 'category' item if transaction['category'] is missing or
        equals the sentinel 'a_identificar'
      - emit 'supplier' item if supplier_canonical is empty AND match_confidence
        is 'none' (raw description was not auto-resolved)
      - emit 'tag' item for each token in transaction['tags'] (parsed via
        parse_tag_column) that is NOT already accepted in tags_index AND not
        in the rejected log (i.e., a fresh proposal)

    Items are GROUPED by item_type — all 'category' items first, then
    'supplier', then 'tag'. Within each group, items are stable-sorted by
    transaction date ascending.
    """
    cats: list[QueueItem] = []
    sups: list[QueueItem] = []
    tags_items: list[QueueItem] = []

    accepted_tokens = set(tags_index.tags.keys())
    rejected_tokens = {r.get("token") for r in tags_index.rejected}

    for idx, tx in enumerate(transactions):
        category = (tx.get("category") or "").strip()
        if not category or category == "a_identificar":
            cats.append(
                QueueItem(
                    transaction_id=idx,
                    item_type="category",
                    context={
                        "description": tx.get("description", ""),
                        "amount": tx.get("amount", ""),
                        "date": tx.get("date", ""),
                        "supplier_canonical": tx.get("supplier_canonical", ""),
                    },
                )
            )

        supplier_canonical = (tx.get("supplier_canonical") or "").strip()
        match_confidence = (tx.get("match_confidence") or "").strip().lower()
        if not supplier_canonical and match_confidence in ("", "none"):
            # Suggest supplier's default_category if any single supplier
            # alias matches the description (already resolved? no — surface).
            sups.append(
                QueueItem(
                    transaction_id=idx,
                    item_type="supplier",
                    context={
                        "description": tx.get("description", ""),
                        "amount": tx.get("amount", ""),
                        "date": tx.get("date", ""),
                        "category": category,
                    },
                )
            )

        tokens = parse_tag_column(tx.get("tags") or "")
        for tok in tokens:
            if tok in accepted_tokens:
                continue
            if tok in rejected_tokens:
                # Caller checks should_resurface() — bare proposal does not
                # re-emit a queue item for an already-rejected token.
                continue
            tags_items.append(
                QueueItem(
                    transaction_id=idx,
                    item_type="tag",
                    context={
                        "proposed_token": tok,
                        "description": tx.get("description", ""),
                        "amount": tx.get("amount", ""),
                    },
                )
            )

    cats.sort(key=lambda item: _tx_date(transactions[item.transaction_id]))
    sups.sort(key=lambda item: _tx_date(transactions[item.transaction_id]))
    tags_items.sort(key=lambda item: _tx_date(transactions[item.transaction_id]))
    return cats + sups + tags_items


def build_pass_2_queue(
    transactions: list[Transaction],
    suppliers_index: SupplierIndex,
    categories_data: dict[str, Any] | None = None,
) -> list[QueueItem]:
    """Build Pass 2 queue: ONLY items where boundary.needs_boundary_prompt is True.

    PRECONDITION: Pass 1 MUST be complete. Every transaction must have:
      - a resolved category (not '' and not 'a_identificar'),
      - a resolved supplier (supplier_canonical non-empty) OR an explicit
        category-driven movable resolution path.
    Raises `QueueOrderingError` if any transaction is unresolved.

    For each remaining transaction:
      - look up the supplier's effective `movable` (with category hint
        fallback through `get_supplier_movable`)
      - call `boundary.needs_boundary_prompt`
      - if True, emit a QueueItem with item_type='boundary' and
        prompt_default='keep' (skip-default per Q13a)

    Pure.
    """
    categories = (categories_data or {}).get("categories", {})
    items: list[QueueItem] = []

    for idx, tx in enumerate(transactions):
        category = (tx.get("category") or "").strip()
        if not category or category == "a_identificar":
            raise QueueOrderingError(
                f"transaction[{idx}] still has unresolved category — "
                "Pass 1 must complete before Pass 2"
            )

        # Determine data_caixa for boundary check.
        raw_caixa = tx.get("data_caixa")
        if isinstance(raw_caixa, date):
            data_caixa = raw_caixa
        elif raw_caixa:
            try:
                data_caixa = date.fromisoformat(str(raw_caixa))
            except ValueError:
                raise QueueOrderingError(
                    f"transaction[{idx}] has unparsable data_caixa: {raw_caixa!r}"
                )
        else:
            raise QueueOrderingError(
                f"transaction[{idx}] missing data_caixa — accrual must run before Pass 2"
            )

        canonical = (tx.get("supplier_canonical") or "").strip()
        cat_def = categories.get(category, {}) if isinstance(categories, dict) else {}
        category_hint = cat_def.get("movable_hint", "non-movable")

        try:
            movable = get_supplier_movable(canonical, suppliers_index, category_hint)
        except UnresolvedMovableError as exc:
            raise QueueOrderingError(
                f"transaction[{idx}] supplier movable unresolved: {exc}"
            ) from exc

        if not boundary.needs_boundary_prompt(tx, movable, data_caixa):
            continue

        items.append(
            QueueItem(
                transaction_id=idx,
                item_type="boundary",
                context={
                    "description": tx.get("description", ""),
                    "amount": tx.get("amount", ""),
                    "data_caixa": data_caixa.isoformat(),
                    "supplier_canonical": canonical,
                    "current_data_competencia": tx.get("data_competencia", ""),
                },
                prompt_default="keep",
            )
        )

    items.sort(key=lambda item: _tx_date(transactions[item.transaction_id]))
    return items


def apply_pass_1_resolution(
    transactions: list[Transaction],
    item: QueueItem,
    user_answer: dict[str, Any],
) -> list[Transaction]:
    """Apply a user's Pass 1 answer to a fresh copy of the transactions list.

    user_answer shapes (by item_type):
      - 'category': {'category': str}
            → set transaction['category'] for the matching row
      - 'supplier': {'canonical': str, 'match_confidence': str}
            → set supplier_canonical + match_confidence for the matching row
              (caller separately persists movable/default_category to
              suppliers.json)
      - 'tag':      {'decision': 'accept'|'merge'|'reject',
                     'token': str,
                     'merge_into': str | None}
            → on accept: ensure token in tags column (semicolon-joined)
            → on merge:  replace proposed token with merge_into in tags column
            → on reject: drop the proposed token from tags column
              (caller separately updates tags.json via tags.reject_tag)

    Pure (input → output). Returns a new list with deep-copied row(s).
    """
    new_txs = [copy.deepcopy(t) for t in transactions]
    tx = new_txs[item.transaction_id]

    if item.item_type == "category":
        tx["category"] = user_answer["category"]
    elif item.item_type == "supplier":
        tx["supplier_canonical"] = user_answer["canonical"]
        tx["match_confidence"] = user_answer.get("match_confidence", "exact")
    elif item.item_type == "tag":
        decision = user_answer["decision"]
        tokens = parse_tag_column(tx.get("tags") or "")
        proposed = user_answer["token"]
        if decision == "accept":
            if proposed not in tokens:
                tokens.append(proposed)
        elif decision == "merge":
            target = user_answer["merge_into"]
            tokens = [target if t == proposed else t for t in tokens]
            # de-dup while preserving order
            seen: set[str] = set()
            deduped: list[str] = []
            for t in tokens:
                if t not in seen:
                    seen.add(t)
                    deduped.append(t)
            tokens = deduped
        elif decision == "reject":
            tokens = [t for t in tokens if t != proposed]
        else:
            raise ValueError(f"unknown tag decision: {decision!r}")
        tx["tags"] = serialize_tag_column(tokens)
    else:
        raise ValueError(f"apply_pass_1_resolution called on non-Pass-1 item: {item.item_type!r}")

    return new_txs


def apply_pass_2_resolution(
    transactions: list[Transaction],
    item: QueueItem,
    user_answer: dict[str, Any],
) -> list[Transaction]:
    """Apply a user's Pass 2 boundary answer.

    user_answer is one of:
      - {'action': 'keep'}                    → no change (default per Q13a)
      - {'action': 'move', 'new_date': date}  → set data_competencia = new_date

    Invariants:
      - data_caixa is NEVER mutated.
      - Only the targeted transaction is updated.

    Pure (input → output).
    """
    if item.item_type != "boundary":
        raise ValueError(f"apply_pass_2_resolution called on non-boundary item: {item.item_type!r}")

    new_txs = [copy.deepcopy(t) for t in transactions]
    tx = new_txs[item.transaction_id]
    action = user_answer.get("action", "keep")

    if action == "keep":
        return new_txs
    if action == "move":
        new_date = user_answer["new_date"]
        if isinstance(new_date, date):
            tx["data_competencia"] = new_date.isoformat()
        else:
            # Validate ISO string by round-tripping.
            tx["data_competencia"] = date.fromisoformat(str(new_date)).isoformat()
        return new_txs

    raise ValueError(f"unknown boundary action: {action!r}")
